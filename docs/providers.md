# Provider configuration and verification

Verified against primary documentation on 2026-09-19:

- Google lists stable model ID `gemini-3.8-flash`, supporting text/image input and
  function calling: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- Official Python SDK is `google-genai`: https://googleapis.github.io/python-genai/
  and https://github.com/googleapis/python-genai . Core uses asynchronous
  `client.aio.models.generate_content`, declared JSON-schema tools, manual tool
  dispatch, preserved native response parts and inline image bytes. GenerateContent
  is now documented as a legacy API but remains in the SDK; a future Interactions
  API migration is isolated to providers.py.
- ElevenLabs REST transcription: POST `/v1/speech-to-text`, multipart file +
  model_id `scribe_v2`: https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- ElevenLabs REST synthesis: POST `/v1/text-to-speech/{voice_id}` with
  `eleven_multilingual_v2`, MP3 output:
  https://elevenlabs.io/docs/api-reference/text-to-speech/convert

Core uses the official Google SDK and httpx for the documented ElevenLabs REST API.
All cloud calls are injectable/mockable. GEMINI_MODEL, ELEVENLABS_STT_MODEL and
ELEVENLABS_TTS_MODEL override defaults. Actual account availability/quotas must be
verified with that account. Documentation verification is not a live provider test.

Set GEMINI_API_KEY and choose `--mode gemini`. Missing credentials produce a clear
configuration_error; the Core never silently switches to mocks. Optional voice needs
ELEVENLABS_API_KEY; speech output also needs an authorized ELEVENLABS_VOICE_ID.
Mock model mode does not mock ElevenLabs: audio still requires voice credentials.
Tests use an injected HTTP transport to avoid cloud requests.

Do not paste secrets in requests. Requests, selected context and consented images go
to Google in live mode; voice recordings/text go to ElevenLabs when voice is used.
Credentials only live in Core environment. Local IPC tokens are separate credentials.
