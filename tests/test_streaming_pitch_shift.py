"""Signal checks for the streaming pitch shifter without audio hardware."""

import unittest

import numpy as np

from services.streaming_pitch_shift import StreamingPitchShift


RATE = 24000


class StreamingPitchShiftTests(unittest.TestCase):
    def test_pitch_is_one_semitone_lower_without_resampling_the_duration(self):
        audio = (0.5 * np.sin(2 * np.pi * 440 * np.arange(RATE * 4) / RATE)).astype(np.float32)
        shift = StreamingPitchShift(semitones=-1)
        output = np.concatenate([
            *[shift.process(audio[start:start + 2400], RATE) for start in range(0, len(audio), 2400)],
            shift.finish(),
        ])
        self.assertEqual(len(output), len(audio) + shift.latency_samples)
        middle = output[RATE:-RATE]
        spectrum = np.abs(np.fft.rfft(middle * np.hanning(len(middle))))
        frequencies = np.fft.rfftfreq(len(middle), 1 / RATE)
        actual = frequencies[np.argmax(spectrum)]
        self.assertAlmostEqual(actual, 440 * 2 ** (-1 / 12), delta=1.5)
        self.assertGreater(np.sqrt(np.mean(middle ** 2)), 0.1)

    def test_arbitrary_chunk_boundaries_produce_the_same_continuous_signal(self):
        audio = np.random.default_rng(1234).uniform(-0.8, 0.8, RATE * 2).astype(np.float32)
        whole = StreamingPitchShift()
        expected = np.concatenate([whole.process(audio, RATE), whole.finish()])
        chunked = StreamingPitchShift()
        blocks = []
        start = 0
        sizes = (1, 17, 480, 2400, 63, 8192)
        while start < len(audio):
            size = sizes[len(blocks) % len(sizes)]
            blocks.append(chunked.process(audio[start:start + size], RATE))
            start += size
        blocks.append(chunked.finish())
        np.testing.assert_allclose(np.concatenate(blocks), expected, atol=1e-6)

    def test_first_and_last_impulses_are_preserved_including_single_sample_answer(self):
        for length in (1, 100, RATE):
            for position in (0, length - 1):
                with self.subTest(length=length, position=position):
                    audio = np.zeros(length, dtype=np.float32)
                    audio[position] = 0.5
                    shift = StreamingPitchShift()
                    output = np.concatenate([shift.process(audio, RATE), shift.finish()])
                    self.assertGreater(np.max(np.abs(output)), 0.1)
                    if position == length - 1:
                        self.assertTrue(output[length:].any())
                    self.assertTrue(np.isfinite(output).all())

    def test_zero_shift_is_exact_and_has_no_tail(self):
        audio = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
        shift = StreamingPitchShift(semitones=0)
        np.testing.assert_array_equal(shift.process(audio, RATE), audio)
        self.assertEqual(len(shift.finish()), 0)

    def test_history_memory_is_bounded_and_tail_is_released_only_once(self):
        shift = StreamingPitchShift()
        for _ in range(100):
            shift.process(np.ones(2400, dtype=np.float32), RATE)
            self.assertEqual(len(shift._history), shift.latency_samples)
        self.assertEqual(len(shift.finish()), shift.latency_samples)
        self.assertEqual(len(shift.finish()), 0)
        self.assertFalse(shift._history.any())
        with self.assertRaises(RuntimeError):
            shift.process(np.ones(480, dtype=np.float32), RATE)

    def test_empty_stream_and_empty_network_chunk_do_not_create_audio(self):
        shift = StreamingPitchShift()
        self.assertEqual(len(shift.process(np.empty(0, dtype=np.float32), RATE)), 0)
        self.assertEqual(len(shift.finish()), 0)


if __name__ == "__main__":
    unittest.main()
