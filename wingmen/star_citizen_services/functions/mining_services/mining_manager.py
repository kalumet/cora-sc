import json
import os
import traceback
import time

from apscheduler.schedulers.background import BackgroundScheduler

from services.printr import Printr
from services.audio_player import AudioPlayer

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

        self.overlay = StarCitizenOverlay()
        self.audio_player = AudioPlayer()
        self.scheduler = BackgroundScheduler()

        self.refineries = self.uex2_service.get_refineries()
        self.refinery_methods = self.uex2_service.get_data(uex_api_module.CATEGORY_REFINERY_METHODS)
        commodities = self.uex2_service.get_data(uex_api_module.CATEGORY_COMMODITIES)
        self.ores = {key: value for key, value in commodities.items() if value.get('is_raw') == 1}

        self.refinery_names = [details["space_station_name"] for details in self.refineries.values() if "space_station_name" in details]
        self.refinery_jobs = []
            
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
                                "enum": ["add_work_order", "delete_processed_work_orders", "get_all_work_orders", None]
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

    #@abstractmethod
    def after_init(self):
        self.scheduler.start()

        self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
        if success:
            self.activate_refinery_job_monitoring(self.refinery_jobs)

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
            cropped_image = screenshots.crop_screenshot(self.mining_data_path, image_path, [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")])
            retrieved_json, success = self.ocr.get_screenshot_texts(cropped_image, "workorder", refinery="{refinery}")
            if not success:
                return {"success": False, "error": retrieved_json, "instructions": "Explain the player the reason for the work order not beeing able to be extracted. "}

            return self.add_work_order(retrieved_json)
        
        if type == "get_all_work_orders":
            self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
            if not success:
                return {"success": False, "error": self.refinery_jobs, 
                        "instructions": "There has been an error trying retrieving current refinery work orders."}
            if len(self.refinery_jobs) <= 0:
                return {"success": False, "instructions": "No current refinery work orders."}
            
            self.activate_refinery_job_monitoring(self.refinery_jobs)
            terminal_counts = {}
            jobs_done_message = "No finished refinery jobs."
            
            if len(self.processed_jobs) > 0:
                for job in self.processed_jobs:
                    terminal_name = job["terminal_name"]
                    if terminal_name in terminal_counts:
                        terminal_counts[terminal_name] += 1
                    else:
                        terminal_counts[terminal_name] = 1
                
                jobs_done_message = f"{len(self.processed_jobs)} jobs have completed. jobs={json.dumps(terminal_counts)}. "
            
            active_jobs_message = "No active jobs."
            if len(self.active_jobs) > 0:
                current_time = int(time.time())
                next_job = min(
                    [job for job in self.active_jobs if job["date_expiration"] > current_time],
                    key=lambda job: job["date_expiration"],
                    default=None
                )
                next_job_terminal = next_job["terminal_name"]
                duration = convert_to_minutes.convert_to_str(next_job["date_expiration"] - current_time)

                active_jobs_message = f"{len(self.active_jobs)} active jobs, the next being finished in {duration} at '{next_job_terminal}'. "
            
            return {"success": True, "instructions": f"summarize in natural language of the player: {active_jobs_message} {jobs_done_message}"}
        
        if type == "delete_processed_work_orders":
            self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
            if not success:
                return {"success": False, "error": self.refinery_jobs, 
                        "instructions": "There has been an error trying retrieving current refinery work orders."}
            if len(self.refinery_jobs) <= 0:
                return {"success": False, "instructions": "No current refinery work orders."}
            
            current_time = int(time.time())
            deleted_ids = []
            errors = []
            for job in self.refinery_jobs:
                if job["date_expiration"] <= current_time:
                    response, success = self.uex2_service.delete_refinery_job(job["id"])
                    if success:
                        deleted_ids.append(job["id"])
                    else: 
                        errors.append((job["id"], response))
                                      
            deleted_ids_str = ", ".join(str(id) for id in deleted_ids)
            errors_str = "; ".join(f"ID {job_id}: {error}" for job_id, error in errors)

            return {"instructions": f"Sumarize in a consize sentence in natural language of the player: Deleted Job IDs: {deleted_ids_str}. Errors: {errors_str}. "}

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

    def activate_refinery_job_monitoring(self, refinery_jobs):
        self.scheduler.remove_all_jobs()
        
        if len(refinery_jobs) <= 0:
            print_debug("No refinery jobs to activate")
            return
        
        current_time = int(time.time())
        # Filter for active jobs
        self.active_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time > 0]

        # processed jobs
        self.processed_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time <= 0]

        for job in self.active_jobs:
            # Schedule the action to be executed once the job expires
            self.scheduler.add_job(self.execute_action, 'date', run_date=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job["date_expiration"])), args=[job])
        
    def execute_action(self, job):
        print(f"Executing action for job {job['id']}")

        self.overlay.display_overlay_text(f"Refinery job {job['id']} finished @{job['terminal_name']}.", display_duration=10000)

        # maybe voice ?

