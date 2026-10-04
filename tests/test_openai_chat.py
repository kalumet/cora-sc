"""Exercise model routing and tool round trips with the real SDK, without network."""

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx
from openai import APIStatusError, OpenAI
from openai.types.chat import ChatCompletionMessage

from services.openai_chat import create_chat_completion


ROOT = Path(__file__).resolve().parents[1]
TOOLS = [{
    "type": "function",
    "function": {
        "name": "execute_command", "description": "Execute a ship command",
        "parameters": {
            "type": "object", "properties": {"command_name": {"type": "string"}},
            "required": ["command_name"],
        },
    },
}]
CALL = {
    "type": "function_call", "id": "fc_1", "call_id": "call_1",
    "name": "execute_command", "arguments": '{"command_name":"open_doors"}',
    "status": "completed",
}
REASONING = {
    "type": "reasoning", "id": "rs_1", "summary": [],
    "encrypted_content": "opaque-reasoning-context",
}


def response(output=None, **overrides):
    return {
        "id": "resp_1", "object": "response", "created_at": 123,
        "model": "gpt-6-luna", "status": "completed", "error": None,
        "incomplete_details": None, "instructions": None, "metadata": {},
        "parallel_tool_calls": True, "tools": [], "tool_choice": "auto",
        "output": output if output is not None else [{
            "type": "message", "id": "msg_1", "role": "assistant",
            "status": "completed", "content": [{
                "type": "output_text", "text": "Türen geöffnet.", "annotations": [],
            }],
        }],
        "usage": {
            "input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 5},
            "output_tokens_details": {"reasoning_tokens": 3},
        },
        **overrides,
    }


