"""Test Realtime TTS event flow and WAV output without API calls or audio hardware."""

import ast
import base64
import io
import json
from pathlib import Path
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch
import wave

from openai import APIStatusError, OpenAI
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect as websocket_connect
from websockets.sync.server import serve

from services.realtime_tts import (
    LEGACY_VOICE_REPLACEMENTS, REALTIME_VOICES, RealtimeTtsError,
    SpeechCancelled, is_realtime_model, resolve_realtime_voice, synthesize_realtime_speech,
)
from services.streaming_tts import STREAMING_SPEECH_MODELS, synthesize_streaming_speech


ROOT = Path(__file__).resolve().parents[1]
PCM = b"\x00\x00\x01\x00\xff\xff\x00\x00"


class FakeConnection:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
        self.closed = False
        self.timeouts = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def send(self, event):
        self.sent.append(json.loads(event))

    def recv(self, timeout=None):
        self.timeouts.append(timeout)
        event = next(self.events, TimeoutError("no more events"))
        if isinstance(event, Exception):
            raise event
        return json.dumps(event)


def success_events():
    return [
        {"type": "session.created"},
        {"type": "session.updated"},
        {"type": "response.created"},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(PCM[:4]).decode()},
        {"type": "response.output_audio_transcript.delta", "delta": "Hallo"},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(PCM[4:]).decode()},
        {"type": "response.output_audio.done"},
        {"type": "response.done", "response": {"status": "completed"}},
    ]


