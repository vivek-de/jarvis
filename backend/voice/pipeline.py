"""
backend/voice/pipeline.py — STT → agent → TTS (Phase 11).
═══════════════════════════════════════════════════════════════════════════════
Chains local speech-to-text, the JARVIS agent, and local text-to-speech, logging each
stage's latency. Fully local — no audio or text leaves the machine. Errors from any
stage are returned (with the failing stage) rather than raised.
"""
from __future__ import annotations

import time

from ..logging_setup import get_logger

log = get_logger("jarvis.voice")


class VoicePipeline:
    def __init__(self, stt, tts, agent):
        self.stt = stt
        self.tts = tts
        self.agent = agent

    async def process(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        # 1) speech → text
        t0 = time.perf_counter()
        stt_res = self.stt.transcribe(audio_bytes, filename)
        stt_ms = int((time.perf_counter() - t0) * 1000)
        if "error" in stt_res:
            return {"error": stt_res["error"], "stage": "stt"}
        transcript = stt_res.get("text", "").strip()
        if not transcript:
            return {"error": "no speech detected", "stage": "stt", "transcript": ""}

        # 2) text → agent reply
        t1 = time.perf_counter()
        out = await self.agent.chat(transcript, channel="voice")
        agent_ms = int((time.perf_counter() - t1) * 1000)
        response_text = out.get("reply", "")

        # 3) reply → speech
        t2 = time.perf_counter()
        tts_res = self.tts.synthesize(response_text)
        tts_ms = int((time.perf_counter() - t2) * 1000)

        latency = {"stt": stt_ms, "agent": agent_ms, "tts": tts_ms}
        log.info("voice.pipeline", extra={"latency_ms": latency, "chars": len(response_text)})

        if "error" in tts_res:
            return {"transcript": transcript, "response_text": response_text,
                    "error": tts_res["error"], "stage": "tts", "latency_ms": latency}
        return {"transcript": transcript, "response_text": response_text,
                "audio_bytes": tts_res["audio_bytes"], "format": "wav",
                "latency_ms": latency}
