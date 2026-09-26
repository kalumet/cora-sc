"""ComponentManager lifecycle with the real central registry and an in-process MCP server."""

import asyncio
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from mcp import Client
from mcp.server import MCPServer
import yaml

from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.function_manager import StarCitizensAiFunctionsManager
from wingmen.star_citizen_services.functions.component_services.component_manager import ComponentManager


TOOLS = {
    "sc_component_info": {"component": "FR-76"},
    "sc_find_components": {"kind": "shield"},
    "sc_where_to_buy": {"item": "FR-76"},
    "sc_ship_loadout": {"ship": "Gladius"},
    "sc_loadout_calc": {"ship": "Gladius", "swaps": [{"kind": "weapon", "component": "Attrition-3"}]},
}
ALIASES = {f"starhead_{name}" for name in TOOLS}


def register_component_only(owner, config, secret_keeper):
    # Avoid discovering unrelated managers with desktop and hardware dependencies.
    name = "ComponentManager"
    owner.manager_classes[name] = ComponentManager
    owner.manager_metadata[name] = owner._extract_manager_metadata(ComponentManager)
    owner.command_phrases[name] = owner._resolve_manager_command_phrases(name)
    owner.manager_states[name] = False


class ComponentManagerTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "configs/system/config.example.yaml"
        self.config = yaml.safe_load(path.read_text(encoding="utf-8"))["wingmen"]["star-citizen-ai"]
        self.config = deepcopy(self.config)
        self.config["mcp"]["manager_tools"] = {
            "ComponentManager": self.config["mcp"]["manager_tools"]["ComponentManager"]
        }
        self.config["features"]["ComponentManager"] = False
        self.server = MCPServer("Component fixture")
        self.calls = []

        @self.server.tool(name="sc_component_info")
        def component_info(component: str) -> dict:
            """Look up a component's performance stats."""
            return self.record("sc_component_info", {"component": component})

        @self.server.tool(name="sc_find_components")
        def find_components(kind: str) -> dict:
            return self.record("sc_find_components", {"kind": kind})

        @self.server.tool(name="sc_where_to_buy")
        def where_to_buy(item: str) -> dict:
            return self.record("sc_where_to_buy", {"item": item})

        @self.server.tool(name="sc_ship_loadout")
        def ship_loadout(ship: str) -> dict:
            return self.record("sc_ship_loadout", {"ship": ship})

        @self.server.tool(name="sc_loadout_calc")
        def loadout_calc(ship: str, swaps: list[dict]) -> dict:
            return self.record("sc_loadout_calc", {"ship": ship, "swaps": swaps})

        @self.server.tool(name="sc_mining")
        def mining() -> str:
            raise AssertionError("Unassigned tool must not be called")

        self.factory = Mock(side_effect=lambda *args: Client(self.server))
        self.owner = self.make_owner(self.config)

    def record(self, name, arguments):
        self.calls.append((name, arguments))
        return {"name": name, "arguments": arguments}

    def make_owner(self, config):
        with patch.object(StarCitizensAiFunctionsManager, "initialize_function_managers", register_component_only):
            owner = StarCitizensAiFunctionsManager(config, {})
        owner.mcp_tools.client_factory = self.factory
        owner.mcp_tools.report_warning = Mock()
        return owner

    def activate(self):
        result = self.owner.activate_manager("ComponentManager")
        self.assertTrue(result["success"], result)
        return self.owner.manager_instances["ComponentManager"]

    def names(self, context=AIContext.CORA):
        return {t["function"]["name"] for t in self.owner.mcp_tools.get_tools(context)}

    def test_activation_exposes_exactly_five_mcp_tools_without_local_search(self):
        self.assertEqual(set(), self.names())
        self.factory.assert_not_called()
        manager = self.activate()
        self.assertEqual(ALIASES, self.names())
        self.assertEqual([manager], self.owner.get_managers(AIContext.CORA))
        self.assertEqual({}, self.owner.get_function_registry())
        self.assertEqual([], manager.get_function_tools())
        self.assertFalse(hasattr(manager, "search_ship_component"))
        self.assertNotIn("search_ship_component", manager.get_function_prompt())
        self.assertEqual([], self.owner.get_managers(AIContext.TDD))
        self.assertEqual(set(), self.names(AIContext.TDD))

    def test_all_tools_dispatch_through_sdk_and_results_are_not_cached(self):
        self.activate()
        for name, args in TOOLS.items():
            with self.subTest(tool=name):
                result = asyncio.run(self.owner.mcp_tools.call_tool(f"starhead_{name}", args, AIContext.CORA))
                self.assertTrue(result["success"], result)
                self.assertTrue(result["do_not_cache"])
                self.assertEqual({"name": name, "arguments": args}, result["data"])
        self.assertEqual(list(TOOLS.items()), self.calls)

    def test_context_and_deactivation_block_retained_calls_and_reactivation_restores_tools(self):
        manager = self.activate()
        self.factory.reset_mock()
        for name, args in TOOLS.items():
            result = asyncio.run(self.owner.mcp_tools.call_tool(f"starhead_{name}", args, AIContext.TDD))
            self.assertFalse(result["success"])
        self.owner.deactivate_manager("ComponentManager")
        self.assertEqual(set(), self.names())
        self.assertEqual([], self.owner.get_managers(AIContext.CORA))
        for name, args in TOOLS.items():
            result = asyncio.run(self.owner.mcp_tools.call_tool(f"starhead_{name}", args, AIContext.CORA))
            self.assertFalse(result["success"])
        self.factory.assert_not_called()
        self.assertEqual([], self.calls)
        self.assertIs(manager, self.activate())
        self.assertEqual(ALIASES, self.names())

    def test_missing_configuration_or_disabled_server_has_no_local_fallback(self):
        for mcp_config in ({}, deepcopy(self.config["mcp"])):
            if mcp_config:
                mcp_config["servers"]["starhead"]["enabled"] = False
            config = deepcopy(self.config)
            config["mcp"] = mcp_config
            self.owner = self.make_owner(config)
            self.activate()
            self.assertEqual(set(), self.names())
            self.assertEqual({}, self.owner.get_function_registry())
        self.factory.assert_not_called()

    def test_discovery_failure_recovers_after_reactivation_and_call_failure_is_reported(self):
        self.factory.side_effect = TimeoutError("fixture unavailable")
        self.activate()
        self.assertEqual(set(), self.names())
        self.assertEqual({}, self.owner.get_function_registry())
        self.owner.mcp_tools.report_warning.assert_called()
        self.owner.deactivate_manager("ComponentManager")
        self.factory.side_effect = lambda *args: Client(self.server)
        self.activate()
        self.assertEqual(ALIASES, self.names())
        self.factory.side_effect = TimeoutError("fixture unavailable")
        result = asyncio.run(self.owner.mcp_tools.call_tool(
            "starhead_sc_component_info", {"component": "FR-76"}, AIContext.CORA))
        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])
        self.assertTrue(result["do_not_cache"])
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
