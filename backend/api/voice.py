"""
backend/api/voice.py — voice HTTP API (Phase 11), mounted at /voice.
  POST /voice/transcribe   multipart audio → {text, language, duration_s}
  POST /voice/speak        {text} → audio/wav (streamed)
  POST /voice/chat         multipart audio → transcribe + agent + TTS → audio/wav
  GET  /voice/status       {stt, tts, pipeline}

All processing is local (Whisper + Piper/say) — audio never leaves the machine.
Max upload 25MB; allowed: wav/mp3/m4a/ogg/webm.
"""
from __future__ import annotations

import io
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024
ALLOWED_EXT = {"wav", "mp3", "m4a", "ogg", "webm"}


class SpeakIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def _stt(request: Request):
    s = getattr(request.app.state, "stt", None)
    if s is None:
        raise HTTPException(status_code=503, detail="voice disabled (JARVIS_VOICE_ENABLED=false)")
    return s


def _tts(request: Request):
    t = getattr(request.app.state, "tts", None)
    if t is None:
        raise HTTPException(status_code=503, detail="voice disabled (JARVIS_VOICE_ENABLED=false)")
    return t


def _pipeline(request: Request):
    p = getattr(request.app.state, "voice", None)
    if p is None:
        raise HTTPException(status_code=503, detail="voice disabled (JARVIS_VOICE_ENABLED=false)")
    return p


async def _read_audio(file: UploadFile) -> bytes:
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"unsupported audio type; allowed: {sorted(ALLOWED_EXT)}")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"audio exceeds {MAX_AUDIO_BYTES // (1024*1024)}MB limit")
    return data


@router.post("/transcribe")
async def transcribe(request: Request, file: UploadFile = File(...)):
    data = await _read_audio(file)
    res = _stt(request).transcribe(data, filename=file.filename or "audio.wav")
    if "error" in res:
        raise HTTPException(status_code=422, detail=res["error"])
    return res


@router.post("/speak")
async def speak(body: SpeakIn, request: Request):
    res = _tts(request).synthesize(body.text)
    if "error" in res:
        raise HTTPException(status_code=422, detail=res["error"])
    return StreamingResponse(io.BytesIO(res["audio_bytes"]), media_type="audio/wav",
                             headers={"X-Duration-S": str(res.get("duration_s"))})


@router.post("/chat")
async def voice_chat(request: Request, file: UploadFile = File(...)):
    data = await _read_audio(file)
    res = await _pipeline(request).process(data, filename=file.filename or "audio.wav")
    if "error" in res and "audio_bytes" not in res:
        raise HTTPException(status_code=422, detail={"stage": res.get("stage"), "error": res["error"],
                                                     "transcript": res.get("transcript")})
    # transcript/response may contain non-latin-1 chars → URL-encode for headers
    return StreamingResponse(
        io.BytesIO(res["audio_bytes"]), media_type="audio/wav",
        headers={"X-Transcript": quote(res.get("transcript", "")),
                 "X-Response-Text": quote(res.get("response_text", ""))})


@router.get("/status")
async def status(request: Request):
    stt = getattr(request.app.state, "stt", None)
    tts = getattr(request.app.state, "tts", None)
    pipe = getattr(request.app.state, "voice", None)
    stt_ok = bool(stt and stt.available())
    tts_ok = bool(tts and tts.available())
    return {"stt": "ok" if stt_ok else "off",
            "tts": "ok" if tts_ok else "off",
            "pipeline": "ok" if (pipe is not None and stt_ok and tts_ok) else "off"}
