import re
import logging
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission
from wingmen.star_citizen_services.model.mission_package import MissionPackage


class TextAnalyzer:
    """
    Analyzes text for specific information related to a delivery mission.
    Extracts details like mission name, revenue, mission provider, and 
    package locations using regular expressions.
    """
    @staticmethod
    def analyze_text(text):
        """
        Analyzes the provided text and extracts delivery mission details.

        Args:
            text (str): Text containing delivery mission information.

        Returns:
            DeliveryMission: A DeliveryMission object populated with extracted data.
        """
        mission = DeliveryMission()

        # Define regular expression patterns
        revenue_pattern = re.compile(r"Payment ([\d,]+) a.{0,2}ec", re.IGNORECASE)
        pickups_pattern = re.compile(r"P.ck.ge #(\d+) fr.m (.+) .n (.+)")
        dropoffs_pattern = re.compile(r"P.ck.ge #(\d+) t. (.+) .n (.+)")

        # Extract revenue
        revenue_match = revenue_pattern.search(text)
        if revenue_match:
            mission.revenue = int(revenue_match.group(1).replace(',', ''))

        # Extract packages and locations
        pickup_infos = pickups_pattern.finditer(text)
        drop_off_infos = dropoffs_pattern.finditer(text)

        for pickup, dropoff in zip(pickup_infos, drop_off_infos):
            mission_package = MissionPackage()
            package_number = int(pickup.group(1))
                        
            pickup_location = {
                "name": pickup.group(2),
                "satellite": pickup.group(3),
                "code": "",  # not known yet
                "planet": "", # not known yet
                "city": "" # not known yet
            }

            drop_off_location = {
                "name": dropoff.group(2),
                "satellite": dropoff.group(3),
                "code": "",  # not known yet
                "planet": "", # not known yet
                "city": "" # not known yet
                }

            mission.pickup_locations[package_number] = pickup_location
            mission.drop_off_locations[package_number] = drop_off_location
            mission.packages.add(package_number)
            
            mission_package.mission_id = mission.id
            mission_package.package_id = package_number
            mission_package.pickup_location_ref = pickup_location
            mission_package.drop_off_location_ref = drop_off_location
            mission.mission_packages.append(mission_package)

        return mission


# Optional: Configure logging
logging.basicConfig(level=logging.INFO)
