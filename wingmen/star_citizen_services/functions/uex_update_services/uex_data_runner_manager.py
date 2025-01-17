import os
import json

from openai import OpenAI

from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_player import AudioPlayer

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.helper import screenshots
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.overlay import StarCitizenOverlay

from wingmen.star_citizen_services.functions.uex_update_services.data_validation_popup import OverlayPopup
from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


printr = Printr()


class UexDataRunnerManager(FunctionManager):
    
    def __init__(self, config, secret_keeper: SecretKeeper):
        super().__init__(config, secret_keeper)
        self.config = config
        self.data_dir_path = f'{self.config["data-root-directory"]}uex/kiosk_analyzer'
        self.openai_api_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False
        )
        self.client: OpenAI = OpenAI(api_key=self.openai_api_key)

        self.best_template_index = 1
        
        self.function_name = "transmit_commodity_prices_for_tradeport"

        self.screenshots_path = f"{self.data_dir_path}/screenshots"

        self.uex2_api_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="uex2_api_key",
            friendly_key_name="UEX2 API key",
            prompt_if_missing=True
        )
        self.uex2_secret_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="uex2_secret_key",
            friendly_key_name="UEX2 secret user key",
            prompt_if_missing=True
        )
        self.uex2_service = UEXApi2.init(
            uex_api_key=self.uex2_api_key,
            user_secret_key=self.uex2_secret_key
        )
        self.overlay = StarCitizenOverlay()
        self.audio_player = AudioPlayer()
        self.current_timestamp = None

        if not os.path.exists(self.screenshots_path):
            os.makedirs(self.screenshots_path)

        with open(f'{self.data_dir_path}/templates/response_structure_commodity_prices.json', 'r', encoding="UTF-8") as file:
            file_content = file.read()

        # JSON-String direkt verwenden
        json_string = file_content   

        self.commodity_prices_ocr = OCR(
            open_ai_model=f'{self.config["open-ai-vision-model"]}',
            openai_api_key=self.openai_api_key, 
            data_dir=self.data_dir_path,
            extraction_instructions=f"Give me the commodity price information within this image. Give me the response in a plain json object structured as defined in this example: {json_string}. Provide the json within markdown ```json ... ```.If you are unable to process the image, just return 'error' as response.",
            overlay=self.overlay)
        
        with open(f'{self.data_dir_path}/templates/response_structure_location_name.json', 'r', encoding="UTF-8") as file:
            location_name_structure = file.read()
        
        self.location_name_ocr = OCR(
            open_ai_model=f'{self.config["open-ai-vision-model"]}',
            openai_api_key=self.openai_api_key, 
            data_dir=self.data_dir_path,
            extraction_instructions=f"Give me the location name in this image. Give me the response in a plain json object structured as defined in this example: {location_name_structure}. Provide the json within markdown ```json ... ```.If you are unable to process the image, just return 'error' as response.",
            overlay=self.overlay)

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        return AIContext.CORA
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.transmit_commodity_prices_for_tradeport.__name__] = self.transmit_commodity_prices_for_tradeport
        function_register[self.sent_one_price_update_information_to_uex.__name__] = self.sent_one_price_update_information_to_uex
    
    # @abstractmethod
    def get_function_prompt(self):
        return (
            "If the user ask you to transmit commodity prices, you can do so by calling one of the following functions: "
            f"- '{self.transmit_commodity_prices_for_tradeport.__name__}' should be called, if the player wants to transmit all prices (many prices) and if he requests from you to analyse the prices displayed on the trading terminal; "
            f"- '{self.sent_one_price_update_information_to_uex.__name__}' should be called, if he wants to transmit a single price, or if he wants you to correct prices from a previous analysis. "
            " Follow these rules: Never (Never!) make assumptions about the values for these functions. Set to empty if the user does not provide values. Never, never call this functions without the user providing the data, like the tradeport he is currently. Before calling these functions, ask the user to provide you the data required."
            " These requests should not incure a context switch to TDD. "
        )
    
    # @abstractmethod
    def get_function_tools(self):
        """ 
        Provides the openai function definition for this manager. 
        """
        tradeport_names = self.uex2_service.get_category_names(category="terminals", field_name="nickname", filter=("type", "commodity"))
        commodity_names = self.uex2_service.get_category_names("commodities")

        tools = [
            {
                "type": "function",
                "function": 
                {
                    "name": self.transmit_commodity_prices_for_tradeport.__name__,
                    "description": "Function to transmit commodity prices to the uex corp. Call this function on phrases like 'New prices for transmission'. Only fill values with user provided input.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "player_provided_tradeport_name": {
                                "type": "string",
                                "description": "The tradeport name provided by the user. Ask, if he didn't provide a tradeport name.",
                                "enum": tradeport_names
                            },
                            "operation": {
                                "type": "string",
                                "description": "What kind of prices the user want to transmit. 'buy' is for buyable commodities at the location, 'sell' are for sellable commodities.",
                                "enum": ["sell", "buy", None]
                            }
                        },
                    }
                }
            },
            {
                "type": "function",
                "function": 
                {
                    "name": self.sent_one_price_update_information_to_uex.__name__,
                    "description": "Function to transmit one commodity price to uex. To be called, if he wants to transmit a specific commodity price. Do not fill in any values without input from the user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "player_provided_tradeport_name": {
                                "type": "string",
                                "description": "The tradeport name provided by the user. ",
                                "enum": tradeport_names
                            },
                            "operation": {
                                "type": "string",
                                "description": "What kind of prices the user want to transmit. 'buy' is for buyable commodities at the location, 'sell' are for sellable commodities.",
                                "enum": ["sell", "buy", None]
                            },
                            "commodity_name": {
                                "type": "string",
                                "description": "The name of the commodity",
                                "enum": commodity_names
                            },
                            "available_SCU_quantity": {
                                "type": "number",
                                "description": "The stock quantity available at this tradeport"
                            },
                            "inventory_state": {
                                "type": "string",
                                "description": "Indicates the fill level of the inventory for this commodity",
                                "enum": ["MAX INVENTORY", "VERY HIGH INVENTORY", "HIGH INVENTORY", "MEDIUM INVENTORY", "LOW INVENTORY", "VERY LOW INVENTORY", "OUT OF STOCK"]
                            },
                            "price_per_unit": {
                                "type": "number",
                                "description": "The price of this commodity at this tradeport for the given operation"
                            },
                            "multiplier": {
                                "type": "string",
                                "description": "The multiplier of the price",
                                "enum": ["M", "k", None]
                            }, 
                            "values_validated_by_user": {
                                "type": "string",
                                "description": "Do not set, unless the user explicitely confirms that values are valid.",
                                "enum": ["confirmed", None]
                            },
                            "confirm_new_available_trade_commodity": {
                                "type": "string",
                                "description": "Do not set. Only set to 'confirmed', if the user confirms, that this commodity should be transmitted to uex.",
                                "enum": ["confirmed", None]
                            }
                        },
                    }
                }
            }
        ]

        # print_debug(json.dumps(tools, indent=2))
        return tools

    def sent_one_price_update_information_to_uex(self, function_args):
        printr.print(f'-> Command: Sending price update to uex: {function_args}')
        self.overlay.display_overlay_text("Trying to submit one price information ...")
        print_debug(function_args)
        confirmed =  function_args.get("values_validated_by_user", None)
        if not confirmed and confirmed != "confirmed":
            function_response = {"success": False, "instruction": f"User needs to validate the following data: {json.dumps(function_args)}"}
            return function_response, None

        tradeport = self.uex2_service.get_terminal(function_args.get("player_provided_tradeport_name", None))
        if not tradeport:
            function_response = {"success": False, "instruction": "You could not identify the tradeport. Ask the user to repeat clearly the name."}
            return function_response, None
        
        operation = function_args.get("operation", None)

        new_commodity_confirmed = function_args.get("confirm_new_available_trade_commodity", None)
        
        commodity_current_tradeport_price = self.uex2_service.get_commodity_for_tradeport(function_args.get("commodity_name", None), tradeport)
        if not commodity_current_tradeport_price:
            if not new_commodity_confirmed and new_commodity_confirmed != "confirmed":
                function_response = {"success": False, "instruction": f"Commodity is not tradeable at this tradeport. Ask him to confirm the information if he wants to send the data anyway: {json.dumps(function_args)}"}
                return function_response, None
            
            if not operation:
                function_response = {"success": False, "instruction": f"If the player wants to submit a new tradeable commodity at this tradeport, he has to provide the operation."}
                return function_response, None
            
            commodity_current_tradeport_price = {
                f"price_{operation}": function_args.get("price_per_unit", None),
                "operation": operation
            }

        available_SCU_quantity = function_args.get("available_SCU_quantity", None)

        inventory_state = function_args.get("inventory_state", None)

        price_per_unit = function_args.get("price_per_unit", None)

        multiplier = function_args.get("multiplier", None)

        commodity = self.uex2_service.get_commodity(function_args["commodity_name"])

        new_price, success = CommodityPriceValidator.validate_price(validated_commodity=commodity_current_tradeport_price, multiplier=multiplier, operation=commodity_current_tradeport_price["operation"], price_to_check=price_per_unit)

        if not success:
            return {"success":False, "instructions": "The commodity price provided is not plausible for this tradeport."}

        commodity_update_info = {
            "code": commodity["code"],
            "uex_price": new_price
        }

        message, success = self.uex2_service.update_tradeport_prices(tradeport=tradeport, commodity_update_infos=commodity_update_info, operation=operation)

        if not success:
            return {"success": False, "instructions": "Request was not accepted by uex.", "reason": message}
        
        self.overlay.display_overlay_text(f'Transmitted: {operation} {commodity_update_info["code"]} @ {tradeport["name_short"]} -> {new_price} aUEC')
        return {"success": True, "instructions": "On repeated command, do not use the same function values. Reset the values_validated_by_user value to be false on next command."}

    def transmit_commodity_prices_for_tradeport(self, function_args):
        printr.print(f'-> Command: Analysing commodity prices to be sent to uex corp. Doing screenshot analysis. Only commodity information and only if active window is star citizen for {function_args}.')
        self.overlay.display_overlay_text("Trying to submit all prices ...")
        print_debug(function_args)
        if not function_args.get("player_provided_tradeport_name"):
            function_response = json.dumps({"success": False, "instruction": "Ask the player to provide the tradeport name for which he wants the prices to be transmitted"})
            return function_response, None
        
        tradeport = self.uex2_service.get_terminal(function_args["player_provided_tradeport_name"], search_fields=["nickname", "name", "space_station_name", "outpost_name", "city_name"])

        if not tradeport:
            function_response = json.dumps({"success": False, "instruction": 'Could not identify the given tradeport name. Please repeat clearly the tradeport name.'})
            return function_response, None
               
        if "operation" not in function_args:
            self.overlay.display_overlay_text("Invalid command.")
            return {"success": False, "instructions": "The user did not provide enough information to process his request. He has to tell at what terminal he is standing and what trading operation he wants to analyse. It is important, that he selects the current location inventory and that he has activated the correct operations tab.", 
                    "error": "missing tradeport or trading operation. "
                    }, None
        
        function_response = self._get_data_from_screenshots(tradeport, function_args["operation"])
        
        printr.print(f'-> Result: {json.dumps(function_response)}', tags="info")

        return function_response

    def _get_data_from_screenshots(self, tradeport=None, asked_operation=None):
        validated_tradeport = tradeport
        operation = "buy"
        if asked_operation == "sell":
            operation = "sell"
        
        screenshot_path = screenshots.take_screenshot(self.data_dir_path, operation, test=TEST, operation=operation, tradeport=tradeport["code"])
        if screenshot_path is None:
            self.overlay.display_overlay_text("Could not take screenshot. ")
            return {"success": False, "instructions": "You where not able to analyse the data. You can provide error information, if he likes. ", 
                    "error": "Could not make screenshot. Maybe, during screenshot taking, the active window displayed was NOT Star Citizen. In that case, I don't make any screenshots! "
                    }, None
    
        location_name_crop = screenshots.crop_screenshot(f"{self.data_dir_path}/location_name_area", screenshot_path, [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_LEFT", "AREA")])
        # retrieved_json, success = self.location_name_ocr.get_screenshot_texts(location_name_crop, "location_name_area")
        
        # if not success:
        #     self.overlay.display_overlay_text("Couldn't retrieve location name ...")
        #     return {
        #             "success": False, "instructions": "Tell the user, that you are not able to validate the provided location name. Bright spots might make recognition inpossible.", 
        #             }, None
        # location_name = retrieved_json['location_name']
        # print_debug(f"got raw location name: {location_name}")

        # success = LocationNameMatching.validate_associated_location_name(location_name, validated_tradeport, min_similarity=50)

        # if not success:
        #     self.overlay.display_overlay_text("Error: Cannot validate location name!")
        #     return {"success": False, 
        #             "instructions": "You cannot validate the given tradeport against the location in the screenshot. The user must select the current location in 'Your Inventories' drop-down. Or, if he did, he might need to transmit prices as single spoken commands without screenshot analysis.", 
        #             }, None
        
        print_debug(f'location name: {validated_tradeport["nickname"]}')            
        self.overlay.display_overlay_text(f'Selected tradeport: {validated_tradeport["nickname"]}')
        buy_result = self._analyse_prices_at_tradeport(screenshot_path, location_name_crop, validated_tradeport, operation)

        print_debug(buy_result)
        if "success" not in buy_result:
            return buy_result, None
    
        return buy_result
         
    def _analyse_prices_at_tradeport(self, screenshot_path, cropped_screenshot_location, validated_tradeport, operation):
        
        commodity_area_crop = screenshots.crop_screenshot(f"{self.data_dir_path}/commodity_info_area", screenshot_path, [("UPPER_LEFT", "LOWER_LEFT", "HORIZONTAL"), ("UPPER_LEFT", "LOWER_LEFT", "VERTICAL")], ["BOTTOM", "RIGHT"])
        prices_raw, success = self.commodity_prices_ocr.get_screenshot_texts(commodity_area_crop, "commodity_info_area", operation, operation=operation, tradeport=validated_tradeport['code'])
        
        if not success or not prices_raw.get("commodity_prices", False):
            self.overlay.display_overlay_text("Error retrieving commodity prices in screenshot.")
            return {"success": False, 
                    "instructions": "There was an error in retrieving the commodity prices from the screenshot. Provide information about the error, if the user asks for it. ", 
                    "message": prices_raw
                    }
        
        number_of_extracted_prices = len(prices_raw["commodity_prices"])

        print_debug(f"extracted {number_of_extracted_prices} price-informations from screenshot")

        terminal_prices = self.uex2_service.get_prices_of(price_category="commodities_prices", id_terminal=validated_tradeport["id"])
        screenshot_prices, validated_prices, invalid_prices, success = CommodityPriceValidator.validate_price_information(prices_raw.get("commodity_prices", []), terminal_prices, operation)

        if not success:
            self.overlay.display_overlay_text("Error: could not identify commodities. Check logs.")
            return {"success": False, 
                    "instructions": "You couldn't identify the commodities and prices. Instruct the user to analyse the log files.", 
                    }
        
        manually_confirmed_data = OverlayPopup.show_data_validation_popup(terminal_prices, operation, screenshot_prices, commodity_area_crop, cropped_screenshot_location)
        
        if manually_confirmed_data == "aborted":
            return {
                "instructions": "Tell the user, that transmission has been aborted. "
            }
        print(f"user-validated: {json.dumps(manually_confirmed_data, indent=2)}")
        
        number_of_validated_prices = len(manually_confirmed_data)

        print_debug(f"{number_of_validated_prices} prices are valid")

        if number_of_validated_prices == 0:
            self.overlay.display_overlay_text("Prices or commodity names not recognized. Check logs.")
            return {"success": False, 
                    "instructions": "You have made errors in recognizing the correct prices on the terminal and all have been rejected.", 
                    "message": "Could not identify commodity names or prices are not within 40% of allowed tollerance to current prices"
                    }
        
        # Write JSON data to a file
        json_file_name = f'{self.data_dir_path}/debug_data/verified_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
        with open(json_file_name, 'w') as file:
            json.dump(manually_confirmed_data, file, indent=4)
        
        self.overlay.display_overlay_text("Now transmitting to UEX.")
        response2, success2 = self.uex2_service.update_tradeport_prices(tradeport=validated_tradeport, commodity_update_infos=manually_confirmed_data, operation=operation)
        if not success2:
            self.overlay.display_overlay_text(f"Error UEX: no price information accepted.", display_duration=1500)
        
            # Write JSON data to a file
            json_file_name = f'{self.data_dir_path}/debug_data/uex2_rejected_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
            with open(json_file_name, 'w') as file:
                json.dump(response2, file, indent=4)
            return {
                        "success": False,
                        "instructions": "Price information was not accepted by UEX. Provide information about the error, if the user asks for it. ",
                        "message": {
                            "tradeport": validated_tradeport["name"],
                            f"{operation}able_commodities_info": {
                                "result_information": response2["status"]
                            }
                        }
                    }
        
        self.overlay.display_overlay_text(f'UEX Corp: acknowledged the data transmittion. ', display_duration=1500)
        
        return {"success": True}  # we don't want cora to repeat what we see on screen, if everything was fine
