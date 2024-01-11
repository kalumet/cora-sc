import json
import random

from services.printr import Printr

from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.uex_api import UEXApi
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext


DEBUG = True
TEST = True

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class TddManager(FunctionManager):

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config  # the wingmen config
        self.uex_service: UEXApi = UEXApi()
        self.overlay: StarCitizenOverlay = StarCitizenOverlay()
        self.tdd_voice = self.config["openai"]["contexts"]["tdd_voice"]

    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.get_trade_information_from_tdd_employee.__name__] = self.get_trade_information_from_tdd_employee
        function_register[self.switch_tdd_employee.__name__] = self.switch_tdd_employee

    # @abstractmethod
    def get_function_tools(self):
        tradeport_names = self.uex_service.get_category_names("tradeports")
        planet_names = self.uex_service.get_category_names("planets")
        satellite_names = self.uex_service.get_category_names("satellites")
        commodity_names = self.uex_service.get_category_names("commodities")
        cities_names = self.uex_service.get_category_names("cities")

        combined_locations_names = planet_names + satellite_names + cities_names + tradeport_names

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
                                "enum": combined_locations_names
                            },
                            "location_name_to": {
                                "type": "string",
                                "description": "The location, where the player wants sell a commodity or end a trade route. Can be the name of a planet, a moon / satellite or a specific tradeport. Can be empty.",
                                "enum": combined_locations_names
                            },
                            "commodity_name": {
                                "type": "string",
                                "description": "The commodity that the user wants to sell or buy. Can be empty.",
                                "enum": commodity_names
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
                                "enum": ["find_best_trade_route_starting_at_location", "find_tradeport_at_location_that_buys_commodity", 
                                         "find_best_trade_route_for_commodity_between_locations", "find_best_sell_price_for_commodity", 
                                         "find_best_trade_route_between"]
                            },
                            "request_validated_by_user": {
                                "type": "boolean",
                                "description": "Set to false, unless the user confirms the request explicitely.",
                            }
                        },
                        "required": ["request_type", "request_validated_by_user"]
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
                "- find_best_sell_price_for_commodity: used if the player wants to know where to get the best price for a given commodity independent of any location. Requires only 'commodity_name' "
        )
    
    #@abstractmethod
    def get_context_mapping(self) -> AIContext:
        return AIContext.TDD

    def get_trade_information_from_tdd_employee(self, function_args):
        print_debug(f"trade request: {function_args}")
        
        request_type = function_args.get("request_type", "")
        request_validated_by_user = function_args.get("request_validated_by_user", False)
                
        if request_type == "find_best_trade_route_starting_at_location":
                
            location_type, location = self.uex_service.get_location(function_args.get("location_name_from", None))
            if not location:
                return {"success": False, "instructions": "Ask the player for the location he wants to start his trade route."}
            if not request_validated_by_user:
                return {"success": False, "instructions": f"Request confirmation of user for the starting location {location['name']}({location_type})"}
            
            function_response = self.uex_service.find_best_trade_from_location(location_name=function_args["location_name_from"])

            if not function_response.get("success", None):
                moon_or_planet_buy = function_response["buy_satellite"] if function_response["buy_satellite"] else function_response["buy_planet"]
                moon_or_planet_sell = function_response["sell_satellite"] if function_response["sell_satellite"] else function_response["sell_planet"]
                self.overlay.display_overlay_text(
                    f'Buy {function_response["commodity"]} at {function_response["buy_at"]} ({moon_or_planet_buy}). '
                    f'Sell at {function_response["sell_at"]} ({moon_or_planet_sell}).'    
                )
            function_response = json.dumps(function_response)
            printr.print(f'-> Resultat: {function_response}', tags="info") 
            return function_response

        if request_type == "find_best_trade_route_between":
            
            location_type_from, location_from = self.uex_service.get_location(function_args.get("location_name_from", None))
            location_type_to, location_to = self.uex_service.get_location(function_args.get("location_name_to", None))
            
            if not (location_from and location_to): 
                return {
                    "success": False, 
                    "instructions": "Ask the user from where he wants to start and where he wants to go."
                }

            if not request_validated_by_user:
                return {
                    "success": False, 
                    "instructions": (
                        f"Request confirmation of user for starting location {location_from['name']}({location_type_from}) "
                        f"and target location {location_to['name']}({location_type_to})"
                    )
                }
            
            function_response = self.uex_service.find_best_trade_between_locations(location_name1=function_args["location_name_from"], location_name2=function_args["location_name_to"])
            if not function_response.get("success", None):
                moon_or_planet_buy = function_response["buy_satellite"] if function_response["buy_satellite"] else function_response["buy_planet"]
                moon_or_planet_sell = function_response["sell_satellite"] if function_response["sell_satellite"] else function_response["sell_planet"]
                self.overlay.display_overlay_text(
                    f'Buy {function_response["commodity"]} at {function_response["buy_at"]} ({moon_or_planet_buy}). '
                    f'Sell at {function_response["sell_at"]} ({moon_or_planet_sell}).'    
                )
            function_response = json.dumps(function_response)
            printr.print(f'-> Resultat: {function_response}', tags="info")
            return function_response

        if request_type == "find_tradeport_at_location_to_sell_commodity":
            
            location_type_to, location_to = self.uex_service.get_location(function_args.get("location_name_to", None))
            commodity = self.uex_service.get_commodity(function_args.get("commodity_name", None))
            
            if not (commodity and location_to):
                return {
                    "success": False, 
                    "instructions": "Ask the player to provide a commodity name and the location where he wants to sell the commodity."
                }

            if not request_validated_by_user:
                return {
                    "success": False, 
                    "instructions": (
                        f"Request confirmation of the user if he wants to sell commodity {commodity['name']} at {location_to['name']}({location_type_to})"
                    )
                }
            
            function_response = self.uex_service.find_best_sell_price_at_location(location_name=function_args["location_name_to"], commodity_name=function_args["commodity_name"])
           
            if not function_response.get("success", None):
                moon_or_planet_sell = function_response["sell_satellite"] if function_response["sell_satellite"] else function_response["sell_planet"]
                self.overlay.display_overlay_text(
                    f'Sell {function_response["commodity"]} at {function_response["sell_at"]} ({moon_or_planet_sell}) for {function_response["sell_price"]} aUEC.'    
                )
            function_response = json.dumps(function_response)
            printr.print(f'-> Resultat: {function_response}', tags="info")

            return function_response

        if request_type == "find_best_trade_route_for_commodity_between_locations":
            commodity = self.uex_service.get_commodity(function_args.get("commodity_name", None))
            
            if not (commodity):
                return {
                    "success": False, 
                    "instructions": "Ask the player for the commodity that he wants to trade."
                }

            if not request_validated_by_user:
                return {
                    "success": False, 
                    "instructions": (
                        f"Request confirmation of the user if he wants to trade commodity {commodity['name']}"
                    )
                }
           
            function_response = self.uex_service.find_best_trade_for_commodity(commodity_name=function_args["commodity_name"])
            if not function_response.get("success", None):
                moon_or_planet_buy = function_response["buy_satellite"] if function_response["buy_satellite"] else function_response["buy_planet"]
                moon_or_planet_sell = function_response["sell_satellite"] if function_response["sell_satellite"] else function_response["sell_planet"]
                self.overlay.display_overlay_text(
                    f'Buy {function_response["commodity"]} at {function_response["buy_at"]} ({moon_or_planet_buy}). '
                    f'Sell at {function_response["sell_at"]} ({moon_or_planet_sell}).'    
                )
            function_response = json.dumps(function_response)
            printr.print(f'-> Resultat: {function_response}', tags="info")
            return function_response

        if request_type == "find_best_sell_price_for_commodity":
             
            commodity = self.uex_service.get_commodity(function_args.get("commodity_name", None))
            
            if not (commodity):
                return {
                    "success": False, 
                    "instructions": "Ask the player the commodity that he wants to sell."
                }
            if not (commodity) or not request_validated_by_user:
                return {
                    "success": False, 
                    "instructions": (
                        f"Request confirmation of the user if he wants to sell commodity {commodity['name']}"
                    )
                }
            
            function_response = self.uex_service.find_best_selling_location_for_commodity(commodity_name=function_args["commodity_name"])
            if not function_response.get("success", None):
                moon_or_planet_sell = function_response["sell_satellite"] if function_response["sell_satellite"] else function_response["sell_planet"]
                self.overlay.display_overlay_text(
                    f'Sell {function_response["commodity"]} at {function_response["sell_at"]} ({moon_or_planet_sell}) for {function_response["sell_price"]} aUEC.'    
                )
            function_response = json.dumps(function_response)
            printr.print(f'-> Resultat: {function_response}', tags="info")
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