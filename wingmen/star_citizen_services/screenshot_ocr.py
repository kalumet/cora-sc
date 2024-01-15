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

import wingmen.star_citizen_services.text_analyser as text_analyser

from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.overlay import StarCitizenOverlay


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class TransportMissionAnalyzer:
    def __init__(self, upper_left_template, lower_right_template, data_dir_path):
        self.payment_template = cv2.imread(upper_left_template, 0)
        self.accept_offer_template = cv2.imread(lower_right_template, 0)
        self.data_dir_path = data_dir_path
        self.screenshots_path = f'{self.data_dir_path}/screenshots'

        self.overlay = StarCitizenOverlay()

        if not os.path.exists(self.screenshots_path):
            os.makedirs(self.screenshots_path)

    def identify_mission(self):

        self.overlay.display_overlay_text("Analyising delivery mission data now.", vertical_position_ratio=8)
        time.sleep(10)
        filename = self.take_screenshot()

        if not filename:
            return None

        screenshot_text, accept_button_coordinates = self.analyze_screenshot(filename)
        print_debug(f"screenshot text: {screenshot_text}")
        delivery_mission = text_analyser.TextAnalyzer.analyze_text(screenshot_text)

        if not delivery_mission or len(delivery_mission.packages) == 0:
            return None

        LocationNameMatching.validate_location_names(delivery_mission)

        print_debug(delivery_mission)
        return delivery_mission

    # def accept_mission_click(self, accept_button_coordinates):
    #     active_window = pygetwindow.getActiveWindow()
    #     if active_window:
    #         # Speichere die aktuelle Position der Maus
    #         original_mouse_x, original_mouse_y = pyautogui.position()

    #         # Fensterposition bestimmen
    #         window_x, window_y = active_window.left, active_window.top

    #         # Templategröße ermitteln
    #         template_height, template_width = self.accept_offer_template.shape[:2]

    #         # Berechne die absolute Mitte des Templates
    #         absolute_x = window_x + accept_button_coordinates[0] + template_width // 2
    #         absolute_y = window_y + accept_button_coordinates[1] + template_height // 2

    #        # Bewege die Maus langsam zur Zielposition
    #         pyautogui.moveTo(absolute_x, absolute_y, duration=0.2)

    #         # Verzögerung vor dem Klick
    #         time.sleep(0.1)

    #         # Führe den Klick aus mit einer längeren Klickdauer
    #         pyautogui.mouseDown()
    #         time.sleep(0.1)  # Halte die Maustaste 0.1 Sekunden lang gedrückt
    #         pyautogui.mouseUp()

    #         # Setze die Mausposition auf die ursprüngliche Position zurück
    #         pyautogui.moveTo(original_mouse_x, original_mouse_y, duration=0.2)
    
    def take_screenshot(self):
        if TEST:
            return self.random_image_from_directory()
        
        active_window = pygetwindow.getActiveWindow()
        if active_window and "Star Citizen" in active_window.title:
            # Aktuellen Zeitpunkt erfassen
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S_%f")  # Format: JahrMonatTag_StundeMinuteSekunde_Millisekunden

            # Dateinamen mit Zeitstempel erstellen
            filename = f'{self.screenshots_path}/screenshot_{timestamp}.png'

            # Fensterposition und -größe bestimmen
            x, y, width, height = active_window.left, active_window.top, active_window.width, active_window.height
            # Screenshot des bestimmten Bereichs machen
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            screenshot.save(filename)
            return filename
        return None

    def random_image_from_directory(self):
        """
        Selects a random image from a specified directory.

        Args:
        directory (str): Path to the directory containing images.
        image_extensions (list, optional): List of acceptable image file extensions.

        Returns:
        str: Path to a randomly selected image.
        """
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        directory = f'{self.data_dir_path}/examples'
        # List all files in the directory
        files = os.listdir(directory)

        # Filter files to get only those with the specified extensions
        images = [file for file in files if any(file.endswith(ext) for ext in image_extensions)]

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

    def analyze_screenshot(self, screenshot_path):
        """Analyze the screenshot and extract text."""
        # Load the screenshot for analysis
        screenshot = cv2.imread(screenshot_path)
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        # Template matching for payment template
        result_payment = cv2.matchTemplate(gray_screenshot, self.payment_template, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc_payment = cv2.minMaxLoc(result_payment)

        # Template matching for accept offer template
        result_offer = cv2.matchTemplate(gray_screenshot, self.accept_offer_template, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc_offer = cv2.minMaxLoc(result_offer)

        # Define the crop area using both templates
        top_left = max_loc_payment
        h_offer, w_offer = self.accept_offer_template.shape
        bottom_right = (max_loc_offer[0] + w_offer, max_loc_offer[1] + h_offer)

        # Crop the screenshot
        cropped_screenshot = gray_screenshot[top_left[1]:bottom_right[1], top_left[0]:bottom_right[0]]

        # Preprocess the cropped screenshot for better OCR results
        preprocessed_cropped_screenshot = self.preprocess_image(cropped_screenshot)

        # Convert preprocessed cropped image to PIL format for pytesseract
        preprocessed_cropped_screenshot_pil = Image.fromarray(preprocessed_cropped_screenshot)

        # Extract text using pytesseract
        text = pytesseract.image_to_string(preprocessed_cropped_screenshot_pil)
        # print_debug(text)
        # print_debug("---------------------")
        return text, max_loc_offer