"""Verify live playback, interruption and cache routing without audio hardware."""

import asyncio
import io
import json
from threading import Event
import unittest
from unittest.mock import Mock, patch
import wave

import httpx
import numpy as np
from openai import OpenAI
import sounddevice as sd

from services.audio_player import AudioPlayer
from services.pcm_player import PcmPlayback
from services.realtime_tts import SpeechCancelled, pcm_to_wav
from services.streaming_tts import synthesize_streaming_speech
from test_instant_command_cache import load_class


namespace = {"asyncio": asyncio, "printr": Mock()}
Wingman = load_class("wingmen/open_ai_wingman.py", "OpenAiWingman", {
    "_play_to_user", "_play_to_user_sync",
}, namespace)


class FakeOutputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.finished_callback = kwargs["finished_callback"]
        self.closed = False
        self.started = False
        self.was_aborted = False
        self.closed_event = Event()

    def start(self):
        self.started = True

    def abort(self):
        self.was_aborted = True
        self.finished_callback()

    def close(self):
        self.closed = True
        self.closed_event.set()

    def pump(self, frames=480):
        output = np.zeros((frames, 1), dtype=np.float32)
        done = False
        try:
            self.callback(output, frames, None, None)
        except sd.CallbackStop:
            self.finished_callback()
            done = True
        except sd.CallbackAbort:
            self.finished_callback()
            raise
        return output[:, 0], done


class PcmPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.streams = []

        def create(**kwargs):
            stream = FakeOutputStream(**kwargs)
            self.streams.append(stream)
            return stream

        self.enterContext(patch("services.pcm_player.sd.OutputStream", side_effect=create))
        self.enterContext(patch("services.audio_player.sd.stop"))
        self.play = self.enterContext(patch("services.audio_player.sd.play"))

    def tearDown(self):
        AudioPlayer.stop_all()

    def playback(self, **kwargs):
        playback = PcmPlayback({"openai": {"tts_stream_buffer_ms": 150},
                                "sound": {"volume": 1}, **kwargs}, Event())
        self.addCleanup(playback.abort)
        return playback

    def drain(self, stream):
        blocks = []
        for _ in range(1000):
            audio, done = stream.pump()
            blocks.append(audio)
            if done:
                self.assertTrue(stream.closed_event.wait(1))
                return np.concatenate(blocks)
        self.fail("stream did not finish")

    def test_start_buffer_then_single_leading_silence_and_exact_speech_samples(self):
        playback = self.playback()
        stream = self.streams[-1]
        self.assertTrue(stream.started)
        pcm = np.arange(4800, dtype=np.int16)
        playback.append(pcm[:1000].tobytes())
        before, done = stream.pump()
        self.assertFalse(done)
        self.assertFalse(before.any())
        self.assertEqual(playback._queued_frames, 1000)
        playback.append(pcm[1000:].tobytes())
        # Audio starts before generation is marked complete.
        blocks = [stream.pump()[0] for _ in range(11)]
        self.assertTrue(blocks[-1].any())
        playback.finish()
        output = np.concatenate(blocks + [self.drain(stream)])
        np.testing.assert_array_equal(output[:4800], np.zeros(4800))
        np.testing.assert_array_equal(output[4800:9600], pcm.astype(np.float32) / 32768)

    def test_short_answer_drains_even_when_smaller_than_start_buffer(self):
        playback = self.playback()
        pcm = np.full(100, 1234, dtype=np.int16)
        playback.append(pcm.tobytes())
        playback.finish()
        output = self.drain(self.streams[-1])
        np.testing.assert_array_equal(output[4800:4900], pcm.astype(np.float32) / 32768)

    def test_network_gap_emits_silence_without_losing_later_samples(self):
        playback = self.playback(openai={"tts_stream_buffer_ms": 0})
        first = np.full(480, 2000, dtype=np.int16)
        second = np.full(480, -2000, dtype=np.int16)
        playback.append(first.tobytes())
        for _ in range(10):
            self.streams[-1].pump()
        actual, _ = self.streams[-1].pump()
        np.testing.assert_array_equal(actual, first.astype(np.float32) / 32768)
        gap, _ = self.streams[-1].pump()
        self.assertFalse(gap.any())
        playback.append(second.tobytes())
        playback.finish()
        np.testing.assert_array_equal(self.drain(self.streams[-1]), second.astype(np.float32) / 32768)

    def test_cancel_aborts_device_and_rejects_late_audio_and_finish(self):
        playback = self.playback()
        playback.append(np.ones(4800, dtype=np.int16).tobytes())
        playback.abort()
        self.assertTrue(self.streams[-1].was_aborted)
        for operation in (lambda: playback.append(b"\x00\x00"), playback.finish):
            with self.assertRaises(SpeechCancelled):
                operation()

    def test_stop_all_cancels_live_and_buffered_requests_but_allows_new_speech(self):
        first = AudioPlayer({})
        cancel = first.begin_speech()
        playback = first.start_pcm_stream({}, cancel)
        AudioPlayer.stop_all()
        self.assertTrue(cancel.is_set())
        with self.assertRaises(SpeechCancelled):
            playback.append(b"\x00\x00")
        first.stream_with_effects(pcm_to_wav(b"\x00\x00").content, {}, cancel_event=cancel)
        self.play.assert_not_called()
        self.assertFalse(first.begin_speech().is_set())

    def test_macro_busy_detection_includes_live_streams(self):
        player = AudioPlayer({})
        with patch("services.audio_player.sd.get_stream", return_value=None):
            self.assertFalse(AudioPlayer.is_busy())
            player.start_pcm_stream({}, player.begin_speech())
            self.assertTrue(AudioPlayer.is_busy())
            AudioPlayer.stop_all()
            self.assertFalse(AudioPlayer.is_busy())

    def test_effects_are_independent_and_preserve_short_speech_length(self):
        playback = self.playback(sound={"effects": ["RADIO"], "volume": 1})
        second = self.playback(sound={"effects": ["RADIO"], "volume": 1})
        self.assertIsNot(playback._effects[0], second._effects[0])
        pcm = (np.sin(np.arange(2400) / 10) * 15000).astype(np.int16)
        playback.append(pcm.tobytes())
        playback.finish()
        self.assertTrue(self.drain(self.streams[0])[4800:7200].any())

    def test_robot_starts_before_completion_and_releases_short_speech_tail(self):
        playback = self.playback(sound={"effects": ["ROBOT"], "volume": 1})
        audio = (np.sin(np.arange(4800) / 10) * 15000).astype(np.int16)
        playback.append(audio.tobytes())
        stream = self.streams[-1]
        blocks = [stream.pump()[0] for _ in range(12)]
        self.assertTrue(np.concatenate(blocks)[4800:].any())
        playback.finish()
        output = np.concatenate(blocks + [self.drain(stream)])
        self.assertTrue(output[9600:].any())

    def test_robot_single_sample_and_last_word_are_not_silent_or_truncated(self):
        for length in (1, 100, 2400):
            with self.subTest(length=length):
                playback = self.playback(sound={"effects": ["ROBOT"], "volume": 1})
                audio = np.zeros(length, dtype=np.int16)
                audio[0] = audio[-1] = 15000
                playback.append(audio.tobytes())
                playback.finish()
                output = self.drain(self.streams[-1])[4800:]
                self.assertTrue(output.any())
                self.assertTrue(output[length:].any())

    def test_robot_abort_discards_delayed_tail_and_rejects_late_chunks(self):
        playback = self.playback(sound={"effects": ["ROBOT"], "volume": 1})
        playback.append(np.ones(100, dtype=np.int16).tobytes())
        queued = playback._queued_frames
        playback.abort()
        with self.assertRaises(SpeechCancelled):
            playback.finish()
        self.assertEqual(playback._queued_frames, queued)
        with self.assertRaises(SpeechCancelled):
            playback.append(np.ones(2400, dtype=np.int16).tobytes())

    def test_robot_tail_is_processed_through_following_effects(self):
        playback = self.playback(sound={"effects": ["ROBOT", "RADIO", "INTERIOR_HELMET"], "volume": 1})
        audio = np.zeros(100, dtype=np.int16)
        audio[-1] = 15000
        playback.append(audio.tobytes())
        playback.finish()
        self.assertTrue(self.drain(self.streams[-1])[4900:].any())

    def test_beeps_are_added_once_before_and_after_speech(self):
        beep = np.full(480, 0.5, dtype=np.float32)
        playback = PcmPlayback({"sound": {"volume": 1}}, Event(), beep=beep)
        self.addCleanup(playback.abort)
        playback.append(np.full(480, -16384, dtype=np.int16).tobytes())
        playback.finish()
        output = self.drain(self.streams[-1])
        np.testing.assert_array_equal(output[4800:5280], beep)
        np.testing.assert_array_equal(output[5280:5760], -beep)
        np.testing.assert_array_equal(output[5760:6240], beep)


