import os
import datetime
import random
import cv2
import numpy as np
from PIL import Image
import pytesseract
import pygetwindow
import pyautogui
from openai import OpenAI
import base64
from io import BytesIO
import requests
import json
import traceback


from wingmen.star_citizen_services.functions.uex_update_services.data_validation_popup import OverlayPopup
from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator

# import wingmen.star_citizen_services.text_analyser as text_analyser
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_player import AudioPlayer

from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.uex_api import UEXApi
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext


DEBUG = True
SHOW_SCREENSHOTS = False
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
        self.client: OpenAI = OpenAI()
        self.client.api_key = self.openai_api_key

        self.best_template_index = 1
        
        self.function_name = "transmit_commodity_prices_for_tradeport"

        self.screenshots_path = f"{self.data_dir_path}/screenshots"
        self.uex_service = UEXApi()

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
        tradeport_names = self.uex_service.get_category_names("tradeports")
        commodity_names = self.uex_service.get_category_names("commodities")

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

        tradeport = self.uex_service.get_tradeport(function_args.get("player_provided_tradeport_name", None))
        if not tradeport:
            function_response = {"success": False, "instruction": "You could not identify the tradeport. Ask the user to repeat clearly the name."}
            return function_response, None
        
        operation = function_args.get("operation", None)

        new_commodity_confirmed = function_args.get("confirm_new_available_trade_commodity", None)
        
        commodity_current_tradeport_price = self.uex_service.get_commodity_for_tradeport(function_args.get("commodity_name", None), tradeport)
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

        commodity = self.uex_service.get_commodity(function_args["commodity_name"])

        new_price, success = CommodityPriceValidator._validate_price(validated_commodity=commodity_current_tradeport_price, multiplier=multiplier, operation=commodity_current_tradeport_price["operation"], price_to_check=price_per_unit)

        if not success:
            return {"success":False, "instructions": "The commodity price provided is not plausible for this tradeport."}

        commodity_update_info = {
            "code": commodity["code"],
            "uex_price": new_price
        }

        message, success = self.uex_service.update_tradeport_prices(tradeport=tradeport, commodity_update_info=commodity_update_info, operation=operation)

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
        
        tradeport = self.uex_service.get_tradeport(function_args["player_provided_tradeport_name"])

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
        
        gray_screenshot = self._take_screenshot(operation, tradeport)
        if gray_screenshot is None:
            self.overlay.display_overlay_text("Could not take screenshot. Or couldn't identify template index")
            return {"success": False, "instructions": "You where not able to analyse the data. You can provide error information, if he likes. ", 
                    "error": "Could not make screenshot. Maybe, during screenshot taking, the active window displayed was NOT Star Citizen. In that case, I don't make any screenshots! "
                    }, None
        
        success = self.choose_best_matching_template_index(gray_screenshot)
        if success is False:
            self.overlay.display_overlay_text("Couldn't identify template index for kiosk")
            return {"success": False, "instructions": "You where not able identify the kiosk design. You can provide error information, if he likes. ", 
                    "error": "Best matching template couldn't be found. Maybe new kiosk design or unknown kiosk type. Create new templates. "
                    }, None
        
        self.__debug_show_screenshot(gray_screenshot)
        
        location_name, location_name_crop, success = self._get_location_name(gray_screenshot)

        if not success:
            self.overlay.display_overlay_text("Trying to validate location name not possible: reduce bright spots ...")
            return {
                    "success": False, "instructions": "Tell the user, that you are not able to validate the provided location name. Bright spots might make recognition inpossible.", 
                    }, None

        print_debug(f"got raw location name: {location_name}")

        success = LocationNameMatching.validate_associated_location_name(location_name, validated_tradeport, min_similarity=50)

        if not success:
            self.overlay.display_overlay_text("Error: Cannot validate location name!")
            return {"success": False, 
                    "instructions": "You cannot validate the given tradeport against the location in the screenshot. The user must select the current location in 'Your Inventories' drop-down. Or, if he did, he might need to transmit prices as single spoken commands without screenshot analysis.", 
                    }, None
        
        print_debug(f'validated location name: {validated_tradeport["name_short"]}')            

        buy_result = self._analyse_prices_at_tradeport(gray_screenshot, location_name_crop, validated_tradeport, operation)

        print_debug(buy_result)
        if "success" not in buy_result:
            return buy_result, None
    
        return buy_result

    def choose_best_matching_template_index(self, gray_screenshot):
        top_left_x = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["top_left_x"]
        top_left_y = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["top_left_y"]
        bottom_right_x = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["bottom_right_x"]
        bottom_right_y = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["bottom_right_y"]
        cropped_screenshot = gray_screenshot[
                top_left_y : bottom_right_y, top_left_x : bottom_right_x
            ]
        
        self.__debug_show_screenshot(cropped_screenshot)
        
        try: 
            continue_template_matching = True
            next_template_index = 1
            highest_score = -1
            best_template_index = None
            while continue_template_matching:
                filename = f"{self.data_dir_path}/template_kiosk_location_upper_left_{next_template_index}.png"
                if not os.path.exists(filename):
                    continue_template_matching = False
                    break
            
                template = cv2.imread(filename, 0)
                proof_position = cv2.matchTemplate(cropped_screenshot, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(proof_position)

                if max_val > highest_score:
                    highest_score = max_val
                    best_template_index = next_template_index

                next_template_index += 1
                    
            self.best_template_index = best_template_index
            print_debug(f"best template index: {best_template_index}")
            return True

        except Exception:
            traceback.print_exc()
            return False
         
    def _analyse_prices_at_tradeport(self, gray_screenshot, cropped_screenshot_location, validated_tradeport, operation):
        
        prices_raw, cropped_screenshot_commodities, success = self._get_price_information(gray_screenshot, operation, validated_tradeport)

        if not success:
            self.overlay.display_overlay_text("Error: no clear view on terminal, reposition and avoid bright spots.")
            return {"success": False, 
                    "instructions": "You cannot analyse the commodity data, as something is obstructing your view. The player should reposition himself to avoid bright spots on the terminal and stand in front of the terminal.", 
                    }
        
        number_of_extracted_prices = len(prices_raw["commodity_prices"])

        print_debug(f"extracted {number_of_extracted_prices} price-informations from screenshot")

        all_prices, validated_prices, invalid_prices, success = CommodityPriceValidator.validate_price_information(prices_raw, validated_tradeport, operation)

        if not success:
            self.overlay.display_overlay_text("Error: could not identify commodities. Check logs.")
            return {"success": False, 
                    "instructions": "You couldn't identify the commodities and prices. Instruct the user to analyse the log files.", 
                    }
        
        manually_confirmed_data = OverlayPopup.show_data_validation_popup(validated_tradeport, operation, all_prices, cropped_screenshot_commodities, cropped_screenshot_location)
        
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
            # Write JSON data to a file
            json_file_name = f'{self.data_dir_path}/debug_data/uex2_rejected_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
            with open(json_file_name, 'w') as file:
                json.dump(response2, file, indent=4)


        response_data, success = self.uex_service.update_tradeport_prices(tradeport=validated_tradeport, commodity_update_infos=manually_confirmed_data, operation=operation)

        if not success:
            printr.print(f'price could not be updated: {json.dumps(response_data, indent=2)}', tags="info")
            # update_errors_uex_status.append(response)
            # validated_price["uex_rejection_reason"] = response
            # rejected_commodities.append(validated_price)
            # continue

        # print_debug(f'price successfully updated')
        # updated_commodities_uex_id.append(response)
        # updated_commodities.append(validated_price)

        # Write JSON data to a file
        
        if response_data["rejected_count"] > 0:
            json_file_name = f'{self.data_dir_path}/debug_data/uex1_price_rejected_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
            with open(json_file_name, 'w') as file:
                json.dump(response_data, file, indent=4)

        if not success or response_data["accepted_count"] == 0:
            self.overlay.display_overlay_text(f"Error UEX: no price information accepted.", display_duration=30000)
            return {
                        "success": False,
                        "instructions": "Tell the player in a funny but fair way, that UEX wasn't able to process the price information request. Tell him, that he should make single update commands. Give him information about the errornous price update if he asks for it. ",
                        "message": {
                            "tradeport": validated_tradeport["name"],
                            f"{operation}able_commodities_info": {
                                "result_information": response_data["response"]
                            }
                        }
                    }
        
        self.overlay.display_overlay_text(f'UEX Corp: {response_data["accepted_count"]} out of {response_data["send_count"]} price information accepted.', display_duration=30000)
        
        if response_data["rejected_count"] > 0:
            result_data = {
                        "success": True,
                        "instructions": "Prices where transmitted. ",
                        "message": {
                                "tradeport": validated_tradeport["name"],
                                f"{operation}able_commodities_info": {
                                    "extracted_prices_from_screenshot": number_of_extracted_prices,
                                    "sent_prices_count": response_data["send_count"],
                                    "accepted_prices_count": response_data["accepted_count"],
                                    "ignored_prices_count": response_data["ignored_count"],
                                    "rejected_prices_count": response_data["rejected_count"],
                                    "uex_response": response_data["response"]
                                }
                            }
                    }
        else:
            return "Ok"  # we don't want cora to repeat what we see on screen, if everything was fine

        return result_data

    def _take_screenshot(self, operation, tradeport):
        if TEST:
            return self.__random_image_from_directory(operation)

        try: 
            active_window = pygetwindow.getActiveWindow()
            if active_window and "Star Citizen" in active_window.title:
                # Aktuellen Zeitpunkt erfassen
                now = datetime.datetime.now()
                self.current_timestamp = now.strftime(
                    "%Y%m%d_%H%M%S_%f"
                )  # Format: JahrMonatTag_StundeMinuteSekunde_Millisekunden

                # Dateinamen mit Zeitstempel erstellen
                filename = f'{self.screenshots_path}/screenshot_{operation}_{tradeport["code"]}_{self.current_timestamp}.png'

                # Fensterposition und -größe bestimmen
                x, y, width, height = (
                    active_window.left,
                    active_window.top,
                    active_window.width,
                    active_window.height,
                )
                
                screenshot = pyautogui.screenshot(region=(x, y, width, height))

                # Konvertieren des PIL-Bildobjekts in ein NumPy-Array und Ändern der Farbreihenfolge von RGB zu BGR
                screenshot_np = np.array(screenshot)
                screenshot_bgr = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

                # Konvertieren in Graustufen
                gray_screenshot = cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2GRAY)

                # Speichern des Graustufenbildes
                cv2.imwrite(filename, gray_screenshot)
                
                return gray_screenshot
        except Exception:
            traceback.print_exc()    
        return None

    def __random_image_from_directory(self, operation):
        """
        Selects a random image from a specified directory.

        Args:
        directory (str): Path to the directory containing images.
        image_extensions (list, optional): List of acceptable image file extensions.

        Returns:
        str: Path to a randomly selected image.
        """
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
        directory = f"{self.data_dir_path}/examples/{operation}"
        # List all files in the directory
        files = os.listdir(directory)

        # Filter files to get only those with the specified extensions
        images = [
            file
            for file in files
            if any(file.endswith(ext) for ext in image_extensions)
        ]

        if not images:
            return None  # No images found

        # Randomly select an image
        image = os.path.join(directory, random.choice(images))

        # Load the screenshot for analysis
        screenshot = cv2.imread(image)
        if screenshot is None:
            return None
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        return gray_screenshot

    def _preprocess_image(self, gray_screenshot):
        """Preprocess the image for better OCR results."""
        # Apply color range filtering for grayscale image
        lower_bound = np.array([185])  # Lower bound for grayscale
        upper_bound = np.array([255])  # Upper bound for grayscale
        mask = cv2.inRange(gray_screenshot, lower_bound, upper_bound)
        result = cv2.bitwise_and(gray_screenshot, gray_screenshot, mask=mask)

        # Apply dilate and erode
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (1, 1))
        dilated = cv2.dilate(result, kernel, iterations=3)
        eroded = cv2.erode(dilated, kernel, iterations=3)

        return eroded

    def _get_location_name(self, gray_screenshot):
        """Analyze the screenshot and extract text."""
        try:
            # Schwellenwert für die Übereinstimmung
            threshold = 0.5

            top_left_x = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["top_left_x"]
            top_left_y = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["top_left_y"]
            bottom_right_x = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["bottom_right_x"]
            bottom_right_y = self.config["uex_data_runner"]["tradeport_kiosks"]["inventory_area"]["bottom_right_y"]
            cropped_screenshot = gray_screenshot[
                    top_left_y : bottom_right_y, top_left_x : bottom_right_x
                ]
            
            self.__debug_show_screenshot(cropped_screenshot)
            
            filename = f"{self.data_dir_path}/template_kiosk_location_upper_left_{self.best_template_index}.png"  # best template index selected during operation validation
            template_upper_left = cv2.imread(filename, 0)

            # Template matching inventory dropdown
            result_location_drop_down_label = cv2.matchTemplate(
                cropped_screenshot,
                template_upper_left,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_val_label, _, max_loc_label = cv2.minMaxLoc(
                result_location_drop_down_label
            )

            if max_val_label < threshold:
                print("Erstes Template nicht erkannt.")
                return "Could not identify location dropdown", None, False

            filename = f"{self.data_dir_path}/template_kiosk_location_lower_right_{self.best_template_index}.png"  # best template index selected during operation validation
            template_lower_right = cv2.imread(filename, 0)

            location_drop_down_action = cv2.matchTemplate(
                cropped_screenshot,
                template_lower_right,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_val_action, _, max_loc_action = cv2.minMaxLoc(location_drop_down_action)

            if max_val_action < threshold:
                print("Zweites Template nicht erkannt.")
                return "Could not identify location dropdown", None, False

            h_loc, w_loc = template_upper_left.shape
            top_left = (max_loc_label[0] - 60, max_loc_label[1] + h_loc) # lower left corner, 60 pixel more to the left

            h_action, w_action = template_lower_right.shape
            bottom_right = (max_loc_action[0], max_loc_action[1] + h_action)

            print_debug(f"cropping for location name: ({top_left[0]}, {top_left[1]}) -> ({bottom_right[0]}, {bottom_right[1]})")
            # Crop the screenshot
            cropped_screenshot_exact = cropped_screenshot[
                top_left[1] : bottom_right[1], top_left[0] : bottom_right[0]
            ]

            self.__debug_show_screenshot(cropped_screenshot_exact)
            # Prüfen, ob das zugeschnittene Bild leer ist
            if cropped_screenshot_exact.size == 0:
                print("Ungültige Region identifiziert.")
                return "Could not extract location name, invalid region.", None, False

            # Preprocess the cropped screenshot for better OCR results
            preprocessed_cropped_screenshot = self._preprocess_image(cropped_screenshot_exact)

            # Convert preprocessed cropped image to PIL format for pytesseract
            preprocessed_cropped_screenshot_pil = Image.fromarray(
                preprocessed_cropped_screenshot
            )

            # Extract text using pytesseract
            text = pytesseract.image_to_string(preprocessed_cropped_screenshot_pil)
            # print_debug(text)
            # print_debug("---------------------")
            return text, preprocessed_cropped_screenshot_pil, True
        except Exception:
            traceback.print_exc()
            return "Error during price analysis. Check console", None, False

    def _adjust_gamma(self, image, gamma=1.0):
        inv_gamma = 1.0 / gamma
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]
        ).astype("uint8")
        return cv2.LUT(image, table)

    def _analyze_histogram(self, image):
        # Konvertierung in Graustufen (falls erforderlich)
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Berechnung des Histogramms
        histogram = cv2.calcHist([gray], [0], None, [256], [0, 256])

        bright_spots = np.sum(histogram[200:])

        # Analyse des Histogramms (z.B. Durchschnittswert, Spitzenwert)
        avg_brightness = np.mean(image)
        peak_brightness = np.argmax(histogram)

        return avg_brightness, peak_brightness, bright_spots

    def _apply_clahe(self, image, clip_limit=2.0, tile_grid_size=(8, 8)):
        # Konvertierung in Graustufen (falls erforderlich)
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Erstellung des CLAHE-Objekts
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
        # Anwendung von CLAHE auf das Graustufenbild
        equalized = clahe.apply(gray)

        return equalized

    def _get_price_information(self, gray_screenshot, operation, validated_tradeport):
        """Analyze the screenshot and extract text."""

        try:
            top_left_x = self.config["uex_data_runner"]["tradeport_kiosks"]["commodity_price_area"]["top_left_x"]
            top_left_y = self.config["uex_data_runner"]["tradeport_kiosks"]["commodity_price_area"]["top_left_y"]
            bottom_right_x = self.config["uex_data_runner"]["tradeport_kiosks"]["commodity_price_area"]["bottom_right_x"]
            bottom_right_y = self.config["uex_data_runner"]["tradeport_kiosks"]["commodity_price_area"]["bottom_right_y"]
            commodities_screenshot_area = gray_screenshot[
                top_left_y : bottom_right_y, top_left_x : bottom_right_x
            ]

            filename = f"{self.data_dir_path}/template_kiosk_buy_button_{self.best_template_index}.png"        
            buy_button_template = cv2.imread(filename, 0)

            # We always take the buy button to recognize the commodity prices area
            res_buy_button = cv2.matchTemplate(
                commodities_screenshot_area, buy_button_template, cv2.TM_CCOEFF_NORMED
            )
            _, max_val_button, _, max_loc_button = cv2.minMaxLoc(res_buy_button)
            threshold = 0.5

            if max_val_button < threshold:
                return "Could not identify buy button. Reposition yourself.", False
            
            h_button, w_button = buy_button_template.shape[:2]

            # Breite und Höhe des Buy-Button Templates

            # Berechne den Ausschnitt ab der unteren linken Ecke des gefundenen Templates
            x_start = max_loc_button[0]
            y_start = max_loc_button[1] + h_button

            # print_debug(f'cropping at ({x_start},{y_start})')

            commodities_screenshot_area = commodities_screenshot_area[y_start:, x_start:]
            # if max_val_bottom_right >= threshold:
            #     cropped_screenshot = gray_screenshot[y_start:y_end, x_start:x_end]

            self.__debug_show_screenshot(commodities_screenshot_area)
            # Dateinamen mit Zeitstempel erstellen
            filename = f'{self.screenshots_path}/cropped_screenshot_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.png'
            cv2.imwrite(filename, commodities_screenshot_area)
        except Exception:
            traceback.print_exc()
            return "Exception", False
        
        prices_raw, success = self._get_screenshot_texts(commodities_screenshot_area, operation, validated_tradeport)
        return prices_raw, commodities_screenshot_area, success

        # self.debug_show_screenshot(cropped_screenshot)

        # # Berechne die durchschnittliche Helligkeit und die Spitze des Histogramms
        # avg_brightness, peak_brightness, bright_spots = self.analyze_histogram(
        #     cropped_screenshot
        # )
        # print_debug(
        #     f"avg_brightness: {avg_brightness}, peak_brightness: {peak_brightness}, bright_spots: {bright_spots}"
        # )

        # # Überprüfung der Helligkeit und des Histogramms
        # if bright_spots > 25000:
        #     # if avg_brightness <70 and peak_brightness < 30:
        #     #     adjusted_image = cropped_screenshot
        #     # el
        #     if bright_spots > 60000:
        #         # nur wenn das bild auch insgesamt zu hell ist wird eine gamma korrektur möglicherweise helfen
        #         # Helle Strahlen im Bild, wende Gamma-Korrektur an
        #         gamma = 2
        #         adjusted_image = self.adjust_gamma(cropped_screenshot, gamma=gamma)
        #         print_debug(f"Bright spots detected, applying gamma correction {gamma}")
        #     else:
        #         gamma = 1.5
        #         adjusted_image = self.adjust_gamma(cropped_screenshot, gamma=gamma)
        #         print_debug(f"Bright spots detected, applying gamma correction {gamma}")

        # elif avg_brightness < 50 and peak_brightness < 30:
        #     # Dunkles Bild, wende CLAHE an
        #     adjusted_image = self.apply_clahe(cropped_screenshot)
        #     print_debug("image very dark, applying clahe")
        # elif avg_brightness > 75 and peak_brightness > 50:
        #     # Helles Bild, wende Gamma-Korrektur an
        #     gamma = 1.4
        #     adjusted_image = self.adjust_gamma(cropped_screenshot, gamma=gamma)
        #     print_debug(f"image very bright, applying gamma correction {gamma}")
        # else:
        #     # Bild hat akzeptable Helligkeit
        #     adjusted_image = cropped_screenshot

        # self.debug_show_screenshot(adjusted_image)

        # # Adaptive Schwellenwertbildung
        # adaptive_thresh = cv2.adaptiveThreshold(
        #     adjusted_image,
        #     255,
        #     cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        #     cv2.THRESH_BINARY,
        #     17,
        #     7,
        # )
        # self.debug_show_screenshot(adaptive_thresh)

        # # # Gaußsche Weichzeichnung anwenden
        # # blurred_screenshot = cv2.GaussianBlur(adaptive_thresh, (3, 3), 1)
        # # self.debug_show_screenshot(blurred_screenshot)

        # # # Canny-Kantendetektion anwenden
        # # edges = cv2.Canny(blurred_screenshot, 150, 200)

        # # self.debug_show_screenshot(edges)

        # # return

        # processed_image = adaptive_thresh

        # # # Morphologische Operationen
        # # kernel = np.ones((2, 2), np.uint8)
        # # img_dilated = cv2.dilate(adaptive_thresh, kernel, iterations=4)
        # # img_eroded = cv2.erode(img_dilated, kernel, iterations=4)

        # # self.debug_show_screenshot(img_dilated)
        # # self.debug_show_screenshot(img_eroded)

        # # Template Matching für das obere Template
        # res_upper = cv2.matchTemplate(
        #     processed_image,
        #     self.template_kiosk_commodity_upper_left,
        #     cv2.TM_CCOEFF_NORMED,
        # )
        # _, max_val_upper, _, max_loc_upper = cv2.minMaxLoc(res_upper)
        # if max_val_upper < threshold:
        #     print("Erstes Template nicht erkannt.")
        #     return None, None

        # loc_left = np.where(res_upper >= threshold)

        # extracted_texts = []

        # # Höhe und Breite des oberen Templates
        # h_left, w_left = self.template_kiosk_commodity_upper_left.shape[:2]

        # # Höhe und Breite des unteren Templates
        # h_right, w_right = self.template_kiosk_commodity_bottom_right.shape[:2]

        # # Durch alle gefundenen Übereinstimmungen des oberen Templates iterieren
        # last_bottom_end_y = 0  # this value has to increase at least of the height of the template, otherwise, the template has matched multiple time
        # # the same region
        # for pt_left in zip(*loc_left[::-1]):
        #     # Bereich für das untere Template definieren
        #     bottom_start_x = pt_left[0] + w_left + 45
        #     bottom_start_y = pt_left[1]
        #     bottom_end_x = cropped_screenshot.shape[1]
        #     bottom_end_y = bottom_start_y + h_left + 10

        #     if bottom_end_y < last_bottom_end_y + h_left:
        #         continue

        #     last_bottom_end_y = bottom_end_y

        #     if DEBUG:
        #         print(
        #             f"start(x: {bottom_start_x}, y: {bottom_start_y}) -> (x: {bottom_end_x}, y: {bottom_end_y})"
        #         )

        #     # Sicherstellen, dass die Koordinaten innerhalb des Bildes liegen
        #     bottom_end_x = min(bottom_end_x, cropped_screenshot.shape[1])
        #     bottom_end_y = min(bottom_end_y, cropped_screenshot.shape[0])

        #     # Template Matching für das untere Template im Suchbereich
        #     bottom_roi = cropped_screenshot[
        #         bottom_start_y:bottom_end_y, bottom_start_x:bottom_end_x
        #     ]

        #     self.debug_show_screenshot(bottom_roi)

        #     # res_bottom = cv2.matchTemplate(bottom_roi, self.template_kiosk_commodity_bottom_right, cv2.TM_CCOEFF_NORMED)
        #     # _, max_val_bottom, _, max_loc_bottom = cv2.minMaxLoc(res_bottom)

        #     # if max_val_bottom < threshold:
        #     #     continue  # Keine Übereinstimmung für das untere Template gefunden

        #     # Textbereich extrahieren und OCR anwenden
        #     text = pytesseract.image_to_string(bottom_roi)
        #     extracted_texts.append(text)
    
    def __debug_show_screenshot(self, image):
        if not SHOW_SCREENSHOTS:
            return
        print_debug("displaying image, press Enter to continue")
        try:
            # Zeige den zugeschnittenen Bereich an
            cv2.imshow("Cropped Screenshot", image)
            while True:
                if cv2.waitKey(0) == 13:  # Warten auf die Eingabetaste (Enter)
                    break
            cv2.destroyAllWindows()
        except Exception:
            traceback.print_exc()
            print_debug("could not display image")
            return

    def _get_screenshot_texts(self, image, operation, validated_tradeport):

        try:

            if not TEST:

                pil_img = Image.fromarray(image)

                # Einen BytesIO-Buffer für das Bild erstellen
                buffered = BytesIO()

                # Das PIL-Bild im Buffer als JPEG speichern
                pil_img.save(buffered, format="JPEG")

                # Base64-String aus dem Buffer generieren
                img_str = base64.b64encode(buffered.getvalue()).decode()

                # client = OpenAI()

                # response = client.chat.completions.create(
                #     model="gpt-4-vision-preview",
                #     response_format={ "type": "json_object" },
                #     messages=[{
                #         "role": "user",
                #         "content": [
                #             {"type": "text", "text": "Give me the text within this image. Give me the response in a json object called image_data."},
                #             {
                #                 "type": "image_url",
                #                 "image_url": {"url": f"data:image/jpeg;base64,{img_str}"},
                #             },
                #         ],
                #     }],
                # )

                # Datei öffnen und lesen
                with open(f'{self.data_dir_path}/response_structure_{operation}.json', 'r') as file:
                    file_content = file.read()

                # JSON-String direkt verwenden
                json_string = file_content

                # # client = OpenAI()
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openai_api_key}",
                }
                payload = {
                    "model": "gpt-4-vision-preview",
                    #"response_format": { "type": "json_object" },  #  not supported on this model
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": (
                                    
                                    f"Give me the text within this image. Give me the response in a plain json object structured as defined in this example: {json_string}. Valid values for 'multiplier' are null, K or M. Do not provide '/Unit'. Provide the json within markdown ```json ... ```.If you are unable to process the image, just return 'error' as response.")
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{img_str}"},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1000,
                }

                self.overlay.display_overlay_text(f"Analysing screenshot for text extraction", display_duration=30000)
                print_debug("Calling openai vision for text extraction")
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=300
                )
                
                if DEBUG:
                    # Write JSON data to a file
                    filename = f'{self.data_dir_path}/debug_data/open_ai_full_response_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
                    with open(filename, 'w') as file:
                        json.dump(response.json(), file, indent=4)

                if response.status_code != 200:
                    print_debug(f'request error: {response.json()["error"]["type"]}. Check the file {filename} for details.')
                    return f"Error calling gpt vision. Check file 'commodity_prices_response_{operation}.json' for details", False
                
                message_content = response.json()["choices"][0]["message"]["content"]
            else:
                # Read JSON data from a file
                filename = f'{self.data_dir_path}/examples/{operation}/open_ai_full_response_{operation}_LVRID_None.json'
                with open(filename, 'r') as file:
                    message_content = json.load(file)["choices"][0]["message"]["content"]

            if "error" in json.dumps(message_content).lower():
                return f"Unable to analyse screenshot (maybe cropping error). {json.dumps(message_content)} ", False
            
            message_blocks = message_content.split("```")
            json_text = message_blocks[1]
            if json_text.startswith("json"):
                # Schneide die Länge des Wortes vom Anfang des Strings ab
                json_text =  json_text[len("json"):]
            print_debug(json_text)
            commodity_prices = json.loads(json_text)

            if DEBUG:
                filename = f'{self.data_dir_path}/debug_data/extracted_open_ai_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
                with open(filename, 'w') as file:
                    json.dump(commodity_prices, file, indent=4)

            return commodity_prices, True
        except BaseException:
            traceback.print_exc()
            return "Some exception raised during screenshot analysis", False