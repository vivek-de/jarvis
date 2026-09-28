"""
backend/voice/stt.py — local speech-to-text via openai-whisper (Phase 11).
═══════════════════════════════════════════════════════════════════════════════
Runs entirely on-device (no API key, no network) — audio never leaves the machine.
The model is imported and loaded lazily and cached, so importing this module (and
starting the app) is cheap even when whisper isn't installed. transcribe() returns
{text, language, duration_s} on success or {"error": ...} on any failure — it never
raises, so the API/pipeline can degrade gracefully.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile

from ..logging_setup import get_logger

log = get_logger("jarvis.voice")


class WhisperSTT:
    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self._model = None

    def available(self) -> bool:
        return importlib.util.find_spec("whisper") is not None

    def _load(self):
        if self._model is None:
            import whisper                          # heavy; loaded once, on first use
            self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        if not audio_bytes:
            return {"error": "empty audio"}
        if not self.available():
            return {"error": "openai-whisper not installed (pip install openai-whisper)"}
        try:
            model = self._load()
        except Exception as e:
            return {"error": f"whisper unavailable: {e}"}

        suffix = os.path.splitext(filename)[1] or ".wav"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
                fh.write(audio_bytes)
                tmp = fh.name
            result = model.transcribe(tmp)
            text = (result.get("text") or "").strip()
            segments = result.get("segments") or []
            duration = round(float(segments[-1].get("end", 0)), 2) if segments else None
            return {"text": text, "language": result.get("language"), "duration_s": duration}
        except Exception as e:
            log.warning("voice.stt_failed", extra={"error": str(e)})
            return {"error": f"transcription failed: {e}"}
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
