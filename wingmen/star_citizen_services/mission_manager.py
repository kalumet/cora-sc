import json
import os
import traceback

from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission, MissionPackage
from wingmen.star_citizen_services.screenshot_ocr import TransportMissionAnalyzer
from wingmen.star_citizen_services.delivery_manager import PackageDeliveryPlanner, DeliveryMissionAction


DEBUG = True


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

        self.config = config
        self.mission_data_path = f'{self.config["data-root-directory"]}{self.config["box-mission-configs"]["mission-data-dir"]}'
        self.missions_file_path = f'{self.mission_data_path}/active-missions.json'
        self.delivery_route_file_path = f'{self.mission_data_path}/active-delivery-route.json'
        self.mission_screen_upper_left_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["upper-left-region-template"]}'
        self.mission_screen_lower_right_template = f'{self.mission_data_path}/{self.config["box-mission-configs"]["lower-right-region-template"]}'

        self.delivery_manager = PackageDeliveryPlanner()
        self.mission_recognition_service = TransportMissionAnalyzer(
            upper_left_template=self.mission_screen_upper_left_template, 
            lower_right_template=self.mission_screen_lower_right_template, 
            data_dir_path=self.mission_data_path
            )
        
        # we always load from file, as we might restart wingmen.ai indipendently from star citizen
        # TODO need to check on start, if we want to discard this mission
        self.load_missions(self.missions_file_path)
        self.load_delivery_route(self.delivery_route_file_path)

    def get_new_mission(self):
        delivery_mission: DeliveryMission = self.mission_recognition_service.identify_mission()
        self.missions[delivery_mission.id] = delivery_mission
        print_debug(delivery_mission.to_json())
        
        self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
         
        # CargoRoutePlanner.finde_routes_for_delivery_missions(ordered_delivery_locations, tradeports_data)
			
        # Save the missions to a JSON file
        self.save_missions(self.missions_file_path)
        self.save_delivery_route(self.delivery_route_file_path)
        # 1 take a screenshot

        # 2 get mission information

        # 3 return new mission and active missions + instructions for ai
        return {"success": "True", 
                "instructions": "Provide following information in your response: the mission with id has been added to the active missions, the revenue and number of packages added. Finaly provide information about the first location the player has to visit: for the mission with id: tradeport, where it's located and what package id and action he has to fulfill",
                "missions_count": len(self.missions),
                "new_mission": delivery_mission.to_json(),
                "first_location": self.delivery_actions[0].to_GPT_json()}

    def discard_mission(self, mission_id):
        """Discard a specific mission by its ID."""
        mission: DeliveryMission = self.missions.pop(mission_id, None)
        self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)

        self.save_missions(self.missions_file_path)
        self.save_delivery_route(self.delivery_route_file_path)
        
        return {"success": "True", 
                "instructions": "Provide only the following information: Acknowledge abortion of mission with given id. Any numbers in your response must be written out. Do not provide any further information.",
                "mission": mission.to_json()}

    def discard_all_missions(self):
        """Discard all missions."""
        number = len(self.missions)
        self.missions.clear()
        self.delivery_actions.clear()

        self.save_missions(self.missions_file_path)
        self.save_delivery_route(self.delivery_route_file_path)

        return {"success": "True", 
                "instructions": "Provide only the following information: Acknowledge the deletion of the number of missions. Any numbers in your response must be written out. Do not provide any further information.",
                "delete_missions_count": number }

    def save_missions(self, filename):
        """Save mission data to a file."""
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

    def load_missions(self, filename):
        """Load mission data from a file."""
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for mid, mission_data in data.items():
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
            print_debug(self.missions)    
        except Exception as e:
            print(f"Error loading missions: {e}")
            traceback.print_exc()

    def save_delivery_route(self, filename):
        """Save mission data to a file."""
        with open(filename, 'w') as file:
            delivery_route_data = []
            for delivery_action in self.delivery_actions:
                delivery_action: DeliveryMissionAction
                deliver_json = delivery_action.to_json()
                delivery_route_data.append(deliver_json)
                
            json.dump(delivery_route_data, file, indent=3)

    def load_delivery_route(self, filename):
        """Load delivery route data from a file."""
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for index, action_json in enumerate(data):
                        action = DeliveryMissionAction.from_json(self.missions, action_json, index)                   
                        self.delivery_actions.append(action)
        except Exception:
            traceback.print_exc()

    def __str__(self):
        """Return a string representation of all missions."""
        return "\n".join(str(mission) for mission in self.missions.values())
