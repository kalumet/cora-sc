# OpenAI model compatibility

GPT-6 models use the Responses API in Wingman's conversation, summary and manager
requests. Other model names continue to use Chat Completions.

For example, this configuration supports command execution with reasoning:

```yaml
openai:
  conversation_model: gpt-6-luna
  conversation_reasoning_effort: low
  summarize_model: gpt-6-luna
  summarize_reasoning_effort: none
```

GPT-6 Luna supports function calling through Chat Completions only when reasoning
effort is `none`. Using Responses preserves the configured reasoning effort.
See the [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).

`services/openai_chat.py` converts function definitions, calls and results, and
returns the chat completion shape expected by existing command handlers.
Native output items, including encrypted reasoning, stay attached to assistant
messages in local history for follow-up requests. Requests use `store: false`.
Streaming requests are buffered until the final response and returned as a chat
completion chunk.

Manager requests map `max_tokens` to `max_output_tokens` and `response_format` to
`text.format`. The output token limit includes reasoning tokens. Sampling
parameters such as `temperature` are omitted unless reasoning effort is `none`.
Existing function schemas retain their non-strict behavior unless `strict: true`
is explicitly configured.

Supported reasoning levels depend on the model; for example, GPT-6 Astra and
GPT-6.1 Sol do not support `none`. See the
[official parameter guidance](https://developers.openai.com/api/docs/guides/latest-model#gpt-6-astra-update-api-and-model-parameters).

## Realtime text-to-speech

`gpt-realtime-2.1-mini` uses the Realtime endpoint over WebSocket, rather than
`/v1/audio/speech`. Wingman sends the already prepared spoken answer as text with
instructions to read it verbatim, collects the audio response and converts PCM16
audio at 24 kHz to a mono WAV file in memory. The existing player, effects and
cache continue to consume audio bytes through `response.content`.

```yaml
openai:
  tts_model: gpt-realtime-2.1-mini
  tts_voice: marin
```

For Star Citizen, also set `wingmen.star-citizen-ai.openai.contexts.cora_voice`,
which overrides the global `tts_voice`. Realtime supports `alloy`, `ash`,
`ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin` and `cedar`.
Existing legacy voice settings are mapped with a warning: `nova` to `marin`,
`fable` to `ballad` and `onyx` to `cedar`. These are replacement voices, not
identical renditions of the legacy voices. Unknown voice names produce a
configuration error before connecting.

Each speech request uses a fresh GA Realtime session, with automatic input turn
detection disabled and no tools. A speech response must complete successfully
before its audio is returned or cached. Server errors, incomplete responses,
disconnects, invalid audio and a 120-second deadline stop generation.

The connection uses the configured OpenAI client's API credentials, organization,
project, custom headers and base URL. It uses the existing `websockets==12.0`
dependency directly; no additional SDK upgrade is needed for this TTS path.
The retired Realtime beta header is excluded.

Explicitly configured legacy speech models retain their existing REST path.
OpenAI lists January 6, 2027 as the retirement date for `tts-1`, `tts-1-hd` and
the deprecated GPT-4o Mini TTS snapshots, recommending `gpt-realtime-2.1-mini`.
See the [model documentation](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini),
[Realtime conversation and voice guide](https://developers.openai.com/api/docs/guides/realtime-conversations)
and [deprecation notice](https://developers.openai.com/api/docs/deprecations#2026-10-01-text-to-speech-models).

The Realtime TTS regression tests use simulated server events and verify the
returned WAV samples and existing `OpenAi.speak` integration:

```sh
python -m unittest discover -s tests -p test_realtime_tts.py -v
```

## Dependencies and chat regression tests

The dependency file now pins `openai==1.75.0`, matching the project's existing
Windows environment and providing Responses support. The previous `1.58.1` pin
predates that API. If necessary, update the active virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install openai==1.75.0
```

Regression tests use the real SDK with simulated HTTP responses; no API key or
live API calls are required:

```sh
python -m unittest discover -s tests -p test_openai_chat.py -v
```
