from collections import defaultdict
import json
import os
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print_debug(to_print)

class MissionManager:
    """ maintains a set of all missions and provides functionality to manage this set
    
        missions: dict(mission id, DeliveryMission)
        pickup_locations: dict(location_code, mission id)
        drop_off_locations: dict(location_code, mission id)
    
    """
    def __init__(self):
        self.missions: dict(int, DeliveryMission) = {}
        self.pickup_locations: dict(int, dict)= defaultdict(set)
        self.drop_off_locations: dict(int, dict) = defaultdict(set)

    def add_mission(self, mission: DeliveryMission):
        """Add a new delivery mission to the manager."""
        self.missions[mission.id] = mission
        for package_id in mission.packages:
            pickup_loc = mission.pickup_locations.get(package_id, ('Unknown', 'Unknown'))
            drop_off_loc = mission.drop_off_locations.get(package_id, ('Unknown', 'Unknown'))
            self.pickup_locations[pickup_loc["code"]].add(mission.id)
            self.drop_off_locations[drop_off_loc["code"]].add(mission.id)

    def discard_mission(self, mission_id):
        """Discard a specific mission by its ID."""
        mission: DeliveryMission = self.missions.pop(mission_id, None)
        if mission:
            for package in mission.packages:
                pickup_loc = mission.pickup_locations.get(package)
                drop_off_loc = mission.drop_off_locations.get(package)
                self.pickup_locations[pickup_loc].discard(mission_id)
                self.drop_off_locations[drop_off_loc].discard(mission_id)

    def discard_all_missions(self):
        """Discard all missions."""
        self.missions.clear()
        self.pickup_locations.clear()
        self.drop_off_locations.clear()

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
        if os.path.exists(filename):
            with open(filename, 'r') as file:
                data = json.load(file)
                for mid, mission_data in data.items():
                    mission = DeliveryMission()
                    mission.__dict__.update(mission_data)
                    mission.packages = set(mission.packages)  # Convert list back to set

                    # Convert pickup and drop-off locations back to their original format if needed

                    self.add_mission(mission)

    def __str__(self):
        """Return a string representation of all missions."""
        return "\n".join(str(mission) for mission in self.missions.values())
