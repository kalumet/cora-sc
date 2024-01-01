import json
import os
import traceback

from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission, MissionPackage
from wingmen.star_citizen_services.screenshot_ocr import TransportMissionAnalyzer
from wingmen.star_citizen_services.delivery_manager import PackageDeliveryPlanner, DeliveryMissionAction, UEXApi
from wingmen.star_citizen_services.overlay import StarCitizenOverlay


DEBUG = True
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MissionManager:
    """ maintains a set of all missions and provides functionality to manage this set
    
        missions: dict(mission id, DeliveryMission)
        pickup_locations: dict(location_code, mission id)
        drop_off_locations: dict(location_code, mission id)
    
    """
    def __init__(self, config=None):

        self.missions: dict(int, DeliveryMission) = {}
        self.delivery_actions: list(DeliveryMissionAction) = []
        self.current_delivery_action_index: int = 0
        self.current_delivery_action_location_end_index = 0

        self.config = config
        self.mission_data_path = f'{self.config["data-root-directory"]}{self.config["box-mission-configs"]["mission-data-dir"]}'
        self.missions_file_path = f'{self.mission_data_path}/active-missions.json'
        self.delivery_route_file_path = f'{self.mission_data_path}/active-delivery-route.json'
        self.mission_screen_upper_left_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["upper-left-region-template"]}'
        self.mission_screen_lower_right_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["lower-right-region-template"]}'

        self.overlay = StarCitizenOverlay()
        self.delivery_manager = PackageDeliveryPlanner()
        self.mission_recognition_service = TransportMissionAnalyzer(
            upper_left_template=self.mission_screen_upper_left_template, 
            lower_right_template=self.mission_screen_lower_right_template, 
            data_dir_path=self.mission_data_path
            )
        
        # we always load from file, as we might restart wingmen.ai indipendently from star citizen
        # TODO need to check on start, if we want to discard this mission
        self.load_missions()
        self.load_delivery_route()

        self.mission_started = False
        self.current_delivery_location = None

    def get_next_actions(self, current_index=0):
        print_debug(f"get_next_actions start at {current_index}")
        if not self.delivery_actions or not self.missions:
            return None, None
        
        index = current_index
        start_index = None
        end_index = 0
        current_location = None
        pick_up_count = 0
        dropoff_count = 0
        
        while index < len(self.delivery_actions):
            action: DeliveryMissionAction = self.delivery_actions[index]
            if action.state == "DONE":
                self.mission_started = True
                print_debug(f"skipping index {index} as done: {action}")

            if action.state == "TODO":
                if start_index is None: # we find the first "TODO" action in the list, which is our start index for the next location
                    print_debug(f"found start at index: {index}")
                    start_index = index
                    current_location = self.delivery_actions[index].location_ref

                if current_location and action.location_ref.get("code") != current_location.get("code"):
                    print_debug("changed location, finished")
                    break

                end_index = index

                if action.action == "pickup":
                    pick_up_count += 1
                else:
                    dropoff_count += 1

            index += 1

        self.current_delivery_action_index = start_index
        self.current_delivery_action_location_end_index = end_index
        self.current_delivery_location = current_location

        print_debug(f"identified next location: {self.current_delivery_location}, same location actions indexes: {self.current_delivery_action_index}->{self.current_delivery_action_location_end_index}")
        
        if start_index is None:  # we have reached the end of the delivery route
            return None, None
        
        return pick_up_count, dropoff_count
    
    def update_last_location(self):
        """Updates all actions between current_delivery_action_index and current_delivery_action_location_end_index to state 'DONE', saves and returns the next index or None, if the end has been reached"""
        if len(self.delivery_actions) == 0:
            return False, {
                "success": "False", 
                "instructions": "There are no delivery missions active"
            }
        
        if self.mission_started is False:
            print_debug("no actions done yet")
            return True, None
        
        index = self.current_delivery_action_index
        end_index = self.current_delivery_action_location_end_index

        while index < len(self.delivery_actions) and index <= end_index:
            print_debug(f"box action done index: {self.delivery_actions[index].index}")
            self.delivery_actions[index].state = "DONE"
            index += 1

        self.current_delivery_action_index = self.current_delivery_action_location_end_index
        if self.current_delivery_action_index >= len(self.delivery_actions):
            self.discard_all_missions()
            return False, {"success": "False", 
            "instructions": "The player has completed all delivery missions. No active missions available."}
                    
        self.save_delivery_route()
 
        return True, None
           
    def manage_missions(self, type="new", mission_id=None):
        if type == "new_delivery_mission":
            return self.get_new_mission()
        if type == "delete_or_discard_all_missions":
            return self.discard_all_missions()
        if type == "delete_or_discard_one_mission_with_id":
            return self.discard_mission(mission_id)
        if type == "get_first_or_next_location_on_delivery_route":
            return self.get_next_location()
        
    def get_missions_information(self):
        mission_count = 0
        package_count = 0
        revenue_sum = 0
        location_count = 0
        planetary_system_changes = 0
        locations = set()
        moons_and_planets = set()
        for mission in self.missions.values():
            mission: DeliveryMission
            print_debug(mission)
            mission_count += 1
            revenue_sum += mission.revenue
            package_count += len(mission.packages)

            for location_info in mission.mission_packages:
                location_info: MissionPackage

                locations.add(location_info.pickup_location_ref.get("code"))
                locations.add(location_info.drop_off_location_ref.get("code"))
                
                moon = location_info.pickup_location_ref.get("satellite")
                planet = location_info.pickup_location_ref.get("planet")

                if moon:
                    moons_and_planets.add(moon)
                else:
                    moons_and_planets.add(planet)

        location_count = len(locations)
        planetary_system_changes = len(moons_and_planets)

        return mission_count, package_count, revenue_sum, location_count, planetary_system_changes

    def get_next_location(self):
        
        uexApi = UEXApi()

        success, message = self.update_last_location()
        
        if success is False:
            return message
        
        pickup_count, dropoff_count = self.get_next_actions(self.current_delivery_action_index)

        print_debug(f"next action: {self.current_delivery_location} pickup #{pickup_count}, dropoff #{dropoff_count}")
        if pickup_count == 0 and dropoff_count == 0:
            # shouldn't happen
            print_debug("ERROR - no next location")
            return {"success": False, "message": "Error"}
        
        next_action: DeliveryMissionAction = self.delivery_actions[self.current_delivery_action_index]
        next_location = self.current_delivery_location
        moon_or_planet = ""
        if next_location.get("satellite"):
            moon_or_planet = uexApi.get_satellite_name(next_location.get("satellite"))
        else:
            moon_or_planet = uexApi.get_planet_name(next_location.get("planet"))

        index = self.current_delivery_action_index
        pickup_packages = []
        dropoff_packages = []
        while index < len(self.delivery_actions) and index <= self.current_delivery_action_location_end_index:
            action: DeliveryMissionAction = self.delivery_actions[index]
            if action.action == "pickup":
                pickup_packages.append(action.package_id)
            else: 
                dropoff_packages.append(action.package_id)
            
            index += 1

        self.overlay.display_overlay_text(
            (
                f'Next location: {next_location.get("name")}  '
                f'on  {moon_or_planet}  '
                f'pickup:  {pickup_packages}  '
                f'dropoff:  {dropoff_packages}'
            )
        )
        
        return {
            "success": True, 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0.",
            "next_location": next_location.get("name"),
            "on_moon": uexApi.get_satellite_name(next_location.get("satellite")),
            "on_planet": uexApi.get_planet_name(next_location.get("planet")),
            "in_city": uexApi.get_city_name(next_location.get("city")),
            "possible_threads": next_action.danger,
            "number_of_packages_to_pickup": pickup_count,
            "number_of_packages_to_dropoff": dropoff_count,
            "sell_commodity": uexApi.get_commodity_name(next_action.sell_commodity_code),
            "buy_commodity": uexApi.get_commodity_name(next_action.buy_commodity_code)
        }
    
    def get_mission_ids(self):
        return [mission for mission in self.missions.keys()]
    
    def get_new_mission(self):

        delivery_mission: DeliveryMission = self.mission_recognition_service.identify_mission()
        self.missions[delivery_mission.id] = delivery_mission
        print_debug(f"new mission: {delivery_mission.to_json()}")
        
        self.calculate_delivery_route()
        
        mission_count, package_count, revenue_sum, location_count, planetary_system_changes = self.get_missions_information()

        self.overlay.display_overlay_text(
            (
                f"Total missions: #{mission_count}  "
                f"for {revenue_sum} αUEC   "
                f"packages: {package_count}."
            ),
            vertical_position_ratio=8
        )

        # 3 return new mission and active missions + instructions for ai
        return {
            "success": "True", 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0.",
            "missions_count": mission_count,
            "total_revenue": revenue_sum,
            "total_packages_to_deliver": package_count,
            "number_of_locations_to_visit": location_count,
            "number_of_moons_or_planets_to_visit": planetary_system_changes,
        }

    def calculate_delivery_route(self):
        self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
         
        # CargoRoutePlanner.finde_routes_for_delivery_missions(ordered_delivery_locations, tradeports_data)
			
        # Save the missions to a JSON file
        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0
       
    def discard_mission(self, mission_id):
        """Discard a specific mission by its ID."""
        uexApi = UEXApi()
        
        self.missions.pop(mission_id, None)
        
        self.calculate_delivery_route()

        pickup_count, dropoff_count = self.get_next_actions()
        next_action: DeliveryMissionAction = self.delivery_actions[self.current_delivery_action_index]
        next_location = self.current_delivery_location
        
        mission_count, package_count, revenue_sum, location_count, planetary_system_changes = self.get_missions_information()

        self.overlay.display_overlay_text(
            f"Discarded Mission #{mission_id}   "
            f"Total missions: #{mission_count}  "
            f"for {revenue_sum} αUEC   "
            f"packages: {package_count}. Next Location: {self.delivery_actions[0].location_ref.get('name')}"
        )
        
        return {
            "success": "True", 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0.",
            "missions_count": mission_count,
            "total_revenue": revenue_sum,
            "total_packages_to_deliver": package_count,
            "number_of_locations_to_visit": location_count,
            "number_of_moons_or_planets_to_visit": planetary_system_changes,
            "next_location": next_location.get("name"),
            "on_moon": next_location.get("satellite"),
            "on_planet": next_location.get("planet"),
            "in_city": next_location.get("city"),
            "possible_threads": next_action.danger,
            "number_of_packages_to_pickup": pickup_count,
            "number_of_packages_to_dropoff": dropoff_count,
            "sell_commodity": uexApi.get_commodity_name(next_action.sell_commodity_code),
            "buy_commodity": uexApi.get_commodity_name(next_action.buy_commodity_code)
        }

    def discard_all_missions(self):
        """Discard all missions."""
        number = len(self.missions)
        self.missions.clear()
        self.delivery_actions.clear()
        self.mission_started = False

        self.overlay.display_overlay_text(
            "Discarded all mission, reject them ingame."
        )

        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0
        self.current_delivery_action_location_end_index = 0

        return {"success": "True", 
                "instructions": "Provide only the following information: Acknowledge the deletion of the number of missions. Any numbers in your response must be written out. Do not provide any further information.",
                "delete_missions_count": number }

    def save_missions(self):
        """Save mission data to a file."""
        filename = self.missions_file_path
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
        filename = self.missions_file_path
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

    def save_delivery_route(self):
        """Save mission data to a file."""
        filename = self.delivery_route_file_path
        with open(filename, 'w') as file:
            delivery_route_data = []
            for delivery_action in self.delivery_actions:
                delivery_action: DeliveryMissionAction
                deliver_json = delivery_action.to_json()
                delivery_route_data.append(deliver_json)
                
            json.dump(delivery_route_data, file, indent=3)

    def load_delivery_route(self):
        """Load delivery route data from a file."""
        filename = self.delivery_route_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for index, action_json in enumerate(data):
                        action = DeliveryMissionAction.from_json(self.missions, action_json, index)                   
                        
                        if isinstance(action.mission_ref, int):
                            action.mission_ref = self.missions[action.mission_ref] # we stored only the id of the mission, so now we recover the reference                    
                        self.delivery_actions.append(action)
                    
                    # we need to reiterate to build the partner-relation
                    for action in self.delivery_actions:
                        me: DeliveryMissionAction = action
                        if isinstance(me.partner_action, int):  # we only need to set, if we haven't already replaced the index by the reference
                            partner: DeliveryMissionAction = self.delivery_actions[me.partner_action]  # we have the index currently saved, so we can access the partner directly

                            me.partner_action = partner
                            partner.partner_action = me
                    print_debug("loaded delivery route")
            else:
                self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
                self.save_delivery_route()
                print_debug("loading failed: calculated delivery route")

        except Exception:
            traceback.print_exc()
    
    def __str__(self):
        """Return a string representation of all missions."""
        return "\n".join(str(mission) for mission in self.missions.values())
