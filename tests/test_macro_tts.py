"""Verify macro TTS routing and countdown caching without desktop dependencies."""

import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from typing import Any, Optional
import unittest
from unittest.mock import Mock, patch
import wave

import httpx
from openai import APIStatusError, OpenAI

from services.realtime_tts import (
    RealtimeSessionPool, is_realtime_model, resolve_realtime_voice,
    synthesize_realtime_speech,
)
from test_instant_command_cache import load_class
from test_realtime_sessions import PersistentConnection
from test_realtime_tts import PCM


MACRO_PATH = "wingmen/star_citizen_services/functions/macro_services/macro_manager.py"


class MacroTtsTests(unittest.TestCase):
    def setUp(self):
        self.printer = Mock()
        self.namespace = {
            "Any": Any, "Optional": Optional, "threading": threading,
            "time": Mock(), "hashlib": hashlib, "json": json,
            "OpenAI": Mock(), "AzureOpenAI": Mock(), "APIStatusError": APIStatusError,
            "AudioPlayer": Mock(), "sd": Mock(), "printr": self.printer,
            "is_realtime_model": is_realtime_model,
            "resolve_realtime_voice": resolve_realtime_voice,
            "synthesize_realtime_speech": synthesize_realtime_speech,
            "RealtimeSessionPool": RealtimeSessionPool,
        }
        cls = load_class(MACRO_PATH, "MacroManager", {
            "_generate_openai_tts_audio", "_generate_azure_tts_audio", "_generate_tts_audio",
            "_get_or_generate_tts_audio", "_get_or_generate_tts_audio_meta",
            "_resolve_tts_model", "_resolve_tts_voice", "_get_player_language_code",
            "_get_or_prepare_spoken_text", "_save_spoken_text_cache", "_speak_text",
            "_run_countdown", "_build_countdown_announcement_plan", "_countdown_step_seconds",
            "_countdown_minutes_left_text", "_countdown_thirty_seconds_text",
            "_countdown_number_text", "_countdown_finished_text", "_clean_optional_text",
            "_collect_tts_texts_for_macro", "_warmup_macro_tts_cache", "_is_audio_output_busy",
            "on_manager_enabled", "on_manager_disabled", "close_speech_sessions",
        }, self.namespace)
        self.manager = cls()
        m = self.manager
        m.name = "MacroManager"
        m.config = {
            "features": {"tts_provider": "openai"},
            "openai": {
                "tts_model": "gpt-realtime-2.1-mini", "tts_voice": "marin",
                "player_language": "de_DE", "tts_voice_instructions": "Calm ship computer",
                "organization": "test-org", "base_url": "https://example.invalid/v1",
            },
        }
        self.client = OpenAI(api_key="test-key")
        self.addCleanup(self.client.close)
        m._openai_tts_client = self.client
        m._azure_tts_client = None
        m.secret_keeper = Mock()
        m.secret_keeper.retrieve.return_value = "test-key"
        m._realtime_tts_sessions = RealtimeSessionPool()
        self.addCleanup(lambda: m._realtime_tts_sessions.close())
        directory = self.enterContext(TemporaryDirectory(prefix="wingman-macro-tts-"))
        m.tts_cache_path = Path(directory)
        m.tts_text_cache_file = m.tts_cache_path / "spoken_text_cache.json"
        m._spoken_text_cache = {}
        m._tts_text_cache_lock = threading.RLock()
        m._prepare_spoken_text_with_model = Mock(side_effect=lambda text, language_code: text)
        m.audio_player = Mock()
        self.namespace["AudioPlayer"].is_busy.return_value = False
        m.stop_all_macros = Mock()
        m.load_macro_definitions = Mock()
        m._activate_enabled_macros_from_disk = Mock()
        self.connections = []

        def connect(*args, **kwargs):
            connection = PersistentConnection()
            self.connections.append(connection)
            return connection

        self.connector = self.enterContext(patch("services.realtime_tts.connect", side_effect=connect))
        self.rest = self.enterContext(patch.object(self.client.audio.speech, "create"))
        self.rest.return_value = Mock(content=b"rest-audio")

    def generate(self, **kwargs):
        return self.manager._generate_openai_tts_audio(**{
            "model": "gpt-realtime-2.1-mini", "voice": "marin",
            "player_language": "de_DE", "text": "Zehn.", **kwargs,
        })

    def assert_pcm(self, content):
        with wave.open(io.BytesIO(content), "rb") as wav:
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)

    def test_realtime_model_uses_websocket_and_returns_complete_wav(self):
        self.assert_pcm(self.generate())
        self.rest.assert_not_called()
        request = self.connections[0].sent[-1]["response"]
        self.assertEqual(request["input"][0]["content"][0]["text"], "Zehn.")
        self.assertEqual(request["conversation"], "none")
        self.assertIn("Calm ship computer", request["instructions"])
        self.assertIn("de_DE", request["instructions"])

    def test_multiple_announcements_reuse_session_and_legacy_voice_alias(self):
        self.generate(text="Zehn.", voice="nova")
        self.generate(text="Neun.", voice="marin")
        self.connector.assert_called_once()
        self.rest.assert_not_called()
        self.printer.print_warn.assert_called_once()
        session = self.connections[0].sent[0]["session"]
        self.assertEqual(session["audio"]["output"]["voice"], "marin")
        self.assertEqual([event["type"] for event in self.connections[0].sent], [
            "session.update", "response.create", "response.create",
        ])

    def test_client_initialization_preserves_configured_endpoint_and_credentials(self):
        self.manager._openai_tts_client = None
        self.namespace["OpenAI"].return_value = self.client
        self.generate()
        self.generate(text="Neun.")
        self.namespace["OpenAI"].assert_called_once_with(
            api_key="test-key", organization="test-org", base_url="https://example.invalid/v1",
        )
        self.manager.secret_keeper.retrieve.assert_called_once()

    def test_missing_key_fails_without_connecting(self):
        self.manager._openai_tts_client = None
        self.manager.secret_keeper.retrieve.return_value = None
        with self.assertRaisesRegex(RuntimeError, "API key is required"):
            self.generate()
        self.connector.assert_not_called()
        self.namespace["OpenAI"].assert_not_called()

    def test_unknown_realtime_voice_fails_without_calling_rest_or_websocket(self):
        with self.assertRaisesRegex(RuntimeError, "OpenAI macro TTS failed.*Unbekannte"):
            self.generate(voice="typo")
        self.rest.assert_not_called()
        self.connector.assert_not_called()

    def test_rest_models_keep_speech_endpoint_and_instructions(self):
        for model in ("tts-1", "tts-1-hd", "gpt-4o-mini-tts", "custom-tts-model"):
            with self.subTest(model=model):
                self.assertEqual(self.generate(model=model, voice="nova"), b"rest-audio")
                request = self.rest.call_args.kwargs
                self.assertEqual(request["model"], model)
                self.assertEqual(request["voice"], "nova")
                self.assertEqual("instructions" in request, model == "gpt-4o-mini-tts")
                if model == "gpt-4o-mini-tts":
                    self.assertIn("Calm ship computer", request["instructions"])
                    self.assertIn("de_DE", request["instructions"])
        self.connector.assert_not_called()

    def test_azure_keeps_configured_deployment_and_endpoint(self):
        client = Mock()
        client.audio.speech.create.return_value = Mock(content=b"azure-audio")
        self.manager._azure_tts_client = client
        result = self.manager._generate_tts_audio(
            provider="azure", model="azure-deployment", voice="nova",
            player_language="de_DE", text="Zehn.",
        )
        self.assertEqual(result, b"azure-audio")
        client.audio.speech.create.assert_called_once_with(
            model="azure-deployment", voice="nova", input="Zehn.",
        )
        self.connector.assert_not_called()
        self.rest.assert_not_called()

    def test_existing_audio_cache_key_is_used_before_tts_call(self):
        key = hashlib.sha256(b"openai|gpt-realtime-2.1-mini|marin|de_DE|Zehn.").hexdigest()
        (self.manager.tts_cache_path / f"{key}.wav").write_bytes(b"cached-macro-audio")
        self.assertEqual(self.manager._get_or_generate_tts_audio_meta("Zehn."), (
            b"cached-macro-audio", False, True,
        ))
        self.connector.assert_not_called()
        self.rest.assert_not_called()

    def test_generated_audio_and_spoken_text_are_cached_and_reused(self):
        first, generated, prepared = self.manager._get_or_generate_tts_audio_meta("Zehn.")
        self.assertTrue(generated)
        self.assertTrue(prepared)
        self.assert_pcm(first)
        self.assertEqual(self.manager._get_or_generate_tts_audio_meta("Zehn."), (first, False, False))
        self.assertEqual(self.connections[0].responses, 1)
        self.manager._prepare_spoken_text_with_model.assert_called_once()
        self.assertEqual(len(list(self.manager.tts_cache_path.glob("*.wav"))), 1)

    def test_failed_realtime_response_leaves_no_audio_cache(self):
        self.generate()  # Establish a usable session before an API error.
        self.connections[0].respond = lambda request: [{
            "type": "error", "error": {"message": "Rejected macro request"},
        }]
        with self.assertRaisesRegex(RuntimeError, "OpenAI macro TTS failed.*Rejected macro request"):
            self.manager._get_or_generate_tts_audio_meta("Neun.")
        self.assertEqual(list(self.manager.tts_cache_path.glob("*.wav")), [])
        self.assertTrue(self.connections[0].closed)
        self.rest.assert_not_called()

    def test_rest_error_keeps_status_code_in_macro_error(self):
        self.rest.side_effect = APIStatusError(
            "Rejected", response=httpx.Response(403, request=httpx.Request("POST", "https://example.invalid")),
            body=None,
        )
        with self.assertRaisesRegex(RuntimeError, r"OpenAI macro TTS failed \(403\)"):
            self.generate(model="tts-1")

    def test_countdown_announcements_play_then_reuse_audio_on_second_countdown(self):
        macro = {"duration_seconds": 1, "text": "Countdown finished."}
        self.manager._sleep_interruptible = Mock(return_value=True)
        for _ in range(2):
            self.namespace["time"].time.side_effect = [0, 0, 1]
            self.assertTrue(self.manager._run_countdown(macro, threading.Event()))
        self.assertEqual(self.manager.audio_player.stream_with_effects.call_count, 6)
        for call in self.manager.audio_player.stream_with_effects.call_args_list:
            self.assert_pcm(call.args[0])
            self.assertTrue(call.kwargs["wait"])
        self.connector.assert_called_once()
        self.assertEqual(self.connections[0].responses, 3)
        self.assertEqual(self.manager._prepare_spoken_text_with_model.call_count, 3)
        self.rest.assert_not_called()

    def test_cache_warmup_uses_realtime_and_second_pass_needs_no_tts(self):
        macro = {"type": "countdown", "duration_seconds": 1}
        self.assertEqual(self.manager._warmup_macro_tts_cache(macro), {
            "total_texts": 3, "audio_generated": 3, "spoken_text_generated": 3,
        })
        self.assertEqual(self.manager._warmup_macro_tts_cache(macro), {
            "total_texts": 3, "audio_generated": 0, "spoken_text_generated": 0,
        })
        self.connector.assert_called_once()
        self.rest.assert_not_called()

    def test_disabling_stops_jobs_and_closes_sessions_then_reenabling_can_speak(self):
        self.generate()
        previous = self.manager._realtime_tts_sessions
        self.manager.on_manager_disabled()
        self.manager.stop_all_macros.assert_called_once_with(persist_state=False)
        self.assertTrue(self.connections[0].closed)
        self.manager.on_manager_enabled()
        self.assertIsNot(self.manager._realtime_tts_sessions, previous)
        self.manager.load_macro_definitions.assert_called_once()
        self.manager._activate_enabled_macros_from_disk.assert_called_once()
        self.assert_pcm(self.generate())
        self.assertEqual(self.connector.call_count, 2)

    def test_sessions_close_even_if_job_cleanup_fails(self):
        self.generate()
        self.manager.stop_all_macros.side_effect = RuntimeError("job cleanup failed")
        with self.assertRaisesRegex(RuntimeError, "job cleanup failed"):
            self.manager.close_speech_sessions()
        self.assertTrue(self.connections[0].closed)

    def test_star_citizen_closes_manager_sessions_and_main_speech_sessions(self):
        self.generate()
        namespace = {"printr": self.printer}
        base = load_class("wingmen/open_ai_wingman.py", "OpenAiWingman", {"close_speech_sessions"}, namespace)
        cls = load_class("wingmen/star_citizen_wingman.py", "StarCitizenWingman", {
            "close_speech_sessions",
        }, namespace, (base.__name__,))
        wingman = cls()
        wingman.openai = Mock()
        wingman.ai_functions_manager = Mock()
        broken = Mock()
        broken.close_speech_sessions.side_effect = RuntimeError("failed")
        wingman.ai_functions_manager.manager_instances = {
            "other": object(), "broken": broken, "MacroManager": self.manager,
        }
        wingman.close_speech_sessions()
        wingman.openai.close_speech_sessions.assert_called_once()
        self.manager.stop_all_macros.assert_called_once_with(persist_state=False)
        self.assertTrue(self.connections[0].closed)
        wingman.ai_functions_manager = None
        wingman.close_speech_sessions()


if __name__ == "__main__":
    unittest.main()
