"""Phase 11 — voice: STT/TTS/pipeline + endpoints. whisper, piper, and subprocess mocked.

No real models or audio backends are invoked: WhisperSTT is monkeypatched, PiperTTS's
shutil.which/subprocess.run are faked (the fake writes a valid WAV), and endpoints use
fake stt/tts/pipeline injected into app.state.
"""
import asyncio
import io
import shutil
import subprocess
import wave

import pytest

from backend.voice import tts as tts_mod
from backend.voice.pipeline import VoicePipeline
from backend.voice.stt import WhisperSTT
from backend.voice.tts import PiperTTS


def make_wav(seconds=0.5, rate=22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


# ══ STT ═══════════════════════════════════════════════════════════════════════
class FakeWhisperModel:
    def transcribe(self, path):
        return {"text": " hello world ", "language": "en", "segments": [{"end": 1.5}]}


def test_stt_transcribes(monkeypatch):
    stt = WhisperSTT("base")
    monkeypatch.setattr(stt, "available", lambda: True)
    monkeypatch.setattr(stt, "_load", lambda: FakeWhisperModel())
    res = stt.transcribe(b"RIFFfake", "clip.wav")
    assert res["text"] == "hello world" and res["language"] == "en" and res["duration_s"] == 1.5


def test_stt_empty_audio_returns_error():
    assert "error" in WhisperSTT().transcribe(b"", "a.wav")


def test_stt_unavailable_returns_error(monkeypatch):
    stt = WhisperSTT()
    monkeypatch.setattr(stt, "available", lambda: False)
    assert "error" in stt.transcribe(b"data", "a.wav")


# ══ TTS ═══════════════════════════════════════════════════════════════════════
def _fake_run_writes_wav(recorder):
    def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None, **kw):
        recorder.append(cmd)
        out = None
        for flag in ("-o", "-f"):
            if flag in cmd:
                out = cmd[cmd.index(flag) + 1]
        if out:
            with open(out, "wb") as fh:
                fh.write(make_wav())

        class CP:
            returncode = 0
        return CP()
    return fake_run


def test_tts_uses_say_fallback_when_no_piper(monkeypatch):
    cmds = []
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/say" if name == "say" else None)
    monkeypatch.setattr(subprocess, "run", _fake_run_writes_wav(cmds))
    res = PiperTTS().synthesize("hello")
    assert res["format"] == "wav" and len(res["audio_bytes"]) > 44 and res["duration_s"] == 0.5
    assert any("say" in c[0] for c in cmds)          # fallback fired


def test_tts_prefers_piper_when_present(monkeypatch):
    cmds = []
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")   # both present
    monkeypatch.setattr(subprocess, "run", _fake_run_writes_wav(cmds))
    res = PiperTTS("en_US-lessac-medium").synthesize("hi")
    assert "audio_bytes" in res and any("piper" in c[0] for c in cmds)


def test_tts_no_backend_returns_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "error" in PiperTTS().synthesize("hi")


def test_tts_empty_text_returns_error():
    assert "error" in PiperTTS().synthesize("   ")


def test_tts_wav_duration_helper():
    assert PiperTTS._wav_duration(make_wav(seconds=1.0)) == 1.0
    assert PiperTTS._wav_duration(b"not a wav") is None


def test_tts_available_reflects_backends(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert PiperTTS().available() is False
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/say" if name == "say" else None)
    assert PiperTTS().available() is True


# ══ pipeline ══════════════════════════════════════════════════════════════════
class FakeSTT:
    def __init__(self, out=None):
        self.out = out or {"text": "hello", "language": "en", "duration_s": 1.0}

    def transcribe(self, audio, filename="a.wav"):
        return self.out

    def available(self):
        return True


class FakeTTS:
    def synthesize(self, text):
        return {"audio_bytes": make_wav(), "format": "wav", "duration_s": 0.5}

    def available(self):
        return True


class FakeAgent:
    async def chat(self, message, channel=None):
        return {"reply": f"you said {message}"}


def test_pipeline_chains_all_three():
    p = VoicePipeline(FakeSTT(), FakeTTS(), FakeAgent())
    res = asyncio.run(p.process(b"audio", "a.wav"))
    assert res["transcript"] == "hello" and res["response_text"] == "you said hello"
    assert len(res["audio_bytes"]) > 44 and set(res["latency_ms"]) == {"stt", "agent", "tts"}


def test_pipeline_stt_error_short_circuits():
    p = VoicePipeline(FakeSTT({"error": "boom"}), FakeTTS(), FakeAgent())
    res = asyncio.run(p.process(b"audio"))
    assert res["error"] == "boom" and res["stage"] == "stt"


def test_pipeline_no_speech():
    p = VoicePipeline(FakeSTT({"text": ""}), FakeTTS(), FakeAgent())
    res = asyncio.run(p.process(b"audio"))
    assert res["stage"] == "stt" and "no speech" in res["error"]


# ══ endpoints ═════════════════════════════════════════════════════════════════
class FakePipeline:
    async def process(self, audio, filename="a.wav"):
        return {"transcript": "hi", "response_text": "hello back", "audio_bytes": make_wav(),
                "format": "wav", "latency_ms": {"stt": 1, "agent": 2, "tts": 3}}


@pytest.fixture
def voice_client(settings, stub_ollama):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    with TestClient(create_app(settings)) as c:
        c.app.state.stt = FakeSTT()
        c.app.state.tts = FakeTTS()
        c.app.state.voice = FakePipeline()
        yield c


def test_status_endpoint_ok(voice_client):
    r = voice_client.get("/voice/status")
    assert r.status_code == 200
    assert r.json() == {"stt": "ok", "tts": "ok", "pipeline": "ok"}


def test_transcribe_endpoint(voice_client):
    r = voice_client.post("/voice/transcribe", files={"file": ("clip.wav", b"RIFFdata", "audio/wav")})
    assert r.status_code == 200 and r.json()["text"] == "hello"


def test_transcribe_rejects_bad_type(voice_client):
    r = voice_client.post("/voice/transcribe", files={"file": ("clip.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_speak_endpoint_returns_wav(voice_client):
    r = voice_client.post("/voice/speak", json={"text": "markets are open"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"


def test_voice_chat_endpoint(voice_client):
    r = voice_client.post("/voice/chat", files={"file": ("q.wav", b"RIFFdata", "audio/wav")})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.headers["x-transcript"] == "hi" and r.content[:4] == b"RIFF"


def test_voice_disabled_returns_503(client):
    # the shared `client` fixture builds the app with voice enabled by default, but if
    # state is missing the endpoint must 503; simulate by clearing it.
    client.app.state.stt = None
    assert client.post("/voice/transcribe",
                       files={"file": ("c.wav", b"x", "audio/wav")}).status_code == 503
