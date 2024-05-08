import json
import random

from services.printr import Printr

from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

from wingmen.star_citizen_services.helper import transform_numbers_in_words


DEBUG = True
# TEST = True

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class TddManager(FunctionManager):

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config  # the wingmen config
        self.uex_service: UEXApi2 = UEXApi2()
        self.overlay: StarCitizenOverlay = StarCitizenOverlay()
        self.tdd_voice = self.config["openai"]["contexts"]["tdd_voice"]

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        return AIContext.TDD
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.get_trade_information_from_tdd_employee.__name__] = self.get_trade_information_from_tdd_employee
        function_register[self.switch_tdd_employee.__name__] = self.switch_tdd_employee
        
    # @abstractmethod
    def get_function_tools(self):
        # tradeport_names = self.uex_service.get_category_names("tradeports")
        # planet_names = self.uex_service.get_category_names("planets")
        # satellite_names = self.uex_service.get_category_names("satellites")
        # commodity_names = self.uex_service.get_category_names("commodities")
        # cities_names = self.uex_service.get_category_names("cities")

        # combined_locations_names = planet_names + satellite_names + cities_names + tradeport_names

        # commands = all defined keybinding label names
        tools = [
            {
                "type": "function",
                "function": 
                {
                    "name": self.get_trade_information_from_tdd_employee.__name__,
                    "description": (
                        "Whenever the user wants to get trading related information, call this function with appropriate parameters. "
                        "If none matches to the context of the player request, respond with general knowledge of a tdd employee."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location_name_from": {
                                "type": "string",
                                "description": "The location, where the player wants buy a commodity or start a trade route from. Can be the name of a planet, a moon / satellite or a specific tradeport. Can be empty.",
                                # "enum": combined_locations_names
                            },
                            "location_name_to": {
                                "type": "string",
                                "description": "The location, where the player wants sell a commodity or end a trade route. Can be the name of a planet, a moon / satellite or a specific tradeport. Can be empty.",
                                # "enum": combined_locations_names
                            },
                            "commodity_name": {
                                "type": "string",
                                "description": "The commodity that the user wants to sell or buy. Can be empty.",
                                # "enum": commodity_names
                            },
                            "include_illegal_commodities": {
                                "type": "boolean",
                                "description": "Indicates if illegal or restricted commodities should be searched as well. Only True, if the user explicitely requests it."
                            },
                            "request_type": {
                                "type": "string",
                                "description": (
                                    "The possible request_types the user can ask for. This defines what other parameters are required for this request to be fulfillable. "
                                ),
                                "enum": ["find_best_trade_route_starting_at_location", 
                                         "find_best_trade_route_for_commodity_between_locations", "find_locations_to_sell_commodity", 
                                         "find_best_trade_route_between, find_tradeport_at_location_to_sell_commodity, find_best_trade_routes_around_location"]
                            },
                        },
                        "required": ["request_type"]
                    }
                }
            },
            {
                "type": "function",
                "function": 
                {
                    "name": self.switch_tdd_employee.__name__,
                    "description": "Whenever the player adresses a new Trading Division Departement, make this function call.",
                }
            }

        ]

        # print_debug(f"tools definition: {json.dumps(tools, indent=2)}")
        return tools

    # @abstractmethod
    def get_function_prompt(self):
        return (
                "When asked for trading information,  "
                "find the best request_type for the trade inquiry of the player and make sure to follow the the given instructions: "
                "All locations can be planets, moons / satellites or tradeports. "
                "For any of the parameters, make sure to only use one of the allowed values. If there is none that matches, ask for clarification. "
                "The request_type should be one of the following: "
                "- find_best_trade_route_starting_at_location: used, if the player beginns a trade route at a location. Requires only the user to provide the parameter 'location_name_from' "
                "- find_best_trade_route_between: used, if the player wants to trade between locations. Requires both 'location_name_from' and 'location_name_to' "
                "- find_tradeport_at_location_to_sell_commodity: used if the player wants to sell a specific commodity at a given location. Requires 'commodity_name' and 'location_name_to' "
                "- find_best_trade_route_for_commodity_between_locations: used if the player wants to trade a given commodity without specifying any buying location or selling location. Requires only 'commodity_name' "
                "- find_locations_to_sell_commodity: used if the player wants to know where he can sell a given commodity independent of any location. Requires only 'commodity_name' "
                "- find_best_trade_routes_around_location: used, if the player wants to trade at or around a given location. Requires only 'location_name_to' "
        )

    def get_trade_information_from_tdd_employee(self, function_args):
        print_debug(f"trade request: {function_args}")
        
        request_type = function_args.get("request_type", "")
                
        if request_type == "find_best_trade_route_starting_at_location":  
            
            location_from = function_args.get("location_name_from", None)
            if location_from is None:
                return {"instructions": "Ask the player from what location he want's to start his trading route. "}
            function_response = self.uex_service.find_best_trade_from_location_code(location_name_from=function_args.get("location_name_from", None))

            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_buy = trade_route["buy_moon"] if trade_route["buy_moon"] else trade_route["buy_orbit"]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}). Profit: {trade_route["profit"]} aUEC.'    
                )
                print_debug((
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}).'    
                ))
            else:
                self.overlay.display_overlay_text(
                    function_response["message"] 
                )
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info") 
            transform_numbers_in_words.transform_numbers(function_response)
            return function_response

        if request_type == "find_best_trade_route_between":
            location_name_from = function_args.get("location_name_from", None)
            location_name_to = function_args.get("location_name_to", None)

            function_response = self.uex_service.find_best_trade_between_locations_code(location_name_from=location_name_from, location_name_to=location_name_to)
            
            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_buy = trade_route["buy_moon"] if trade_route["buy_moon"] else trade_route["buy_orbit"]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}). Profit: {trade_route["profit"]} aUEC.'    
                )
                print_debug((
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}).'    
                ))
            else:
                print_debug(function_response["message"])
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
            transform_numbers_in_words.transform_numbers(function_response)
            return function_response

        if request_type == "find_tradeport_at_location_to_sell_commodity":
            
            location_name = function_args.get("location_name_to", None)
           
            commodity_name = function_args.get("commodity_name", None)
                        
            function_response = self.uex_service.find_best_sell_price_at_location_codes(location_name=location_name, commodity_name=commodity_name)
            
            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.'    
                )
                print_debug((
                     f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.'      
                ))
            else:
                print_debug("No selling location found.")
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")

            transform_numbers_in_words.transform_numbers(function_response)
            return function_response

        if request_type == "find_best_trade_route_for_commodity_between_locations":
                       
            function_response = self.uex_service.find_best_trade_for_commodity_code(commodity_name=function_args.get("commodity_name", None))
            
            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_buy = trade_route["buy_moon"] if trade_route["buy_moon"] else trade_route["buy_orbit"]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}). Profit: {trade_route["profit"]} aUEC.'    
                )
                print_debug((
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}).'   
                ))
            else:
                print_debug(function_response["message"])
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
            transform_numbers_in_words.transform_numbers(function_response)
            return function_response

        if request_type == "find_locations_to_sell_commodity":
            
            function_response = self.uex_service.find_best_selling_location_for_commodity_code(commodity_name=function_args.get("commodity_name", None))
            
            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.'    
                )
                print_debug((
                    f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.'    
                ))
            else:
                print_debug(function_response["message"])
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
            transform_numbers_in_words.transform_numbers(function_response)
            return function_response
        
        if request_type == "find_best_trade_routes_around_location":  
            
            location_name = function_args.get("location_name_to", None)
            function_response = self.uex_service.find_best_trade_between_locations_code(location_name_from=location_name, location_name_to=location_name)

            success = function_response.get("success", False)
            if success:
                trade_route = function_response["trade_routes"][0]
                moon_or_planet_buy = trade_route["buy_moon"] if trade_route["buy_moon"] else trade_route["buy_orbit"]
                moon_or_planet_sell = trade_route["sell_moon"] if trade_route["sell_moon"] else trade_route["sell_orbit"]
                self.overlay.display_overlay_text(
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}). Profit: {trade_route["profit"]} aUEC.'    
                )
                print_debug((
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}).'    
                ))
            else:
                print_debug(function_response["message"])
            printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
            transform_numbers_in_words.transform_numbers(function_response)
            return function_response

    def switch_tdd_employee(self, function_args):
        tdd_voices = set(self.config["openai"]["contexts"]["tdd_voices"].split(","))
        tdd_voices.remove(self.tdd_voice)
        self.tdd_voice = random.choice(list(tdd_voices))
        self.config["openai"]["contexts"]["tdd_voice"] = self.tdd_voice
        self.config["openai"]["tts_voice"] = self.tdd_voice
        printr.print("TDD Department changed", tags="info")
        return json.dumps(
            {"success": True, 
                "instructions": (
                    "You are now a different TDD-Employee. Please briefly introduce yourself with your (sy fy) first name "
                    "and your position within the requested TDD-Departement and how you can help the player. "
                )
            }), None