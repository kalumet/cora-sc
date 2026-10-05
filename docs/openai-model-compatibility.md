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
audio at 24 kHz to a mono WAV file in memory. With streaming enabled, the player
also receives PCM chunks during generation. The complete WAV remains available
through `response.content` for the existing audio cache.

```yaml
openai:
  tts_model: gpt-realtime-2.1-mini
  tts_voice: marin
  tts_streaming: true
  tts_stream_buffer_ms: 150
```

For Star Citizen, also set `wingmen.star-citizen-ai.openai.contexts.cora_voice`,
which overrides the global `tts_voice`. Realtime supports `alloy`, `ash`,
`ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin` and `cedar`.
Existing legacy voice settings are mapped with a warning: `nova` to `marin`,
`fable` to `ballad` and `onyx` to `cedar`. These are replacement voices, not
identical renditions of the legacy voices. Unknown voice names produce a
configuration error before connecting.

Streaming uses one continuous output stream, a configurable 150 ms start buffer
and the existing 200 ms leading silence once per utterance. Audio is played as
it arrives; network gaps insert silence without discarding speech samples.
Volume, radio/interior effects and optional start/end beeps remain supported.
`ROBOT` also streams, including in the Cora context. Its streaming path uses a
separate pitch shifter with two crossfaded delay-line readers, still targeting
one semitone down. This avoids a Pedalboard `PitchShift(reset=False)` bug that
returns silence or empty audio (see the
[upstream fix proposal](https://github.com/spotify/pedalboard/pull/486)). The
remaining delay, chorus, reverb, distortion and gain effects keep their settings
and retain state across chunks. The pitch shifter uses about 40 ms of bounded
audio history and releases its delayed final samples before the closing beep.
Cancellation prevents those delayed samples from being played.

This is a different pitch-shifting algorithm, so its texture can differ from
the original buffered `ROBOT` sound. Buffered playback and existing cache hits
continue to use the original Pedalboard effect; cache entries remain compatible
and never require a new TTS call merely because streaming is enabled. Set
`tts_streaming: false` to return to buffered playback for any model.

Each OpenAI service keeps GA Realtime sessions open per model and voice. After
the first uncached utterance, further utterances reuse the socket and skip both
the connection handshake and `session.update`. Each response supplies its own
text and voice instructions using `conversation: "none"`, so spoken responses
do not accumulate conversation history. Responses are matched by request metadata
and response ID to exclude delayed events from earlier utterances. Separate
connections are necessary because a Realtime voice cannot change after audio
has been generated. The first request for a different voice still requires setup.

Idle connections close after ten minutes (cleanup runs every thirty seconds),
and sessions rotate after 55 minutes, before the API's one-hour session limit.
The pool holds at most sixteen sessions per service and serializes requests for
the same connection, with cancellable waits. Context reload and application
shutdown close all sessions. A stale reused socket reconnects once if no audio
has arrived; a partially streamed response is never retried automatically.
Cancellation, timeout or an error discards the affected connection, so the next
uncached utterance creates a clean session. Automatic input turn detection
remains disabled and no tools are available. Only successfully completed
responses are returned or cached. Errors and interrupted responses stop playback and do not
store partial audio. The configured spoken cancellation phrases (for example,
"Abbruch") stop both live and buffered audio. A cancellation token prevents late
audio chunks or a pending buffered TTS response from restarting playback. The
existing configured acknowledgment is still spoken after cancellation.

The cache is checked before starting streaming or calling a TTS model. Existing
command cache keys and manually edited text with the regeneration flag retain
their behavior. Answers without a command key also use a key derived from the
spoken text. Cache hits play the complete stored audio through the existing
player. A newly streamed response is cached once and is not played again.

OpenAI `tts-1`, `tts-1-hd` and `gpt-4o-mini-tts` also support PCM streaming through
the Speech endpoint. Other models and providers keep their buffered path and
the same cache checks. Speech generation runs off the event loop. Realtime
receive waits check cancellation every 100 ms; connection establishment and
provider calls may take longer to return, but cancelled requests cannot play.
The Realtime generation deadline remains 120 seconds.

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
python -m unittest discover -s tests -p test_realtime_sessions.py -v
python -m unittest discover -s tests -p test_speech_streaming.py -v
python -m unittest discover -s tests -p test_streaming_pitch_shift.py -v
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
