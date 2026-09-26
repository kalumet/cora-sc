"""Manager permissions and SDK integration without desktop/audio dependencies."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mcp import Client
from mcp.server import MCPServer

from services.manager_mcp import ManagerMcpTools


ALIAS = "starhead_sc_mining"
CONFIG = {
    "servers": {"starhead": {"enabled": True, "url": "https://example.invalid/mcp", "timeout_seconds": 2}},
    "manager_tools": {"MiningManager": {"starhead": ["sc_mining"]}},
}


class ManagerMcpTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer("Mining test fixture")
        self.calls = []
        self.managers = {"MiningManager": (True, "CORA")}
        self.reserved = set()
        self.warnings = Mock()

        @self.server.tool(name="sc_mining")
        def mining(location: str = "", material: str = "", method: str = "ship") -> dict:
            """Find mining locations or materials. Not a numeric signature lookup."""
            self.calls.append({"location": location, "material": material, "method": method})
            return {"location": location, "material": material, "method": method}

        @self.server.tool(name="sc_ship_info")
        def ship_info(ship: str) -> str:
            return ship

        self.factory = Mock(side_effect=lambda url, timeout: Client(self.server))
        self.registry = self.make_registry()

    def available(self, manager, context):
        enabled, owner_context = self.managers.get(manager, (False, None))
        return enabled and (context is None or context == owner_context)

    def make_registry(self, config=None, factory=None):
        return ManagerMcpTools(
            CONFIG if config is None else config,
            is_manager_available=self.available,
            reserved_names=lambda: self.reserved,
            report_warning=self.warnings,
            client_factory=factory or self.factory,
        )

    def discover(self):
        self.registry.discover_for_manager("MiningManager")
        self.assertEqual([ALIAS], [t["function"]["name"] for t in self.registry.get_tools("CORA")])

    def test_sdk_discovery_preserves_description_schema_and_filters_tools(self):
        self.discover()
        tool = self.registry.get_tools("CORA")[0]["function"]
        self.assertIn("Find mining", tool["description"])
        self.assertEqual("string", tool["parameters"]["properties"]["location"]["type"])
        self.assertFalse(self.registry.handles("starhead_sc_ship_info"))
        self.assertEqual([], self.registry.get_tools("TDD"))
        tool["parameters"]["properties"].clear()
        self.assertIn("location", self.registry.get_tools("CORA")[0]["function"]["parameters"]["properties"])

    def test_sdk_call_uses_original_name_and_returns_uncached_data(self):
        self.discover()
        result = asyncio.run(self.registry.call_tool(ALIAS, {"location": "Daymar", "method": "roc"}, "CORA"))
        self.assertTrue(result["success"], result)
        self.assertTrue(result["do_not_cache"])
        self.assertEqual("starhead", result["source"])
        self.assertEqual("sc_mining", result["tool"])
        self.assertEqual("Daymar", result["data"]["location"])
        self.assertEqual([{"location": "Daymar", "material": "", "method": "roc"}], self.calls)
        # No cross-loop reuse: a second audio request owns a fresh SDK client.
        asyncio.run(self.registry.call_tool(ALIAS, {"material": "Quantanium"}, "CORA"))
        self.assertEqual(3, self.factory.call_count)

    def test_disabled_manager_or_wrong_context_denies_before_connection(self):
        self.discover()
        self.factory.reset_mock()
        self.assertFalse(asyncio.run(self.registry.call_tool(ALIAS, {}, "TDD"))["success"])
        self.managers["MiningManager"] = (False, "CORA")
        self.assertEqual([], self.registry.get_tools("CORA"))
        self.assertFalse(asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))["success"])
        self.factory.assert_not_called()
        self.assertEqual([], self.calls)

    def test_reenable_and_shared_tool_keep_one_alias(self):
        self.managers["OtherManager"] = (True, "TDD")
        config = deepcopy(CONFIG)
        config["manager_tools"]["OtherManager"] = {"starhead": ["sc_mining"]}
        self.registry = self.make_registry(config)
        self.discover()
        self.assertEqual(1, len(self.registry.get_tools("TDD")))
        self.managers["MiningManager"] = (False, "CORA")
        self.assertEqual([], self.registry.get_tools("CORA"))
        self.assertEqual(1, len(self.registry.get_tools("TDD")))
        self.managers["MiningManager"] = (True, "CORA")
        self.discover()
        self.assertEqual(1, len(self.registry.get_tools("CORA")))

    def test_no_config_disabled_server_and_disabled_manager_make_no_connections(self):
        configs = [{}, {"servers": CONFIG["servers"]}, deepcopy(CONFIG)]
        configs[-1]["servers"]["starhead"]["enabled"] = False
        for config in configs:
            registry = self.make_registry(config)
            registry.discover_for_manager("MiningManager")
            self.assertEqual([], registry.get_tools("CORA"))
        self.managers["MiningManager"] = (False, "CORA")
        self.registry.discover_for_manager("MiningManager")
        self.factory.assert_not_called()

    def test_reserved_and_ambiguous_names_are_denied(self):
        self.reserved.add(ALIAS)
        self.registry.discover_for_manager("MiningManager")
        self.assertEqual([], self.registry.get_tools("CORA"))
        self.assertFalse(asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))["success"])
        self.reserved.clear()
        config = deepcopy(CONFIG)
        config["servers"]["starhead_sc"] = dict(config["servers"]["starhead"])
        config["manager_tools"]["MiningManager"]["starhead_sc"] = ["mining"]
        self.registry = self.make_registry(config)
        self.registry.discover_for_manager("MiningManager")
        self.assertEqual([], self.registry.get_tools("CORA"))

    def test_missing_remote_tool_is_not_exposed(self):
        config = deepcopy(CONFIG)
        config["manager_tools"]["MiningManager"]["starhead"] = ["removed_tool"]
        self.registry = self.make_registry(config)
        self.registry.discover_for_manager("MiningManager")
        self.assertEqual([], self.registry.get_tools("CORA"))
        self.warnings.assert_called()

    def test_invalid_arguments_do_not_reach_sdk(self):
        self.discover()
        self.factory.reset_mock()
        for args in ([], {"location": 123}):
            result = asyncio.run(self.registry.call_tool(ALIAS, args, "CORA"))
            self.assertFalse(result["success"])
        self.factory.assert_not_called()

    def test_sdk_failure_does_not_leak_error_details_and_can_recover(self):
        self.factory.side_effect = RuntimeError("secret header value")
        self.registry.discover_for_manager("MiningManager")
        self.assertEqual([], self.registry.get_tools("CORA"))
        self.assertNotIn("secret", str(self.warnings.call_args_list))
        self.factory.side_effect = lambda url, timeout: Client(self.server)
        self.discover()
        self.factory.side_effect = RuntimeError("secret header value")
        result = asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))
        self.assertFalse(result["success"])
        self.assertTrue(result["do_not_cache"])
        self.assertNotIn("secret", str(result))

    def test_discovery_inside_running_loop(self):
        async def activate_from_audio_request():
            self.discover()
        asyncio.run(activate_from_audio_request())

    def test_decode_json_text_plain_text_and_empty_response(self):
        for text, expected in [('{"locations": ["Daymar"]}', {"locations": ["Daymar"]}), ("No matches", "No matches")]:
            result = SimpleNamespace(structured_content=None, content=[SimpleNamespace(type="text", text=text)])
            self.assertEqual(expected, self.registry._decode_result(result))
        with self.assertRaises(ValueError):
            self.registry._decode_result(SimpleNamespace(structured_content=None, content=[]))

    def test_permission_is_checked_again_after_connection(self):
        self.discover()
        owner = self
        class RevokingClient:
            async def __aenter__(self):
                owner.managers["MiningManager"] = (False, "CORA")
                return self
            async def __aexit__(self, *args):
                pass
            async def call_tool(self, *args):
                raise AssertionError("Must not call after manager was disabled")
        self.registry.client_factory = lambda *args: RevokingClient()
        result = asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))
        self.assertFalse(result["success"])

    def test_pagination_and_tool_error(self):
        tool = SimpleNamespace(name="sc_mining", description="Mining", title=None,
                               input_schema={"type": "object", "properties": {}})
        class PagedClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def list_tools(self, cursor=None):
                return SimpleNamespace(tools=[tool] if cursor else [], next_cursor=None if cursor else "page2")
            async def call_tool(self, *args):
                return SimpleNamespace(is_error=True, structured_content=None,
                                       content=[SimpleNamespace(type="text", text="No data available")])
        self.registry.client_factory = lambda *args: PagedClient()
        self.discover()
        result = asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))
        self.assertFalse(result["success"])
        self.assertEqual("No data available", result["data"])

    def test_timeout_closes_client(self):
        self.discover()
        exited = []
        class SlowClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): exited.append(True)
            async def call_tool(self, *args): await asyncio.sleep(1)
        self.registry.client_factory = lambda *args: SlowClient()
        self.registry.servers["starhead"]["timeout"] = 0.01
        result = asyncio.run(self.registry.call_tool(ALIAS, {}, "CORA"))
        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])
        self.assertEqual([True], exited)


class WingmanMcpDispatchTests(unittest.TestCase):
    """Run the real Wingman dispatcher/cache methods without desktop imports."""

    def setUp(self):
        from test_instant_command_cache import Base, load_class

        fixture = self.fixture = ManagerMcpTests()
        fixture.setUp()
        fixture.discover()
        self.local_call = Mock(return_value={"success": True})
        ns = {"OpenAiWingman": Base, "AIContext": SimpleNamespace(CORA="CORA", TDD="TDD"),
              "FunctionManager": type("FunctionManager", (), {}), "DEBUG": False, "printr": Mock()}
        cls = load_class("wingmen/star_citizen_wingman.py", "StarCitizenWingman", {
            "_execute_command_by_function_call", "_get_context_tools", "_get_cora_tools",
            "_build_tools", "_refresh_manager_runtime_state",
        }, ns, ("OpenAiWingman",))
        self.wingman = w = cls()
        w.ai_functions_manager = SimpleNamespace(
            mcp_tools=fixture.registry,
            get_managers=lambda context: [SimpleNamespace(get_function_tools=lambda: [
                {"type": "function", "function": {"name": "mining_signature_lookup"}},
                {"type": "function", "function": {"name": "refinery_job_work_order_management"}},
            ])] if context == "CORA" else [],
            get_function_registry=lambda: {"mining_signature_lookup": self.local_call},
            get_function=lambda name: self.local_call,
        )
        w.current_context = "CORA"
        w.contexts_history = {"CORA": {"tools": []}, "TDD": {"tools": []}}
        w.config = {"openai": {}}
        w.debug = False
        w.manage_feature_manager_state = Mock(__name__="manage_feature_manager_state")
        w._manager_control_tool = lambda: {"function": {"name": "manage_feature_manager_state"}}
        w._get_keybinding_commands = lambda: {"function": {"name": "execute_command"}}
        w._context_switch_tool = lambda **kw: {"function": {"name": "switch_context"}}
        w._tdd_voice_switch_tool = lambda: {"function": {"name": "switch_tdd_voice"}}
        w._log_debug_event = Mock()
        w._truncate_debug_value = lambda value, limit: value
        w._generate_cache_key = lambda value: "key"
        w.messages = []
        w.instant_command_cache_manager = Mock()

    def test_tool_list_combines_local_tools_and_mcp_and_refreshes_after_disable(self):
        w = self.wingman
        names = {t["function"]["name"] for t in w._build_tools()}
        self.assertTrue({ALIAS, "mining_signature_lookup", "refinery_job_work_order_management"} <= names)
        self.fixture.managers["MiningManager"] = (False, "CORA")
        w._refresh_manager_runtime_state()
        for context in w.contexts_history.values():
            self.assertNotIn(ALIAS, {t["function"]["name"] for t in context["tools"]})
        # Even a manually retained old tool list cannot bypass the runtime check.
        w.current_tools = [{"function": {"name": ALIAS}}]
        self.fixture.factory.reset_mock()
        result, _ = asyncio.run(w._execute_command_by_function_call(ALIAS, {"location": "Daymar"}))
        self.assertFalse(result["success"])
        self.fixture.factory.assert_not_called()

    def test_local_dispatch_still_works_and_mcp_dispatch_checks_context(self):
        w = self.wingman
        asyncio.run(w._execute_command_by_function_call("mining_signature_lookup", {"signature_value": 10800}))
        self.local_call.assert_called_once_with({"signature_value": 10800})
        result, _ = asyncio.run(w._execute_command_by_function_call(ALIAS, {"location": "Daymar"}))
        self.assertTrue(result["success"])
        w.current_context = "TDD"
        self.fixture.factory.reset_mock()
        result, _ = asyncio.run(w._execute_command_by_function_call(ALIAS, {}))
        self.assertFalse(result["success"])
        self.fixture.factory.assert_not_called()

    def test_mcp_calls_are_neither_replayed_from_nor_written_to_instant_cache(self):
        import json
        w = self.wingman
        for name in (ALIAS, "mcp_starhead_MiningManager_sc_mining"):
            self.assertFalse(w._is_cached_command_data_valid([[name, {"location": "Daymar"}]]))
        tool = SimpleNamespace(id="mcp1", function=SimpleNamespace(
            name=ALIAS, arguments=json.dumps({"location": "Daymar"})))
        asyncio.run(w._handle_tool_calls([tool], "cache-key", command_phrase="Was gibt es auf Daymar?"))
        w.instant_command_cache_manager.put.assert_not_called()
        self.assertEqual("Daymar", json.loads(w.messages[-1]["content"])["data"]["location"])


if __name__ == "__main__":
    unittest.main()
