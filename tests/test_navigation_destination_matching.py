"""Destination matching must not silently route to another similarly named place."""

import unittest
from unittest.mock import Mock

from wingmen.star_citizen_services.functions.navigation_services.navigation_manager import (
    NavigationManager,
)


class NavigationDestinationMatchingTests(unittest.TestCase):
    def setUp(self):
        self.manager = object.__new__(NavigationManager)
        self.manager.location_match_score_cutoff = 70
        self.manager.confirmation_request_reason = ""
        self.manager.confirmation_instructions_template = ""
        self.manager.no_match_instructions = ""
        self.manager.overlay = Mock()
        self.manager._execute_navigation_sequence = Mock(return_value={"success": True})
        self.set_names(space_stations=["Pyro Gateway (Stanton)"])

    def set_names(self, **categories):
        self.manager._navigation_location_names_by_category = categories
        self.manager._navigation_location_names = [
            name for names in categories.values() for name in names
        ]

    def navigate(self, name, category="station"):
        args = {"location_name": name}
        if category:
            args["location_category"] = category
        return self.manager.navigate_to_location(args)

    def test_reported_gateway_mismatch_does_not_execute_navigation(self):
        result = self.navigate("Stanton Gateway (Stanton)")
        self.assertFalse(result["success"])
        self.assertFalse(result["location_match"]["matched"])
        self.assertGreaterEqual(result["location_match"]["score"], 70)
        self.assertTrue(result["confirmation_request"]["required"])
        self.assertEqual(
            result["confirmation_request"]["candidate_location_name"],
            "Pyro Gateway (Stanton)",
        )
        self.assertIn("explicit user confirmation", result["instructions"])
        self.manager._execute_navigation_sequence.assert_not_called()
        self.manager.overlay.display_overlay_text.assert_not_called()

    def test_bare_gateway_does_not_match_a_different_gateway(self):
        result = self.navigate("Stanton Gateway")
        self.assertFalse(result["success"])
        self.manager._execute_navigation_sequence.assert_not_called()

    def test_exact_destination_still_routes(self):
        result = self.navigate("  PYRO GATEWAY (STANTON)  ")
        self.assertTrue(result["success"])
        self.manager._execute_navigation_sequence.assert_called_once_with("Pyro Gateway")

    def test_unique_unqualified_destination_still_routes(self):
        result = self.navigate("Pyro Gateway")
        self.assertTrue(result["success"])
        self.manager._execute_navigation_sequence.assert_called_once_with("Pyro Gateway")

    def test_ambiguous_unqualified_gateway_requires_confirmation(self):
        self.set_names(space_stations=["Stanton Gateway (Pyro)", "Stanton Gateway (Nyx)"])
        result = self.navigate("Stanton Gateway")
        self.assertFalse(result["success"])
        self.assertTrue(result["confirmation_request"]["required"])
        self.manager._execute_navigation_sequence.assert_not_called()

    def test_conflicting_system_suffix_is_not_discarded(self):
        self.set_names(space_stations=["Stanton Gateway (Pyro)"])
        result = self.navigate("Stanton Gateway (Stanton)")
        self.assertFalse(result["success"])
        self.manager._execute_navigation_sequence.assert_not_called()

    def test_even_high_similarity_typo_requires_confirmation(self):
        self.set_names(space_stations=["Port Tressler"])
        result = self.navigate("Port Tresler")
        self.assertFalse(result["success"])
        self.assertGreater(result["location_match"]["score"], 90)
        self.manager._execute_navigation_sequence.assert_not_called()
        confirmed = self.navigate(result["confirmation_request"]["candidate_location_name"])
        self.assertTrue(confirmed["success"])
        self.manager._execute_navigation_sequence.assert_called_once_with("Port Tressler")

    def test_suggestion_uses_best_score_across_categories(self):
        self.set_names(outposts=["Port Other"], space_stations=["Port Tressler"])
        result = self.navigate("Port Tresler", category=None)
        self.assertEqual(result["confirmation_request"]["candidate_location_name"], "Port Tressler")
        self.assertEqual(result["confirmation_request"]["candidate_location_category"], "space_stations")

    def test_explicit_category_limits_suggestions(self):
        self.set_names(outposts=["Port Tressler"], space_stations=["Pyro Gateway"])
        result = self.navigate("Port Tressler")
        self.assertFalse(result["success"])
        self.assertEqual(result["confirmation_request"]["candidate_location_category"], "space_stations")
        self.manager._execute_navigation_sequence.assert_not_called()

    def test_empty_category_still_returns_clarification_instructions(self):
        self.set_names(outposts=["Some Outpost"], space_stations=[])
        result = self.navigate("Stanton Gateway")
        self.assertFalse(result["success"])
        self.assertNotIn("confirmation_request", result)
        self.assertIn("Ask the user", result["instructions"])
        self.manager._execute_navigation_sequence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