def load_speech_service():
    """Use the production methods without importing Windows GUI dependencies."""
    path = ROOT / "services/open_ai.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OpenAi")
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {
        "speak", "_sanitize_tts_input", "supports_speech_streaming",
    }]
    cls.body.insert(0, ast.Assign(targets=[ast.Name(id="_MAX_TTS_INPUT_CHARS", ctx=ast.Store())], value=ast.Constant(4000)))
    namespace = {
        "is_realtime_model": is_realtime_model, "resolve_realtime_voice": resolve_realtime_voice,
        "synthesize_realtime_speech": synthesize_realtime_speech,
        "RealtimeTtsError": RealtimeTtsError, "APIStatusError": APIStatusError,
        "SpeechCancelled": SpeechCancelled, "STREAMING_SPEECH_MODELS": STREAMING_SPEECH_MODELS,
        "synthesize_streaming_speech": synthesize_streaming_speech,
        "printr": Mock(), "traceback": Mock(),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["OpenAi"], namespace["printr"]


class RealtimeTtsTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenAI(api_key="test-key", organization="test-org", project="test-project")
        self.addCleanup(self.client.close)
        self.connection = FakeConnection(success_events())
        self.connector = self.enterContext(patch("services.realtime_tts.connect", return_value=self.connection))

    def synthesize(self, **kwargs):
        return synthesize_realtime_speech(self.client, **{
            "text": "Hallo, Commander Artemis.", "model": "gpt-realtime-2.1-mini",
            "voice": "marin", **kwargs,
        })

    def test_ga_event_flow_and_playable_wav_preserve_audio_samples(self):
        response = self.synthesize()
        args, kwargs = self.connector.call_args
        self.assertEqual(args[0], "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini")
        headers = kwargs["additional_headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["OpenAI-Organization"], "test-org")
        self.assertEqual(headers["OpenAI-Project"], "test-project")
        self.assertNotIn("OpenAI-Beta", headers)
        session, request = self.connection.sent
        self.assertEqual(session["type"], "session.update")
        self.assertEqual(session["session"]["type"], "realtime")
        self.assertEqual(session["session"]["audio"]["output"], {
            "voice": "marin", "format": {"type": "audio/pcm", "rate": 24000},
        })
        self.assertIsNone(session["session"]["audio"]["input"]["turn_detection"])
        self.assertEqual(request["type"], "response.create")
        self.assertEqual(request["response"]["conversation"], "none")
        self.assertEqual(request["response"]["output_modalities"], ["audio"])
        self.assertEqual(request["response"]["tools"], [])
        self.assertEqual(request["response"]["input"][0]["content"][0], {
            "type": "input_text", "text": "Hallo, Commander Artemis.",
        })
        self.assertTrue(self.connection.closed)
        with wave.open(io.BytesIO(response.content), "rb") as wav:
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)

    def test_voice_style_and_language_preserve_verbatim_speech_instructions(self):
        self.synthesize(voice_instruction="Speak like a ship computer", player_language="de_DE")
        instructions = self.connection.sent[-1]["response"]["instructions"]
        self.assertIn("ship computer", instructions)
        self.assertIn("de_DE", instructions)
        self.assertIn("verbatim", instructions)
        self.assertIn("Do not answer", instructions)
        self.assertIn("preserving its language and wording", instructions)

    def test_audio_arrives_before_completion_and_full_wav_is_retained(self):
        chunks = []

        def receive(chunk):
            self.assertFalse(self.connection.closed)
            chunks.append(chunk)

        result = self.synthesize(on_audio=receive)
        self.assertEqual(b"".join(chunks), PCM)
        with wave.open(io.BytesIO(result.content), "rb") as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), PCM)

    def test_cancel_during_audio_stops_generation_without_returning_partial_wav(self):
        cancel = Event()
        with self.assertRaises(SpeechCancelled):
            self.synthesize(on_audio=lambda chunk: cancel.set(), cancel_event=cancel)
        self.assertEqual(self.connection.sent[-1]["type"], "response.cancel")
        self.assertTrue(self.connection.closed)

    def test_cancel_before_connection_does_not_call_api(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(SpeechCancelled):
            self.synthesize(cancel_event=cancel)
        self.connector.assert_not_called()

    def test_cancel_interrupts_receive_wait(self):
        cancel = Event()

        def receive(timeout=None):
            self.assertLessEqual(timeout, 0.1)
            cancel.set()
            raise TimeoutError()

        self.connection.recv = receive
        with self.assertRaises(SpeechCancelled):
            self.synthesize(cancel_event=cancel)

    def test_receive_polling_still_respects_generation_deadline(self):
        self.connection.events = iter([TimeoutError()])
        with patch("services.realtime_tts.time.monotonic", side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(RealtimeTtsError, "Zeitlimit"):
                self.synthesize(cancel_event=Event(), timeout_seconds=1)

    def test_speech_streaming_capabilities_leave_unknown_models_buffered(self):
        cls, _ = load_speech_service()
        service = cls()
        for model in (None, "gpt-realtime-2.1-mini", "tts-1", "tts-1-hd", "gpt-4o-mini-tts"):
            self.assertTrue(service.supports_speech_streaming(model))
        self.assertFalse(service.supports_speech_streaming("custom-speech-model"))

    def test_pcm_network_boundaries_preserve_complete_frames(self):
        self.connection.events = iter([
            {"type": "session.updated"},
            *[{"type": "response.output_audio.delta", "delta": base64.b64encode(chunk).decode()}
              for chunk in (PCM[:1], PCM[1:5], PCM[5:])],
            {"type": "response.done", "response": {"status": "completed"}},
        ])
        chunks = []
        self.synthesize(on_audio=chunks.append)
        self.assertTrue(all(len(chunk) % 2 == 0 for chunk in chunks))
        self.assertEqual(b"".join(chunks), PCM)

    def test_real_websocket_transport_against_local_server(self):
        received = []

        def handler(connection):
            received.append(json.loads(connection.recv(timeout=5)))
            connection.send(json.dumps({"type": "session.updated"}))
            received.append(json.loads(connection.recv(timeout=5)))
            for event in success_events()[2:]:
                connection.send(json.dumps(event))

        with serve(handler, "127.0.0.1", 0, compression=None) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.socket.getsockname()[1]
                client = OpenAI(api_key="test-key", base_url=f"http://127.0.0.1:{port}/v1")
                self.addCleanup(client.close)
                with patch("services.realtime_tts.connect", side_effect=websocket_connect):
                    result = synthesize_realtime_speech(
                        client, "Hallo Cora.", "gpt-realtime-2.1-mini", timeout_seconds=5,
                    )
                self.assertEqual([event["type"] for event in received], ["session.update", "response.create"])
                with wave.open(io.BytesIO(result.content), "rb") as wav:
                    self.assertEqual(wav.readframes(wav.getnframes()), PCM)
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_api_error_closes_connection_without_partial_audio(self):
        self.connection.events = iter([
            {"type": "error", "error": {"message": "Unsupported voice"}},
        ])
        with self.assertRaisesRegex(RealtimeTtsError, "Unsupported voice"):
            self.synthesize()
        self.assertTrue(self.connection.closed)
        self.assertEqual(len(self.connection.sent), 1)

    def test_failed_cancelled_and_incomplete_responses_are_rejected(self):
        for status in ("failed", "cancelled", "incomplete"):
            with self.subTest(status=status):
                self.connection.events = iter([
                    {"type": "session.updated"},
                    {"type": "response.output_audio.delta", "delta": base64.b64encode(PCM).decode()},
                    {"type": "response.done", "response": {
                        "status": status, "status_details": {"error": {"message": "Rejected"}},
                    }},
                ])
                with self.assertRaisesRegex(RealtimeTtsError, "Rejected"):
                    self.synthesize()
                self.assertTrue(self.connection.closed)

    def test_empty_and_invalid_pcm_are_rejected(self):
        for pcm in (b"", b"\x00"):
            with self.subTest(pcm=pcm):
                self.connection.events = iter([
                    {"type": "session.updated"},
                    {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
                    {"type": "response.done", "response": {"status": "completed"}},
                ])
                with self.assertRaisesRegex(RealtimeTtsError, "PCM16"):
                    self.synthesize()

    def test_timeout_covers_setup_and_audio_generation(self):
        for events in ([TimeoutError()], [{"type": "session.updated"}, TimeoutError()]):
            with self.subTest(events=events):
                self.connection.events = iter(events)
                with self.assertRaisesRegex(RealtimeTtsError, "Zeitlimit"):
                    self.synthesize(timeout_seconds=1)
                self.assertTrue(self.connection.closed)
                self.assertTrue(all(0 < timeout <= 1 for timeout in self.connection.timeouts))

    def test_deadline_limits_streams_that_keep_sending_events(self):
        with patch("services.realtime_tts.time.monotonic", side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(RealtimeTtsError, "Zeitlimit"):
                self.synthesize(timeout_seconds=1)
        self.assertTrue(self.connection.closed)

    def test_disconnect_does_not_return_partial_audio(self):
        self.connection.events = iter([
            {"type": "session.updated"},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(PCM).decode()},
            ConnectionClosedError(None, None),
        ])
        with self.assertRaisesRegex(RealtimeTtsError, "geschlossen"):
            self.synthesize()
        self.assertTrue(self.connection.closed)

    def test_response_creation_waits_for_session_update_and_happens_once(self):
        self.connection.events = iter([
            {"type": "session.created"}, {"type": "rate_limits.updated"},
            {"type": "session.updated"}, *success_events(),
        ])
        self.synthesize()
        self.assertEqual([event["type"] for event in self.connection.sent], ["session.update", "response.create"])

    def test_custom_base_url_and_headers_are_preserved_without_beta_header(self):
        client = OpenAI(
            api_key="test-key", base_url="http://localhost:1234/custom/v1",
            default_headers={"X-Custom": "test", "OpenAI-Beta": "realtime=v1"},
        )
        self.addCleanup(client.close)
        self.client = client
        self.synthesize()
        args, kwargs = self.connector.call_args
        self.assertEqual(args[0], "ws://localhost:1234/custom/v1/realtime?model=gpt-realtime-2.1-mini")
        self.assertEqual(kwargs["additional_headers"]["X-Custom"], "test")
        self.assertNotIn("OpenAI-Beta", kwargs["additional_headers"])

    def test_supported_and_legacy_voices(self):
        for voice in REALTIME_VOICES:
            self.assertEqual(resolve_realtime_voice(voice), voice)
        warnings = Mock()
        for voice, replacement in LEGACY_VOICE_REPLACEMENTS.items():
            self.assertEqual(resolve_realtime_voice(voice, warnings), replacement)
        self.assertEqual(warnings.call_count, 3)
        self.assertEqual(resolve_realtime_voice(None), "marin")
        with self.assertRaisesRegex(RealtimeTtsError, "Unbekannte"):
            resolve_realtime_voice("typo")

    def test_unknown_voice_and_missing_client_fail_before_connection(self):
        with self.assertRaises(RealtimeTtsError):
            self.synthesize(voice="typo")
        with self.assertRaises(RealtimeTtsError):
            synthesize_realtime_speech(None, "Hello", "gpt-realtime-2.1-mini")
        self.connector.assert_not_called()

    def test_speak_uses_realtime_and_translates_cora_legacy_voice(self):
        cls, printer = load_speech_service()
        service = cls()
        service.client = self.client
        response = service.speak("  Hallo\n Cora.  ", "gpt-realtime-2.1-mini", "nova")
        self.assertIsNotNone(response)
        printer.print_warn.assert_called_once()
        self.assertEqual(self.connection.sent[0]["session"]["audio"]["output"]["voice"], "marin")
        self.assertEqual(self.connection.sent[-1]["response"]["input"][0]["content"][0]["text"], "Hallo Cora.")
        self.assertTrue(response.content.startswith(b"RIFF"))

    def test_speak_handles_realtime_errors_and_skips_empty_input(self):
        cls, printer = load_speech_service()
        service = cls()
        service.client = self.client
        self.assertIsNone(service.speak(" ", "gpt-realtime-2.1-mini", "marin"))
        self.connector.assert_not_called()
        self.connection.events = iter([{"type": "error", "error": {"message": "Invalid model"}}])
        self.assertIsNone(service.speak("Hello", "gpt-realtime-2.1-mini", "marin"))
        self.assertIn("Invalid model", printer.print.call_args.args[0])

    def test_default_speech_model_and_voice_use_realtime(self):
        cls, _ = load_speech_service()
        service = cls()
        service.client = self.client
        self.assertIsNotNone(service.speak("Hallo Cora."))
        session = self.connection.sent[0]["session"]
        self.assertEqual(session["model"], "gpt-realtime-2.1-mini")
        self.assertEqual(session["audio"]["output"]["voice"], "marin")

    def test_legacy_speech_models_keep_their_existing_endpoint(self):
        cls, _ = load_speech_service()
        service = cls()
        service.client = Mock()
        for model in ("tts-1", "tts-1-hd", "gpt-4o-mini-tts"):
            with self.subTest(model=model):
                service.client.audio.speech.create.reset_mock()
                service.speak("Hello", model, "nova", "Cheerful", "en_GB")
                kwargs = service.client.audio.speech.create.call_args.kwargs
                self.assertEqual(kwargs["model"], model)
                self.assertEqual(kwargs["voice"], "nova")
                self.assertEqual("instructions" in kwargs, model == "gpt-4o-mini-tts")
        self.connector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
