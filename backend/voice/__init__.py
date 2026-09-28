"""Phase 11 — voice: local speech-to-text (Whisper), text-to-speech (Piper/say), pipeline.

All processing is LOCAL — audio never leaves the machine. Import submodules directly
(backend.voice.stt / .tts / .pipeline); heavy deps are imported lazily so these modules
load even when whisper/piper aren't installed.
"""
