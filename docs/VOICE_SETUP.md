# Voice setup for JARVIS (local STT → JARVIS → TTS)

Everything runs **on-device**: speech-to-text with Whisper, text-to-speech with Piper
(or the built-in macOS `say`). No audio or text is ever sent to an external service.

Voice is optional. With nothing installed, `/voice/status` reports what's available and
the endpoints return a clear error rather than failing. Disable it entirely with
`JARVIS_VOICE_ENABLED=false`.

## Speech-to-text (Whisper)
`openai-whisper` is **not** installed by default (it pulls in PyTorch and is large):
```bash
pip install openai-whisper
```
It also needs `ffmpeg` on the system:
```bash
brew install ffmpeg        # macOS
```
Model size is configurable — `JARVIS_WHISPER_MODEL` (default `base`; options
`tiny`/`base`/`small`/`medium`/`large`). The model downloads on first use and is cached.

## Text-to-speech
Two backends, tried in order:

1. **Piper** (offline neural voices) — install the CLI and a voice, then it's picked up
   automatically:
   ```bash
   pip install piper-tts
   # download a voice (e.g. en_US-lessac-medium) per piper's docs, ensure `piper` is on PATH
   ```
   Voice is set by `JARVIS_PIPER_VOICE` (default `en_US-lessac-medium`).
2. **macOS `say`** (fallback) — always present on macOS, needs no install. Used
   automatically when Piper isn't found.

## Endpoints
```bash
# transcribe an audio file
curl -F 'file=@clip.wav' http://localhost:8100/voice/transcribe

# synthesize speech (saves WAV)
curl -s -X POST http://localhost:8100/voice/speak -H 'content-type: application/json' \
     -d '{"text":"markets are open"}' --output reply.wav

# full voice turn: audio in → audio out (transcript + reply in response headers)
curl -F 'file=@question.wav' http://localhost:8100/voice/chat --output answer.wav -D -

# what's available
curl -s http://localhost:8100/voice/status | python3 -m json.tool
```
Limits: max 25MB upload; allowed types wav/mp3/m4a/ogg/webm.

## Notes
- All processing is local by design — this is a privacy guarantee, not a convenience.
- `/voice/status` returns `{stt, tts, pipeline}` as `ok`/`off` so you can see exactly
  which backends are ready.
