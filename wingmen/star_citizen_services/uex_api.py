import json
import os
import time
import requests
import random
from services.printr import Printr


DEBUG = False
TEST = True
CALL_UEX_SR_ENDPOINT = False


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
            shorten_name = "".join(character for character in entry_name if character.isalnum())  # wir entfernen alle leer und sonderzeichen
            self.code_mapping[category][entry_code] = entry_name
            self.name_mapping[category][shorten_name] = entry_code
            json_data[shorten_name] = {export_code_field_name: entry_code, export_value_field_name: entry_name}

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

        # Finding the best trade option
        best_trade = {"location_code_from": location_code1, "location_code_to": location_code2, "message": "No trade route found between these locations."}
        max_profit = 0
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
                        
                            profit = sell_price - buy_price
                            if profit > max_profit:
                                max_profit = profit
                                best_trade = {
                                    "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
                                    "buy_at": trade1.get("name", ''),
                                    "buy_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(trade1.get("satellite", ''), ''),
                                    "buy_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(trade1.get("planet", ''), ''),
                                    "sell_at": trade2.get("name", ''),
                                    "sell_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(trade2.get("satellite", ''), ''),
                                    "sell_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(trade2.get("planet", ''), ''),
                                    "buy_price": buy_price,
                                    "sell_price": sell_price,
                                    "profit": profit
                                }
        return best_trade

    def _find_best_trade_for_commodity(self, tradeports_data, commodities_data, commodity_code, include_restricted_illegal=False):
        """
        Find the best trade route for a specific commodity.
        """
        best_buy = None
        best_sell = None
        no_route = {"commodity_code": commodity_code, "message": "No selling location found for this commodity."}
        min_buy_price = float('inf')
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route

        for trade in tradeports_data.values():
            if commodity_code in trade.get('prices', {}):
                details = trade['prices'][commodity_code]
                buy_price = details.get('price_buy', 0)
                sell_price = details.get('price_sell', 0)
                if details['operation'] == 'buy' and buy_price and buy_price < min_buy_price:
                    min_buy_price = buy_price
                    best_buy = trade
                if details['operation'] == 'sell' and sell_price and sell_price > max_sell_price:
                    max_sell_price = sell_price
                    best_sell = trade
     
        if not best_sell:
            return no_route
        
        if max_sell_price - min_buy_price < 0:
            return no_route
        
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "buy_at": best_buy.get("name", ''),
            "buy_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_buy.get("satellite", ''), ''),
            "buy_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_buy.get("planet", ''), ''),
            "sell_at": best_sell.get("name", ''),
            "sell_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_sell.get("satellite", ''), ''),
            "sell_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_sell.get("planet", ''), ''),
            "buy_price": min_buy_price,
            "sell_price": max_sell_price,
            "profit": max_sell_price - min_buy_price
        }
    
    def _find_best_selling_location_for_commodity(self, tradeports_data, commodities_data, commodity_code, include_restricted_illegal=False):
        """
        Find the best selling option for a commodity.
        """
        best_sell = None
        no_route = {"commodity_code": commodity_code, "message": "No selling location found for this commodity."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route

        for trade in tradeports_data.values():
            print_debug(f"checking {trade}")
            if commodity_code in trade.get('prices', {}):
                details = trade['prices'][commodity_code]
                sell_price = details.get('price_sell', 0)
                if details['operation'] == 'sell' and sell_price and sell_price > max_sell_price:
                    max_sell_price = sell_price
                    best_sell = trade
     
        if not best_sell:
            return no_route
        
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "sell_at": best_sell.get("name", ''),
            "sell_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_sell.get("satellite", ''), ''),
            "sell_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_sell.get("planet", ''), ''),
            "sell_price": max_sell_price
        }

    def _find_best_sell_price_at_location(self, tradeports_data, commodities_data, commodity_code, location_code):
        """
        Find the best trade route for a specific commodity around a specific location.
        """

        tradeports = [trade for trade in tradeports_data.values() if trade['system'] == location_code or trade['planet'] == location_code or trade['satellite'] == location_code or trade['city'] == location_code or trade['code'] == location_code]

        best_sell = None
        no_route = {"location_from": location_code, "commodity_code": commodity_code, "message": "No available trade route for this commodity found at this location."}
        max_sell_price = 0

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal=True, isOnlySellable=True)
        if commodity_code not in allowedCommodities:
            return no_route

        for trade in tradeports:
            if commodity_code in trade.get('prices', {}):
                details = trade['prices'][commodity_code]
                sell_price = details.get('price_sell', 0)
                if details['operation'] == 'sell' and sell_price and sell_price > max_sell_price:
                    max_sell_price = sell_price
                    best_sell = trade

        if not best_sell:
            return no_route
        
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "sell_at": best_sell.get("name", ''),
            "sell_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_sell.get("satellite", ''), ''),
            "sell_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_sell.get("planet", ''), ''),
            "sell_price": max_sell_price
        }

    def _find_best_trade_from_location(self, tradeports_data, commodities_data, location_code, include_restricted_illegal=False):
        """
        Find the best trading option starting from a given location.
        """
        # Extrahiere alle Handelsposten am Startort
        start_location_trades = [trade for trade in tradeports_data.values() if trade['system'] == location_code or trade['planet'] == location_code or trade['satellite'] == location_code or trade['city'] == location_code or trade['code'] == location_code]
        
        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
            
        best_trade = {"location_from": location_code, "message": "No available trade route from this location found."}
        max_profit = 0
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
                    if profit > max_profit:
                        max_profit = profit
                        best_trade = {
                            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity, ''),
                            "buy_at": start_trade.get('name', ''),
                            "buy_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(start_trade.get('satellite', ''), ''),
                            "buy_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(start_trade.get('planet', ''), ''),
                            "sell_at": best_sell_location.get('name', ''),
                            "sell_satellite": self.code_mapping.get(CATEGORY_SATELLITES, {}).get(best_sell_location.get('satellite', ''), ''),
                            "sell_planet": self.code_mapping.get(CATEGORY_PLANETS, {}).get(best_sell_location.get('planet', ''), ''),
                            "buy_price": start_trade.get('prices', {}).get(commodity, {}).get('price_buy', 0),
                            "sell_price": best_sell_location.get('prices', {}).get(commodity, {}).get('price_sell', 0),
                            "profit": profit
                        }

        return best_trade

    def _find_location_code(self, location_name) -> str:
        
        if (location_name in self.name_mapping[CATEGORY_PLANETS]):
            return self.name_mapping[CATEGORY_PLANETS].get(location_name)
        if (location_name in self.name_mapping[CATEGORY_SATELLITES]):
            return self.name_mapping[CATEGORY_SATELLITES].get(location_name)
        if (location_name in self.name_mapping[CATEGORY_CITIES]):
            return self.name_mapping[CATEGORY_CITIES].get(location_name)
        if (location_name in self.name_mapping[CATEGORY_TRADEPORTS]):
            return self.name_mapping[CATEGORY_TRADEPORTS].get(location_name)
        return None
        
    def _find_commodity_code(self, commodity_name) -> str:
        
        # print_debug(self.name_mapping[CATEGORY_COMMODITIES])
        if (commodity_name in self.name_mapping[CATEGORY_COMMODITIES]):
            return self.name_mapping[CATEGORY_COMMODITIES].get(commodity_name)
        
        return None

    def find_best_trade_between_locations(self, location_name1, location_name2):
        self._refresh_data()
        location_code1 = self._find_location_code(location_name1)
        location_code2 = self._find_location_code(location_name2)
        printr.print(text=f"Suche beste Handelsoption für die Reise {location_name1} ({location_code1}) -> {location_name2} ({location_code2})", tags="info")
        if (location_code1 and location_code2):
            return self._find_best_trade_between_locations(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), location_code1, location_code2)
        return {"success": "False", "message": f"Could not identify locations {location_name1}({location_code1}) or {location_name2}({location_code2})"}

    def find_best_trade_from_location(self, location_name):
        self._refresh_data()
        location_code = self._find_location_code(location_name)
        printr.print(text=f"Suche beste Handelsoption ab {location_name} ({location_code})", tags="info")
        if (location_code):
            return self._find_best_trade_from_location(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), location_code)
        return {"success": "False", "message": f"Could not identify location {location_name}"}

    def find_best_trade_for_commodity(self, commodity_name):
        self._refresh_data()
        commodity_code = self._find_commodity_code(commodity_name)
        printr.print(text=f"Suche beste Route für {commodity_name} ({commodity_code})", tags="info")
        if (commodity_code):
            return self._find_best_trade_for_commodity(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity_code)
        return {"success": "False", "message": f"Could not identify commodity {commodity_name}"}

    def find_best_selling_location_for_commodity(self, commodity_name):
        self._refresh_data()
        commodity_code = self._find_commodity_code(commodity_name)
        printr.print(text=f"Suche beste Verkaufsort für {commodity_name} ({commodity_code})", tags="info")
        if (commodity_code):
            return self._find_best_selling_location_for_commodity(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity_code)
        return {"success": "False", "message": f"Could not identify commodity {commodity_name}"}

    def find_best_sell_price_at_location(self, commodity_name, location_name):
        self._refresh_data()
        commodity_code = self._find_commodity_code(commodity_name)
        location_code = self._find_location_code(location_name)
        printr.print(text=f"Suche beste Verkaufsoption für {commodity_name} ({commodity_code}) bei {location_name} ({location_code})", tags="info")
        if (commodity_code and location_code):
            return self._find_best_sell_price_at_location(self.data['tradeports'].get("data"), self.data['commodities'].get("data"), commodity_code=commodity_code, location_code=location_code)
        return {"success": "False", "message": f"Could not identify commodity {commodity_name}({commodity_code}) or location {location_name}({location_code})"}
    
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
    
    def get_data(self, category):
        self._refresh_data()
        return self.data[category].get("data", [])
        
    def get_category_names(self, category: str) -> list[str]:
        self._refresh_data()
        # mapping Datei einlesen
        with open(f"{self.root_data_path}/{category}_mapping.json", 'r', encoding='utf-8') as file:
            data = json.load(file)
            return list(data.keys())
        
    def update_tradeport_price(self, tradeport, commodity_update_info, operation):
        url = f"{self.api_endpoint}/sr/"
        
        update_data = {
            "commodity": commodity_update_info.get("code"),
            "tradeport": tradeport.get("code"),
            "operation": operation,
            "price": commodity_update_info.get("price"),
            "user_hash": self.uex_access_code,
        }
        
        if not CALL_UEX_SR_ENDPOINT:
            possible_strings = ["2423", "1234", "5678", "53249", "5294"]
            possible_bools = [True, True, True, False]
            return random.choice(possible_strings), random.choice(possible_bools)

        if not TEST:
            update_data["production"] = "1"

        response = requests.post(url, headers=self.headers, data=update_data, timeout=30)
        if response.status_code == 200:
            return response.json()["data"], True # report id received
        
        print_debug(f'Fehler beim updaten von Preis-Daten - reason: {response.json()["status"]}')
        return response.json()["status"], False # error reason
    
    def test(self):
        self._fetch_data()
        if not self.data:
            exit("No Data available")

        # Test the functions with sample data
        test_location_1 = "CRU"
        test_location_2 = "ARC"
        test_commodity_code = "AGRI" # Agricium
        test_location_code = "HUR"

        test_best_trade_systems = self._find_best_trade_between_locations(data['tradeports'].get("data"), data['commodities'].get("data"), test_location_1, test_location_2)
        test_best_trade_commodity = self._find_best_trade_for_commodity(data['tradeports'].get("data"), data['commodities'].get("data"), test_commodity_code)
        test_best_trade_location = self._find_best_trade_from_location(data['tradeports'].get("data"), data['commodities'].get("data"), test_location_code)
        test_best_sell_location = self._find_best_sell_price_at_location(data['tradeports'].get("data"), data['commodities'].get("data"), location_code=test_location_code, commodity_code=test_commodity_code)

        print_debug(f"best traderoute between {test_location_1} and {test_location_2}: {json.dumps(test_best_trade_systems)}")
        print_debug(f"best route for commodity {test_commodity_code}: {json.dumps(test_best_trade_commodity)}")
        print_debug(f"best trade from location {test_location_code}: {json.dumps(test_best_trade_location)}")
        print_debug(f"best sell price at location {test_location_code}: {json.dumps(test_best_sell_location)}")


if __name__ == "__main__":
    uex = UEXApi()
    uex.test()