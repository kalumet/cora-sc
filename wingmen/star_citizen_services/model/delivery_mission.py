from wingmen.star_citizen_services.model.mission_package import MissionPackage
from wingmen.star_citizen_services.helper.json_serializable import JsonSerializable


class DeliveryMission(JsonSerializable):
    """
    Represents a delivery mission, storing all relevant information 
    about the mission including name, revenue, provider, and locations.

    Args:
        id
        revenue
        mission_packages: [MissionPackage] contains all info about one package
        
        fast access attributes:
        packages = set() ids of packages
        pickup_locations = {} key: package, value: location
        drop_off_locations = {} key: package, value: location

    """
    _id_counter = 1  # Class variable for unique ID generation

    def __init__(self):
        """Initialize a new DeliveryMission instance with default values."""
        self.id = DeliveryMission._id_counter
        DeliveryMission._id_counter += 1  # Increment the ID counter

        self.revenue = 0  # the UEC to be earned in this mission
        self.mission_packages: [MissionPackage] = []
        self.packages = set()
        """contains all package ids."""
        self.pickup_locations = {}
        """
        pickup_location = {
                "name": pickup location short name,
                "satellite": moon or planet name 
                "code": code of this location
                "planet": code of planet
                "city": code of city
            }
        mission.pickup_locations[package_number] = pickup_location
        """
        self.drop_off_locations = {}
        """
        drop_off_location = {
                "name": dropoff.group(2),
                "satellite": dropoff.group(3),
                "code": None  # not known yet
                "planet": code of planet
                "city": code of city
                }
        mission.drop_off_locations[package_number] = drop_off_location
        """

    def __str__(self):
        """Return a string representation of the DeliveryMission."""
        mission_info = f"Mission ID: {self.id}\n"
        mission_info += f"Revenue: {self.revenue} aUEC\n"
        
        if self.packages:
            mission_info += "Packages:\n"
            for package in self.packages:
                pickup = self.pickup_locations.get(package, ('Unknown', 'Unknown'))
                pickup_sat_or_plan = pickup["satellite"] if pickup["satellite"] else pickup["planet"]
                drop_off = self.drop_off_locations.get(package, ('Unknown', 'Unknown'))
                dropoff_sat_or_plan = drop_off["satellite"] if drop_off["satellite"] else drop_off["planet"]
                mission_info += f'  - Package #{package}:\n     Pickup at {pickup["name"]} on {pickup_sat_or_plan}\n     Drop-off at {drop_off["name"]} on {dropoff_sat_or_plan}\n'

        return mission_info
    
    def to_json(self):
        # from wingmen.star_citizen_services.uex_api import UEXApi
        # uex_api = UEXApi()

        # satellites = uex_api.get_data("satellites")
        # planets = uex_api.get_data("planets")
        # cities = uex_api.get_data("cities")

        # for package in self.packages:
        #     pickup_location = self.pickup_locations[package]

        #     satellite = pickup_location["satellite"]
        #     pickup_location["satellite"] = satellites.get(satellite, {}).get("name", satellite)
            
        #     planet = pickup_location["planet"]
        #     pickup_location["planet"] = planets.get(planet, {}).get("name", planet)

        #     city = pickup_location["city"]
        #     pickup_location["city"] = cities.get(city, {}).get("name", city)

        #     drop_off_location = self.drop_off_locations[package]

        #     d_satellite = drop_off_location["satellite"]
        #     drop_off_location["satellite"] = satellites.get(d_satellite, {}).get("name", d_satellite)

        #     d_planet = drop_off_location["planet"]
        #     drop_off_location["planet"] = planets.get(d_planet, {}).get("name", d_planet)

        #     d_city = drop_off_location["city"]
        #     drop_off_location["city"] = cities.get(d_city, {}).get("name", d_city)
        return {
            "mission_id": self.id,
            "revenue": self.revenue,
            "packag_ids" : list(self.packages),
            # "pickup_locations": self.pickup_locations,
            # "drop_off_locations": self.drop_off_locations
        }


# Marking attributes to ignore on serialization
DeliveryMission.ignore_for_json('mission_packages')
