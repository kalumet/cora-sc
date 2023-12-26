import Levenshtein
import random

from fuzzywuzzy import process, fuzz
from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission
from wingmen.star_citizen_services.uex_api import UEXApi


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print_debug(to_print)

class LocationNameMatching:
    @staticmethod
    def validate_location_names(delivery_mission: DeliveryMission):
        MIN_SIMILARITY_THRESHOLD = 50
        MIN_SIMILARITY_SATELLITE_THRESHOLD = 50

        uex_service = UEXApi()
        tradeports = uex_service.get_data("tradeports")
        satellites = uex_service.get_data("satellites")

        for package_number in delivery_mission.packages:
            matched_pickup_location = None
            max_pickup_similarity = 0

            matched_dropoff_location = None
            max_dropoff_similarity = 0

            pickup_location = delivery_mission.pickup_locations[package_number]
            dropoff_location = delivery_mission.drop_off_locations[package_number]

            pickup_location_name = pickup_location["name"]
            dropoff_location_name = dropoff_location["name"]

            found_pickup_location = False
            found_dropoff_location = False

            # print_debug(
            #     f'Checking pickup location "{pickup_location_name}" in trading database'
            # )
            # print_debug(
            #     f'Checking dropoff location "{dropoff_location_name}" in trading database'
            # )

            for tradeport in tradeports.values():
                validated_name = tradeport["name"]

                # Check for exact match
                if not found_pickup_location and validated_name == pickup_location_name:
                    found_pickup_location = True
                    matched_pickup_location = tradeport

                if (
                    not found_dropoff_location
                    and validated_name == dropoff_location_name
                ):
                    found_dropoff_location = True
                    matched_dropoff_location = tradeport

                # Check satellite name for pickup location
                if not found_pickup_location and "satellite" in tradeport:
                    satellite = satellites.get(tradeport["satellite"], {})
                    similarity = _calculate_similarity(
                        pickup_location.get("satellite", "").lower(),
                        satellite.get("name", "").lower(),
                        MIN_SIMILARITY_SATELLITE_THRESHOLD,
                    )
                    if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                        # we found a similar satellite so we'll use this
                        pickup_location["satellite"] = satellite.get("code", "")

                        # Check location name similarity
                        similarity = _calculate_similarity(
                            pickup_location_name.lower(),
                            validated_name.lower(),
                            MIN_SIMILARITY_THRESHOLD,
                        )
                        if similarity > max_pickup_similarity:
                            matched_pickup_location = tradeport
                            max_pickup_similarity = similarity

                # Check satellite name for dropoff location
                if not found_dropoff_location and "satellite" in tradeport:
                    satellite = satellites.get(tradeport["satellite"], {})
                    similarity = _calculate_similarity(
                        dropoff_location.get("satellite", "").lower(),
                        satellite.get("name", "").lower(),
                        MIN_SIMILARITY_SATELLITE_THRESHOLD,
                    )
                    if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                        # we found a similar satellite so we'll use this
                        dropoff_location["satellite"] = satellite.get("code", "")

                        # Check location name similarity
                        similarity = _calculate_similarity(
                            dropoff_location_name.lower(),
                            validated_name.lower(),
                            MIN_SIMILARITY_THRESHOLD,
                        )
                        if similarity > max_dropoff_similarity:
                            matched_dropoff_location = tradeport
                            max_dropoff_similarity = similarity

            _process_matched_location(
                pickup_location, matched_pickup_location, "pickup"
            )
            _process_matched_location(
                dropoff_location, matched_dropoff_location, "dropoff"
            )


def _calculate_similarity(str1, str2, threshold):
    distance = Levenshtein.distance(str1, str2)
    similarity = 100 - (100 * distance / max(len(str1), len(str2)))
    return similarity if similarity >= threshold else 0


def _process_matched_location(location, matched_location, location_type):
    if matched_location:
        # print_debug(
        #     f"Matched found for {location_type} ({location['name']}): {matched_location['name']}"
        # )
        for key in location:
            if key in matched_location:
                location[key] = matched_location[key]
    else:  # we only have a satellite + a name of the location (probably derelict outpost), create a unique code of the location
        location["code"] = ''.join(word[0] for word in location["name"].split()).upper()
        location["code"] += str(random.randint(300, 400))
