"""
backend/voice/tts.py — local text-to-speech (Phase 11).
═══════════════════════════════════════════════════════════════════════════════
Prefers Piper (offline neural TTS); falls back to the macOS `say` command. Both are
local — no audio or text is sent to any external service. synthesize() returns
{audio_bytes, format, duration_s} (WAV) or {"error": ...}; it never raises.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import wave

from ..logging_setup import get_logger

log = get_logger("jarvis.voice")

SYNTH_TIMEOUT_S = 60


class PiperTTS:
    def __init__(self, voice: str = "en_US-lessac-medium"):
        self.voice = voice

    # ── availability ─────────────────────────────────────────────────────────
    def _piper_exe(self) -> str | None:
        return shutil.which("piper")

    def _say_exe(self) -> str | None:
        return shutil.which("say")

    def available(self) -> bool:
        return bool(self._piper_exe() or self._say_exe())

    def backend(self) -> str | None:
        if self._piper_exe():
            return "piper"
        if self._say_exe():
            return "say"
        return None

    # ── synthesis ──────────────────────────────────────────────────────────────
    def synthesize(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"error": "empty text"}

        wav = None
        if self._piper_exe():
            wav = self._piper_synth(text)
        if wav is None and self._say_exe():
            wav = self._say_synth(text)          # macOS fallback
        if wav is None:
            return {"error": "no TTS backend available (install piper, or run on macOS)"}
        return {"audio_bytes": wav, "format": "wav", "duration_s": self._wav_duration(wav)}

    def _piper_synth(self, text: str) -> bytes | None:
        exe = self._piper_exe()
        out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            subprocess.run([exe, "-m", self.voice, "-f", out],
                           input=text.encode("utf-8"), capture_output=True,
                           timeout=SYNTH_TIMEOUT_S, check=True)
            with open(out, "rb") as fh:
                return fh.read()
        except Exception as e:
            log.warning("voice.piper_failed", extra={"error": str(e)})
            return None
        finally:
            if os.path.exists(out):
                with contextlib.suppress(Exception):
                    os.unlink(out)

    def _say_synth(self, text: str) -> bytes | None:
        exe = self._say_exe()
        out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            subprocess.run([exe, "-o", out, "--file-format=WAVE",
                            "--data-format=LEI16@22050", text],
                           capture_output=True, timeout=SYNTH_TIMEOUT_S, check=True)
            with open(out, "rb") as fh:
                return fh.read()
        except Exception as e:
            log.warning("voice.say_failed", extra={"error": str(e)})
            return None
        finally:
            if os.path.exists(out):
                with contextlib.suppress(Exception):
                    os.unlink(out)

    @staticmethod
    def _wav_duration(data: bytes) -> float | None:
        try:
            with contextlib.closing(wave.open(io.BytesIO(data), "rb")) as w:
                rate = w.getframerate() or 1
                return round(w.getnframes() / float(rate), 2)
        except Exception:
            return None
