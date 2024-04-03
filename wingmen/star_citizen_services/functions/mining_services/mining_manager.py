import json
import os
import traceback

from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.helper import screenshots, find_best_match, convert_to_minutes
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.functions.mining_services.refinery_screenshot_ocr import RefineryWorkOrderAnalyzer
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.uex_v2 import uex_api_module


DEBUG = True
TEST = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MiningManager(FunctionManager):
    """  
        This is an example implementation structure that can be copy pasted for new managers.
    """
    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        # do further initialisation steps here

        self.config = config
        self.mining_data_path = f'{self.config["data-root-directory"]}/mining-data'
        self.mining_file_path = f'{self.mining_data_path}/active-refinery-jobs.json'

        self.active_work_orders = {}

        self.openai_api_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False
        )
        self.uex2_api_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="uex2_api_key",
            friendly_key_name="UEX2 API key",
            prompt_if_missing=True
        )
        self.uex2_secret_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="uex2_secret_key",
            friendly_key_name="UEX2 secret user key",
            prompt_if_missing=True
        )
        self.uex2_service = UEXApi2.init(
            uex_api_key=self.uex2_api_key,
            user_secret_key=self.uex2_secret_key
        )

        self.refinery_terminal_analyzer = RefineryWorkOrderAnalyzer(
            data_dir_path=self.mining_data_path,
            openai_api_key=self.openai_api_key
        )

        self.refineries = self.uex2_service.get_refineries()
        self.refinery_methods = self.uex2_service.get_data(uex_api_module.CATEGORY_REFINERY_METHODS)
        commodities = self.uex2_service.get_data(uex_api_module.CATEGORY_COMMODITIES)
        self.ores = {key: value for key, value in commodities.items() if value.get('is_raw') == 1}

        self.refinery_names = [details["space_station_name"] for details in self.refineries.values() if "space_station_name" in details]
        
        self.overlay = StarCitizenOverlay()

        with open(f'{self.mining_data_path}/examples/response_structure_refinery.json', 'r', encoding="UTF-8") as file:
            file_content = file.read()

        # JSON-String direkt verwenden
        json_string = file_content   

        self.ocr = OCR(
            openai_api_key=self.openai_api_key, 
            data_dir=self.mining_data_path,
            extraction_instructions=f"Give me the text within this image. Give me the response in a plain json object structured as defined in this example: {json_string}. Provide the json within markdown ```json ... ```.If you are unable to process the image, just return 'error' as response.",
            overlay=self.overlay)

        # # we always load from file, as we might restart wingmen.ai indipendently from star citizen
        # # TODO need to check on start, if we want to discard this mission
        # self.load_missions()
        # self.load_delivery_route()

        # self.mission_started = False
        # self.current_delivery_location = None
      
    # @abstractmethod - overwritten
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to. This means, that this function will only be callable if the current context matches the defined context here.
        """
        return AIContext.CORA    
    
    # @abstractmethod - overwritten
    def register_functions(self, function_register):
        """  
            You register method(s) that can be called by openAI.
        """
        function_register[self.refinery_work_order_management.__name__] = self.refinery_work_order_management
        # function_register[self.get_first_or_next_location_on_delivery_route.__name__] = self.get_first_or_next_location_on_delivery_route
    
    # @abstractmethod - overwritten
    def get_function_prompt(self) -> str:      
        """  
            Here you can provide instructions to open ai on how to use this function. 
        """
        return (
            f"You are able to manage refinery work orders. The following functions allow you to help the player in this task: "
            f"- {self.refinery_work_order_management.__name__}: call it to add 1, remove 1 or retrieve all refinery work order. "
            # f"  This function will return all available and registered mission ids that you will need for further requests. "
            # f"- {self.get_first_or_next_location_on_delivery_route.__name__}: get information about the next location the user should go. "
        )
    
    # @abstractmethod - overwritten
    def get_function_tools(self) -> list[dict]:      
        """  
            This is the function definition for OpenAI, provided as a list of tool definitions:
            Location names (planet, moons, cities, tradeports / outposts) are given in the system context, 
            so no need to make reference to it here.
        """       
        tools = [
            {
                "type": "function",
                "function": {
                    "name": self.refinery_work_order_management.__name__,
                    "description": "Allows the player to add or remove a refinery work order, or to retrieve all active work order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["add_work_order", "remove_work_order", "get_all_work_orders", None]
                            },
                            "work_order_index": {
                                "type": "number",
                                "description": "The work order, the player wants to delete",
                            },
                            "confirm_deletion": {
                                "type": "string",
                                "description": "User confirmed deletion",
                                "enum": ["confirmed", "notconfirmed", None]
                            }
                        }
                    }
                }
            }
        ]

        return tools

    def refinery_work_order_management(self, function_args):
        work_order_index = function_args.get("work_order_index", None)
        confirmed_deletion = function_args.get("confirm_deletion", None)
        function_type = function_args["type"]
        printr.print(f'-> Refinery Management: {function_type}', tags="info")
        function_response = self.manage_work_order(type=function_type, work_order_index=work_order_index, confirmed_deletion=confirmed_deletion)
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response
    
    def manage_work_order(self, type="new", work_order_index=None, confirmed_deletion=None):
        if type == "add_work_order":
            image_path = screenshots.take_screenshot(self.mining_data_path, refinery="{refinery}")
            retrieved_json, success = self.ocr.get_screenshot_texts(image_path, "workorder", refinery="{refinery}")
            if not success:
                return {"success": False, "error": retrieved_json, "instructions": "Explain the player the reason for the work order not beeing able to be extracted. "}

            return self.add_work_order(retrieved_json)
        return "Ok"

    def add_work_order(self, work_order):
        station = work_order["work_order"]["station_name"]
        refinery, success = find_best_match.find_best_match(station, self.refineries, attribute="space_station_name")
        if not success:
            return f"Couldn't identify refinery from '{station}'."
        print_debug(f'matched refinery "{refinery["matched_value"]}" with confidence {refinery["score"]}')
        
        method = work_order["work_order"]["processing_selection_method"]
        refinery_method, success = find_best_match.find_best_match(
            method, 
            self.refinery_methods, 
            attribute="name")
        if not success:
            return f"Couldn't identify refinery method from '{method}'."

        uex_refinery_order = {
            "id_terminal": refinery["root_object"]["id"],
            "id_refinery_method": refinery_method["root_object"]["id"],
            "cost": work_order["work_order"]["total_cost"],
            "time_minutes": convert_to_minutes.convert_to_minutes(work_order["work_order"]["processing_time"]),
            "refinery_capacity": work_order["work_order"]["current_capacity"]
        }

        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.ores, attribute="name")
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            item = {
                "yield": material["yield"],
                "quantity": material["quantity"],
                "id_commodity": ore["root_object"]["id"]
            }
            materials.append(item)

        uex_refinery_order["items"] = materials

        return self.uex2_service.add_refinery_job(uex_refinery_order)

    def save_missions(self):
        """Save mission data to a file."""
        filename = self.mining_file_path
        with open(filename, 'w') as file:
            missions_data = {}
            for mission_id, mission in self.missions.items():
                mission_dict = mission.to_dict()
                
                # mission_dict = mission.__dict__.copy()
                mission_dict['packages'] = list(mission_dict['packages'])  # Convert set to list

                # Convert pickup and drop-off locations to a serializable format if needed
                # Depending on how they are stored, you might need similar conversion
                
                missions_data[mission_id] = mission_dict
            json.dump(missions_data, file, indent=3)

    def load_missions(self):
        """Load mission data from a file."""
        filename = self.mining_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for mid, mission_data in data.items():
                        print_debug(f"loading mission: {mission_data}")
                        mission = DeliveryMission()

                        # Grundlegende Attribute aktualisieren
                        mission.id = mission_data['id']
                        mission.revenue = mission_data['revenue']

                        # Sets und Listen rekonstruieren
                        mission.packages = set(mission_data['packages'])
                        
                        # Dictionaries für pickup und drop-off locations rekonstruieren
                        mission.pickup_locations = {int(k): v for k, v in mission_data['pickup_locations'].items()}
                        mission.drop_off_locations = {int(k): v for k, v in mission_data['drop_off_locations'].items()}

                        # MissionPackages für jede package_id erstellen
                        for package_id in mission.packages:
                            mission_package = MissionPackage()
                            mission_package.mission_id = mission.id
                            mission_package.package_id = package_id
                            mission_package.pickup_location_ref = mission.pickup_locations.get(package_id)
                            mission_package.drop_off_location_ref = mission.drop_off_locations.get(package_id)
                            mission.mission_packages.append(mission_package)

                        self.missions[mission.id] = mission  
                        print_debug(f"loaded mission: {mission.to_json()}")
        except Exception as e:
            print(f"Error loading missions: {e}")
            traceback.print_exc()