def load_methods(path, class_name, methods):
    """Load production methods without Wingman's Windows audio/GUI imports."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods]
    namespace = {
        "create_chat_completion": create_chat_completion,
        "APIStatusError": APIStatusError, "AzureConfig": SimpleNamespace,
        "Mapping": dict, "printr": Mock(),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(ROOT / path), "exec"), namespace)
    return namespace[class_name]


class OpenAiChatTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.reply = response()
        self.status_code = 200
        self.stream_events = None
        self.client = OpenAI(
            api_key="test-key", base_url="https://example.invalid/v1", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handle)),
        )
        self.addCleanup(self.client.close)

    def handle(self, request):
        self.requests.append((request.url.path, json.loads(request.content)))
        if self.stream_events is not None:
            content = "".join(f"data: {json.dumps(event)}\n\n" for event in self.stream_events)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json=self.reply)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={
                "id": "chat_1", "created": 123, "object": "chat.completion",
                "model": "gpt-4o-mini", "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "OK"},
                }],
            })
        return httpx.Response(200, json=self.reply)

    def ask(self, **kwargs):
        return create_chat_completion(
            self.client, messages=[{"role": "user", "content": "Öffne die Türen"}],
            **{"model": "gpt-6-luna", "reasoning_effort": "low", **kwargs},
        )

    def test_luna_tools_keep_reasoning_and_existing_chat_contract(self):
        tools = deepcopy(TOOLS)
        self.reply = response([REASONING, CALL])
        completion = self.ask(tools=tools)
        path, request = self.requests[-1]
        self.assertEqual(path, "/v1/responses")
        self.assertEqual(request["reasoning"], {"effort": "low"})
        self.assertFalse(request["store"])
        self.assertEqual(request["include"], ["reasoning.encrypted_content"])
        self.assertEqual(request["tools"][0]["name"], "execute_command")
        self.assertFalse(request["tools"][0]["strict"])
        self.assertEqual(request["tools"][0]["parameters"], TOOLS[0]["function"]["parameters"])
        self.assertEqual(tools, TOOLS)
        message = completion.choices[0].message
        self.assertIsInstance(message, ChatCompletionMessage)
        self.assertEqual(message.tool_calls[0].id, "call_1")
        self.assertEqual(message.tool_calls[0].function.name, "execute_command")
        self.assertEqual(json.loads(message.tool_calls[0].function.arguments), {"command_name": "open_doors"})
        self.assertEqual(completion.choices[0].finish_reason, "tool_calls")
        self.assertEqual(completion.usage.prompt_tokens, 20)
        self.assertEqual(completion.usage.completion_tokens_details.reasoning_tokens, 3)

    def test_tool_result_round_trip_preserves_native_reasoning_and_call_id(self):
        self.reply = response([REASONING, CALL])
        first = self.ask(tools=TOOLS)
        message = first.choices[0].message
        self.reply = response()
        second = create_chat_completion(
            self.client, model="gpt-6-luna", reasoning_effort="low", tools=TOOLS,
            messages=[
                {"role": "user", "content": "Öffne die Türen"}, message,
                {"role": "tool", "tool_call_id": "call_1", "content": '{"success":true}'},
            ],
        )
        items = self.requests[-1][1]["input"]
        self.assertEqual(items[1:3], [REASONING, CALL])
        self.assertEqual(items[3], {
            "type": "function_call_output", "call_id": "call_1", "output": '{"success":true}',
        })
        self.assertEqual(second.choices[0].message.content, "Türen geöffnet.")
        self.assertNotIn("_responses_output", message.model_dump())
        self.assertNotIn("opaque-reasoning-context", first.model_dump_json())

    def test_existing_chat_tool_history_can_be_replayed(self):
        message = ChatCompletionMessage(
            role="assistant", content=None,
            tool_calls=[{"id": "call_1", "type": "function", "function": {
                "name": CALL["name"], "arguments": CALL["arguments"],
            }}],
        )
        create_chat_completion(self.client, model="gpt-6-luna", messages=[
            message, {"role": "tool", "tool_call_id": "call_1", "content": "OK"},
        ])
        self.assertEqual(self.requests[-1][1]["input"][0], {
            "type": "function_call", "call_id": "call_1",
            "name": CALL["name"], "arguments": CALL["arguments"],
        })

    def test_manager_parameters_and_structured_output_are_converted(self):
        for effort in (None, "low", "high"):
            with self.subTest(effort=effort):
                self.ask(reasoning_effort=effort, max_tokens=512, temperature=0.7,
                         response_format={"type": "json_object"})
                request = self.requests[-1][1]
                self.assertEqual(request["max_output_tokens"], 512)
                self.assertEqual(request["text"], {"format": {"type": "json_object"}})
                self.assertNotIn("temperature", request)
                self.assertNotIn("max_tokens", request)

    def test_none_effort_and_json_schema_are_preserved(self):
        schema = {"name": "result", "strict": True, "schema": {"type": "object"}}
        self.ask(reasoning_effort="none", temperature=0.7,
                 response_format={"type": "json_schema", "json_schema": schema})
        request = self.requests[-1][1]
        self.assertEqual(request["reasoning"], {"effort": "none"})
        self.assertEqual(request["temperature"], 0.7)
        self.assertEqual(request["text"]["format"], {"type": "json_schema", **schema})

    def test_summaries_and_gpt6_model_variants_use_responses(self):
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna-2026-09-01"):
            with self.subTest(model=model):
                completion = self.ask(model=model, reasoning_effort="low")
                self.assertEqual(self.requests[-1][0], "/v1/responses")
                self.assertEqual(self.requests[-1][1]["model"], model)
                self.assertEqual(completion.choices[0].message.content, "Türen geöffnet.")

    def test_older_models_and_other_providers_keep_chat_completions(self):
        for model in ("gpt-4o-mini", "gpt-5-mini", "openai/gpt-oss-120b"):
            with self.subTest(model=model):
                self.ask(model=model, tools=TOOLS, max_tokens=512, temperature=0.7)
                path, request = self.requests[-1]
                self.assertEqual(path, "/v1/chat/completions")
                self.assertEqual(request["tools"], TOOLS)
                self.assertEqual(request["reasoning_effort"], "low")
                self.assertEqual(request["max_tokens"], 512)
                self.assertEqual(request["temperature"], 0.7)

    def test_length_and_refusal_are_visible_to_existing_callers(self):
        self.reply = response([], status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        self.assertEqual(self.ask().choices[0].finish_reason, "length")
        self.reply = response([{
            "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "refusal", "refusal": "Cannot comply"}],
        }])
        self.assertEqual(self.ask().choices[0].message.refusal, "Cannot comply")

    def test_multiple_tools_and_explicit_strict_schema_are_preserved(self):
        tools = deepcopy(TOOLS)
        tools[0]["function"]["strict"] = True
        tools[0]["function"]["parameters"]["additionalProperties"] = False
        second_call = {**CALL, "id": "fc_2", "call_id": "call_2"}
        self.reply = response([REASONING, CALL, second_call])
        completion = self.ask(tools=tools)
        self.assertTrue(self.requests[-1][1]["tools"][0]["strict"])
        self.assertEqual([call.id for call in completion.choices[0].message.tool_calls], ["call_1", "call_2"])

    def test_api_errors_propagate_to_the_existing_error_handler(self):
        self.status_code = 400
        self.reply = {"error": {"message": "Invalid request", "type": "invalid_request_error", "code": None}}
        with self.assertRaises(APIStatusError) as raised:
            self.ask(tools=TOOLS)
        self.assertEqual(raised.exception.status_code, 400)

    def test_failed_responses_are_not_returned_as_empty_successes(self):
        self.reply = response([], status="failed", error={"code": "server_error", "message": "Failed"})
        with self.assertRaisesRegex(RuntimeError, "Responses request failed"):
            self.ask()

    def test_streaming_retains_chat_chunk_contract(self):
        self.stream_events = [{"type": "response.completed", "response": response([REASONING, CALL])}]
        chunks = list(self.ask(tools=TOOLS, stream=True))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].choices[0].delta.tool_calls[0].function.name, "execute_command")
        self.assertEqual(chunks[0].choices[0].delta.tool_calls[0].index, 0)
        self.assertEqual(chunks[0].choices[0].finish_reason, "tool_calls")

    def test_failed_streams_raise_an_error(self):
        self.stream_events = [{
            "type": "response.failed",
            "response": response([], status="failed", error={"code": "server_error", "message": "Failed"}),
        }]
        with self.assertRaisesRegex(RuntimeError, "Responses stream failed"):
            list(self.ask(stream=True))

    def test_images_are_converted_without_mutating_history(self):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "Read this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "high"}},
        ]}]
        original = deepcopy(messages)
        create_chat_completion(self.client, model="gpt-6-luna", messages=messages)
        self.assertEqual(self.requests[-1][1]["input"][0]["content"], [
            {"type": "input_text", "text": "Read this"},
            {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "high"},
        ])
        self.assertEqual(messages, original)

    def test_openai_ask_routes_real_command_request_and_sanitizes_history(self):
        cls = load_methods("services/open_ai.py", "OpenAi", {
            "ask", "_sanitize_messages_for_tool_call_sequence", "_get_message_role",
            "_get_message_tool_calls", "_get_tool_call_id", "_get_message_tool_call_id",
        })
        service = cls()
        service.client = self.client
        self.reply = response([REASONING, CALL])
        completion = service.ask(
            messages=[{"role": "tool", "tool_call_id": "orphan", "content": "invalid"},
                      {"role": "user", "content": "Öffne die Türen"}],
            model="gpt-6-luna", reasoning_effort="low", tools=TOOLS,
        )
        self.assertIsNotNone(completion)
        self.assertEqual(self.requests[-1][0], "/v1/responses")
        self.assertEqual(len(self.requests[-1][1]["input"]), 1)
        messages = [{"role": "user", "content": "Öffne die Türen"},
                    completion.choices[0].message,
                    {"role": "tool", "tool_call_id": "call_1", "content": "OK"}]
        self.assertIsNotNone(service.ask(messages=messages, model="gpt-6-luna", tools=TOOLS, reasoning_effort="low"))
        self.assertEqual(self.requests[-1][1]["input"][1], REASONING)

    def test_manager_ask_ai_uses_same_adapter(self):
        cls = load_methods("wingmen/star_citizen_services/function_manager.py", "FunctionManager", {"ask_ai"})
        manager = cls()
        manager.name = "TestManager"
        manager.config = {}
        manager._resolve_ask_ai_request = Mock(return_value={
            "provider": "openai", "model": "gpt-6-luna", "reasoning_effort": "low", "max_tokens": 512,
        })
        manager._get_llm_client = Mock(return_value=self.client)
        manager._sanitize_debug_stage_fragment = Mock(return_value="")
        manager._ask_ai_debug_stage_prefix = "test"
        manager._ask_ai_debug_request_logger = None
        manager._ask_ai_debug_event_logger = None
        manager._ask_ai_debug_response_logger = None
        completion = manager.ask_ai("Return JSON", "Get ship status")
        self.assertIsNotNone(completion)
        self.assertEqual(self.requests[-1][0], "/v1/responses")
        request = self.requests[-1][1]
        self.assertEqual(request["max_output_tokens"], 512)
        self.assertNotIn("temperature", request)


if __name__ == "__main__":
    unittest.main()
