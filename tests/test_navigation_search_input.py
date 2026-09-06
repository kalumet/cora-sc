"""Navigation input checks without keyboard events on the desktop."""

import unittest
from unittest.mock import Mock, patch

from wingmen.star_citizen_services.functions.navigation_services import navigation_manager as nav


class NavigationSearchInputTests(unittest.TestCase):
    def setUp(self):
        self.manager = object.__new__(nav.NavigationManager)
        self.manager.text_input_step_wait_seconds = 0.12
        self.manager.overlay = Mock()
        self.backend = Mock()
        self.clipboard = Mock()
        for owner, name, replacement in (
            (nav, "key_module", self.backend),
            (nav, "pyperclip", self.clipboard),
            (nav.time, "sleep", Mock()),
        ):
            patcher = patch.object(owner, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_paste_leaves_destination_in_clipboard_without_copy_back(self):
        self.manager._typewrite_text("Levski")
        self.clipboard.copy.assert_called_once_with("Levski")
        self.clipboard.paste.assert_not_called()
        self.assertNotIn(unittest.mock.call("c"), self.backend.keyDown.call_args_list)

    def test_select_failure_still_releases_ctrl(self):
        self.backend.press.side_effect = RuntimeError("select failed")
        with self.assertRaisesRegex(RuntimeError, "select failed"):
            self.manager._typewrite_text("Levski")
        self.backend.keyUp.assert_called_with("ctrl")

    def test_paste_failure_releases_v_and_ctrl(self):
        def key_down(key):
            if key == "v":
                raise RuntimeError("paste failed")
        self.backend.keyDown.side_effect = key_down
        with self.assertRaisesRegex(RuntimeError, "paste failed"):
            self.manager._typewrite_text("Levski")
        self.backend.keyUp.assert_any_call("v")
        self.backend.keyUp.assert_called_with("ctrl")

    def prepare_sequence(self):
        self.manager._execute_sc_command = Mock(return_value=(True, ""))
        self.manager._focus_sc_window_for_input = Mock()
        self.manager._zoom_out_map = Mock()
        self.manager._get_or_capture_click_point = Mock(return_value=((299, 179), True, None))
        self.manager._focus_search_field = Mock()
        self.manager._click_screen_coordinates = Mock(return_value=True)
        self.manager._press_route_key = Mock()
        self.manager.lock_mouse_until_route_clicked = False
        for name in ("map_open_wait_seconds", "map_input_activation_wait_seconds",
                     "post_zoom_wait_seconds", "post_type_wait_seconds", "selection_wait_seconds"):
            setattr(self.manager, name, 0)

    def test_input_failure_aborts_before_selection_and_route(self):
        self.prepare_sequence()
        self.clipboard.copy.side_effect = RuntimeError("clipboard busy")
        result = self.manager._execute_navigation_sequence("Levski")
        self.assertFalse(result["success"])
        self.manager._get_or_capture_click_point.assert_called_once()
        self.manager._press_route_key.assert_not_called()
        self.assertIn("no route was set", result["instructions"])

    def test_sent_route_is_not_reported_as_verified(self):
        self.prepare_sequence()
        result = self.manager._execute_navigation_sequence("Levski")
        self.manager._press_route_key.assert_called_once()
        self.assertTrue(result["success"])
        self.assertFalse(result["route_verified"])
        self.assertIn("unverified", result["message"])


if __name__ == "__main__":
    unittest.main()
