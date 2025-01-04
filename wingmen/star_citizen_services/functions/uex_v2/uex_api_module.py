import json
import os
import time
import requests
import random
import heapq

if __name__ != "__main__":
    from wingmen.star_citizen_services.helper import find_best_match


DEBUG = True
TEST = False
CALL_UEX_SR_ENDPOINT = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


if __name__ != "__main__":
    from services.printr import Printr

    printr = Printr()

# basic field names among all endpoints:
ID_FIELD_NAME = "id"
NAME_FIELD_NAME = "name"

# endpoint names
CATEGORY_VEHICLES = "vehicles"
CATEGORY_CITIES = "cities"
CATEGORY_COMMODITIES = "commodities"
CATEGORY_TERMINALS = "terminals"
CATEGORY_OUTPOSTS = "outposts"
CATEGORY_ORBITS = "orbits"
CATEGORY_MOONS = "moons"
CATEGORY_ITEMS = "items"
PRICES_COMMODITIES = "commodities_prices"
PRICES_VEHICLES = "vehicles_purchases_prices"
PRICES_ITEMS = "items_prices"
CATEGORY_REFINERY_METHODS = "refineries_methods"


ACTIVE_STAR_SYSTEMS = {
    "Stanton": 68,
    "Pyro": 64,
}


class UEXApi2():

    _uex_instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._uex_instance:
            cls._uex_instance = super(UEXApi2, cls).__new__(cls)
        return cls._uex_instance

    def __init__(self):
        # Initialize your instance here, if not already initialized
        if not hasattr(self, 'is_initialized'):
            self.root_data_path = "star_citizen_data/uex2"
            
            self.base_url = "https://uexcorp.space/api/2.0/"
            self.session = requests.Session()
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})
            self.session.headers.update({"secret_key": f"{self.user_secret_key}"})
            
            self.vehicles_max_age = 864010  # ~10 days
            self.cities_max_age = 864120  # ~10 days
            self.commodities_max_age = 864230  # ~10 days
            self.terminals_max_age = 864340  # ~10 days
            self.outposts_max_age = 864450  # ~10 days
            self.orbits_max_age = 864560  # ~10 days
            self.moons_max_age = 864670  # ~10 days
            self.items_max_age = 864780  # ~10 days
            self.vehicle_prices_max_age = 864090  # ~10 days (UEX refresh)(prices)
            self.commodities_prices_max_age = 1210  # ~20 min (UEX 1h refresh)(prices)
            self.item_prices_max_age = 7210  # ~2h (UEX refresh)(prices)
            self.refinery_methods_max_age = 864780  # ~10 days

            self.max_ages = {
                CATEGORY_VEHICLES: self.vehicles_max_age,
                CATEGORY_CITIES: self.cities_max_age,
                CATEGORY_COMMODITIES: self.commodities_max_age,
                CATEGORY_TERMINALS: self.terminals_max_age,
                CATEGORY_ORBITS: self.orbits_max_age,
                CATEGORY_MOONS: self.moons_max_age,
                CATEGORY_ITEMS: self.item_prices_max_age,
                CATEGORY_OUTPOSTS: self.outposts_max_age,
                PRICES_COMMODITIES: self.commodities_prices_max_age,
                PRICES_ITEMS: self.item_prices_max_age,
                PRICES_VEHICLES: self.item_prices_max_age,
                CATEGORY_REFINERY_METHODS: self.refinery_methods_max_age
            }

            self.inventory_state_mapping = {
                "OUT OF STOCK": 1, 
                "VERY LOW INVENTORY": 2, 
                "LOW INVENTORY": 3,
                "MEDIUM INVENTORY": 4,
                "HIGH INVENTORY": 5,
                "VERY HIGH INVENTORY": 6,
                "MAX INVENTORY": 7
            }


            self.code_mapping = {}
            self.name_mapping = {}
            self.data = {}

            print_debug("Initializing UexApi2 instance")
            self.is_initialized = True
        else:
            print_debug("UexApi2 instance already initialized")
    
    @classmethod
    def init(cls, uex_api_key: str, user_secret_key: str):
        cls.api_key = uex_api_key
        cls.user_secret_key = user_secret_key
        # get secret mappings stuff

        return cls()

    def get_api_endpoints_per_category(self, system_id, category=None):
        api_endpoints = {
                CATEGORY_VEHICLES: f"{CATEGORY_VEHICLES}/",
                CATEGORY_CITIES: f"{CATEGORY_CITIES}/id_star_system/{system_id}/",
                CATEGORY_COMMODITIES: f"{CATEGORY_COMMODITIES}/",
                CATEGORY_TERMINALS: f"{CATEGORY_TERMINALS}/id_star_system/{system_id}/",
                CATEGORY_ORBITS: f"{CATEGORY_ORBITS}/id_star_system/{system_id}/",
                CATEGORY_MOONS: f"{CATEGORY_MOONS}/id_star_system/{system_id}/",
                CATEGORY_ITEMS: f"{CATEGORY_ITEMS}/",
                CATEGORY_OUTPOSTS: f"{CATEGORY_OUTPOSTS}/id_star_system/{system_id}/",
                PRICES_COMMODITIES: f"{PRICES_COMMODITIES}/",
                PRICES_ITEMS: f"{PRICES_ITEMS}/",  # filter applied later
                PRICES_VEHICLES: f"{PRICES_VEHICLES}/",  # filter applied later
                CATEGORY_REFINERY_METHODS: f"{CATEGORY_REFINERY_METHODS}/"
            }
        
        if category:
            return api_endpoints.get(category)
        
        return api_endpoints
        
    def _fetch_from_file_or_api(self, category, **additional_category_filters):
        file_age = self.max_ages[category]
        max_age_seconds = self.max_ages[category]

        file_path = f"{self.root_data_path}/{category}"
        for attribut, value in additional_category_filters.items():
            file_path += f"_{attribut}-{value}"
        
        file_path += ".json"

        file_data = None
        # Check if the file exists and is not too old
        if os.path.exists(file_path):
            file_age = time.time() - os.path.getmtime(file_path)

            with open(file_path, 'r', encoding="utf-8") as file:
                file_data = json.load(file)
                
        if file_age < max_age_seconds:
            # print_debug(f"Loading from file {name}")
            return file_data, file_age
        
        data = self._fetch_data_api(category, **additional_category_filters)
        if not data:
            # print_debug("Force loading from file")
            if not file_data:
                # print_debug("empty")
                return None, None
            
            print_debug(f"no data from uex.api. Postponing file refresh: {file_path}")
            # we got an error from api, so we should extend the time before we retry the next time
            # therefore, we write back the data to file to update the file-date
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(file_data, file, indent=3)
            return file_data, file_age
        else:
            # Make a map of the uexDB:
            uex_location_code_map = {loc.get(ID_FIELD_NAME): loc for loc in data}

            # save the call to the file system
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(uex_location_code_map, file, indent=3)

            # print_debug(f"saved new api data to {file_path}")
            return uex_location_code_map, 0

    def _fetch_data(self):
        return self._refresh_data()

    def _refresh_data(self):
        """
        Fetch data from a file if it exists and is not too old, otherwise fetch from the API.
        :param category: if provided, will get data only for the given category, else all categories will be fetched and updated.
        :param additional_category_filters: only relevant, if the category is provided (usually a price category request that should be filtered to something)
        :return: Data either from the file or the API
        """
        categories = [CATEGORY_CITIES, CATEGORY_COMMODITIES, CATEGORY_MOONS, CATEGORY_ORBITS, CATEGORY_OUTPOSTS, CATEGORY_TERMINALS, CATEGORY_VEHICLES, CATEGORY_REFINERY_METHODS]
        
        for check_category in categories:
            if self._needs_refresh(check_category):
                data, age = self._fetch_from_file_or_api(check_category)
                
                self._write_code_mapping_to_file(data=data, category=check_category, api_value_field=NAME_FIELD_NAME, export_value_field_name=NAME_FIELD_NAME, export_code_field_name=ID_FIELD_NAME)
                self.data[check_category] = {"data": data, "age": age}

        # # Kombinieren aller Daten in einem Dictionary
        # data = {
        #     CATEGORY_SHIPS: {"data": ship_data, "age": ship_age},
        #     CATEGORY_CITIES: {"data": cities_data, "age": cities_age},
        #     CATEGORY_COMMODITIES: {"data": commodities_data, "age": commoties_age},
        #     CATEGORY_TRADEPORTS: {"data": tradeports_data, "age": tradeports_age},
        #     CATEGORY_PLANETS: {"data": planets_data, "age": planets_age},
        #     CATEGORY_SATELLITES: {"data": satellites_data, "age": sattelites_age}
        # }

    def _needs_refresh(self, category, **additional_category_filters):
        if not category or not self.data or category not in self.data:
            return True
        
        category_key = category
        for attribute, value in additional_category_filters:
            category_key += f"_{attribute}-{value}"
        return self.data[category_key].get("age") is None or self.data[category_key].get("age") > self.max_ages[category]

    def _write_code_mapping_to_file(self, data, category, api_value_field, export_code_field_name, export_value_field_name):
        """
        Writes the code mapping for entities to a file from the given data.

        Args:
        - data (list of dicts): Data containing the key-value pairs to be written.
        - category (str): Category of the data, used for filename and internal mapping.
        - key_field (str): The field to be used as the key in the key-value pair.
        - value_field (str): The field to be used as the value in the key-value pair.
        """

        if not data:
            return

        if category not in self.code_mapping:
            self.code_mapping[category] = {}
            self.name_mapping[category] = {}

        # Erstellen eines Dictionarys zur Speicherung der JSON-Daten
        json_data = {}
        for _, category_entry in data.items():
            entry_code = category_entry.get("code", "")
            entry_name = category_entry.get(api_value_field, "")
            entry_id = category_entry.get(export_code_field_name, "")
            self.code_mapping[category][entry_id] = entry_name
            self.name_mapping[category][entry_name] = entry_id
            json_data[entry_name] = {
                export_code_field_name: entry_id,
                export_value_field_name: entry_name,
                "code": entry_code
                }

        # Schreiben des Dictionarys in eine Datei als JSON
        with open(f"{self.root_data_path}/{category}_mapping.json", 'w', encoding='utf-8') as file:
            json.dump(json_data, file, ensure_ascii=False, indent=4)
 
    def _fetch_data_api(self, category, **additional_category_filters):
        
        category_data = []
        system_relevant_categories = {
            CATEGORY_CITIES,
            CATEGORY_TERMINALS,
            CATEGORY_ORBITS,
            CATEGORY_MOONS,
            CATEGORY_OUTPOSTS,
        }

        # only one iteration, if category not dependent of star system    
        for system_code in ACTIVE_STAR_SYSTEMS.values():
            print_debug(f"Fetching data for system {system_code}")

            endpoint = self.get_api_endpoints_per_category(system_code, category)

            url = f"{self.base_url}{endpoint}"
            response = self.session.get(url, params=additional_category_filters, timeout=30)
            actual_url = response.request.url

            if response.status_code == 200:
                print_debug(f"Request: {actual_url}")
                print_debug(f'result: {json.dumps(response.json(), indent=2)[0:100]}...')
                if category in system_relevant_categories:
                    category_data.extend(response.json()["data"])
                else:
                    return response.json()["data"]
            else:
                sent_headers = response.request.headers
                print_debug(f"Error calling: {actual_url}")
                print_debug(f"Sent headers: {json.dumps(dict(sent_headers), indent=2)}")
                print_debug(f"Response Body: {json.dumps(response.json(), indent=2)}")
                return None  # if there is one error, we stop the whole process
        
        return category_data


    def _filter_available_commodities(self, commodities_data, include_restricted_illegal, isOnlySellable=False):
        """
        Filters commodities based on buyable, sellable, and legal status.

        Args:
        - commodities_data (dict): Contains the data of commodities.
        - include_restricted_illegal (bool): If True, includes commodities regardless of their legal status (restricted or illegal).
        - isOnlySellable (bool): If True, filters only for sellable commodities. If False, filters for commodities that are both buyable and sellable.

        Returns:
        - dict: A dictionary of filtered commodities. If isOnlySellable is True, returns commodities that are sellable. 
                Otherwise, returns commodities that are both buyable and sellable, depending on the include_restricted_illegal flag.
        """
        if (include_restricted_illegal):
            buyable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_buyable'] == 1 and commodity['price_buy'] > 0}
            sellable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_sellable'] == 1 and commodity['price_sell'] > 0}
        else:
            buyable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_buyable'] == 1 and commodity['price_buy'] > 0 and commodity['is_illegal'] != 1}
            sellable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_sellable'] == 1 and commodity['price_sell'] > 0 and commodity['is_illegal'] != 1}

        # print_debug(f"buyable:  {json.dumps(buyable, indent=2)[0:150]}")
        # print_debug(f"sellable:  {json.dumps(sellable, indent=2)[0:150]}")
        if isOnlySellable:
            return sellable

        # Intersection of buyable and sellable commodities
        buyable_and_sellable = {code: buyable[code] for code in buyable if code in sellable}
        return buyable_and_sellable
    
    def get_prices_of(self, price_category=PRICES_COMMODITIES, **additional_category_filters):
        """
        Get prices of something for given filters

        :param price_category PRICES_COMMODITIES, PRICES_ITEMS or PRICES_VEHICLES
        :param additional_category_filters must contain at least one parameter:
            - the id of the terminal - id_terminal=id
            - the id of the commodity - id_commodity=id


        :return: A dictionary of filtered prices of the category type.
        """
        if self._needs_refresh(price_category, **additional_category_filters):
            data, age = self._fetch_from_file_or_api(
                price_category,
                **additional_category_filters)

        # print_debug(f"price query result: {json.dumps(data, indent=2)[0:100]}...")
        return data if data else None
          
    def _find_best_trade_between_locations(self, location_id1, location_category1, location_id2, location_category2, include_restricted_illegal=False ):
        """
        Find the best trading option between two systems.
        """
        # Extracting trade data for the specified systems
        terminal_data = [trade for trade in self.data[CATEGORY_TERMINALS].get("data").values() if trade["type"] == "commodity"]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")

        # depending on the location type, we need to match the tradeports available at that location
        id_field_name = ''
        if location_category1 == CATEGORY_ORBITS:
            id_field_name = 'id_orbit'
        elif location_category1 == CATEGORY_MOONS:
            id_field_name = 'id_moon'
        elif location_category1 == CATEGORY_CITIES:
            id_field_name = 'id_city'
        elif location_category1 == CATEGORY_OUTPOSTS:
            id_field_name = 'id_outpost'

        terminals_start = [trade for trade in terminal_data if trade[id_field_name] == location_id1]

        id_field_name = ''
        if location_category2 == CATEGORY_ORBITS:
            id_field_name = 'id_orbit'
        elif location_category2 == CATEGORY_MOONS:
            id_field_name = 'id_moon'
        elif location_category2 == CATEGORY_CITIES:
            id_field_name = 'id_city'
        elif location_category2 == CATEGORY_OUTPOSTS:
            id_field_name = 'id_outpost'

        # terminals_end = [trade for trade in terminal_data if trade[id_field_name] == location_id2]
        target_terminal_ids = {trade['id'] for trade in terminal_data if trade[id_field_name] == location_id2}

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)

        commodity_prices = {}
        for commodity_id in allowedCommodities.keys():
            prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
            if prices is None:
                print_debug(f"Skipping commodity with id {commodity_id} as no prices found. ")
                continue
            commodity_prices[commodity_id] = list(prices.values())

        # Using a heap to store the top 3 trades
        top_trades = []
        heapq.heapify(top_trades)

        commodities_in_top_trades = {}
        trade_id = 0

        # first, go through all possible terminals at the start location
        # and get all possible commodities that can be bought
        for buy_terminal in terminals_start:
            buy_terminal_id = buy_terminal[ID_FIELD_NAME]

            buyable_commodities = [
                commodity_price for commodity_list in commodity_prices.values()
                for commodity_price in commodity_list
                if commodity_price["id_terminal"] == buy_terminal_id and commodity_price["price_buy"] > 0
            ]

            # next, for each of the buyable commodities, get available selling tradeports
            for terminal_buyable_commodity in buyable_commodities:
                commodity_id = terminal_buyable_commodity["id_commodity"]
                print_debug(f"price_buy for {terminal_buyable_commodity['commodity_name']}: {terminal_buyable_commodity['price_buy']}")
                
                buy_price = terminal_buyable_commodity["price_buy"]

                # among the target selling terminals, find those that sell the given commodity
                sellable_terminal_prices = [
                    commodity_price for commodity_list in commodity_prices.values()
                    for commodity_price in commodity_list
                    if commodity_price["id_commodity"] == commodity_id
                    and commodity_price["price_sell"] > 0
                    and commodity_price["id_terminal"] in target_terminal_ids
                ]

                # finally, go through these locations, and find the best selling options for the given commodity
                for terminal_selling_commodity in sellable_terminal_prices:
                    sell_price = terminal_selling_commodity['price_sell']
                
                    profit = round(sell_price - buy_price, ndigits=2)
                    if profit <= 0:
                        continue
                    commodity_in_heap = commodities_in_top_trades.get(commodity_id)

                    if commodity_in_heap:
                        # Compare profit with existing entry in heap
                        if profit > commodity_in_heap['profit']:
                            # Remove old trade and update the dictionary
                            top_trades.remove((commodity_in_heap['negative_profit'], commodity_in_heap['trade_id'], commodity_in_heap['trade_info']))
                            heapq.heapify(top_trades)  # Re-heapify after removing an item
                            # Add new trade
                            trade_info = self._create_trade_info(terminal_buyable_commodity, terminal_selling_commodity, commodity_id, buy_price, sell_price, profit)
                            heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                            # Update commodities_in_top_trades
                            commodities_in_top_trades[commodity_id] = {'profit': profit, 'negative_profit': -profit, 'trade_id': trade_id, 'trade_info': trade_info}
                            trade_id += 1
                    else:

                        # -profit as heapq sorts with lowest value first
                        if len(top_trades) < 3 or -profit < top_trades[0][0]:
                            if len(top_trades) == 3:
                                removed_trade = heapq.heappop(top_trades)  # remove the trade route with the lowest profit
                                removed_commodity_code = self.name_mapping.get(CATEGORY_COMMODITIES, {}).get(removed_trade[2]['commodity'], '')  # and remove also the commodity from our commodity map
                                del commodities_in_top_trades[removed_commodity_code]
                            trade_info = self._create_trade_info(terminal_buyable_commodity, terminal_selling_commodity, commodity_id, buy_price, sell_price, profit) 
                            heapq.heappush(top_trades, (-profit, trade_id, trade_info))  # Insert new trade with negative profit (heap smallest value first). Include trade_id for a fallback sorting option
                            commodities_in_top_trades[commodity_id] = {'profit': profit, 'negative_profit': -profit, 'trade_id': trade_id, 'trade_info': trade_info}
                            trade_id += 1
        
        print_debug(top_trades)
        # Convert heap to a sorted list
        top_trades = sorted([trade for _, _, trade in top_trades], key=lambda x: x["profit"], reverse=True)

        if not top_trades:
            return {"success": False, "message": f"No trade route found between {location_id1} and {location_id2}."}
        
        return {
            "success": True, 
            "additional_instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": top_trades,
            "number_of_alternatives": len(top_trades)
        }

    def _create_trade_info(self, buy_terminal, sell_terminal, commodity_code, buy_price, sell_price, profit):
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "buy_at_tradeport_name": buy_terminal.get("terminal_name", ''),
            "buy_moon": buy_terminal.get("moon_name", ''),
            "buy_orbit": buy_terminal.get("orbit_name", ''),
            "buy_system": buy_terminal.get("star_system_name", ''),
            "sell_at_tradeport_name": sell_terminal.get("terminal_name", ''),
            "sell_moon": sell_terminal.get("moon_name", ''),
            "sell_orbit": sell_terminal.get("orbit_name", ''),
            "sell_system": sell_terminal.get("star_system_name", ''),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "profit": profit
        }
    
    def _find_best_trade_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best trade route for a specific commodity.
        """
        terminal_data = [trade for trade in self.data[CATEGORY_TERMINALS].get("data").values() if trade["type"] == "commodity"]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")

        no_route = {"success": False, "message": f"No trade route found for commodity {commodity_id}."}

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_id not in allowedCommodities:
            return no_route
        
        # get all prices for the commodity
        prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if prices is None:
            return no_route
        
        prices = {item['id_terminal']: item for item in prices.values()}

        top_trades = []
        trade_id = 0

        for trade1 in terminal_data:  # buy tradeport
 
            buy_terminal = prices.get(trade1['id'], None)
            if buy_terminal is None:
                continue

            buy_price = buy_terminal["price_buy"]
            if buy_price <= 0:
                continue

            for trade2 in terminal_data:  # sell tradeport
                
                sell_terminal = prices.get(trade2['id'], None)
                if sell_terminal is None:
                    continue
        
                sell_price = sell_terminal['price_sell']
                if sell_price <= 0:
                    continue

                profit = sell_price - buy_price
                if profit <= 0:
                    continue

                trade_info = self._create_trade_info(buy_terminal, sell_terminal, commodity_id, buy_price, sell_price, round(profit, ndigits=2))
                heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                trade_id += 1
                
        if not top_trades:
            return no_route
        
        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, trade_info = heapq.heappop(top_trades)
            best_trade_routes.append(trade_info)

        return {
            "success": True,
            "additional_instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }
    
    def _find_best_selling_location_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best selling option for a commodity.
        """
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")

        no_route = {"success": False, "message": f"No selling location found for commodity {commodity_id}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_id not in allowedCommodities.keys():
            return no_route

        # get all prices for the commodity
        prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if prices is None:
            return no_route
        
        top_trades = []
        trade_id = 0
  
        for terminal_prices in prices.values():
            sell_price = terminal_prices['price_sell']
            
            if sell_price > 0 and (sell_price > max_sell_price or len(top_trades) < 3):
                trade_info = self._build_trade_selling_info(commodity_id, terminal_prices, round(sell_price, ndigits=2))
                # - profit as lowest value is always at top_trades[0]
                heapq.heappush(top_trades, (-sell_price, trade_id, trade_info))
                trade_id += 1
                max_sell_price = sell_price

        if not top_trades:
            return no_route
            
        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, trade_info = heapq.heappop(top_trades)
            best_trade_routes.append(trade_info)

        return {
            "success": True,
            "additional_instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'!", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def _find_best_sell_price_at_location(self, commodity_id, location_id, location_category):
        """
        Find the best trade route for a specific commodity around a specific location.
        """
        terminal_data = [trade for trade in self.data[CATEGORY_TERMINALS].get("data").values() if trade["type"] == "commodity"]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")
        
        # depending on the location type, we need to match the tradeports available at that location
        id_field_name = ''
        if location_category == CATEGORY_ORBITS:
            id_field_name = 'id_orbit'
        elif location_category == CATEGORY_MOONS:
            id_field_name = 'id_moon'
        elif location_category == CATEGORY_CITIES:
            id_field_name = 'id_city'
        elif location_category == CATEGORY_OUTPOSTS:
            id_field_name = 'id_outpost'

        tradeports = [trade for trade in terminal_data if trade[id_field_name] == location_id]
   
        no_route = {"success": False, "message": f"No available tradeport found for commodity {commodity_id} at location {location_id}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal=True, isOnlySellable=True)
        
        if commodity_id not in allowedCommodities.keys():
            return no_route

        # get all prices for the commodity
        prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if prices is None:
            return no_route
        
        prices = {item['id_terminal']: item for item in prices.values()}

        top_trades = []
        trade_id = 0

        for trade in tradeports:
                    
            # at the tradeport, there can only be one sell price for the given commodity
            tradeport_price = prices.get(trade['id'], None)
            if tradeport_price is None:
                continue

            sell_price = tradeport_price['price_sell']
            if sell_price > max_sell_price or len(top_trades) < 3:
                trade_info = self._build_trade_selling_info(commodity_id, tradeport_price, round(sell_price, ndigits=2))
                # - profit as lowest value is always at top_trades[0]
                heapq.heappush(top_trades, (-sell_price, trade_id, trade_info))
                trade_id += 1
                max_sell_price = sell_price

        if not top_trades:
            return no_route
        
        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, trade_info = heapq.heappop(top_trades)
            best_trade_routes.append(trade_info)

        return {
            "success": True,
            "additional_instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def _build_trade_selling_info(self, commodity_code, best_sell, max_sell_price):
        return {
                "commodity": best_sell.get("commodity_name", ''),
                "sell_at_tradeport_name": best_sell.get("terminal_name", ''),
                "sell_moon": best_sell.get("moon_name", ''),
                "sell_orbit": best_sell.get("orbit_name", ''),
                "sell_system": best_sell.get("star_system_name", ''),
                "sell_price": max_sell_price
            }

    def _find_best_trade_from_location(self, location_id, location_category, include_restricted_illegal=False):
        """
        Find the best trading option starting from a given location.

        location_id is the id of any location / or area the player wants to start a trade (specific outpost, or any outpost of a specific moon)

        first identifies all possible terminals within the search area for the start.
        next identifies all tradeble commodities (can be bought and sold)

        reduce to buyable commodities, that are available at any of the potential starting locations.

        for every starting location, find for any of the available buyable commodities at that location where
        it could be sold. Save all possible trade routes in order of profit.
        """
        # Extracting trade data for the specified systems
        terminal_data = [trade for trade in self.data[CATEGORY_TERMINALS].get("data").values() if trade["type"] == "commodity"]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")
        
        # depending on the location type, we need to match the tradeports available at that location
        id_field_name = ''
        if location_category == CATEGORY_ORBITS:
            id_field_name = 'id_orbit'
        elif location_category == CATEGORY_MOONS:
            id_field_name = 'id_moon'
        elif location_category == CATEGORY_CITIES:
            id_field_name = 'id_city'
        elif location_category == CATEGORY_OUTPOSTS:
            id_field_name = 'id_outpost'

        start_location_terminals = [trade for trade in terminal_data if trade[id_field_name] == location_id]
        
        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
        
        # first, get current prices of all available commodities for trade
        commodity_prices = {}
        buyable_commodity_prices = {}
        sellable_commodity_prices = {}
        for commodity_id in allowedCommodities.keys():
            prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
            if prices is None:
                print_debug(f"Skipping commodity with id {commodity_id} as no prices found. ")
                continue
            commodity_prices[commodity_id] = list(prices.values())
        
        # commodity prices:
        # "1" {[
        # {
            #     "id": 4,
            #     "id_commodity": 1,
            #     "id_star_system": 68,
            #     "id_planet": 4,
            #     "id_orbit": 4,
            #     "id_moon": 0,
            #     "id_city": 1,
            #     "id_outpost": 0,
            #     "id_poi": 0,
            #     "id_terminal": 12,
            #     "price_buy": 0,
            #     "price_sell": 2539,
            #     "scu_sell_stock": 3,
            #     "status_buy": 0,
            #     "status_sell": 1,
            #     "commodity_name": "Agricium",
            #     "commodity_code": "AGRI",
            #     "commodity_slug": "agricium",
            #     "star_system_name": "Stanton",
            #     "planet_name": "ArcCorp",
            #     "orbit_name": "ArcCorp",
            #     "moon_name": null,
            #     "space_station_name": null,
            #     "city_name": "Area 18",
            #     "outpost_name": null,
            #     "terminal_name": "TDD - Trade and Development Division - Area 18",
            #     "terminal_slug": "tdd-trade-and-development-division-area-18",
            #     "terminal_code": "TDD-A18"
            # },
        max_profit = 0

        top_trades = []
        trade_id = 0

        # Durchlaufe alle Waren, die am Startort gekauft werden können
        for buy_terminal in start_location_terminals:
            buy_terminal_id = buy_terminal[ID_FIELD_NAME]
            buy_terminal_name = buy_terminal['name']

            buyable_commodities = [
                commodity_price for commodity_list in commodity_prices.values()
                for commodity_price in commodity_list
                if commodity_price["id_terminal"] == buy_terminal_id and commodity_price["price_buy"] > 0
            ]

            for terminal_buyable_commodity in buyable_commodities:
                commodity_id = terminal_buyable_commodity["id_commodity"]
                print_debug(f"price_buy for {terminal_buyable_commodity['commodity_name']}: {terminal_buyable_commodity['price_buy']}")
                
                buy_price = terminal_buyable_commodity["price_buy"]

                # Finde den besten Verkaufspreis für die Ware an anderen Orten
                best_sell_price = 0
                best_sell_location_name = None

                sellable_terminal_prices = [
                    commodity_price for commodity_list in commodity_prices.values()
                    for commodity_price in commodity_list
                    if commodity_price["id_commodity"] == commodity_id and commodity_price["price_sell"] > 0
                ]

                for sell_terminal in sellable_terminal_prices:
                    sell_terminal_name = sell_terminal["terminal_name"]
                    
                    sell_price = sell_terminal['price_sell']
                    #  print_debug(f"price_sell for {commodity_id}: {commodity2['price_sell']}")
                    if sell_price > best_sell_price:
                        best_sell_price = sell_price
                        best_sell_terminal = sell_terminal

                # Berechne den Profit und prüfe, ob es eine bessere Option ist
                profit = best_sell_price - buy_price
                if profit > 0 and profit > max_profit:
                    trade_info = self._create_trade_info(terminal_buyable_commodity, best_sell_terminal, commodity_id, buy_price, best_sell_price, round(profit, ndigits=2))
                    # - profit as lowest value is always at top_trades[0]
                    heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                    max_profit = profit
                    trade_id += 1
                        
        if not top_trades:
            return {"success": False, "message": f"No trade route found starting at {location_id}."}
        
        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, trade_info = heapq.heappop(top_trades)
            best_trade_routes.append(trade_info)

        return {
            "success": True,
            "additional_instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def find_best_trade_between_locations_code(self, location_name_from, location_name_to):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Handelsoption für die Reise {location_name_from} -> {location_name_to}", tags="info")
        category_from, location_from = self.get_location(location_name_from)
        category_to, location_to = self.get_location(location_name_to)
        
        if not location_from: 
            return {
                "success": False, 
                "message": f"Start location not recognised: {location_name_from}"
            }
        
        if not location_to:
            return {
                "success": False, 
                "message": f"Target location not recognised: {location_name_to}"
            }   

        return self._find_best_trade_between_locations(location_from[ID_FIELD_NAME], category_from, location_to[ID_FIELD_NAME], category_to)

    def find_best_trade_from_location_code(self, location_name_from):
        if __name__ != "__main__":
            printr.print(text=f"Search best trade option from {location_name_from}", tags="info")
        category, location_from = self.get_location(location_name_from)
        
        if not location_from: 
            return {
                "success": False, 
                "message": f"Start location not recognised: {location_name_from}"
            }
        
        return self._find_best_trade_from_location(location_from[ID_FIELD_NAME], category)

    def find_best_trade_for_commodity_code(self, commodity_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Route für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "additional_instructions": "Ask the player for the commodity that he wants to trade."
            }
        
        return self._find_best_trade_for_commodity(commodity[ID_FIELD_NAME])
    
    def find_best_selling_location_for_commodity_code(self, commodity_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Verkaufsort für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "additional_instructions": "Ask the player the commodity that he wants to sell."
            }
    
        return self._find_best_selling_location_for_commodity(commodity[ID_FIELD_NAME])
    
    def find_best_sell_price_at_location_codes(self, commodity_name, location_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Verkaufsoption für {commodity_name} bei {location_name}", tags="info")
        
        category, location_to = self.get_location(location_name)

        commodity = self.get_commodity(commodity_name)
        
        if not location_to:
            print(f"find_tradeport_at_location_to_sell_commodity - location {location_name} not found.")
            return {
                "success": False, 
                "additional_instructions": f"The location {location_name} could not be found. User should try again speaking clearly. "
            }
        
        if not commodity:
            print(f"find_tradeport_at_location_to_sell_commodity - commodity {commodity_name} not found.")
            return {
                "success": False, 
                "additional_instructions": f"The commodity {commodity_name} could not be identified. Ask the user to repeat the name clearly. "
            }
    
        return self._find_best_sell_price_at_location(commodity_id=commodity[ID_FIELD_NAME], location_id=location_to[ID_FIELD_NAME], location_category=category)
      
    def get_commodity_name(self, commodity_id):
        self._refresh_data()
        if commodity_id in self.code_mapping.get(CATEGORY_COMMODITIES):
            return self.code_mapping.get(CATEGORY_COMMODITIES).get(commodity_id)
        
        return commodity_id
    
    def get_satellite_name(self, moon_id):
        self._refresh_data()
    
        if moon_id in self.code_mapping.get(CATEGORY_MOONS):
            return self.code_mapping.get(CATEGORY_MOONS).get(moon_id)
        
        return moon_id
    
    def get_planet_name(self, planet_id):
        self._refresh_data()
    
        if planet_id in self.code_mapping.get(CATEGORY_ORBITS):
            return self.code_mapping.get(CATEGORY_ORBITS).get(planet_id)
        
        return planet_id
    
    def get_city_name(self, city_id):
        self._refresh_data()
    
        if city_id in self.code_mapping.get(CATEGORY_CITIES):
            return self.code_mapping.get(CATEGORY_CITIES).get(city_id)
        
        return city_id
    
    def get_tradeport_name(self, terminal_id):
        self._refresh_data()
    
        if terminal_id in self.code_mapping.get(CATEGORY_TERMINALS):
            return self.code_mapping.get(CATEGORY_TERMINALS).get(terminal_id)
        
        return terminal_id

    def get_tradeports(self):
        self._refresh_data()
        category = CATEGORY_TERMINALS
        return self.data[category].get("data", [])
    
    def get_refineries(self):
        self._refresh_data()
        category = CATEGORY_TERMINALS
        data, age = self._fetch_from_file_or_api(category, type="refinery")
        return data 
    
    def get_terminal(self, tradeport_mapping_name, type="commodity", search_fields=["name"], cutoff=80):
        
        self._refresh_data()
        filtered_data = [item for item in self.data[CATEGORY_TERMINALS].get('data', {}).values() if str(item.get("type", "")) == type]
        terminal_mapping, success = find_best_match.find_best_match(tradeport_mapping_name, filtered_data, attributes=search_fields, score_cutoff=cutoff)
        if not success:
            return None
        
        return terminal_mapping["root_object"]
    
    def get_location(self, location_mapping_name):
        self._refresh_data()
        location_categories = [CATEGORY_ORBITS, CATEGORY_MOONS, CATEGORY_CITIES, CATEGORY_OUTPOSTS]
        
        for category in location_categories:
            # print_debug(f"location names for {category}: {json.dumps(self.name_mapping[category], indent=2)[0:150]}")
            location_mapping, success = find_best_match.find_best_match(location_mapping_name, self.data[category].get('data', {}), attributes=["name"])
            if not success:
                continue

            location = location_mapping["root_object"]
            print_debug(f"found location '{location_mapping_name}' in category '{category}':\n {json.dumps(location_mapping, indent=2)}")
            return category, location
        
        return None, None
    
    def get_commodity(self, commodity_mapping_name):
        self._refresh_data()
        commodity_mapping, success = find_best_match.find_best_match(commodity_mapping_name, self.data[CATEGORY_COMMODITIES].get('data', {}), attributes=["name"])
        if not success:
            return None
        
        commodity = commodity_mapping["root_object"]
        print_debug(f"found commodity '{commodity_mapping_name}':\n {json.dumps(commodity, indent=2)}")
        return commodity

    def get_commodity_for_tradeport(self, commodity_mapping_name, tradeport):
        self._refresh_data()
        commodity_id = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        # print_debug(f'uex: {commodity_mapping_name}-> {code} @ {tradeport["name_short"]}')
        if not commodity_id:
            return None
        
        commodity_prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id, id_tradeport=tradeport[ID_FIELD_NAME])

        return commodity_prices[commodity_id] if commodity_prices else None
        
    def get_data(self, category):
        self._refresh_data()
        return self.data[category].get("data", [])
        
    def get_category_names(self, category: str, field_name: str = "name", filter: tuple[str, str] = None) -> list[str]:
        """
        Fetch names from a given category filtered by the provided attribute-value tuple.
        
        :param category: The category to fetch from, e.g., "terminals" or "planets".
        :param field_name: The field name to fetch, e.g., "name" or "nickname".
        :param filter: A tuple containing the filter attribute and filter value, e.g., ("is_available", "1").
        :return: A list of names (or other properties) from the filtered items.
        """
        self._refresh_data()
        
        if filter is None:
            return list(self.name_mapping[category].keys())
        
        category_data = self.data[category].get("data")

        filter_attribute, filter_value = filter
        # Filter the data based on the provided attribute and value
        filtered_data = [item for item in category_data.values() if str(item.get(filter_attribute, "")) == filter_value]

        # Assuming 'name' is a key in the dictionary that holds the name of the entity
        names = [item[field_name] for item in filtered_data]
        return names
        
    def update_tradeport_prices(self, tradeport, commodity_update_infos, operation):
        self._refresh_data()
        url = f"{self.base_url}data_submit/"
        
        if not ("code" in tradeport):
            return "missing code, rejected", False
        
        terminal_id = self.name_mapping[CATEGORY_TERMINALS][tradeport["name"]] if tradeport["name"] in self.name_mapping[CATEGORY_TERMINALS] else None        
        prices = []
        for commodity_info in commodity_update_infos:
            # {
            #     "commodity_name": "Medical Supplies",
            #     "available_SCU_quantity": 0,
            #     "inventory_state": "OUT OF STOCK",
            #     "price_per_unit": 1.92499995,
            #     "multiplier": "K",
            #     "currency": "\u00a2",
            #     "code": "MEDS",
            #     "uex_price": 1924.99995,
            #     "validation_result": "all plausible",
            #     "transmit": true
            # }
            if commodity_info["transmit"] is False:
                continue

            if commodity_info["commodity_name"] not in self.name_mapping[CATEGORY_COMMODITIES]:
                print_debug(f'unknown commodity id for {commodity_info["commodity_name"]}. Skipping update.')
                continue
            
            if "uex_price" not in commodity_info:
                print_debug(f'no valid price for {commodity_info["commodity_name"]}. Skipping update.')
                continue
            
            prices.append(
                {
                    "id_commodity": self.name_mapping[CATEGORY_COMMODITIES][commodity_info["commodity_name"]],
                    f"price_{operation}": commodity_info["uex_price"],
                    f"scu_{operation}": commodity_info["available_SCU_quantity"],
                    f"status_{operation}": self.inventory_state_mapping[commodity_info["inventory_state"]]
                }
            )
  
        update_data = {
            "id_terminal": terminal_id,
            "type": "commodity",
            "prices": prices
        }
        
        if not CALL_UEX_SR_ENDPOINT:
            possible_strings = ["2423", "1234", "5678", "53249", "5294"]
            possible_bools = [True, True, True, False]
            return random.choice(possible_strings), random.choice(possible_bools)

        if not TEST:
            update_data["is_production"] = "1"

        response = self.session.post(url, data=json.dumps(update_data), timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX2 prices where accepted: {json.dumps(response.json(), indent=2)}")    
            return response.json(), True  # report id received
        
        print_debug(f"Fehler beim Abrufen von Daten von {url} mit params {json.dumps(update_data, indent=2)}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason

    def add_refinery_job(self, work_order):
        url = f"{self.base_url}user_refineries_jobs_add/"

        if not CALL_UEX_SR_ENDPOINT:
            possible_strings = ["2423", "1234", "5678", "53249", "5294"]
            possible_bools = [True, True, True, False]
            return random.choice(possible_strings), random.choice(possible_bools)

        if not TEST:
            work_order["is_production"] = "1"

        response = self.session.post(url, data=json.dumps(work_order), timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery job added: {json.dumps(response.json(), indent=2)}")    
            return response.json(), True  # report id received
        
        print_debug(f"Error retrieving data from {url} mit params {json.dumps(work_order, indent=2)}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason
    
    def get_refinery_jobs(self):
        url = f"{self.base_url}user_refineries_jobs/"

        response = self.session.get(url, timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery jobs retrieved: {json.dumps(response.json(), indent=2)}")    
            return response.json()["data"], True  # report id received
        
        print_debug(f"Error retrieving data from {url}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason
    
    def delete_refinery_job(self, job_id):
        print_debug(f"UEX refinery job deleting: '{job_id}'")   
        url = f"{self.base_url}user_refineries_jobs_remove/id/{job_id}/is_production/1/"

        response = self.session.delete(url, timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery jobs deleted: {json.dumps(response.json(), indent=2)}")    
            return response.json()["data"], True  # report id received
        
        print_debug(f"Error deleting job from {url}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason
    

if __name__ == "__main__":
    api = UEXApi2.init(uex_api_key="****", 
                       user_secret_key="****")
    
    import sys
    # Fügen Sie den absoluten Pfad zum Verzeichnis hinzu, in dem sich das Paket befindet
    sys.path.append(os.path.abspath(r'D:\Dokumente\dev\python-projects\wigman-ai\wingman-ai'))
    from wingmen.star_citizen_services.helper import find_best_match

    # print("========= TEST start Hurston ========")
    # result = api.find_best_trade_from_location_code(location_name_from="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST start HDMS-Lathan ========")
    # result = api.find_best_trade_from_location_code(location_name_from="HDMS-Lathan")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST start Arccorp ========")
    # result = api.find_best_trade_from_location_code(location_name_from="ArcCorp")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Arccorp -> Hurston ========")
    # result = api.find_best_trade_between_locations_code(location_name_from="ArcCorp", location_name_to="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Hurston -> Arccorp ========")
    # result = api.find_best_trade_between_locations_code(location_name_from="hurton", location_name_to="Arccorp")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Medical Supplies -> Hurston ========")
    # result = api.find_best_sell_price_at_location_codes(commodity_name="Medical Supplies", location_name="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST where sell Laranite? ========")
    # result = api.find_best_selling_location_for_commodity_code(commodity_name="Laranite")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST best trade for Medical Supplies? ========")
    # result = api.find_best_trade_for_commodity_code(commodity_name="Medical Supplies")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))