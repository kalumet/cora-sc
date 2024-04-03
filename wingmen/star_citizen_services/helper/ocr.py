import os
import datetime
import base64
from io import BytesIO
import json
import traceback

import cv2
from PIL import Image
import requests

from wingmen.star_citizen_services.overlay import StarCitizenOverlay


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class OCR:
    def __init__(self, data_dir, openai_api_key, extraction_instructions, overlay:StarCitizenOverlay):
        self.extraction_instructions = extraction_instructions
        self.data_dir = data_dir
        self.openai_api_key = openai_api_key
        self.overlay = overlay

    def get_screenshot_texts(self, image, *subdirectories, **filename_placeholders):

        screenshot = cv2.imread(image)
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        subdir_path = "/".join(subdirectories)
        # Process placeholders in the filename
        placeholder_part = "_".join(f"{key}-{value}" for key, value in filename_placeholders.items())

        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")  # Format: YearMonthDay_HourMinuteSecond_Milliseconds

        try:

            if not TEST:

                pil_img = Image.fromarray(gray_screenshot)

                # Einen BytesIO-Buffer für das Bild erstellen
                buffered = BytesIO()

                # Das PIL-Bild im Buffer als JPEG speichern
                pil_img.save(buffered, format="JPEG")

                # Base64-String aus dem Buffer generieren
                img_str = base64.b64encode(buffered.getvalue()).decode()

                # client = OpenAI()
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
                                    
                                    f"{self.extraction_instructions}")
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
                    # Format the path for subdirectories correctly
                                            
                    path = os.path.join(self.data_dir, 'debug_data', subdir_path)

                    if not os.path.exists(path):
                        os.makedirs(path)

                    # Create the full path and filename
                    filename = f"open_ai_full_response_{placeholder_part}_{timestamp}.json"
                    full_path = os.path.normpath(os.path.join(path, filename))
                    # Write JSON data to a file
                    with open(full_path, 'w', encoding="UTF-8") as file:
                        json.dump(response.json(), file, indent=4)

                if response.status_code != 200:
                    print_debug(f'request error: {response.json()["error"]["type"]}. Check the file {filename} for details.')
                    return "Error calling gpt vision.", False
                
                message_content = response.json()["choices"][0]["message"]["content"]
            else:
                # Read JSON data from a file
                path = os.path.join(self.data_dir, 'examples', subdir_path)
                if not os.path.exists(path):
                    os.makedirs(path)

                filename = f'open_ai_full_response_{placeholder_part}.json'
                full_path = os.path.normpath(os.path.join(path, filename))
                with open(full_path, 'r', encoding="UTF-8") as file:
                    message_content = json.load(file)["choices"][0]["message"]["content"]

            if "error" in json.dumps(message_content).lower():
                return f"Unable to analyse screenshot (maybe cropping error). {json.dumps(message_content)} ", False
            
            message_blocks = message_content.split("```")
            json_text = message_blocks[1]
            if json_text.startswith("json"):
                # Schneide die Länge des Wortes vom Anfang des Strings ab
                json_text = json_text[len("json"):]
            print_debug(json_text)
            retrieved_text = json.loads(json_text)

            if DEBUG:
                path = os.path.join(self.data_dir, 'debug_data', subdir_path)
                if not os.path.exists(path):
                    os.makedirs(path)

                filename = f'extracted_open_ai_text_{placeholder_part}_{timestamp}.json'
                full_path = os.path.normpath(os.path.join(path, filename))
                with open(full_path, 'w', encoding="UTF-8") as file:
                    json.dump(retrieved_text, file, indent=4)

            return retrieved_text, True
        except BaseException:
            traceback.print_exc()
            return "Some exception raised during screenshot analysis", False
