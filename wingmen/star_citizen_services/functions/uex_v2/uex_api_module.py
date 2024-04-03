import json
import os
import time
import requests
import random
import heapq

from services.printr import Printr


DEBUG = True
TEST = False
CALL_UEX_SR_ENDPOINT = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)

        
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

# System IDs
STANTON = 68


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
            
            self.base_url = "https://ptu.uexcorp.space/api/"
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

            # Beispiel-Systemcode
            self.system_code = STANTON  # Beispiel: Stanton=68

            self.code_mapping = {}
            self.name_mapping = {}
            self.uex1_tradeport_name_to_uex2_id_mapping = {  # TODO Temporary mapping until v2 live
                "Area 18 - Trade & Development Division": 12,
                "New Babbage - Trade & Development Division": 89,
                "Orison - Trade & Development Division": 90,
                "Central Business District": 18,
                "L19 Residences Admin Office": 51,
                "ARC-L1 Wide Forest Station": 1,
                "ARC-L2 Liveley Pathway Station": 2,
                "ARC-L3 Modern Express Station": 3,
                "ARC-L4 Faint Glen Station": 4,
                "ARC-L5 Yellow Core Station": 5,
                "MIC-L1 Shallow Frontier Station": 54,
                "MIC-L2 Long Forest Station": 55,
                "MIC-L3 Endless Odyssey Station": 56,
                "MIC-L4 Red Crossroads Station": 57,
                "MIC-L5 Modern Icarus Station": 58,
                "HUR-L1 Green Glade Station": 44,
                "HUR-L2 Faithful Dream Station": 45,
                "HUR-L3 Thundering Express Station": 46,
                "HUR-L4 Melodic Fields Station": 47,
                "HUR-L5 High Course Station": 48,
                "CRU-L1 Ambitious Dream Station": 19,
                "CRU-L4 Shallow Fields Station": 20,
                "CRU-L5 Beautiful Glen Station": 22
            }
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

    def get_api_endpoints_per_category(self, system_id=STANTON, category=None):
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
        
    def _fetch_from_file_or_api(self, category, max_age_seconds, api_call, **additional_category_filters):
        file_path = f"{self.root_data_path}/{category}"
        for attribut, value in additional_category_filters.items():
            file_path += f"_{attribut}-{value}"
        
        file_path += ".json"

        file_data = None
        file_age = max_age_seconds
        # Check if the file exists and is not too old
        if os.path.exists(file_path):
            file_age = time.time() - os.path.getmtime(file_path)

            with open(file_path, 'r', encoding="utf-8") as file:
                file_data = json.load(file)
                
        if file_age < max_age_seconds:
            # print_debug(f"Loading from file {name}")
            return file_data, file_age
        
        data = self._fetch_data_api(api_call, **additional_category_filters)
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
            uex_location_code_map = {loc.get(ID_FIELD_NAME): loc for loc in data["data"]}

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
        categories = [CATEGORY_CITIES, CATEGORY_COMMODITIES, CATEGORY_ITEMS, CATEGORY_MOONS, CATEGORY_ORBITS, CATEGORY_OUTPOSTS, CATEGORY_TERMINALS, CATEGORY_VEHICLES, CATEGORY_REFINERY_METHODS]
        
        for check_category in categories:
            if self._needs_refresh(check_category):
                data, age = self._fetch_from_file_or_api(check_category, self.max_ages[check_category], self.get_api_endpoints_per_category(self.system_code, check_category))
                
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
        return self.data[category_key].get("age") > self.max_ages[category]

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
 
    def _fetch_data_api(self, endpoint, **additional_category_filters):
        url = f"{self.base_url}/{endpoint}"
        response = self.session.get(url, params=additional_category_filters, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print_debug(f"Fehler beim Abrufen von Daten von {url} mit params {json.dumps(additional_category_filters)}: {response.status_code}")
            return None

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
            buyable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_buyable'] == "1"}
            sellable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_sellable'] == "1"}
        else:
            buyable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_buyable'] == "1" and commodity['is_illegal'] != "1"}
            sellable = {commodity[ID_FIELD_NAME]: commodity for commodity in commodities_data.values() if commodity['is_sellable'] == "1" and commodity['is_illegal'] != "1"}

        if isOnlySellable:
            return sellable

        # Intersection of buyable and sellable commodities
        buyable_and_sellable = {code: buyable[code] for code in buyable if code in sellable}
        return buyable_and_sellable
    
    def _get_prices_of(self, price_category=PRICES_COMMODITIES, **additional_category_filters):
        """
        Get prices of something for given filters

        :param price_category PRICES_COMMODITIES, PRICES_ITEMS or PRICES_VEHICLES
        :param additional_category_filters must contain at least one parameter, usually {id_terminal: id}


        :return: A dictionary of filtered prices of the category type.
        """
        if self._needs_refresh(price_category, **additional_category_filters):
            data, age = self._fetch_from_file_or_api(price_category, self.max_ages[price_category], self.get_api_endpoints_per_category(self.system_code, price_category), **additional_category_filters)

        return data["data"] if data else None
          
    def _find_best_trade_between_locations(self, location_id1, location_id2, include_restricted_illegal=False ):
        """
        Find the best trading option between two systems.
        """
        # Extracting trade data for the specified systems
        terminal_data = self.data[CATEGORY_TERMINALS].get("data")
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")
        trades_system1 = [trade for trade in terminal_data.values() if trade['id_star_system'] == location_id1 or trade['id_orbit'] == location_id1 or trade['id_moon'] == location_id1 or trade['id_city'] == location_id1 or trade[ID_FIELD_NAME] == location_id1]
        trades_system2 = [trade for trade in terminal_data.values() if trade['id_star_system'] == location_id2 or trade['id_orbit'] == location_id2 or trade['id_moon'] == location_id2 or trade['id_city'] == location_id2 or trade[ID_FIELD_NAME] == location_id2]

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)

        # Using a heap to store the top 3 trades
        top_trades = []
        heapq.heapify(top_trades)

        commodities_in_top_trades = {}
        trade_id = 0
        for trade1 in trades_system1:
            for trade2 in trades_system2:
                for commodity_id, commodity in self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade1[ID_FIELD_NAME]).items():
                    if commodity_id not in allowedCommodities:
                        continue  # we are only looking for tradable commodities (that can be bought and sold)
                
                    commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade2[ID_FIELD_NAME], id_commodity=commodity_id)
                    if commodity_prices:                                       
                        commodity2 = commodity_prices[commodity_id]

                        # Check if the commodity is buyable at trade1 and sellable at trade2
                        if commodity['price_buy'] > 0 and commodity2['price_sell'] > 0:
                            sell_price = commodity2['price_sell']
                            buy_price = commodity['price_buy']
                        
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
                                    trade_info = self._create_trade_info(trade1, trade2, commodity_id, buy_price, sell_price, profit)
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
                                    trade_info = self._create_trade_info(trade1, trade2, commodity_id, buy_price, sell_price, profit) 
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
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": top_trades,
            "number_of_alternatives": len(top_trades)
        }

    def _create_trade_info(self, buy_tradeport, sell_tradeport, commodity_code, buy_price, sell_price, profit):
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "buy_at_tradeport_name": buy_tradeport.get(NAME_FIELD_NAME, ''),
            "buy_moon": self.code_mapping.get(CATEGORY_MOONS, {}).get(buy_tradeport.get("id_moon", ''), ''),
            "buy_orbit": self.code_mapping.get(CATEGORY_ORBITS, {}).get(buy_tradeport.get("id_orbit", ''), ''),
            "sell_at_tradeport_name": sell_tradeport.get(NAME_FIELD_NAME, ''),
            "sell_moon": self.code_mapping.get(CATEGORY_MOONS, {}).get(sell_tradeport.get("id_moon", ''), ''),
            "sell_orbit": self.code_mapping.get(CATEGORY_ORBITS, {}).get(sell_tradeport.get("id_orbit", ''), ''),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "profit": profit
        }
    
    def _find_best_trade_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best trade route for a specific commodity.
        """
        tradeports_data = self.data[CATEGORY_TERMINALS].get("data")
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data"), 
        no_route = {"success": False, "message": f"No trade route found for commodity {commodity_id}."}

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_id not in allowedCommodities:
            return no_route
        
        top_trades = []
        trade_id = 0

        for trade1 in tradeports_data.values():  # buy tradeport
            commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade1[ID_FIELD_NAME], id_commodity=commodity_id)
            if not commodity_prices:
                continue
            
            details = commodity_prices[commodity_id]
            buy_price = details["price_buy"]
            if buy_price <= 0:
                continue

            for trade2 in tradeports_data.values():  # sell tradeport
                
                commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade2[ID_FIELD_NAME], id_commodity=commodity_id)
                if not commodity_prices:
                    continue
            
                details = commodity_prices[commodity_id]
                sell_price = details['price_sell']
                if sell_price <= 0:
                    continue

                profit = sell_price - buy_price
                if profit <= 0:
                    continue

                trade_info = self._create_trade_info(trade1, trade2, commodity_id, buy_price, sell_price, round(profit, ndigits=2))
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
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }
    
    def _find_best_selling_location_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best selling option for a commodity.
        """
        tradeports_data = self.data[CATEGORY_TERMINALS].get("data")
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")

        no_route = {"success": False, "message": f"No selling location found for commodity {commodity_id}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_id not in allowedCommodities:
            return no_route

        top_trades = []
        trade_id = 0

        for trade in tradeports_data.values():
            commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade[ID_FIELD_NAME], id_commodity=commodity_id)
            if not commodity_prices:
                continue
            
            details = commodity_prices[commodity_id]
            sell_price = details['price_sell']
            if sell_price > max_sell_price or len(top_trades) < 3:
                trade_info = self._build_trade_selling_info(commodity_id, trade, round(sell_price, ndigits=2))
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
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'!", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def _find_best_sell_price_at_location(self, commodity_id, location_id):
        """
        Find the best trade route for a specific commodity around a specific location.
        """
        terminal_data = self.data[CATEGORY_TERMINALS].get("data")
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data"), 
        tradeports = [trade for trade in terminal_data.values() if trade['id_star_system'] == location_id or trade['id_orbit'] == location_id or trade['id_moon'] == location_id or trade['id_city'] == location_id or trade[ID_FIELD_NAME] == location_id]
    
        no_route = {"success": False, "message": f"No available tradeport found for commodity {commodity_id} at location {location_id}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal=True, isOnlySellable=True)
        if commodity_id not in allowedCommodities:
            return no_route

        top_trades = []
        trade_id = 0

        for trade in tradeports:
            
            commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=trade[ID_FIELD_NAME], id_commodity=commodity_id)
            if not commodity_prices:
                continue
        
            details = commodity_prices[commodity_id]
            sell_price = details['price_sell']
            if sell_price > max_sell_price or len(top_trades) < 3:
                trade_info = self._build_trade_selling_info(commodity_id, trade, round(sell_price, ndigits=2))
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
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def _build_trade_selling_info(self, commodity_code, best_sell, max_sell_price):
        return {
                "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
                "sell_at_tradeport_name": best_sell.get(NAME_FIELD_NAME, ''),
                "sell_moon": self.code_mapping.get(CATEGORY_MOONS, {}).get(best_sell.get("id_moon", ''), ''),
                "sell_orbit": self.code_mapping.get(CATEGORY_ORBITS, {}).get(best_sell.get("id_orbit", ''), ''),
                "sell_price": max_sell_price
            }

    def _find_best_trade_from_location(self, location_id, include_restricted_illegal=False):
        """
        Find the best trading option starting from a given location.
        """
        # Extracting trade data for the specified systems
        terminal_data = self.data[CATEGORY_TERMINALS].get("data")
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data")
        # Extrahiere alle Handelsposten am Startort
        start_location_trades = [trade for trade in terminal_data.values() if trade['id_star_system'] == location_id or trade['id_orbit'] == location_id or trade['id_moon'] == location_id or trade['id_city'] == location_id or trade[ID_FIELD_NAME] == location_id]
        
        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
            
        max_profit = 0

        top_trades = []
        trade_id = 0

        # Durchlaufe alle Waren, die am Startort gekauft werden können
        for buy_terminal in start_location_trades:
            for commodity_id, commodity in self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=buy_terminal[ID_FIELD_NAME]).items():
                if commodity_id not in allowedCommodities:
                    continue
                
                if commodity["price_buy"] <= 0:
                    continue  # commodity cannot be bought at this terminal
                
                buy_price = commodity["price_buy"]

                # Finde den besten Verkaufspreis für die Ware an anderen Orten
                best_sell_price = 0
                best_sell_location = None
                for sell_terminal in terminal_data.values():
                    commodity_price = self._get_prices_of(price_category=PRICES_COMMODITIES, id_terminal=sell_terminal[ID_FIELD_NAME], id_commodity=commodity_id)
                    
                    if commodity_price:                                       
                        commodity2 = commodity_price[commodity_id]
                    
                        sell_price = commodity2['price_sell']
                        if sell_price > 0:
                            if sell_price > best_sell_price:
                                best_sell_price = sell_price
                                best_sell_location = sell_terminal

                # Berechne den Profit und prüfe, ob es eine bessere Option ist
                profit = best_sell_price - buy_price
                if profit > 0 and profit > max_profit:
                    trade_info = self._create_trade_info(buy_terminal, best_sell_location, commodity, buy_price, best_sell_price, round(profit, ndigits=2))
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
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": best_trade_routes,
            "number_of_alternatives": len(best_trade_routes)
        }

    def find_best_trade_between_locations_code(self, location_name_from, location_name_to):
        printr.print(text=f"Suche beste Handelsoption für die Reise {location_name_from} -> {location_name_to}", tags="info")
        _, location_from = self.get_location(location_name_from)
        _, location_to = self.get_location(location_name_to)
        
        if not location_from: 
            return {
                "success": False, 
                "instructions": f"Start location not recognised: {location_name_from}"
            }
        
        if not location_to:
            return {
                "success": False, 
                "instructions": f"Target location not recognised: {location_name_to}"
            }   

        return self._find_best_trade_between_locations(location_from[ID_FIELD_NAME], location_to[ID_FIELD_NAME])

    def find_best_trade_from_location_code(self, location_name_from):
        printr.print(text=f"Suche beste Handelsoption ab {location_name_from}", tags="info")
        _, location_from = self.get_location(location_name_from)
        
        if not location_from: 
            return {
                "success": False, 
                "instructions": f"Start location not recognised: {location_name_from}"
            }
        
        return self._find_best_trade_from_location(location_from[ID_FIELD_NAME])

    def find_best_trade_for_commodity_code(self, commodity_name):
        printr.print(text=f"Suche beste Route für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "instructions": "Ask the player for the commodity that he wants to trade."
            }
        
        return self._find_best_trade_for_commodity(commodity[ID_FIELD_NAME])
    
    def find_best_selling_location_for_commodity_code(self, commodity_name):
        printr.print(text=f"Suche beste Verkaufsort für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "instructions": "Ask the player the commodity that he wants to sell."
            }
    
        return self._find_best_selling_location_for_commodity(commodity[ID_FIELD_NAME])
    
    def find_best_sell_price_at_location_codes(self, commodity_name, location_name):
        printr.print(text=f"Suche beste Verkaufsoption für {commodity_name} bei {location_name}", tags="info")
        
        _, location_to = self.get_location(location_name)

        commodity = self.get_commodity(commodity_name)
        
        if not location_to:
            print(f"find_tradeport_at_location_to_sell_commodity - location {location_name} not found.")
            return {
                "success": False, 
                "instructions": f"The location {location_name} could not be found. User should try again speaking clearly. "
            }
        
        if not commodity:
            print(f"find_tradeport_at_location_to_sell_commodity - commodity {commodity_name} not found.")
            return {
                "success": False, 
                "instructions": f"The commodity {commodity_name} could not be identified. Ask the user to repeat the name clearly. "
            }
    
        return self._find_best_sell_price_at_location(commodity_id=commodity[ID_FIELD_NAME], location_id=location_to[ID_FIELD_NAME])
      
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
        category = CATEGORY_TERMINALS
        data, age = self._fetch_from_file_or_api(category, self.max_ages[category], self.get_api_endpoints_per_category(self.system_code, category), type="refinery")
        return data 
    
    def get_tradeport(self, tradeport_mapping_name):
        terminal_id = self.name_mapping[CATEGORY_TERMINALS].get(tradeport_mapping_name, None)
        if not terminal_id:
            return None
        
        return self.data[CATEGORY_TERMINALS].get("data", []).get(terminal_id, None)
    
    def get_location(self, location_mapping_name):

        location_categories = [CATEGORY_TERMINALS, CATEGORY_OUTPOSTS, CATEGORY_CITIES, CATEGORY_MOONS, CATEGORY_ORBITS]
        for category in location_categories:
            location_id = self.name_mapping[category].get(location_mapping_name, None)
            if location_id:
                return category, self.data[category].get("data", []).get(location_id, None)
        
        return None, None
    
    def get_commodity(self, commodity_mapping_name):
        commodity_id = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        if commodity_id:
            return self.data[CATEGORY_COMMODITIES].get("data", []).get(commodity_id, None)
        
        return None
    
    def get_commodity_for_tradeport(self, commodity_mapping_name, tradeport):
        commodity_id = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        # print_debug(f'uex: {commodity_mapping_name}-> {code} @ {tradeport["name_short"]}')
        if not commodity_id:
            return None
        
        commodity_prices = self._get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id, id_tradeport=tradeport[ID_FIELD_NAME])

        return commodity_prices[commodity_id] if commodity_prices else None
        
    def get_data(self, category):
        self._refresh_data()
        return self.data[category].get("data", [])
        
    def get_category_names(self, category: str) -> list[str]:
        self._refresh_data()
        
        return list(self.name_mapping[category].keys())
        
    def update_tradeport_prices(self, tradeport, commodity_update_infos, operation):
        self._refresh_data()
        url = f"{self.base_url}data_submit/"
        
        if not ("code" in tradeport):
            return "missing code, rejected", False
        
        terminal_id = self.name_mapping[CATEGORY_TERMINALS][tradeport["name"]] if tradeport["name"] in self.name_mapping[CATEGORY_TERMINALS] else None
        if not terminal_id:  # TODO temporary try to find best matching name for uex2 based on uex1
            terminal_id = self.uex1_tradeport_name_to_uex2_id_mapping[tradeport["name"]] if tradeport["name"] in self.uex1_tradeport_name_to_uex2_id_mapping else None

            if not terminal_id:
                print_debug(f"Unknown uex2 terminal id for tradeport['name']={tradeport['name']}")
                return "unknown terminal id", False
            # example uex1: Area 18 - Trade & Development Division, Area 18 TDD, ARCTD
            # uex2: TDD - Trade and Development Division - Area 18, TDD Area 18, TDD-A18
        
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
        
        print_debug(f"Fehler beim Abrufen von Daten von {url} mit params {json.dumps(work_order, indent=2)}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason