from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission
from wingmen.star_citizen_services.model.mission_package import MissionPackage


def build(delivery_mission_json):
    """
    Analyzes the provided JSON and creates a DeliveryMission object.

    Args:
        delivery_mission_json (dict): JSON dictionary containing delivery mission information.

    Returns:
        DeliveryMission: A DeliveryMission object populated with extracted data.
    """
    mission = DeliveryMission()
    mission.revenue = delivery_mission_json['revenue']

    for package_info in delivery_mission_json['packages']:
        package_id = package_info['package_id']
        pickup_info = package_info['pickup']
        drop_off_info = package_info['drop_off']

        pickup_location = {
            "name": pickup_info['facility'],
            "satellite": pickup_info['location'],  # Assuming satellite is same as location
            "code": None, 
            "planet": None,  # Placeholder if planet information is available
            "city": None    # Placeholder if city information is available
        }
        drop_off_location = {
            "name": drop_off_info['facility'],
            "satellite": drop_off_info['location'],
            "code": None,
            "planet": None,
            "city": None
        }

        # Append package ID to the set of package IDs in the mission
        mission.packages.add(package_id)
        
        # Map package ID to its respective locations
        mission.pickup_locations[package_id] = pickup_location
        mission.drop_off_locations[package_id] = drop_off_location

        mission_package = MissionPackage()

        mission_package.mission_id = mission.id
        mission_package.package_id = package_id
        mission_package.pickup_location_ref = pickup_location
        mission_package.drop_off_location_ref = drop_off_location
        mission.mission_packages.append(mission_package)

    return mission
