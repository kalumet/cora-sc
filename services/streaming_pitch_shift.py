"""Duration-preserving pitch shifting with two crossfaded delay-line readers."""

import numpy as np


class StreamingPitchShift:
    """Keep phase and a bounded audio history across arbitrary mono chunks.

    Moving the read position changes pitch without changing the output rate.
    Two readers half a cycle apart use complementary Hann fades, so a reader
    is silent when its delay wraps. This avoids Pedalboard's reset=False bug.
    """

    def __init__(self, semitones=-1, window_ms=40):
        self.semitones = semitones
        self.window_ms = window_ms
        self._sample_rate = None
        self._finished = False

    def _prepare(self, sample_rate):
        if self._sample_rate is not None:
            if sample_rate != self._sample_rate:
                raise ValueError("Sample rate cannot change during pitch shifting.")
            return
        if sample_rate <= 0 or self.window_ms <= 0:
            raise ValueError("Pitch shifting requires a positive rate and window.")
        self._sample_rate = sample_rate
        self._span = max(2, round(sample_rate * self.window_ms / 1000))
        self._minimum_delay = 2
        self._history = np.zeros(self._span + self._minimum_delay + 2, dtype=np.float32)
        self._phase = 0.0
        self._step = (1 - 2 ** (self.semitones / 12)) / self._span
        self._has_audio = False

    @property
    def latency_samples(self):
        """Maximum delay; also the amount of padding needed to release the tail."""
        if self._sample_rate is None or self.semitones == 0:
            return 0
        return len(self._history)

    def process(self, audio, sample_rate):
        if self._finished:
            raise RuntimeError("Pitch shifting has already finished.")
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("Streaming pitch shifting expects mono audio.")
        self._prepare(sample_rate)
        if not len(audio):
            return audio.copy()
        self._has_audio = True
        if self.semitones == 0:
            return audio.copy()
        history_size = len(self._history)
        buffer = np.concatenate([self._history, audio])
        offsets = np.arange(len(audio), dtype=np.float64)
        phase = (self._phase + offsets * self._step) % 1
        other_phase = (phase + 0.5) % 1
        positions = history_size + offsets
        first_read = positions - self._minimum_delay - phase * self._span
        second_read = positions - self._minimum_delay - other_phase * self._span

        def read(indices):
            lower = indices.astype(np.intp)
            fraction = indices - lower
            return buffer[lower] * (1 - fraction) + buffer[lower + 1] * fraction

        fade = np.sin(np.pi * phase) ** 2
        output = read(first_read) * fade + read(second_read) * (1 - fade)
        self._history = buffer[-history_size:].copy()
        self._phase = (self._phase + len(audio) * self._step) % 1
        return output.astype(np.float32)

    def finish(self):
        if self._finished:
            return np.empty(0, dtype=np.float32)
        if self._sample_rate is None or not self._has_audio:
            self._finished = True
            return np.empty(0, dtype=np.float32)
        tail = self.process(np.zeros(self.latency_samples, dtype=np.float32), self._sample_rate)
        self._finished = True
        self._history.fill(0)
        return tail


class StreamingRobotEffect:
    """Replace only ROBOT's PitchShift; keep its remaining Pedalboard effects."""

    def __init__(self, board):
        pitch_shift = board[0]
        del board[0]
        self.pitch_shift = StreamingPitchShift(semitones=pitch_shift.semitones)
        self.board = board

    def __call__(self, audio, sample_rate, reset=False):
        pitched = self.pitch_shift.process(audio, sample_rate)
        return self.board(pitched, sample_rate, reset=False) if len(pitched) else pitched

    def flush(self, sample_rate):
        tail = self.pitch_shift.finish()
        return self.board(tail, sample_rate, reset=False) if len(tail) else tail
