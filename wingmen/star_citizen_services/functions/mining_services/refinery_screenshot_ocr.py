import os
import base64
from io import BytesIO
import json
import traceback
from PIL import Image
import requests

from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.helper import screenshots


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class RefineryWorkOrderAnalyzer:
    def __init__(self, data_dir_path, openai_api_key):
        self.data_dir_path = data_dir_path
        self.openai_api_key = openai_api_key

        self.overlay = StarCitizenOverlay()
    
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