"""Exercise persistent TTS sockets, interruption and lifecycle without API calls."""

import base64
from collections import deque
import io
import json
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from openai import OpenAI
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect as websocket_connect
from websockets.sync.server import serve

from services.realtime_tts import (
    RealtimeSessionPool, RealtimeTtsError, SpeechCancelled, synthesize_realtime_speech,
)
from test_instant_command_cache import load_class
from test_realtime_tts import load_speech_service, PCM


def response_events(request, response_id="response-1", pcm=PCM):
    metadata = request["response"]["metadata"]
    return [
        {"type": "response.created", "response": {"id": response_id, "metadata": metadata}},
        {"type": "response.output_audio.delta", "response_id": response_id,
         "delta": base64.b64encode(pcm).decode()},
        {"type": "response.done", "response": {
            "id": response_id, "metadata": metadata, "status": "completed",
        }},
    ]


class PersistentConnection:
    def __init__(self):
        self.events = deque()
        self.sent = []
        self.closed = False
        self.responses = 0
        self.respond = lambda request: response_events(request, f"response-{self.responses}")

    def send(self, data):
        if self.closed:
            raise ConnectionClosedError(None, None)
        event = json.loads(data)
        self.sent.append(event)
        if event["type"] == "session.update":
            self.events.append({"type": "session.updated"})
        elif event["type"] == "response.create":
            self.responses += 1
            self.events.extend(self.respond(event))

    def recv(self, timeout=None):
        if self.closed:
            raise ConnectionClosedError(None, None)
        event = self.events.popleft() if self.events else TimeoutError()
        if isinstance(event, Exception):
            raise event
        return json.dumps(event)

    def close(self):
        self.closed = True


class RealtimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenAI(api_key="test-key")
        self.addCleanup(self.client.close)
        self.pool = RealtimeSessionPool()
        self.addCleanup(self.pool.close)
        self.connections = []

        def create(*args, **kwargs):
            connection = PersistentConnection()
            self.connections.append(connection)
            return connection

        self.connector = self.enterContext(patch("services.realtime_tts.connect", side_effect=create))

    def speech(self, **kwargs):
        return synthesize_realtime_speech(self.client, **{
            "text": "Hallo Cora.", "model": "gpt-realtime-2.1-mini", "voice": "marin",
            "session_pool": self.pool, **kwargs,
        })

    def assert_pcm(self, response, expected=PCM):
        with wave.open(io.BytesIO(response.content), "rb") as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), expected)

    def test_reuses_connection_without_session_update_and_keeps_requests_independent(self):
        self.assert_pcm(self.speech(text="Erster Text.", voice_instruction="Calm"))
        self.assert_pcm(self.speech(text="Zweiter Text.", voice_instruction="Cheerful", player_language="en_GB"))
        self.connector.assert_called_once()
        connection = self.connections[0]
        self.assertFalse(connection.closed)
        self.assertEqual([e["type"] for e in connection.sent], [
            "session.update", "response.create", "response.create",
        ])
        first, second = [e["response"] for e in connection.sent if e["type"] == "response.create"]
        self.assertEqual(first["input"][0]["content"][0]["text"], "Erster Text.")
        self.assertEqual(second["input"][0]["content"][0]["text"], "Zweiter Text.")
        self.assertIn("Cheerful", second["instructions"])
        self.assertIn("en_GB", second["instructions"])
        self.assertNotIn("Calm", second["instructions"])
        self.assertEqual(second["conversation"], "none")
        self.assertNotEqual(first["metadata"], second["metadata"])

    def test_streaming_delivers_audio_before_done_and_retains_complete_wav(self):
        self.speech()
        chunks = []

        def receive(chunk):
            self.assertTrue(self.connections[0].events)
            self.assertFalse(self.connections[0].closed)
            chunks.append(chunk)

        self.assert_pcm(self.speech(on_audio=receive))
        self.assertEqual(b"".join(chunks), PCM)
        self.connector.assert_called_once()

    def test_model_voice_and_credentials_get_separate_sessions(self):
        self.speech()
        self.speech(voice="cedar")
        self.speech(model="gpt-realtime")
        self.client.api_key = "changed-key"
        self.speech()
        self.assertEqual(self.connector.call_count, 4)
        self.speech(voice="nova")  # Legacy alias resolves to the existing marin socket.
        self.assertEqual(self.connector.call_count, 4)

    def test_old_response_events_cannot_contaminate_or_finish_next_response(self):
        self.speech()
        old = self.connections[0].sent[-1]
        old_events = response_events(old, "response-1", b"\xff\x7f")
        self.connections[0].events.extend(old_events)

        def respond(request):
            events = response_events(request, "response-2")
            # Include unrelated events both before and after the matching created event.
            return [*old_events, events[0], *old_events, *events[1:]]

        self.connections[0].respond = respond
        chunks = []
        self.assert_pcm(self.speech(on_audio=chunks.append))
        self.assertEqual(b"".join(chunks), PCM)

    def test_cancel_targets_active_response_and_discards_socket(self):
        self.speech()
        cancel = Event()
        with self.assertRaises(SpeechCancelled):
            self.speech(cancel_event=cancel, on_audio=lambda chunk: cancel.set())
        connection = self.connections[0]
        self.assertEqual(connection.sent[-1], {
            "type": "response.cancel", "response_id": "response-2",
        })
        self.assertTrue(connection.closed)
        self.assert_pcm(self.speech())
        self.assertEqual(len(self.connections), 2)

    def test_cancellation_before_request_leaves_existing_session_usable(self):
        self.speech()
        cancel = Event()
        cancel.set()
        with self.assertRaises(SpeechCancelled):
            self.speech(cancel_event=cancel)
        self.assertFalse(self.connections[0].closed)
        self.assertEqual(self.connections[0].responses, 1)
        self.speech()
        self.connector.assert_called_once()

    def test_stale_reused_socket_reconnects_once_before_audio(self):
        self.speech()
        self.connections[0].closed = True
        self.assert_pcm(self.speech())
        self.assertEqual(len(self.connections), 2)
        self.assertEqual([e["type"] for e in self.connections[1].sent], ["session.update", "response.create"])

    def test_disconnect_before_created_reconnects_without_exposing_old_events(self):
        self.speech()
        self.connections[0].respond = lambda request: [ConnectionClosedError(None, None)]
        self.assert_pcm(self.speech())
        self.assertTrue(self.connections[0].closed)
        self.assertEqual(len(self.connections), 2)

    def test_disconnect_after_audio_does_not_retry_or_return_partial_wav(self):
        self.speech()
        self.connections[0].respond = lambda request: [
            *response_events(request, "response-2")[:2], ConnectionClosedError(None, None),
        ]
        chunks = []
        with self.assertRaisesRegex(RealtimeTtsError, "geschlossen"):
            self.speech(on_audio=chunks.append)
        self.assertEqual(b"".join(chunks), PCM)
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(self.connections[0].closed)

    def test_fresh_socket_disconnect_does_not_retry(self):
        connection = PersistentConnection()
        connection.respond = lambda request: [ConnectionClosedError(None, None)]
        self.connector.side_effect = None
        self.connector.return_value = connection
        with self.assertRaisesRegex(RealtimeTtsError, "geschlossen"):
            self.speech()
        self.connector.assert_called_once()
        self.assertTrue(connection.closed)

    def test_timeout_and_api_error_discard_socket_without_retry(self):
        for events in ([TimeoutError()], [{"type": "error", "error": {"message": "Rejected"}}]):
            with self.subTest(events=events):
                self.speech()
                connection = self.connections[-1]
                connection.respond = lambda request: events
                calls = self.connector.call_count
                with self.assertRaises(RealtimeTtsError):
                    self.speech()
                self.assertTrue(connection.closed)
                self.assertEqual(self.connector.call_count, calls)

    def test_idle_cleanup_releases_connection_and_next_request_reopens(self):
        with patch("services.realtime_tts.time.monotonic", return_value=100) as clock:
            self.speech()
            clock.return_value = 701
            self.pool._prune()
            self.assertTrue(self.connections[0].closed)
            self.speech()
        self.assertEqual(len(self.connections), 2)

    def test_max_age_rotates_session_even_when_not_idle(self):
        self.pool.idle_seconds = 10000
        with patch("services.realtime_tts.time.monotonic", return_value=100) as clock:
            self.speech()
            clock.return_value = 3401
            self.speech()
        self.assertTrue(self.connections[0].closed)
        self.assertEqual(len(self.connections), 2)

    def test_capacity_evicts_oldest_idle_session(self):
        self.pool.max_sessions = 2
        with patch("services.realtime_tts.time.monotonic", return_value=100) as clock:
            self.speech()
            clock.return_value = 101
            self.speech(voice="cedar")
            clock.return_value = 102
            self.speech(voice="shimmer")
        self.assertTrue(self.connections[0].closed)
        self.assertFalse(self.connections[1].closed)
        self.assertFalse(self.connections[2].closed)
        self.assertEqual(len(self.pool._sessions), 2)

    def test_close_releases_all_sockets_and_prevents_new_work(self):
        self.speech()
        self.speech(voice="cedar")
        self.pool.close()
        self.pool.close()
        self.assertTrue(all(c.closed for c in self.connections))
        with self.assertRaises(SpeechCancelled):
            self.speech()
        self.assertEqual(len(self.connections), 2)
        self.pool._worker.join(timeout=1)
        self.assertFalse(self.pool._worker.is_alive())

    def test_same_session_wait_is_cancellable_without_disrupting_active_response(self):
        entered = Event()
        release = Event()
        results = []
        errors = []

        def receive(chunk):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release active response")

        def first():
            try:
                results.append(self.speech(on_audio=receive))
            except Exception as error:
                errors.append(error)

        thread = Thread(target=first)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            cancel = Event()
            original_wait = self.pool._condition.wait

            def waiting(timeout):
                cancel.set()
                return original_wait(timeout)

            with patch.object(self.pool._condition, "wait", side_effect=waiting):
                with self.assertRaises(SpeechCancelled):
                    self.speech(cancel_event=cancel)
            self.assertFalse(self.connections[0].closed)
            self.assertEqual(self.connections[0].responses, 1)
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assert_pcm(results[0])
        self.speech()
        self.connector.assert_called_once()

    def test_openai_speak_passes_pool_for_streaming_and_buffered_realtime(self):
        cls, _ = load_speech_service()
        service = cls()
        service.client = self.client
        service._realtime_sessions = self.pool
        self.assert_pcm(service.speak("Erster Text."))
        chunks = []
        self.assert_pcm(service.speak("Zweiter Text.", on_audio=chunks.append))
        self.assertEqual(b"".join(chunks), PCM)
        self.connector.assert_called_once()

    def test_concurrent_requests_wait_and_reuse_socket_without_mixing_audio(self):
        entered, waiting, release = Event(), Event(), Event()
        results, errors = [], []

        def receive(chunk):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release active response")

        def run(**kwargs):
            try:
                results.append(self.speech(**kwargs))
            except Exception as error:
                errors.append(error)

        first = Thread(target=run, kwargs={"on_audio": receive})
        second = Thread(target=run, kwargs={"text": "Zweiter Text."})
        original_wait = self.pool._condition.wait

        def wait(timeout):
            waiting.set()
            return original_wait(timeout)

        first.start()
        try:
            self.assertTrue(entered.wait(2))
            with patch.object(self.pool._condition, "wait", side_effect=wait):
                second.start()
                self.assertTrue(waiting.wait(2))
                self.assertEqual(self.connections[0].responses, 1)
                release.set()
                first.join(timeout=5)
                second.join(timeout=5)
        finally:
            release.set()
            first.join(timeout=5)
            if second.ident is not None:
                second.join(timeout=5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        for result in results:
            self.assert_pcm(result)
        self.connector.assert_called_once()

    def test_shutdown_during_connection_setup_cannot_leak_socket_or_start_response(self):
        started, release = Event(), Event()
        connection = PersistentConnection()
        errors = []

        def connect(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release connection setup")
            return connection

        def run():
            try:
                self.speech()
            except Exception as error:
                errors.append(error)

        self.connector.side_effect = connect
        thread = Thread(target=run)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            self.pool.close()
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SpeechCancelled)
        self.assertTrue(connection.closed)
        self.assertEqual(connection.sent, [])
        self.assertEqual(self.pool._sessions, {})

    def test_pool_is_initialized_before_stt_constructor_early_return(self):
        namespace = {
            "STTConfig": SimpleNamespace, "OpenAI": Mock(return_value=self.client),
            "RealtimeSessionPool": Mock(return_value=self.pool),
        }
        cls = load_class("services/open_ai.py", "OpenAi", {"__init__", "close_speech_sessions"}, namespace)
        service = cls("test-key", SimpleNamespace(local=False, stt_provider="openai"))
        self.assertIs(service._realtime_sessions, self.pool)
        self.assertIs(service.stt_client, self.client)
        self.speech()
        service.close_speech_sessions()
        self.assertTrue(self.connections[0].closed)

    def test_local_websocket_serves_two_utterances_on_one_connection(self):
        received = []
        connections = []
        errors = []

        def handler(connection):
            connections.append(connection)
            try:
                received.append(json.loads(connection.recv(timeout=5)))
                connection.send(json.dumps({"type": "session.updated"}))
                for index in range(2):
                    request = json.loads(connection.recv(timeout=5))
                    received.append(request)
                    for event in response_events(request, f"response-{index}"):
                        connection.send(json.dumps(event))
            except Exception as error:
                errors.append(error)

        with serve(handler, "127.0.0.1", 0, compression=None) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.socket.getsockname()[1]
                client = OpenAI(api_key="test-key", base_url=f"http://127.0.0.1:{port}/v1")
                self.addCleanup(client.close)
                with patch("services.realtime_tts.connect", side_effect=websocket_connect):
                    for text in ("Erster Text.", "Zweiter Text."):
                        self.assert_pcm(synthesize_realtime_speech(
                            client, text, "gpt-realtime-2.1-mini", session_pool=self.pool, timeout_seconds=5,
                        ))
                    self.pool.close()
                self.assertEqual(len(connections), 1)
                self.assertEqual([e["type"] for e in received], [
                    "session.update", "response.create", "response.create",
                ])
                self.assertEqual(errors, [])
            finally:
                server.shutdown()
                thread.join(timeout=5)


class SessionLifecycleTests(unittest.TestCase):
    def test_wingman_forwards_cleanup_and_accepts_uninitialized_service(self):
        cls = load_class("wingmen/open_ai_wingman.py", "OpenAiWingman", {"close_speech_sessions"}, {})
        wingman = cls()
        wingman.openai = None
        wingman.close_speech_sessions()
        wingman.openai = Mock()
        wingman.close_speech_sessions()
        wingman.openai.close_speech_sessions.assert_called_once()

    def test_application_closes_all_wingmen_even_if_one_cleanup_fails(self):
        cls = load_class("main.py", "WingmanAI", {"close_speech_sessions", "shutdown"}, {})
        app = cls()
        first, second = Mock(name="first"), Mock(name="second")
        first.close_speech_sessions.side_effect = RuntimeError("failed")
        app.tower = Mock()
        app.tower.get_wingmen.return_value = [first, object(), second]
        app.deactivate = Mock()
        app.save_wingman_caches = Mock()
        app.audio_recorder = Mock()
        with patch("builtins.print"):
            app.shutdown()
        first.close_speech_sessions.assert_called_once()
        second.close_speech_sessions.assert_called_once()
        app.audio_recorder.close.assert_called_once()

    def test_context_reload_closes_old_sessions(self):
        printer = Mock()
        tower = Mock(return_value=Mock())
        cls = load_class("main.py", "WingmanAI", {"load_context", "close_speech_sessions"}, {
            "Tower": tower, "printr": printer, "traceback": Mock(),
        })
        app = cls()
        wingman = Mock()
        app.tower = Mock()
        app.tower.get_wingmen.return_value = [wingman]
        app.save_wingman_caches = Mock()
        app.config_manager = Mock()
        app.secret_keeper = Mock()
        app.app_root_dir = "."
        app.load_context("new")
        wingman.close_speech_sessions.assert_called_once()
        tower.assert_called_once()


if __name__ == "__main__":
    unittest.main()
