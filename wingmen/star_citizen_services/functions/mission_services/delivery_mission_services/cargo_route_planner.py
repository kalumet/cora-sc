from wingmen.star_citizen_services.model.mission_location_information import MissionLocationInformation
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission

class CargoRoutePlanner:

    @staticmethod
    def finde_routes_for_delivery_missions(ordered_delivery_missions: [MissionLocationInformation], uex_locations_and_prices):
        planet = ""
        index = 1

        while planet == "":
            last = ordered_delivery_missions[-index]

            if last.location.get("planet") is None or last.location.get("planet") == "":
                if index < len(ordered_delivery_missions):
                    index += 1
                    continue
                else:
                    return  # No buying possible

            planet = last.location.get("planet")
            print(f"location observed: {last}")

        search_planet = planet

        # Make a map of the uexDB:
        CargoRoutePlanner.uex_location_code_map = {loc.get("code"): loc for loc in uex_locations_and_prices}

        # Filter and find city with TDD
        city = next((loc for loc in uex_locations_and_prices if loc.get("planet") == search_planet and 
                     loc.get("city") and "TDD" in loc.get("name_short", "")), None)

        if city is None:
            print(f"Didn't find TDD for planet: {planet}")
            return  # No city TDD found

        # Sellable commodities at the city location
        city_sellable_commodities = {key for key, value in city.get("prices", {}).items() if value.get("operation") == "sell"}

        # Store the codes of prices
        buyable_commodities_on_itinerary = set()
        sellable_commodities_on_itinerary = set()

        # Determine commodities buyable and sellable on the itinerary
        for location_packages in ordered_delivery_missions:
            location = location_packages.location
            for key, prices in location.get("prices", {}).items():
                if prices.get("operation") == "buy":
                    buyable_commodities_on_itinerary.add(key)
                if prices.get("operation") == "sell":
                    sellable_commodities_on_itinerary.add(key)

        # Intersection of sellable and buyable commodities
        sellable_commodities_on_itinerary.update(city_sellable_commodities)
        buyable_commodities_on_itinerary.intersection_update(sellable_commodities_on_itinerary)

        # Find best commodity to buy and sell
        city_packages = MissionLocationInformation(city)
        ordered_delivery_missions.append(city_packages)

        current_revert_index = len(ordered_delivery_missions) - 1
        commodity_to_buy_location = None

        while current_revert_index >= 0:
            potential_selling_location = ordered_delivery_missions[current_revert_index]

            # Filter commodities that can be sold here
            targeted_commodities = {key: value for key, value in potential_selling_location.location.get("prices", {}).items()
                                    if value.get("operation") == "sell" and key in sellable_commodities_on_itinerary}

            # Call method to find commodities to buy (to be implemented)
            commodity_to_buy_location = CargoRoutePlanner.find_commodities_to_buy(
                ordered_delivery_missions, uex_location_map, potential_selling_location,
                current_revert_index, commodity_to_buy_location, buyable_commodities_on_itinerary, targeted_commodities)

            current_revert_index -= 1

    @staticmethod
    def find_commodities_to_buy(ordered_pickup_and_delivery_locations, uex_location_map, potential_selling_location, 
                                current_revert_index, commodity_to_buy_location, buyable_commodities_on_itinerary, targeted_commodities):
        
        # If a commodity to buy has already been identified, no need to continue for this location
        if commodity_to_buy_location is not None:
            if commodity_to_buy_location == potential_selling_location:
                # Restart the process to find another commodity that could be sold here
                commodity_to_buy_location = None
            else:
                return commodity_to_buy_location

        # Keep commodities that are buyable on the itinerary
        targeted_commodities = {k: v for k, v in targeted_commodities.items() if k in buyable_commodities_on_itinerary}

        # Sort commodities by their selling price in descending order
        sorted_prices = dict(sorted(targeted_commodities.items(), key=lambda item: -item[1]['price_sell']))

        # Iterate over commodities to find the best buying spot within 3 hops
        best_commodity_key = None
        best_margin = 0.0
        best_location = None

        for commodity_key, current_commodity in sorted_prices.items():
            found_location = CargoRoutePlanner.find_location_in_distance_for_commodity(
                ordered_pickup_and_delivery_locations, current_revert_index, 0, None, commodity_key)

            if found_location is not None:
                # Calculate margin for the current commodity
                potential_selling_location_key = potential_selling_location.location['code']
                found_location_key = found_location.location['code']
                current_location_margin = (uex_location_map[potential_selling_location_key]['prices'][commodity_key]['price_sell'] - 
                                           uex_location_map[found_location_key]['prices'][commodity_key]['price_buy'])

                # Update best commodity, margin, and location if current margin is better
                if best_commodity_key is None or current_location_margin > best_margin:
                    best_commodity_key = commodity_key
                    best_margin = current_location_margin
                    best_location = found_location

        # Set the buy and sell locations if a best commodity is found
        if best_location is not None:
            best_location.buy_at_location = True
            best_location.buying_commodity_code = best_commodity_key

            potential_selling_location.sell_at_location = True
            potential_selling_location.selling_commodity_code = best_commodity_key

            return best_location

        return None
    
    @staticmethod
    def find_location_in_distance_for_commodity(ordered_pickup_and_delivery_locations, current_revert_index, distance,
                                                tmp_location_package, commodity_key):
        # Check if there are still locations to be visited within the distance limit
        next_temp_location = None
        if current_revert_index >= 1 and distance < 3:
            next_temp_location = CargoRoutePlanner.find_location_in_distance_for_commodity(
                ordered_pickup_and_delivery_locations, current_revert_index - 1, distance + 1,
                tmp_location_package, commodity_key)

        current_tmp_location = ordered_pickup_and_delivery_locations[current_revert_index]

        # Skip locations marked as outlaw to reduce risk
        if current_tmp_location.location['outlaw']:
            return None

        current_tmp_price = current_tmp_location.location['prices'].get(commodity_key)
        if current_tmp_price is None or current_tmp_price['operation'] == 'sell':
            # Commodity cannot be bought at this location
            return next_temp_location

        if next_temp_location is None:
            # No decision needed, return the current temporary location
            return current_tmp_location

        next_tmp_price = next_temp_location.location['prices'].get(commodity_key)
        if next_tmp_price is None or next_tmp_price['operation'] == 'sell':
            # Commodity cannot be bought at the next temporary location
            return current_tmp_location

        # Return the location with the lower buy price
        return current_tmp_location if current_tmp_price['price_buy'] <= next_tmp_price['price_buy'] else next_temp_location
    