
import cv2
import numpy as np
from PIL import Image
import pytesseract

import wingmen.star_citizen_services.text_analyser as text_analyser

from wingmen.star_citizen_services.mission_manager import MissionManager
from wingmen.star_citizen_services.uex_api import UEXApi
from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.delivery_manager import PackageDeliveryPlanner
from wingmen.star_citizen_services.cargo_route_planner import CargoRoutePlanner
from wingmen.star_citizen_services.model.mission_location_information import MissionLocationInformation


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print_debug(to_print)

        
class TransportMissionAnalyzer:
    def __init__(self, payment_template_path, accept_offer_template_path):
        self.payment_template = cv2.imread(payment_template_path, 0)
        self.accept_offer_template = cv2.imread(accept_offer_template_path, 0)

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
        return text

    @staticmethod
    def testScreenshot():
        print_debug("test")
        # Initialize the analyzer with the path to the template images
        analyzer = TransportMissionAnalyzer('star_citizen_data/screenshots/template_payment.jpg', 'star_citizen_data/screenshots/template_accept_offer_2.jpg')

        # Analyze the provided screenshots
        screenshot_paths = [
            'star_citizen_data/screenshots/examples/mission_level1_3_2.jpg',
            'star_citizen_data/screenshots/examples/mission_level1_4_1.jpg'
        ]

        mission_manager = MissionManager()
        delivery_manager = PackageDeliveryPlanner()

        for path in screenshot_paths:
            screenshot_text = analyzer.analyze_screenshot(path)
            delivery_mission = text_analyser.TextAnalyzer.analyze_text(screenshot_text)
            # Usage example
            LocationNameMatching.validate_location_names(delivery_mission)
            mission_manager.add_mission(delivery_mission)
            delivery_manager.insert(delivery_mission)

        # ordered_delivery_locations: [MissionLocationInformation] = PackageDeliveryPlanner.sort(mission_manager.missions)
        
        # CargoRoutePlanner.finde_routes_for_delivery_missions(ordered_delivery_locations, tradeports_data)
			
        # Save the missions to a JSON file
        mission_manager.save_missions('star_citizen_data/screenshots/examples/missions.json')
