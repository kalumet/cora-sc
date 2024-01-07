import os
import datetime
import time
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

# import wingmen.star_citizen_services.text_analyser as text_analyser

from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.uex_update_service.commodity_price_validator import CommodityPriceValidator
from wingmen.star_citizen_services.uex_api import UEXApi


DEBUG = True
TEST = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class UexCommodityKioskAnalyser:
    def __init__(self, data_dir_path, openai_api_key):
        self.data_dir_path = f"{data_dir_path}/kiosk_analyzer"
        
        self.template_kiosk_buy_lower_right = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_buy_lower_right.png", 0
        )
        self.template_kiosk_buy_upper_left = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_buy_upper_left.png", 0
        )
        self.template_kiosk_location_lower_right = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_location_lower_right.png", 0
        )
        self.template_kiosk_location_upper_left = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_location_upper_left.png", 0
        )
        self.template_kiosk_sell_lower_right = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_sell_lower_right.png", 0
        )
        self.template_kiosk_sell_upper_left = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_sell_upper_left.png", 0
        )
        self.template_kiosk_sell_button = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_sell_button.png", 0
        )
        self.template_kiosk_buy_button = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_buy_button.png", 0
        )
        self.template_kiosk_commodity_upper_left = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_commodity_upper_left.png", 0
        )
        self.template_kiosk_commodity_bottom_right = cv2.imread(
            f"{self.data_dir_path}/template_kiosk_commodity_bottom_right.png", 0
        )

        self.screenshots_path = f"{self.data_dir_path}/screenshots"
        self.uex_service = UEXApi()
        self.openai_api_key = openai_api_key

        if not os.path.exists(self.screenshots_path):
            os.makedirs(self.screenshots_path)

    def identify_kiosk_prices(self):
        operation = "buy"
        screenshot_file_name = self.take_screenshot(operation)

        if not screenshot_file_name:
            return False

        location_name, success = self.get_location_name(screenshot_file_name)

        if not success:
            return {"success": False, 
                    "instructions": "You cannot analyse the commodity terminal, as something is obstructing your view. The player should reposition himself to avoid bright spots on the terminal and stand in front of the terminal.", 
                    "message": location_name
                    }

        print_debug(f"got raw location name: {location_name}")

        validated_tradeport, success = LocationNameMatching.validate_tradeport_name(location_name)

        if not success:
            return {"success": False, 
                    "instructions": "You cannot identify at which tradeport the user is. He must select the tradeport in the commidity terminal and repeat the command.", 
                    "message": validated_tradeport
                    }
        
        print_debug(f'validated location name: {validated_tradeport["name_short"]}')

        buy_result = self._analyse_prices_at_tradeport(screenshot_file_name, validated_tradeport, operation)

        if not TEST and not buy_result["success"]:
            return buy_result
        
        operation = "sell"
        self._click_sell_button(screenshot_file_name)

        sell_screenshot_filename = self.take_screenshot(operation)

        sell_result = self._analyse_prices_at_tradeport(sell_screenshot_filename, validated_tradeport, operation)

        if not sell_result["success"]:
            buy_result["success"] = False
            
        buy_result['message']['sellable_commodities_info'] = sell_result['message']['sellable_commodities_info']
            
        return buy_result
        
    def _click_sell_button(self, screenshot_file_name):
        # first, get the coordinates of the sell button in the screen
        screenshot = cv2.imread(screenshot_file_name)
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        
        # Template matching for accept offer template
        sell_button_position = cv2.matchTemplate(gray_screenshot, self.template_kiosk_sell_button, cv2.TM_CCOEFF_NORMED)
        _, _, _, sell_button_coordinates = cv2.minMaxLoc(sell_button_position)
        
        active_window = pygetwindow.getActiveWindow()
        if active_window:
            # Speichere die aktuelle Position der Maus
            original_mouse_x, original_mouse_y = pyautogui.position()

            # Fensterposition bestimmen
            window_x, window_y = active_window.left, active_window.top

            # Templategröße ermitteln
            template_height, template_width = self.template_kiosk_sell_button.shape[:2]

            # Berechne die absolute Mitte des Templates
            absolute_x = window_x + sell_button_coordinates[0] + template_width // 2
            absolute_y = window_y + sell_button_coordinates[1] + template_height // 2

            # Bewege die Maus langsam zur Zielposition
            pyautogui.moveTo(absolute_x, absolute_y, duration=0.2)

            # Verzögerung vor dem Klick
            time.sleep(0.1)

            # Führe den Klick aus mit einer längeren Klickdauer
            pyautogui.mouseDown()
            time.sleep(0.1)  # Halte die Maustaste 0.1 Sekunden lang gedrückt
            pyautogui.mouseUp()

            # Setze die Mausposition auf die ursprüngliche Position zurück
            pyautogui.moveTo(original_mouse_x, original_mouse_y, duration=0.2)
     
    def _analyse_prices_at_tradeport(self, screen_shot_path, validated_tradeport, operation):
        
        prices_raw, success = self._get_price_information(screen_shot_path, operation)

        if not success:
            return {"success": False, 
                    "instructions": "You cannot analyse the commodity data, as something is obstructing your view. The player should reposition himself to avoid bright spots on the terminal and stand in front of the terminal.", 
                    "message": prices_raw
                    }
        
        number_of_extracted_prices = len(prices_raw["commodity_prices"])

        print_debug(f"extracted {number_of_extracted_prices} price-informations from screenshot")

        validated_prices, success = CommodityPriceValidator.validate_price_information(prices_raw, validated_tradeport, operation)

        if not success:
            return {"success": False, 
                    "instructions": "You couldn't identify the commodities and prices. Instruct the user to analyse the log files.", 
                    "message": validated_prices
                    }
        
        number_of_validated_prices = len(validated_prices)

        print_debug(f"{number_of_validated_prices} prices are valid")

        if number_of_validated_prices == 0:
            return {"success": False, 
                    "instructions": "You have made errors in recognizing the correct prices on the terminal and all have been rejected.", 
                    "message": "Could not identify commodity names or prices are not within 20% of allowed tollerance to current prices"
                    }
        
        # Write JSON data to a file
        json_file_name = f'{self.data_dir_path}/debug_data/commodity_prices_validated_response_{operation}.json'
        with open(json_file_name, 'w') as file:
            json.dump(validated_prices, file, indent=4)
        
        updated_commodities = []
        update_errors = []

        for validated_price in validated_prices:
            response, success = self.uex_service.update_tradeport_price(tradeport=validated_tradeport, commodity_update_info=validated_price, operation=operation)

            if not success:
                print_debug(f'price could not be updated: {response}')
                update_errors.append(response)
                continue

            print_debug(f'price successfully updated')
            updated_commodities.append(response)
        
        success = False
        if len(updated_commodities) > 0:
            success = True
        
        return {
                    "success": success,
                    "instructions": "You where able to recognize the commodities and tried to transmit the prices to the uex corp. Provide a short summary, especially, not all prices could be identified, or if there have been transmission errors. ",
                    "message": {
                        "tradeport": validated_tradeport["name"],
                        f"{operation}able_commodities_info": {
                            "identified": number_of_extracted_prices,
                            "valid": number_of_validated_prices,
                            "transmitted_to_uex": len(updated_commodities),
                            "transmission_errors": len(update_errors)
                        }
                    }
                }

        # filename = self.take_screenshot("sell")

        # screenshot_text = self.get_price_information(filename)

        # if not screenshot_text:
        #     return None

        # if DEBUG:
        #     for text in screenshot_text:
        #         print(text)

        # delivery_mission = text_analyser.TextAnalyzer.analyze_text(screenshot_text)

        # if not delivery_mission or len(delivery_mission.packages) == 0:
        #     return None

        # LocationNameMatching.validate_location_names(delivery_mission)

        # if not TEST:
        #     self.accept_mission_click(accept_button_coordinates)

        # print_debug(delivery_mission)
        # return delivery_mission

    def accept_mission_click(self, accept_button_coordinates):
        active_window = pygetwindow.getActiveWindow()
        if active_window:
            # Speichere die aktuelle Position der Maus
            original_mouse_x, original_mouse_y = pyautogui.position()

            # Fensterposition bestimmen
            window_x, window_y = active_window.left, active_window.top

            # Templategröße ermitteln
            template_height, template_width = self.accept_offer_template.shape[:2]

            # Berechne die absolute Mitte des Templates
            absolute_x = window_x + accept_button_coordinates[0] + template_width // 2
            absolute_y = window_y + accept_button_coordinates[1] + template_height // 2

            # Bewege die Maus langsam zur Zielposition
            pyautogui.moveTo(absolute_x, absolute_y, duration=0.2)

            # Verzögerung vor dem Klick
            time.sleep(0.1)

            # Führe den Klick aus mit einer längeren Klickdauer
            pyautogui.mouseDown()
            time.sleep(0.1)  # Halte die Maustaste 0.1 Sekunden lang gedrückt
            pyautogui.mouseUp()

            # Setze die Mausposition auf die ursprüngliche Position zurück
            pyautogui.moveTo(original_mouse_x, original_mouse_y, duration=0.2)

    def take_screenshot(self, operation):
        if TEST:
            return self.random_image_from_directory(operation)

        active_window = pygetwindow.getActiveWindow()
        if active_window and "Star Citizen" in active_window.title:
            # Aktuellen Zeitpunkt erfassen
            now = datetime.datetime.now()
            timestamp = now.strftime(
                "%Y%m%d_%H%M%S_%f"
            )  # Format: JahrMonatTag_StundeMinuteSekunde_Millisekunden

            # Dateinamen mit Zeitstempel erstellen
            filename = f"{self.screenshots_path}/screenshot_{timestamp}.png"

            # Fensterposition und -größe bestimmen
            x, y, width, height = (
                active_window.left,
                active_window.top,
                active_window.width,
                active_window.height,
            )
            # Screenshot des bestimmten Bereichs machen
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            screenshot.save(filename)
            return filename
        return None

    def random_image_from_directory(self, operation):
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
        return os.path.join(directory, random.choice(images))

    def preprocess_image(self, image):
        """Preprocess the image for better OCR results."""
        # Apply color range filtering for grayscale image
        lower_bound = np.array([185])  # Lower bound for grayscale
        upper_bound = np.array([255])  # Upper bound for grayscale
        mask = cv2.inRange(image, lower_bound, upper_bound)
        result = cv2.bitwise_and(image, image, mask=mask)

        # Apply dilate and erode
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (1, 1))
        dilated = cv2.dilate(result, kernel, iterations=3)
        eroded = cv2.erode(dilated, kernel, iterations=3)

        return eroded

    def get_location_name(self, screenshot_path):
        """Analyze the screenshot and extract text."""
        try:
            # Load the screenshot for analysis
            screenshot = cv2.imread(screenshot_path)
            if screenshot is None:
                raise FileNotFoundError(
                    f"Die Bilddatei wurde nicht gefunden: {screenshot_path}"
                )
            gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
            self.debug_show_screenshot(gray_screenshot)

            # Schwellenwert für die Übereinstimmung
            threshold = 0.5

            # Template matching for payment template
            result_location_drop_down_label = cv2.matchTemplate(
                gray_screenshot,
                self.template_kiosk_location_upper_left,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_val_label, _, max_loc_label = cv2.minMaxLoc(
                result_location_drop_down_label
            )

            if max_val_label < threshold:
                print("Erstes Template nicht erkannt.")
                return "Could not identify location dropdown", False

            location_drop_down_action = cv2.matchTemplate(
                gray_screenshot,
                self.template_kiosk_location_lower_right,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_val_action, _, max_loc_action = cv2.minMaxLoc(location_drop_down_action)

            if max_val_action < threshold:
                print("Zweites Template nicht erkannt.")
                return "Could not identify location dropdown", False

            h_loc, w_loc = self.template_kiosk_location_upper_left.shape
            top_left = (max_loc_label[0], max_loc_label[1] + h_loc)

            h_action, w_action = self.template_kiosk_location_lower_right.shape
            bottom_right = (max_loc_action[0], max_loc_action[1] + h_action)

            print_debug(f"cropping for location name: ({top_left[0]}, {top_left[1]}) -> ({bottom_right[0]}, {bottom_right[1]})")
            # Crop the screenshot
            cropped_screenshot = gray_screenshot[
                top_left[1] : bottom_right[1], top_left[0] : bottom_right[0]
            ]
            # Prüfen, ob das zugeschnittene Bild leer ist
            if cropped_screenshot.size == 0:
                print("Ungültige Region identifiziert.")
                return "Could not extract location name, invalid region.", False

            # Preprocess the cropped screenshot for better OCR results
            preprocessed_cropped_screenshot = self.preprocess_image(cropped_screenshot)

            # Convert preprocessed cropped image to PIL format for pytesseract
            preprocessed_cropped_screenshot_pil = Image.fromarray(
                preprocessed_cropped_screenshot
            )

            # Extract text using pytesseract
            text = pytesseract.image_to_string(preprocessed_cropped_screenshot_pil)
            # print_debug(text)
            # print_debug("---------------------")
            return text, True
        except Exception:
            traceback.print_exc()

    def adjust_gamma(self, image, gamma=1.0):
        inv_gamma = 1.0 / gamma
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]
        ).astype("uint8")
        return cv2.LUT(image, table)

    def analyze_histogram(self, image):
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

    def apply_clahe(self, image, clip_limit=2.0, tile_grid_size=(8, 8)):
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

    def _get_price_information(self, screenshot_path, operation):
        """Analyze the screenshot and extract text."""
        # Screenshot laden
        print_debug(f"file: {screenshot_path}")
        screenshot = cv2.imread(screenshot_path)
        if screenshot is None:
            raise FileNotFoundError(
                f"Die Bilddatei wurde nicht gefunden: {screenshot_path}"
            )
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        
        # We always take the buy button to recognize the commodity prices area
        res_buy_button = cv2.matchTemplate(
            gray_screenshot, self.template_kiosk_buy_button, cv2.TM_CCOEFF_NORMED
        )
        _, max_val_button, _, max_loc_button = cv2.minMaxLoc(res_buy_button)
        threshold = 0.5

        if max_val_button < threshold:
            return "Could not identify buy button. Reposition yourself.", False

        # Breite und Höhe des Buy-Button Templates
        h_button, w_button = self.template_kiosk_buy_button.shape[:2]

        # Berechne den Ausschnitt ab der unteren linken Ecke des gefundenen Templates
        x_start = max(max_loc_button[0] - 150, 0)
        y_start = max_loc_button[1] + h_button

        cropped_screenshot = gray_screenshot[y_start:, x_start:]

        self.debug_show_screenshot(cropped_screenshot)

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

        prices_raw, success = self._get_screenshot_texts(cropped_screenshot, operation)
        return prices_raw, success

    def debug_show_screenshot(self, image):
        if not DEBUG:
            return
        # Zeige den zugeschnittenen Bereich an
        cv2.imshow("Cropped Screenshot", image)
        while True:
            if cv2.waitKey(0) == 13:  # Warten auf die Eingabetaste (Enter)
                break
        cv2.destroyAllWindows()

    def _get_screenshot_texts(self, image, operation):

        try:

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
                                
                                f"Give me the text within this image. Give me the response in a plain json object structured as defined in this example: {json_string}")
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

            response = requests.post(
                "https://api.openai.com/v1/chat/completions", headers=headers, json=payload
            )
            
            # Write JSON data to a file
            filename = f'{self.data_dir_path}/debug_data/commodity_prices_raw_response_{operation}.json'
            with open(filename, 'w') as file:
                json.dump(response.json(), file, indent=4)

            if response.status_code != 200:
                print_debug(f'request error: {response.json()["error"]["type"]}. Check the file {filename} for details.')
                return f"Error calling gpt vision. Check file 'commodity_prices_response_{operation}.json' for details", False
            message_content = response.json()["choices"][0]["message"]["content"]
            
            message_content = message_content.strip("`")
            if message_content.startswith("json"):
                # Schneide die Länge des Wortes vom Anfang des Strings ab
                message_content =  message_content[len("json"):]
            print_debug(message_content)
            commodity_prices = json.loads(message_content)

            filename = f'{self.data_dir_path}/debug_data/commodity_prices_{operation}.json'
            with open(filename, 'w') as file:
                json.dump(commodity_prices, file, indent=4)

            return commodity_prices, True
        except BaseException as e:
            filename = f'{self.data_dir_path}/debug_data/commodity_prices_exception_{operation}.txt'
            print_debug(f"Unspecified error, check file 'commodity_prices_exception_{operation}.txt'")
            traceback.print_exception(type(e), value=e, tb=e.__traceback__, limit=3, file=filename)
            return f"Some exception raised, check file 'commodity_prices_exception_{operation}.txt'", False

