"""PCM streaming for the Speech endpoint; return a complete WAV for caching."""

from threading import Event, Thread

from services.realtime_tts import SpeechCancelled, pcm_to_wav


STREAMING_SPEECH_MODELS = frozenset({"tts-1", "tts-1-hd", "gpt-4o-mini-tts"})


def synthesize_streaming_speech(client, text, model, voice, voice_instruction,
                               player_language, on_audio, cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise SpeechCancelled()
    request = dict(model=model, voice=voice, input=text, response_format="pcm", timeout=120)
    if model == "gpt-4o-mini-tts":
        request["instructions"] = f"{voice_instruction} Please speak in {player_language}."
    pcm = bytearray()
    streamed_bytes = 0
    with client.audio.speech.with_streaming_response.create(**request) as response:
        finished = Event()

        def close_on_cancel():
            while not finished.wait(0.1):
                if cancel_event.is_set():
                    response.close()
                    return

        watcher = None
        if cancel_event is not None:
            watcher = Thread(target=close_on_cancel, daemon=True)
            watcher.start()
        try:
            for chunk in response.iter_bytes(chunk_size=4800):
                if cancel_event is not None and cancel_event.is_set():
                    raise SpeechCancelled()
                pcm.extend(chunk)
                end = len(pcm) - len(pcm) % 2
                if end > streamed_bytes:
                    on_audio(bytes(pcm[streamed_bytes:end]))
                    streamed_bytes = end
        except Exception:
            if cancel_event is not None and cancel_event.is_set():
                raise SpeechCancelled() from None
            raise
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=1)
    if cancel_event is not None and cancel_event.is_set():
        raise SpeechCancelled()
    return pcm_to_wav(pcm)
