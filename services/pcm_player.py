"""Continuous PCM playback with a start buffer and cancellation token."""

from collections import deque
from threading import Event, Lock, Thread

import numpy as np
import sounddevice as sd

from services.realtime_tts import SAMPLE_RATE, SpeechCancelled
from services.sound_effects import get_sound_effects_from_config


class PcmPlayback:
    def __init__(self, config, cancel_event, beep=None):
        self.cancel_event = cancel_event
        self._lock = Lock()
        self._lifecycle_lock = Lock()
        self._chunks = deque()
        self._offset = 0
        self._queued_frames = 0
        self._complete = False
        self._ready = False
        self._finished = Event()
        self._effects = get_sound_effects_from_config(config, fresh=True, streaming=True)
        self._volume = config.get("sound", {}).get("volume", 0.8)
        self._beep = beep
        self._threshold = int(SAMPLE_RATE * max(0, config.get("openai", {}).get("tts_stream_buffer_ms", 150)) / 1000)
        # Preserve the existing protection against clipped beginnings, once per utterance.
        self._prefix = np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.float32)
        if beep is not None:
            self._prefix = np.concatenate([self._prefix, beep])
        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=480,
            callback=self._callback, finished_callback=self._finished.set,
        )
        try:
            self._stream.start()
        except Exception:
            self._stream.close()
            raise
        # Close outside PortAudio's callback thread after the final block is played.
        Thread(target=self._close_when_finished, daemon=True).start()

    def _close_when_finished(self):
        self._finished.wait()
        with self._lifecycle_lock:
            self._stream.close()

    @property
    def active(self):
        return not self.cancel_event.is_set() and not self._finished.is_set()

    def _enqueue(self, audio):
        if len(audio):
            self._chunks.append(audio)
            self._queued_frames += len(audio)

    def append(self, pcm):
        if self.cancel_event.is_set():
            raise SpeechCancelled()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        for effect in self._effects:
            # Each stream owns its effects; preserve their state across network chunks.
            audio = effect(audio, SAMPLE_RATE, reset=False)
        audio = np.clip(audio * self._volume, -1.0, 1.0)
        with self._lock:
            if self.cancel_event.is_set():
                raise SpeechCancelled()
            self._enqueue(audio)

    def finish(self):
        if self.cancel_event.is_set():
            raise SpeechCancelled()
        for index, effect in enumerate(self._effects):
            if not hasattr(effect, "flush"):
                continue
            tail = effect.flush(SAMPLE_RATE)
            if len(tail):
                # Drain each delayed effect through every effect that follows it.
                for subsequent in self._effects[index + 1:]:
                    tail = subsequent(tail, SAMPLE_RATE, reset=False)
                with self._lock:
                    if self.cancel_event.is_set():
                        raise SpeechCancelled()
                    self._enqueue(np.clip(tail * self._volume, -1.0, 1.0))
        with self._lock:
            if self.cancel_event.is_set():
                raise SpeechCancelled()
            if self._beep is not None:
                self._enqueue(np.clip(self._beep * self._volume, -1.0, 1.0))
            self._complete = True

    def abort(self):
        self.cancel_event.set()
        # abort discards device buffers immediately; stop would drain them.
        with self._lifecycle_lock:
            try:
                if not self._stream.closed:
                    self._stream.abort()
            finally:
                self._finished.set()

    def _callback(self, outdata, frames, _time, _status):
        outdata.fill(0)
        if self.cancel_event.is_set():
            raise sd.CallbackAbort
        with self._lock:
            if not self._ready:
                if (not self._queued_frames or self._queued_frames < self._threshold) and not self._complete:
                    return
                self._ready = True
                prefix = np.clip(self._prefix * self._volume, -1.0, 1.0)
                self._chunks.appendleft(prefix)
                self._queued_frames += len(prefix)
            written = 0
            while self._chunks and written < frames:
                chunk = self._chunks[0]
                count = min(frames - written, len(chunk) - self._offset)
                outdata[written:written + count, 0] = chunk[self._offset:self._offset + count]
                written += count
                self._offset += count
                self._queued_frames -= count
                if self._offset == len(chunk):
                    self._chunks.popleft()
                    self._offset = 0
            if self._complete and not self._chunks:
                raise sd.CallbackStop
            # On network gaps output silence and retain every speech sample.
