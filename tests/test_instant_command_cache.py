"""Exercise cache paths without loading Windows audio and keyboard dependencies."""

import ast
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]


def load_class(path, name, methods, namespace, bases=()):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    cls.body = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods]
    cls.bases = [ast.Name(id=base, ctx=ast.Load()) for base in bases]
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(ROOT / path), "exec"), namespace)
    return namespace[name]


namespace = {"json": json, "DEBUG": False, "printr": Mock(),
             "find_best_match": SimpleNamespace(find_best_match=Mock(return_value=(0, False)))}
Base = load_class("wingmen/open_ai_wingman.py", "OpenAiWingman", {
    "_is_cached_command_name_valid", "_is_cached_command_data_valid",
    "_get_response_for_transcript", "_handle_tool_calls",
}, namespace)
StarCitizen = load_class("wingmen/star_citizen_wingman.py", "StarCitizenWingman", {
    "_is_cached_command_name_valid",
}, namespace, ("OpenAiWingman",))

OLD = "spaceship_general_Open_All_Doors"
CURRENT = "vehicle_general_Open_All_Doors"


def calls(name):
    return [["execute_command", {"command_name": name}]]


class InstantCommandCacheTests(unittest.TestCase):
    def setUp(self):
        self.wingman = StarCitizen()
        w = self.wingman
        w.config = {}
        w._get_command = Mock(side_effect=lambda name: {"name": name} if name == "custom" else None)
        w.sc_keybinding_service = Mock()
        w.sc_keybinding_service.get_bound_keybinding_names.return_value = [CURRENT]
        w.manage_feature_manager_state = Mock(__name__="manage_feature_manager_state")
        w.ai_functions_manager = Mock()
        w.ai_functions_manager.get_function_registry.return_value = {"registered_tool": Mock()}
        w.debug = False
        w.messages = []
        w._log_debug_event = Mock()
        w._truncate_debug_value = lambda value, limit: value
        w._generate_cache_key = lambda value: hashlib.sha256(str(value).encode()).hexdigest()
        w.instant_command_cache_manager = Mock()

    def test_current_and_custom_commands_remain_compatible(self):
        for name in (CURRENT, "custom"):
            self.assertTrue(self.wingman._is_cached_command_data_valid(calls(name)))

    def test_removed_inactive_and_disallowed_commands_are_rejected(self):
        w = self.wingman
        self.assertFalse(w._is_cached_command_data_valid(calls(OLD)))
        w.config["avoid-commands"] = [CURRENT]
        self.assertFalse(w._is_cached_command_data_valid(calls(CURRENT)))
        w.config.clear()
        w.sc_keybinding_service.get_bound_keybinding_names.return_value = []
        self.assertFalse(w._is_cached_command_data_valid(calls(CURRENT)))

    def test_malformed_and_mixed_batches_are_rejected(self):
        for data in ([], {}, [["execute_command", {}]], [["execute_command", None]],
                     calls(123), [[[], {}]], calls(CURRENT) + calls(OLD)):
            with self.subTest(data=data):
                self.assertFalse(self.wingman._is_cached_command_data_valid(data))
        self.assertTrue(self.wingman._is_cached_command_data_valid([["registered_tool", {}]]))

    def test_stale_exact_and_fuzzy_hits_fall_back_without_execution(self):
        for stale_calls in (calls(OLD), [["search_ship_component", {"component_name": "FR-76"}]]):
            with self.subTest(stale_calls=stale_calls):
                self.assertFalse(self.wingman._is_cached_command_data_valid(stale_calls))
                self.check_stale_cache_fallback(stale_calls)

    def check_stale_cache_fallback(self, stale_calls):
        for fuzzy in (False, True):
            with self.subTest(fuzzy=fuzzy):
                w = self.wingman
                cache = Mock()
                w.instant_command_cache_manager = cache
                cache.get.side_effect = [None, stale_calls] if fuzzy else [stale_calls]
                cache.get_key_from_text.return_value = "old-fuzzy-key"
                w.cache_config = {key: [] for key in (
                    "delete_last_cached_command_phrases", "do_not_cache_phrases", "short_memory_commands")}
                w._try_instant_activation = Mock(return_value=None)
                w._add_user_message = Mock()
                w._gpt_call = Mock(return_value=None)
                w._handle_tool_call_sequence_error = Mock(return_value=None)
                w._handle_tool_calls = AsyncMock()
                asyncio.run(w._get_response_for_transcript(" Schiff öffnen. ", None))
                expected_key = "old-fuzzy-key" if fuzzy else w._generate_cache_key("schiff öffnen.")
                cache._remove_entry.assert_called_once_with(expected_key)
                w._gpt_call.assert_called_once()
                w._handle_tool_calls.assert_not_called()

    def test_invalid_new_calls_are_not_cached(self):
        w = self.wingman
        w._execute_command_by_function_call = AsyncMock(return_value=({"success": False}, None))
        for name, should_cache in ((OLD, False), (CURRENT, True)):
            with self.subTest(name=name):
                w.instant_command_cache_manager.reset_mock()
                tool = SimpleNamespace(id="call1", function=SimpleNamespace(
                    name="execute_command", arguments=json.dumps({"command_name": name})))
                asyncio.run(w._handle_tool_calls([tool], "new-key", command_phrase="schiff öffnen."))
                self.assertEqual(should_cache, w.instant_command_cache_manager.put.called)


if __name__ == "__main__":
    unittest.main()
