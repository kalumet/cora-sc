import unittest
from unittest.mock import patch

from wingmen.star_citizen_services.functions.component_services import component_manager


class ComponentManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = component_manager.ComponentManager({}, {})
        self.session_patch = patch.object(component_manager.requests, "Session")
        self.session = self.session_patch.start().return_value.__enter__.return_value
        self.addCleanup(self.session_patch.stop)
        self.printr_patch = patch.object(component_manager, "printr")
        self.printr_patch.start()
        self.addCleanup(self.printr_patch.stop)

    def search(self, prices, shops=None):
        self.session.get.return_value.json.return_value = {
            "data": [{"name": "Ambit Coverall", "uex_prices": prices, "shops": shops}]
        }
        result = self.manager.search_ship_component({"component_name": "coverall"})
        self.assertTrue(result["success"])
        self.assertEqual(1, result["total_found"])
        return result["components"][0]

    def test_coverall_empty_purchase_list(self):
        component = self.search({"purchase": []}, [])
        self.assertIsNone(component["price"])
        self.assertIsNone(component["price_location"])
        self.assertFalse(component["purchasable_ingame"])

    def test_current_and_legacy_formats_select_cheapest_numeric_price(self):
        offers = [
            {"price_buy": "100", "terminal_name": "Expensive"},
            {"price_buy": "20.5", "terminal_name": "Cheapest"},
            {"price_buy": 50, "terminal_name": "Other"},
        ]
        for prices in (offers, {"purchase": offers}):
            with self.subTest(prices=prices):
                component = self.search(prices)
                self.assertEqual(20.5, component["price"])
                self.assertEqual("Cheapest", component["price_location"])
                self.assertTrue(component["purchasable_ingame"])

    def test_invalid_offers_do_not_hide_valid_purchase(self):
        invalid_values = [None, "", "invalid", 0, -1, True, [], {}, "NaN", "Infinity"]
        offers = ["purchase", None, {}, {"price_sell": 10}]
        offers.extend({"price_buy": value} for value in invalid_values)
        offers.append({"price_buy": 42, "terminal_name": "Shop"})
        component = self.search({"purchase": offers})
        self.assertEqual(42, component["price"])
        self.assertEqual("Shop", component["price_location"])

    def test_unavailable_prices_preserve_component_and_shop_information(self):
        for prices in (None, "unavailable", {}, [], {"purchase": None},
                       {"purchase": "unavailable"}, {"purchase": {}},
                       {"purchase": [{"price_buy": None, "price_sell": 9281}]}):
            with self.subTest(prices=prices):
                component = self.search(prices, [{"name": "Shop"}])
                self.assertIsNone(component["price"])
                self.assertIsNone(component["price_location"])
                self.assertTrue(component["purchasable_ingame"])
                self.assertEqual("Ambit Coverall", component["name"])

    def test_no_results(self):
        self.session.get.return_value.json.return_value = {"data": []}
        result = self.manager.search_ship_component({"component_name": "coverall"})
        self.assertFalse(result["success"])

    def test_network_failure_returns_error(self):
        self.session.get.side_effect = component_manager.requests.exceptions.Timeout("timeout")
        result = self.manager.search_ship_component({"component_name": "coverall"})
        self.assertFalse(result["success"])
        self.assertEqual("timeout", result["error"])


if __name__ == "__main__":
    unittest.main()
