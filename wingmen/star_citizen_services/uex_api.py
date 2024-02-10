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

CATEGORY_SHIPS = "ships"
CATEGORY_CITIES = "cities"
CATEGORY_COMMODITIES = "commodities"
CATEGORY_TRADEPORTS = "tradeports"
CATEGORY_PLANETS = "planets"
CATEGORY_SATELLITES = "satellites"


class UEXApi():

    _uex_instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._uex_instance:
            cls._uex_instance = super(UEXApi, cls).__new__(cls)
        return cls._uex_instance

    def __init__(self):
        # Initialize your instance here, if not already initialized
        if not hasattr(self, 'is_initialized'):
            self.headers = {"api_key": f"{self.api_key}"}
            self.api_endpoint = "https://portal.uexcorp.space/api/"
            self.root_data_path = "star_citizen_data/uex"

            self.ship_max_age = 864000  # 10 days
            self.cities_max_age = 864000  # 10 days
            self.commodities_max_age = 864000  # 10 days
            self.tradeports_max_age = 900  # 15 min (contains prices)
            self.planets_max_age = 864000  # 10 days
            self.satellites_max_age = 864000  # 10 days

            self.max_ages = {
                CATEGORY_SHIPS: self.ship_max_age,
                CATEGORY_CITIES: self.cities_max_age,
                CATEGORY_COMMODITIES: self.commodities_max_age,
                CATEGORY_TRADEPORTS: self.tradeports_max_age,
                CATEGORY_PLANETS: self.planets_max_age,
                CATEGORY_SATELLITES: self.satellites_max_age
            }

            # Beispiel-Systemcode
            self.system_code = "ST"  # Beispiel: Stanton

            self.code_mapping = {}
            self.name_mapping = {}
            self.data = {}

            print_debug("Initializing UexApi instance")
            self.is_initialized = True
        else:
            print_debug("UexApi instance already initialized")
    
    @classmethod
    def init(cls, uex_api_key: str, uex_access_code: str):
        cls.api_key = uex_api_key
        cls.uex_access_code = uex_access_code
        # get secret mappings stuff

        return cls()

    def _fetch_from_file_or_api(self, name, max_age_seconds, api_call):
        file_path = f"{self.root_data_path}/{name}.json"
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
        
        data = self._fetch_data_api(api_call)
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
            uex_location_code_map = {loc.get("code"): loc for loc in data["data"]}

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
        :param file_path: Path of the file where data is stored
        :param max_age_in_seconds: Maximum age of the file data in seconds
        :param system_code: Code of the system for fetching data from the API
        :return: Data either from the file or the API
        """

        category = CATEGORY_SHIPS
        if self._needs_refresh(category):
            ship_data, ship_age = self._fetch_from_file_or_api(category, self.ship_max_age, "ships/")
            self._write_code_mapping_to_file(data=ship_data, category=category, api_value_field='name', export_value_field_name="name", export_code_field_name="code")
            self.data[category] = {"data": ship_data, "age": ship_age}

        category = CATEGORY_CITIES
        if self._needs_refresh(category):
            cities_data, cities_age = self._fetch_from_file_or_api(category, self.cities_max_age, f"cities/system/{self.system_code}/")
            self._write_code_mapping_to_file(data=cities_data, category=category, api_value_field='name', export_value_field_name='name', export_code_field_name='code')
            self.data[category] = {"data": cities_data, "age": cities_age}

        category = CATEGORY_COMMODITIES
        if self._needs_refresh(category):
            commodities_data, commoties_age = self._fetch_from_file_or_api(category, self.commodities_max_age, "commodities/")
            self._write_code_mapping_to_file(data=commodities_data, category=category, api_value_field='name', export_value_field_name='name', export_code_field_name='code')
            self.data[category] = {"data": commodities_data, "age": commoties_age}

        category = CATEGORY_TRADEPORTS
        if self._needs_refresh(category):
            tradeports_data, tradeports_age = self._fetch_from_file_or_api(category, self.tradeports_max_age, f"tradeports/system/{self.system_code}/")
            self._write_code_mapping_to_file(data=tradeports_data, category=category, api_value_field='name', export_value_field_name='name', export_code_field_name='code')
            self.data[category] = {"data": tradeports_data, "age": tradeports_age}

        category = CATEGORY_PLANETS
        if self._needs_refresh(category):
            planets_data, planets_age = self._fetch_from_file_or_api(category, self.planets_max_age, f"planets/system/{self.system_code}/")
            self._write_code_mapping_to_file(data=planets_data, category=category, api_value_field='name', export_value_field_name='name', export_code_field_name='code')
            self.data[category] = {"data": planets_data, "age": planets_age}
        
        category = CATEGORY_SATELLITES
        if self._needs_refresh(category):
            satellites_data, sattelites_age = self._fetch_from_file_or_api(category, self.satellites_max_age, f"satellites/system/{self.system_code}/")
            self._write_code_mapping_to_file(data=satellites_data, category=category, api_value_field='name', export_value_field_name='name', export_code_field_name='code')
            self.data[category] = {"data": satellites_data, "age": sattelites_age}

        # # Kombinieren aller Daten in einem Dictionary
        # data = {
        #     CATEGORY_SHIPS: {"data": ship_data, "age": ship_age},
        #     CATEGORY_CITIES: {"data": cities_data, "age": cities_age},
        #     CATEGORY_COMMODITIES: {"data": commodities_data, "age": commoties_age},
        #     CATEGORY_TRADEPORTS: {"data": tradeports_data, "age": tradeports_age},
        #     CATEGORY_PLANETS: {"data": planets_data, "age": planets_age},
        #     CATEGORY_SATELLITES: {"data": satellites_data, "age": sattelites_age}
        # }

    def _needs_refresh(self, category):
        if not category or not self.data or category not in self.data:
            return True
        return self.data[category].get("age") > self.max_ages[category]

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
        for category_entry_code, category_entry in data.items():
            entry_code = category_entry_code
            entry_name = category_entry.get(api_value_field, "")
            self.code_mapping[category][entry_code] = entry_name
            self.name_mapping[category][entry_name] = entry_code
            json_data[entry_name] = {export_code_field_name: entry_code, export_value_field_name: entry_name}

        # Schreiben des Dictionarys in eine Datei als JSON
        with open(f"{self.root_data_path}/{category}_mapping.json", 'w', encoding='utf-8') as file:
            json.dump(json_data, file, ensure_ascii=False, indent=4)
 
    def _fetch_data_api(self, endpoint, params=None):
        url = f"{self.api_endpoint}/{endpoint}"
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print_debug(f"Fehler beim Abrufen von Daten von {url}: {response.status_code}")
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
            buyable = {commodity['code']: commodity for commodity in commodities_data.values() if commodity['buyable'] == "1"}
            sellable = {commodity['code']: commodity for commodity in commodities_data.values() if commodity['sellable'] == "1"}
        else:
            buyable = {commodity['code']: commodity for commodity in commodities_data.values() if commodity['buyable'] == "1" and commodity['illegal'] != "1" and commodity['restricted'] != "1"}
            sellable = {commodity['code']: commodity for commodity in commodities_data.values() if commodity['sellable'] == "1" and commodity['illegal'] != "1" and commodity['restricted'] != "1"}

        if isOnlySellable:
            return sellable

        # Intersection of buyable and sellable commodities
        buyable_and_sellable = {code: buyable[code] for code in buyable if code in sellable}
        return buyable_and_sellable
          
    def _find_best_trade_between_locations(self, tradeports_data, commodities_data, location_code1, location_code2, include_restricted_illegal=False ):
        """
        Find the best trading option between two systems.
        """
        # Extracting trade data for the specified systems
        trades_system1 = [trade for trade in tradeports_data.values() if trade['system'] == location_code1 or trade['planet'] == location_code1 or trade['satellite'] == location_code1 or trade['city'] == location_code1 or trade['code'] == location_code1]
        trades_system2 = [trade for trade in tradeports_data.values() if trade['system'] == location_code2 or trade['planet'] == location_code2 or trade['satellite'] == location_code2 or trade['city'] == location_code2 or trade['code'] == location_code2]

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)

        # Using a heap to store the top 3 trades
        top_trades = []
        heapq.heapify(top_trades)

        commodities_in_top_trades = {}
        trade_id = 0
        for trade1 in trades_system1:
            for trade2 in trades_system2:
                for commodity_code, commodity in trade1.get('prices', {}).items():
                    if commodity_code not in allowedCommodities:
                        continue  # we are only looking for tradable commodities (that can be bought and sold)
                
                    if commodity_code in trade2.get('prices', {}):                                       
                        commodity2 = trade2['prices'][commodity_code]

                        # Check if the commodity is buyable at trade1 and sellable at trade2
                        if 'buy' in commodity['operation'] and 'sell' in commodity2['operation']:
                            sell_price = commodity2.get('price_sell', 0)
                            buy_price = commodity.get('price_buy', 0)
                        
                            profit = round(sell_price - buy_price, ndigits=2)
                            if profit <= 0:
                                continue
                            commodity_in_heap = commodities_in_top_trades.get(commodity_code)

                            if commodity_in_heap:
                                # Compare profit with existing entry in heap
                                if profit > commodity_in_heap['profit']:
                                    # Remove old trade and update the dictionary
                                    top_trades.remove((commodity_in_heap['negative_profit'], commodity_in_heap['trade_id'], commodity_in_heap['trade_info']))
                                    heapq.heapify(top_trades)  # Re-heapify after removing an item
                                    # Add new trade
                                    trade_info = self._create_trade_info(trade1, trade2, commodity_code, buy_price, sell_price, profit)
                                    heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                                    # Update commodities_in_top_trades
                                    commodities_in_top_trades[commodity_code] = {'profit': profit, 'negative_profit': -profit, 'trade_id': trade_id, 'trade_info': trade_info}
                                    trade_id += 1
                            else:

                                # -profit as heapq sorts with lowest value first
                                if len(top_trades) < 3 or -profit < top_trades[0][0]:
                                    if len(top_trades) == 3:
                                        removed_trade = heapq.heappop(top_trades)  # remove the trade route with the lowest profit
                                        removed_commodity_code = self.name_mapping.get(CATEGORY_COMMODITIES, {}).get(removed_trade[2]['commodity'], '')  # and remove also the commodity from our commodity map
                                        del commodities_in_top_trades[removed_commodity_code]
                                    trade_info = self._create_trade_info(trade1, trade2, commodity_code, buy_price, sell_price, profit) 
                                    heapq.heappush(top_trades, (-profit, trade_id, trade_info))  # Insert new trade with negative profit (heap smallest value first). Include trade_id for a fallback sorting option
                                    commodities_in_top_trades[commodity_code] = {'profit': profit, 'negative_profit': -profit, 'trade_id': trade_id, 'trade_info': trade_info}
                                    trade_id += 1
        
        print_debug(top_trades)
        # Convert heap to a sorted list
        top_trades = sorted([trade for _, _, trade in top_trades], key=lambda x: x["profit"], reverse=True)

        if not top_trades:
            return {"success": False, "message": f"No trade route found between {location_code1} and {location_code2}."}
        
        return {
            "success": True, 
            "instructions": "Tell the user how many alternatives you have identified. Provide him the first trade route details. Write out all numbers, especially prices. Example: instead of 24 write 'twentyfour'! ", 
            "trade_routes": top_trades,
            "number_of_alternatives": len(top_trades)
        }

    def _create_trade_info(self, buy_tradeport, sell_tradeport, commodity_code, buy_price, sell_price, profit):
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "buy_at_tradeport_name": buy_tradeport.get("name", ''),
            "buy_moon": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(buy_tradeport.get("satellite", ''), ''),
            "buy_orbit": self.code_mapping.get(CATEGORY_PLANETS, {}).get(buy_tradeport.get("planet", ''), ''),
            "sell_at_tradeport_name": sell_tradeport.get("name", ''),
            "sell_moon": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(sell_tradeport.get("satellite", ''), ''),
            "sell_orbit": self.code_mapping.get(CATEGORY_PLANETS, {}).get(sell_tradeport.get("planet", ''), ''),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "profit": profit
        }
    
    def _find_best_trade_for_commodity(self, tradeports_data, commodities_data, commodity_code, include_restricted_illegal=False):
        """
        Find the best trade route for a specific commodity.
        """
        no_route = {"success": False, "message": f"No trade route found for commodity {commodity_code}."}

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route
        
        top_trades = []
        trade_id = 0

        for trade1 in tradeports_data.values():  # buy tradeport
            if commodity_code not in trade1.get('prices', {}):
                continue
            
            details = trade1['prices'][commodity_code]
            if details['operation'].lower() != 'buy':
                continue

            buy_price = details.get('price_buy', 0)

            for trade2 in tradeports_data.values():  # sell tradeport
                
                if commodity_code not in trade2.get('prices', {}):
                    continue
            
                details = trade2['prices'][commodity_code]
                if details['operation'].lower() != 'sell':
                    continue

                sell_price = details.get('price_sell', 0)

                profit = sell_price - buy_price
                if profit <= 0:
                    continue

                trade_info = self._create_trade_info(trade1, trade2, commodity_code, buy_price, sell_price, round(profit, ndigits=2))
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
    
    def _find_best_selling_location_for_commodity(self, tradeports_data, commodities_data, commodity_code, include_restricted_illegal=False):
        """
        Find the best selling option for a commodity.
        """
        no_route = {"success": False, "message": f"No selling location found for commodity {commodity_code}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route

        top_trades = []
        trade_id = 0

        for trade in tradeports_data.values():
            # print_debug(f"checking {trade}")
            if commodity_code in trade.get('prices', {}):
                details = trade['prices'][commodity_code]
                sell_price = details.get('price_sell', 0)
                if details['operation'] == 'sell' and sell_price and (sell_price > max_sell_price or len(top_trades) < 3):
                    trade_info = self._build_trade_selling_info(commodity_code, trade, round(sell_price, ndigits=2))
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

    def _find_best_sell_price_at_location(self, tradeports_data, commodities_data, commodity_code, location_code):
        """
        Find the best trade route for a specific commodity around a specific location.
        """

        tradeports = [trade for trade in tradeports_data.values() if trade['system'] == location_code or trade['planet'] == location_code or trade['satellite'] == location_code or trade['city'] == location_code or trade['code'] == location_code]

        no_route = {"success": False, "message": f"No available tradeport found for commodity {commodity_code} at location {location_code}."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal=True, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route

        top_trades = []
        trade_id = 0

        for trade in tradeports:
            if commodity_code in trade.get('prices', {}):
                details = trade['prices'][commodity_code]
                sell_price = details.get('price_sell', 0)
                if details['operation'] == 'sell' and sell_price and (sell_price > max_sell_price or len(top_trades) < 3):
                    trade_info = self._build_trade_selling_info(commodity_code, trade, round(sell_price, ndigits=2))
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
                "sell_at_tradeport_name": best_sell.get("name", ''),
                "sell_moon": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_sell.get("satellite", ''), ''),
                "sell_orbit": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_sell.get("planet", ''), ''),
                "sell_price": max_sell_price
            }

    def _find_best_trade_from_location(self, tradeports_data, commodities_data, location_code, include_restricted_illegal=False):
        """
        Find the best trading option starting from a given location.
        """
        # Extrahiere alle Handelsposten am Startort
        start_location_trades = [trade for trade in tradeports_data.values() if trade['system'] == location_code or trade['planet'] == location_code or trade['satellite'] == location_code or trade['city'] == location_code or trade['code'] == location_code]
        
        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
            
        max_profit = 0

        top_trades = []
        trade_id = 0

        # Durchlaufe alle Waren, die am Startort verkauft werden
        for start_trade in start_location_trades:
            for commodity, details in start_trade.get('prices', {}).items():
                if commodity not in allowedCommodities:
                    continue
                if 'buy' in details['operation']:
                    if commodity not in allowedCommodities:
                        continue
                    buy_price = details.get('price_buy', 0)

                    if buy_price == 0:
                        continue

                    # Finde den besten Einkaufspreis für die Ware an anderen Orten
                    best_sell_price = 0
                    best_sell_location = None
                    for trade in tradeports_data.values():
                        if commodity in trade.get('prices', {}) and 'sell' in trade['prices'][commodity]['operation']:
                            sell_price = trade['prices'][commodity].get('price_sell', 0)
                            if sell_price > best_sell_price:
                                best_sell_price = sell_price
                                best_sell_location = trade

                    # Berechne den Profit und prüfe, ob es die beste Option ist
                    profit = best_sell_price - buy_price
                    if profit > 0 and profit > max_profit:
                        trade_info = self._create_trade_info(start_trade, best_sell_location, commodity, buy_price, best_sell_price, round(profit, ndigits=2))
                        # - profit as lowest value is always at top_trades[0]
                        heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                        max_profit = profit
                        trade_id += 1
                        
        if not top_trades:
            return {"success": False, "message": f"No trade route found starting at {location_code}."}
        
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
        
        return self._find_best_trade_between_locations(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), location_from["code"], location_to["code"])

    def find_best_trade_from_location_code(self, location_name_from):
        printr.print(text=f"Suche beste Handelsoption ab {location_name_from}", tags="info")
        _, location = self.get_location(location_name_from)
        if not location:
            return {"success": False, "instructions": "Missing starting location"}
        
        return self._find_best_trade_from_location(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), location["code"])

    def find_best_trade_for_commodity_code(self, commodity_name):
        printr.print(text=f"Suche beste Route für {commodity_name}", tags="info")
        
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "instructions": "Ask the player for the commodity that he wants to trade."
            }
        
        return self._find_best_trade_for_commodity(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity["code"])   
    
    def find_best_selling_location_for_commodity_code(self, commodity_name):
        printr.print(text=f"Suche beste Verkaufsort für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
            
        if not commodity:
            return {
                "success": False, 
                "instructions": "Ask the player the commodity that he wants to sell."
            }
    
        return self._find_best_selling_location_for_commodity(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity["code"])
    
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
        
        return self._find_best_sell_price_at_location(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity_code=commodity["code"], location_code=location_to["code"])
      
    def get_commodity_name(self, code):
        self._refresh_data()
        if code in self.code_mapping.get(CATEGORY_COMMODITIES):
            return self.code_mapping.get(CATEGORY_COMMODITIES).get(code)
        
        return code
    
    def get_satellite_name(self, code):
        self._refresh_data()
    
        if code in self.code_mapping.get(CATEGORY_SATELLITES):
            return self.code_mapping.get(CATEGORY_SATELLITES).get(code)
        
        return code
    
    def get_planet_name(self, code):
        self._refresh_data()
    
        if code in self.code_mapping.get(CATEGORY_PLANETS):
            return self.code_mapping.get(CATEGORY_PLANETS).get(code)
        
        return code
    
    def get_city_name(self, code):
        self._refresh_data()
    
        if code in self.code_mapping.get(CATEGORY_CITIES):
            return self.code_mapping.get(CATEGORY_CITIES).get(code)
        
        return code
    
    def get_tradeport_name(self, code):
        self._refresh_data()
    
        if code in self.code_mapping.get(CATEGORY_TRADEPORTS):
            return self.code_mapping.get(CATEGORY_TRADEPORTS).get(code)
        
        return code

    def get_tradeports(self):
        self._refresh_data()
        category = CATEGORY_TRADEPORTS
        return self.data[category].get("data", [])
    
    def get_tradeport(self, tradeport_mapping_name):
        code = self.name_mapping[CATEGORY_TRADEPORTS].get(tradeport_mapping_name, None)
        if not code:
            return None
        
        return self.data[CATEGORY_TRADEPORTS].get("data", []).get(code, None)
    
    def get_location(self, location_mapping_name):
        code = self.name_mapping[CATEGORY_TRADEPORTS].get(location_mapping_name, None)
        if code:
            return "tradeport", self.data[CATEGORY_TRADEPORTS].get("data", []).get(code, None)
        
        code = self.name_mapping[CATEGORY_SATELLITES].get(location_mapping_name, None)
        if code:
            return "satellite", self.data[CATEGORY_SATELLITES].get("data", []).get(code, None)
        
        code = self.name_mapping[CATEGORY_PLANETS].get(location_mapping_name, None)
        if code:
            return "planet", self.data[CATEGORY_PLANETS].get("data", []).get(code, None)
        
        code = self.name_mapping[CATEGORY_CITIES].get(location_mapping_name, None)
        if code:
            return "city", self.data[CATEGORY_CITIES].get("data", []).get(code, None)
        
        return None, None
    
    def get_commodity(self, commodity_mapping_name):
        code = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        if code:
            return self.data[CATEGORY_COMMODITIES].get("data", []).get(code, None)
        
        return None
    
    def get_commodity_for_tradeport(self, commodity_mapping_name, tradeport):
        code = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        # print_debug(f'uex: {commodity_mapping_name}-> {code} @ {tradeport["name_short"]}')
        if not code:
            return None
        
        prices_dict = tradeport.get("prices", {})

        return prices_dict.get(code, None)
        
    def get_data(self, category):
        self._refresh_data()
        return self.data[category].get("data", [])
        
    def get_category_names(self, category: str) -> list[str]:
        self._refresh_data()
        
        return list(self.name_mapping[category].keys())
        
    def update_tradeport_prices(self, tradeport, commodity_update_infos, operation):
        url = f"{self.api_endpoint}/srm/"

        encoded_data = {}
        result_data = {
            "ignored_count": 0,
            "send_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "response": ""
        }
        ignored_count = 0
        send_count = 0
        accepted_count = 0
        rejected_count = 0

        for index, commodity_update_info in enumerate(commodity_update_infos):
            if not ("code" in commodity_update_info) or not ("uex_price" in commodity_update_info):
                print_debug(f"uex1: missing code or uex_price, not submitting {json.dumps(commodity_update_info,indent=2)}")
                ignored_count += 1
                continue
            
            send_count += 1
            accepted_count += 1  # TODO temporary, until I know how the response looks like
            update_data = {
                "commodity": commodity_update_info["code"],
                "tradeport": tradeport["code"],
                "operation": operation,
                "price": commodity_update_info["uex_price"],
            }
            for key, value in update_data.items():
                encoded_data[f'{key}[{index}]'] = value

        encoded_data["access_code"] = self.uex_access_code
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            "api_key": f"{self.api_key}"
        }
       
        if not CALL_UEX_SR_ENDPOINT:
            possible_values = [1, 2, 4, 5, 7]
            possible_bools = [True, True, True, False]
            return random.choice(possible_values), random.choice(possible_bools)

        if not TEST:
            encoded_data["production"] = "1"

        print_debug(f"calling uex1 with data={json.dumps(encoded_data, indent=2)}")

        response = requests.post(url, headers=headers, data=encoded_data, timeout=360)
        result_data["accepted_count"] = accepted_count
        result_data["ignored_count"] = ignored_count
        result_data["rejected_count"] = rejected_count
        result_data["send_count"] = send_count
        result_data["response"] = response.json()
        if response.status_code == 200:
            print_debug(f"UEX1: Success Response: {json.dumps(response.json(), indent=2)}")
            return result_data, True # report id received
        
        print_debug(f'Fehler beim updaten von Preis-Daten - reason: {json.dumps(response.json(), indent=2)}')
        # es scheint nur ein alles oder nichts verfahren zu geben, daher überschreiben wir im Fehlerfall:
        result_data["accepted_count"] = 0
        result_data["rejected_count"] = send_count
        return result_data, False # error reason
    