class SpeechCacheRoutingTests(unittest.TestCase):
    def setUp(self):
        self.w = Wingman()
        w = self.w
        w.config = {"openai": {"tts_model": "gpt-realtime-2.1-mini"}}
        w.tts_provider = "openai"
        w.openai = Mock()
        w.openai.supports_speech_streaming.return_value = True
        w.audio_player = Mock()
        w.audio_player.begin_speech.side_effect = Event
        w._generate_cache_key = lambda text: "text:" + text
        w._log_debug_event = Mock()
        w._truncate_debug_value = lambda text, limit: text
        w._generate_with_openai = Mock(return_value=b"complete wav")
        w._generate_with_azure = Mock(return_value=b"azure wav")
        w._generate_with_elevenlabs = Mock(return_value=b"elevenlabs wav")
        w.tts_cache_manager = Mock()
        w.tts_cache_manager.get.return_value = None
        w.tts_cache_manager.needs_tts_update.return_value = False

    def run_speech(self, key=None):
        asyncio.run(self.w._play_to_user("Hallo Cora", key))

    def test_cached_audio_bypasses_every_model_and_stream_start(self):
        self.w.tts_cache_manager.get.return_value = b"cached wav"
        self.run_speech("command-key")
        self.w._generate_with_openai.assert_not_called()
        self.w.audio_player.start_pcm_stream.assert_not_called()
        self.w.audio_player.stream_with_effects.assert_called_once()
        self.assertEqual(self.w.audio_player.stream_with_effects.call_args.args[0], b"cached wav")

    def test_normal_answer_without_command_key_uses_text_cache(self):
        self.w.tts_cache_manager.get.return_value = b"cached wav"
        self.run_speech()
        self.w.tts_cache_manager.get.assert_called_once_with("text:Hallo Cora")
        self.w._generate_with_openai.assert_not_called()

    def test_repeated_answer_calls_tts_only_once_then_uses_stored_audio(self):
        stored = {}
        self.w.tts_cache_manager.get.side_effect = stored.get
        self.w.tts_cache_manager.put.side_effect = lambda **entry: stored.update({entry["key"]: entry["data"]})
        self.run_speech()
        self.run_speech()
        self.w._generate_with_openai.assert_called_once()
        self.w.audio_player.start_pcm_stream.assert_called_once()
        self.w.audio_player.stream_with_effects.assert_called_once()
        self.assertEqual(self.w.audio_player.stream_with_effects.call_args.args[0], b"complete wav")

    def test_failed_live_generation_aborts_without_caching(self):
        self.w._generate_with_openai.return_value = None
        self.run_speech()
        self.w.audio_player.start_pcm_stream.return_value.abort.assert_called_once()
        self.w.tts_cache_manager.put.assert_not_called()

    def test_live_generation_finishes_and_caches_without_replaying(self):
        self.run_speech("command-key")
        playback = self.w.audio_player.start_pcm_stream.return_value
        playback.finish.assert_called_once()
        playback.abort.assert_not_called()
        self.w.tts_cache_manager.put.assert_called_once_with(
            key="command-key", data=b"complete wav", storage_mode="bytes",
            file_extension=".wav", key_text="Hallo Cora")
        self.w.audio_player.stream_with_effects.assert_not_called()

    def test_interruption_never_caches_or_replays_partial_stream(self):
        def generate(text, on_audio, cancel_event):
            on_audio(b"first chunk")
            cancel_event.set()
            return None

        self.w._generate_with_openai.side_effect = generate
        self.run_speech()
        playback = self.w.audio_player.start_pcm_stream.return_value
        playback.abort.assert_called_once()
        playback.finish.assert_not_called()
        self.w.tts_cache_manager.put.assert_not_called()
        self.w.audio_player.stream_with_effects.assert_not_called()

    def test_provider_model_and_config_fallbacks_keep_buffered_playback_and_cache(self):
        for mode in ("azure", "elevenlabs", "unsupported", "disabled"):
            with self.subTest(mode=mode):
                self.setUp()
                if mode in {"azure", "elevenlabs"}:
                    self.w.tts_provider = mode
                elif mode == "unsupported":
                    self.w.openai.supports_speech_streaming.return_value = False
                else:
                    self.w.config["openai"]["tts_streaming"] = False
                self.run_speech()
                self.w.audio_player.start_pcm_stream.assert_not_called()
                self.w.audio_player.stream_with_effects.assert_called_once()
                self.w.tts_cache_manager.put.assert_called_once()

    def test_cora_robot_effect_streams_and_reuses_cached_answer(self):
        self.w.config["sound"] = {"effects": ["ROBOT"]}
        stored = {}
        self.w.tts_cache_manager.get.side_effect = stored.get
        self.w.tts_cache_manager.put.side_effect = lambda **entry: stored.update({entry["key"]: entry["data"]})
        self.run_speech()
        self.w.audio_player.start_pcm_stream.assert_called_once()
        self.w.audio_player.start_pcm_stream.return_value.finish.assert_called_once()
        self.run_speech()
        self.w._generate_with_openai.assert_called_once()
        self.w.audio_player.stream_with_effects.assert_called_once()

    def test_interrupted_buffered_generation_does_not_restart_audio(self):
        self.w.tts_provider = "azure"
        cancel = Event()
        self.w.audio_player.begin_speech.return_value = cancel
        self.w.audio_player.begin_speech.side_effect = None
        self.w._generate_with_azure.side_effect = lambda text: (cancel.set(), b"wav")[1]
        self.run_speech()
        self.w.audio_player.stream_with_effects.assert_not_called()
        self.w.tts_cache_manager.put.assert_not_called()

    def test_edited_cached_text_is_regenerated_and_update_flag_is_reset_by_put(self):
        self.w.tts_cache_manager.get.return_value = b"old wav"
        self.w.tts_cache_manager.needs_tts_update.return_value = True
        self.w.tts_cache_manager.get_cached_text.return_value = "Edited answer"
        self.run_speech("command-key")
        self.assertEqual(self.w._generate_with_openai.call_args.args[0], "Edited answer")
        self.assertEqual(self.w.tts_cache_manager.put.call_args.kwargs["key_text"], "Edited answer")


class SpeechEndpointStreamingTests(unittest.TestCase):
    def test_real_sdk_pcm_stream_returns_complete_wav_and_preserves_odd_boundaries(self):
        requests = []
        pcm = np.arange(4801, dtype=np.int16).tobytes()

        class Body(httpx.SyncByteStream):
            def __iter__(self):
                yield pcm[:1]
                yield pcm[1:5001]
                yield pcm[5001:]

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "audio/pcm"}, stream=Body())

        with OpenAI(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
            chunks = []
            result = synthesize_streaming_speech(client, "Hallo", "tts-1", "nova", "", "de_DE", chunks.append, Event())
        self.assertEqual(b"".join(chunks), pcm)
        self.assertTrue(all(len(chunk) % 2 == 0 for chunk in chunks))
        self.assertEqual(requests[0]["response_format"], "pcm")
        self.assertNotIn("instructions", requests[0])
        with wave.open(io.BytesIO(result.content), "rb") as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)

    def test_cancelled_speech_endpoint_does_not_return_partial_wav(self):
        cancel = Event()

        class Body(httpx.SyncByteStream):
            def __iter__(self):
                yield b"\x00\x00" * 4800
                yield b"\x01\x00" * 4800

        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
        with OpenAI(api_key="test-key", http_client=httpx.Client(transport=transport)) as client:
            with self.assertRaises(SpeechCancelled):
                synthesize_streaming_speech(client, "Hallo", "tts-1", "nova", "", "de_DE", lambda chunk: cancel.set(), cancel)


class SpokenCancellationTests(unittest.TestCase):
    def test_spoken_abort_stops_audio_before_acknowledgment_and_skips_model(self):
        from unittest.mock import AsyncMock

        printer = Mock()
        cls = load_class("wingmen/wingman.py", "Wingman", {"process"}, {"printr": printer})
        wingman = cls()
        wingman.debug = False
        wingman.name = "Cora"
        wingman.transcript_ignore_response = "Ok, befehl ignoriert"
        wingman.start_execution_benchmark = Mock()
        wingman._transcribe = AsyncMock(return_value=("Abbruch", "de_DE"))
        wingman._should_ignore_transcript = Mock(return_value=True)
        wingman._get_response_for_transcript = AsyncMock()
        wingman._generate_cache_key = lambda text: text
        calls = []
        wingman.audio_player = Mock()
        wingman.audio_player.stop.side_effect = lambda: calls.append("stop")
        wingman._play_to_user = AsyncMock(side_effect=lambda *args, **kwargs: calls.append("acknowledge"))
        asyncio.run(wingman.process("recording.wav"))
        self.assertEqual(calls, ["stop", "acknowledge"])
        wingman._get_response_for_transcript.assert_not_called()


if __name__ == "__main__":
    unittest.main()
