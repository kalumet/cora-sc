import json
import time

from apscheduler.schedulers.background import BackgroundScheduler

from services.printr import Printr
from services.audio_player import AudioPlayer

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.helper import screenshots, find_best_match, time_string_converter
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.functions.mining_services.regolith_api import RegolithAPI
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.uex_v2 import uex_api_module


DEBUG = True
TEST = False
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
            prompt_if_missing=False
        )
        self.uex2_secret_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="uex2_secret_key",
            friendly_key_name="UEX2 secret user key",
            prompt_if_missing=False
        )
        self.uex2_service = UEXApi2.init(
            uex_api_key=self.uex2_api_key,
            user_secret_key=self.uex2_secret_key
        )
        regolith_api_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="regolith_secret_key",
            friendly_key_name="Regolith secret api key",
            prompt_if_missing=True
        )
        self.regolith = RegolithAPI(config=config, x_api_key=regolith_api_key)

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
            open_ai_model=f'{self.config["open-ai-vision-model"]}',
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
        function_register[self.refinery_job_work_order_management.__name__] = self.refinery_job_work_order_management
        function_register[self.mining_or_salvage_session_management.__name__] = self.mining_or_salvage_session_management
        function_register[self.add_rock_scan_or_deposit_cluster_information.__name__] = self.add_rock_scan_or_deposit_cluster_information
    
    # @abstractmethod - overwritten
    def get_function_prompt(self) -> str:      
        """  
            Here you can provide instructions to open ai on how to use this function. 
        """
        return (
            f"You are able to manage mining or salvaging sessions and corresponding refinery work orders. "
            f"The following functions allow you to help the player in this task. For each of them, don't make assumptions on the value and set to None if the user hasn't provided information about it. "
            f"- {self.refinery_job_work_order_management.__name__}: call it to add 1, remove 1 or retrieve all refinery work orders / jobs of the active refinery session. This function does not require any further information from the user. "
            f"- {self.mining_or_salvage_session_management.__name__}: call it to create a new mining / salvage session, delete all finalised sessions or to retrieve the current session. It also allows to open the active session in the browser. "
            f"- {self.add_rock_scan_or_deposit_cluster_information.__name__}: call it when the player wants to provide information about a scanned rock or found a new mining deposit cluster. "
            "Never make assumptions on the values. Ask the user to provide them. "
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
                    "name": self.refinery_job_work_order_management.__name__,
                    "description": "Allows the player to add or remove a refinery work order / jobs to the active session, or to retrieve all active work order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["add_work_order", "get_all_work_orders", None]
                            },
                            "confirm_deletion": {
                                "type": "string",
                                "description": "User confirmed deletion",
                                "enum": ["confirmed", "notconfirmed", None]
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.mining_or_salvage_session_management.__name__,
                    "description": "Allows the player to create, remove or get a session for ship mining, vehicle mining or salvaging at Regolith.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute. ",
                                "enum": ["new_session", "delete_processed_sessions", "open_session_in_browser"]
                            },
                            "name": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The name the session should get. Do not make assumptions on the value. "
                            },
                            "activity": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The activity of this session.  Do not make assumptions on the value. ",
                                "enum": self.regolith.get_activity_names() + [None]
                            },
                            "refinery": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The refinery where the ores will be processed. Is mandatory. Do not make assumptions on the value. ",
                                "enum": self.regolith.get_refinery_names() + [None]
                            },
                            "session_id": {
                                "type": "string",
                                "description": "The session_id of the session the player wants to open in his browser. "
                            },
                            "confirm_deletion": {
                                "type": "string",
                                "description": "User confirmed deletion. Only relevant if the user wants to delete sessions, ask for explizit confirmation. ",
                                "enum": ["confirmed", "notconfirmed", None]
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.add_rock_scan_or_deposit_cluster_information.__name__,
                    "description": "Allows the player to add information about found mining deposit clusters and scan results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["save_scan_result", "add_new_cluster", None]
                            },
                            "cluster_count": {
                                "type": "integer",
                                "description": "Is only necessary for type 'add_new_cluster'. The number of rocks in the cluster. Do not ask for this value if type is 'save_scan_result'. Optional "
                            },
                            "cluster_type": {
                                "type": "string",
                                "description": "Is only necessary for type 'add_new_cluster'. The deposit / rock types within this cluster. Do not ask for this value if type is 'save_scan_result'. Optional ",
                                "enum": [
                                    "C-Type",
                                    "E-Type",
                                    "M-Type",
                                    "P-Type",
                                    "Q-Type",
                                    "S-Type",
                                    "Atacamite",
                                    "Felsic",
                                    "Gneiss",
                                    "Granite",
                                    "Igneous",
                                    "Obsidian",
                                    "Quartzite",
                                    "Shale",
                                    None]
                            }
                            
                        }
                    }
                }
            },
        ]

        return tools

    # overwritten
    def after_init(self):
        # self.scheduler.start()

        # self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
        # if success:
        #     self.activate_refinery_job_monitoring(self.refinery_jobs)

        self.regolith.initialize_all_names()

    # overwritten
    def cora_start_information(self):
        """  
            This method can be implemented to retrieve information from the manager, that Cora should provide to the user on startup.
        """
        result = self.regolith.get_active_work_orders()
        if result and not result["success"]:
            return ""  # we don't tell the user that errors occured
        
        if result["data"]["total_finished_refinery_orders"] == 0 and result["data"]["total_refinery_orders_in_processing"] == 0:
            return ""
        
        return {
            "mining_session_work_order_request": result
        }

    def mining_or_salvage_session_management(self, function_args):
        printr.print(f"Executing function '{self.mining_or_salvage_session_management.__name__}'.", tags="info")
        confirmed_deletion = function_args.get("confirm_deletion", None)
        function_type = function_args["type"]
        printr.print(f'-> Work Session Management: {function_type} with args: \n{json.dumps(function_args, indent=2)}', tags="info")
        function_response = self.manage_work_session(type=function_type, function_args=function_args, confirmed_deletion=confirmed_deletion)
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response

    def manage_work_session(self, type, function_args, confirmed_deletion):
        if type == "new_session":
            return self.create_session(function_args)
        
        if type == "open_session_in_browser":
            session_id = function_args.get("session_id", None)
            success = self.regolith.open_session_in_browser(session_id)
            if not success:
                return {"success": False, "message": f"I couldn't open the browser{' as there is no active session. ' if self.regolith.active_session_id is None else '. '}"}
            return {"success": True}
        
        if type == "delete_processed_sessions":
            if not confirmed_deletion:
                return {"success": False, "message": "Do you really want to delete all processed sessions? "}
            return self.regolith.delete_processed_sessions()
            
            # self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
            # if not success:
            #     return {"success": False, "error": self.refinery_jobs, 
            #             "instructions": "There has been an error trying retrieving current refinery work orders."}
            # if len(self.refinery_jobs) <= 0:
            #     return {"success": False, "instructions": "No current refinery work orders."}
            
            # current_time = int(time.time())
            # deleted_ids = []
            # errors = []
            # for job in self.refinery_jobs:
            #     if job["date_expiration"] <= current_time:
            #         response, success = self.uex2_service.delete_refinery_job(job["id"])
            #         if success:
            #             deleted_ids.append(job["id"])
            #         else: 
            #             errors.append((job["id"], response))
                                      
            # deleted_ids_str = ", ".join(str(id) for id in deleted_ids)
            # errors_str = "; ".join(f"ID {job_id}: {error}" for job_id, error in errors)

            # return {"instructions": f"Sumarize in a consize sentence in natural language of the player: Deleted Job IDs: {deleted_ids_str}. Errors: {errors_str}. "}

    def create_session(self, function_args):
        name = function_args.get("name", None)
        activity = function_args.get("activity", None)
        refinery = function_args.get("refinery", None)

        if activity is None: 
            return {"success": False, "message": f"Please provide the activity you want the session to track. One of: {self.regolith.get_activity_names()}"}
        if activity == "SHIP_MINING" and refinery is None:
            return {"success": False, "message": "Please provide the refinery name to create a mining session. "}
        
        session_id = self.regolith.create_mining_session(name, activity, refinery)
        if session_id is not None:
            return {"success": True, "message": "Session created. "}
        
        return {"success": False, "message": "Session was not created."}

    def refinery_job_work_order_management(self, function_args):
        printr.print(f"Executing function '{self.refinery_job_work_order_management.__name__}'.", tags="info")
        work_order_index = function_args.get("work_order_index", None)
        confirmed_deletion = function_args.get("confirm_deletion", None)
        function_type = function_args["type"]
        printr.print(f'-> Refinery Management: {function_type}', tags="info")
        function_response = self.manage_work_order(type=function_type, work_order_index=work_order_index, confirmed_deletion=confirmed_deletion)
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response
    
    def add_rock_scan_or_deposit_cluster_information(self, function_args):
        printr.print(f"Executing function '{self.add_rock_scan_or_deposit_cluster_information.__name__}'. with args {json.dumps(function_args, indent=2)}", tags="info")
        function_type = function_args["type"]
        if not function_type or function_type == "save_scan_result":
            image_path = screenshots.take_screenshot(self.mining_data_path, "scans", test=TEST)
            if not image_path:
                return {"success": False, "instructions": "Could not take screenshot. Explain the player, that you only take screenshots, if the active window is Star Citizen. "}
            cropped_image = screenshots.crop_screenshot(f"{self.mining_data_path}/templates/scans", image_path, [("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")])
            base64_jpg_image = screenshots.convert_cv2_image_to_base64_jpeg(cropped_image)
            scan_result = self.regolith.get_rock_scan_image_infos(base64_jpg_image)
            if scan_result and "captureShipRockScan" in scan_result:
                session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
                scout_finding_id, cluster_count = self.regolith.get_or_create_scouting_cluster(session_id)
                function_response = self.regolith.add_ship_cluster_scan_results(session_id, scout_finding_id, cluster_count, scan_result["captureShipRockScan"])
        
        elif function_type == "add_new_cluster":
            cluster_count = function_args.get("cluster_count", 0)
            cluster_type = function_args.get("cluster_type", None)
            session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
            scout_finding_id = self.regolith.create_scouting_cluster(session_id, cluster_count, cluster_type)
            if scout_finding_id is None:
                return {"success": False, "message": "Couldn't create a new cluster."}
            function_response = {"success": True, "message": f"Created a new cluster with {cluster_count} rocks."}
       
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response

    def manage_work_order(self, type="new", work_order_index=None, confirmed_deletion=None):
        if type == "add_work_order":
            image_path = screenshots.take_screenshot(self.mining_data_path, "workorder", "images", test=TEST)
            if not image_path:
                return {"success": False, "instructions": "Could not take screenshot. Explain the player, that you only take screenshots, if the active window is Star Citizen. "}
            cropped_image = screenshots.crop_screenshot(f"{self.mining_data_path}/templates/refineries", image_path, [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")])
            
            # open ai image recognition
            # retrieved_json, success = self.ocr.get_screenshot_texts(cropped_image, "workorder", refinery="{refinery}", test=TEST)
            # if not success:
            #     return {"success": False, "error": retrieved_json, "instructions": "Explain the player the reason for the work order not beeing able to be extracted. "}

            # return self.add_work_order_regolith(retrieved_json)
            
            # if regolith api provides amt from screenshot, i can use this.
            base64_jpg_image = screenshots.convert_cv2_image_to_base64_jpeg(cropped_image)
            scan_result = self.regolith.get_work_order_image_infos(base64_jpg_image)

            return self.add_work_order_regolith_from_scan(scan_result)
            
        if type == "get_all_work_orders":
            return self.regolith.get_active_work_orders()
            
            # self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
            # if not success:
            #     return {"success": False, "error": self.refinery_jobs, 
            #             "instructions": "There has been an error trying retrieving current refinery work orders."}
            # if len(self.refinery_jobs) <= 0:
            #     return {"success": False, "instructions": "No current refinery work orders."}
            
            # self.activate_refinery_job_monitoring(self.refinery_jobs)
            # terminal_counts = {}
            # jobs_done_message = "No finished refinery jobs."
            
            # if len(self.processed_jobs) > 0:
            #     for job in self.processed_jobs:
            #         terminal_name = job["terminal_name"]
            #         if terminal_name in terminal_counts:
            #             terminal_counts[terminal_name] += 1
            #         else:
            #             terminal_counts[terminal_name] = 1
                
            #     jobs_done_message = f"{len(self.processed_jobs)} jobs have completed. jobs={json.dumps(terminal_counts)}. "
            
            # active_jobs_message = "No active jobs."
            # if len(self.active_jobs) > 0:
            #     current_time = int(time.time())
            #     next_job = min(
            #         [job for job in self.active_jobs if job["date_expiration"] > current_time],
            #         key=lambda job: job["date_expiration"],
            #         default=None
            #     )
            #     next_job_terminal = next_job["terminal_name"]
            #     duration = time_string_converter.convert_seconds_to_str(next_job["date_expiration"] - current_time)

            #     active_jobs_message = f"{len(self.active_jobs)} active jobs, the next being finished in {duration} at '{next_job_terminal}'. "
            
            # return {"success": True, "instructions": f"summarize in natural language of the player: {active_jobs_message} {jobs_done_message}"}

        return {"success": False, "message": "I couldn't identify the action to be taken. Please repeat. "}
    
    def add_work_order_regolith_from_scan(self, scan_result):
        print_debug("\n ===== ADDING REGOLITH WORK ORDER ======")
        
        if "captureRefineryOrder" not in scan_result:
            print_debug("No refinery work order information available.")
            return {"success": False, "message": f"Couldn't retrieve data from {json.dumps(scan_result, indent=2)}."}
        
        current_time = int(time.time() * 1000)
        session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=scan_result["captureRefineryOrder"]["refinery"])
        if session_id is None:
            print_debug(f"Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        
        shipOres = scan_result["captureRefineryOrder"]["shipOres"]

        for ore in shipOres:
            amt = self.regolith.ore_amt_calc(ore["yield"], ore["ore"], scan_result["captureRefineryOrder"]["refinery"], scan_result["captureRefineryOrder"]["method"] )
            ore["amt"] = amt
            del ore["yield"]  # Remove the "yield" key from the dictionary

        variables = {
            "sessionId": session_id,
            "shipOres": shipOres,
            "workOrder": {
                "expenses": scan_result["captureRefineryOrder"]["expenses"],
                "includeTransferFee": True,
                "isRefined": True,
                "isSold": False,
                "method": scan_result["captureRefineryOrder"]["method"],  
                "note": "Work order created by Cora - Your Star Citizen Ai-compagnion",
                "processStartTime": current_time,
                "processDurationS": scan_result["captureRefineryOrder"]["processDurationS"], 
                "refinery": scan_result["captureRefineryOrder"]["refinery"],
            }
        }

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_work_order_regolith(self, work_order):
        print_debug("\n ===== ADDING REGOLITH WORK ORDER ======")
        station = work_order["work_order"]["station_name"]
        refinery, success = find_best_match.find_best_match(station, self.regolith.get_refinery_names(), score_cutoff=0)
        if not success:
            print_debug(f"Couldn't identify refinery from '{station}'.")
            return f"Couldn't identify refinery from '{station}'."
        print_debug(f'matched refinery "{refinery["matched_value"]}" with confidence {refinery["score"]}')
        
        method = work_order["work_order"]["processing_selection_method"]
        refinery_method, success = find_best_match.find_best_match(
            method, 
            self.regolith.get_refinery_method_names(), score_cutoff=80)
        if not success:
            print_debug(f"Couldn't identify refinery method from '{method}'.")
            return f"Couldn't identify refinery method from '{method}'."
        print_debug(f'matched refinery method "{refinery_method["matched_value"]}" with confidence {refinery_method["score"]}')

        current_time = int(time.time() * 1000)
        session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=refinery["matched_value"])
        processing_time_s = time_string_converter.convert_to_seconds(work_order["work_order"]["processing_time"])
        if session_id is None:
            print_debug(f"Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        variables = {
            "sessionId": session_id,
            "workOrder": {
                "expenses": [
                    {
                        "amount": work_order["work_order"]["total_cost"],
                        "name": "Refinery Fee"
                    }
                ],
                "includeTransferFee": True,
                "isRefined": True,
                "isSold": False,
                "method": refinery_method["matched_value"],
                "note": "Work order created by Cora - Your Star Citizen ai-compagnion",
                "processDurationS": processing_time_s, 
                "processStartTime": current_time,
                # "processEndTime": (current_time + (processing_time_s * 1000)), not supported, will be returned
                "refinery": refinery["matched_value"],  
            }
        }
        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.regolith.get_ship_ore_names(), score_cutoff=0)
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            print_debug(f'matched ore "{ore["matched_value"]}" with confidence {ore["score"]}')
            
            item = {
                # "yield": material["yield"], not supported, is only returned
                "amt": material["quantity"],  
                "ore": ore["matched_value"]  
            }
            materials.append(item)

        variables["shipOres"] = materials

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_scan_result_regolith(self, scan_result):
        print_debug("\n ===== ADDING REGOLITH SCAN Result ======")
    
        session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
        if session_id is None:
            print_debug(f"Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        variables = {
            "sessionId": session_id,
            "scoutingFind": {
                "state": "DISCOVERED",
                "clusterCount": 1
            },
        }
        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.regolith.get_ship_ore_names(), score_cutoff=0)
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            print_debug(f'matched ore "{ore["matched_value"]}" with confidence {ore["score"]}')
            
            item = {
                # "yield": material["yield"], not supported, is only returned
                "amt": material["quantity"],  
                "ore": ore["matched_value"]  
            }
            materials.append(item)

        variables["shipOres"] = materials

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_work_order_uex(self, work_order):
        print_debug("\n ===== ADDING UEX WORK ORDER ======")
        station = work_order["work_order"]["station_name"]
        refinery, success = find_best_match.find_best_match(station, self.refineries, attributes=["space_station_name"])
        if not success:
            return f"Couldn't identify refinery from '{station}'."
        print_debug(f'matched refinery "{refinery["matched_value"]}" with confidence {refinery["score"]}')
        
        method = work_order["work_order"]["processing_selection_method"]
        refinery_method, success = find_best_match.find_best_match(
            method, 
            self.refinery_methods, 
            attributes=["name"])
        if not success:
            return f"Couldn't identify refinery method from '{method}'."

        uex_refinery_order = {
            "id_terminal": refinery["root_object"]["id"],
            "id_refinery_method": refinery_method["root_object"]["id"],
            "cost": work_order["work_order"]["total_cost"],
            "time_minutes": time_string_converter.convert_to_minutes(work_order["work_order"]["processing_time"]),
            "refinery_capacity": work_order["work_order"]["current_capacity"]
        }

        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.ores, attributes=["name"])
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
        pass
        # self.scheduler.remove_all_jobs()
        
        # if len(refinery_jobs) <= 0:
        #     print_debug("No refinery jobs to activate")
        #     return
        
        # current_time = int(time.time())
        # # Filter for active jobs
        # self.active_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time > 0]

        # # processed jobs
        # self.processed_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time <= 0]

        # for job in self.active_jobs:
        #     # Schedule the action to be executed once the job expires
        #     self.scheduler.add_job(self.execute_action, 'date', run_date=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job["date_expiration"])), args=[job])
        
    def execute_action(self, job):
        print(f"Executing action for job {job['id']}")

        self.overlay.display_overlay_text(f"Refinery job {job['id']} finished @{job['terminal_name']}.", display_duration=10000)

        # maybe voice ?

