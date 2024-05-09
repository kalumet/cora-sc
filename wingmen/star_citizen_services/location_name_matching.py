import random
import Levenshtein
import re
import json
import os

from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.helper import find_best_match


DEBUG = False
regex_remove_control_characters = r'[^\S ]'


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class LocationNameMatching:
    @staticmethod
    def validate_location_names(delivery_mission: DeliveryMission, data_dir_path):
        MIN_SIMILARITY_THRESHOLD = 50
        MIN_SIMILARITY_SATELLITE_THRESHOLD = 50

        uex_service = UEXApi2()
        outposts = uex_service.get_data("outposts")
        moons = uex_service.get_data("moons")
        orbits = uex_service.get_data("orbits")
        unknown_outposts = {}  # name -> code, satellite

        filename = f"{data_dir_path}/unknown_locations.json"
        if os.path.exists(filename):
            with open(filename, 'r', encoding="UTF-8") as file:
                unknown_outposts = json.load(file)

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

            for outpost in outposts.values():
                validated_name = outpost["name"]

                # Check for exact match
                if not found_pickup_location and validated_name == pickup_location_name:
                    found_pickup_location = True
                    matched_pickup_location = outpost

                if (
                    not found_dropoff_location
                    and validated_name == dropoff_location_name
                ):
                    found_dropoff_location = True
                    matched_dropoff_location = outpost

                # Check satellite name for pickup location
                moon = moons.get(str(outpost["id_moon"]), {})
                orbit = orbits.get(str(outpost["id_orbit"]), {})
                if not found_pickup_location:
                    
                    similarity = _calculate_similarity(
                        pickup_location.get("satellite", "").lower(),
                        moon.get("name", "").lower(),
                        MIN_SIMILARITY_SATELLITE_THRESHOLD,
                    )
                    if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                        # we found a similar satellite so we'll use this
                        pickup_location["satellite"] = moon.get("code", "")
                    else:
                        similarity = _calculate_similarity(
                            pickup_location.get("satellite", "").lower(),
                            orbit.get("name", "").lower(),
                            MIN_SIMILARITY_SATELLITE_THRESHOLD,
                        )
                        if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                            # we found a similar satellite so we'll use this
                            pickup_location["planet"] = orbit.get("code", "")
                            pickup_location["satellite"] = ""

                    # Check location name similarity
                    similarity = _calculate_similarity(
                        pickup_location_name.lower(),
                        validated_name.lower(),
                        MIN_SIMILARITY_THRESHOLD,
                    )
                    if similarity > max_pickup_similarity:
                        matched_pickup_location = outpost
                        max_pickup_similarity = similarity

                # Check satellite name for dropoff location
                if not found_dropoff_location:
                    similarity = _calculate_similarity(
                        dropoff_location.get("satellite", "").lower(),
                        moon.get("name", "").lower(),
                        MIN_SIMILARITY_SATELLITE_THRESHOLD,
                    )
                    if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                        # we found a similar satellite so we'll use this
                        dropoff_location["satellite"] = moon.get("code", "")
                    else:
                        similarity = _calculate_similarity(
                            dropoff_location.get("satellite", "").lower(),  # at this point, only satellite is filled
                            orbit.get("name", "").lower(),
                            MIN_SIMILARITY_SATELLITE_THRESHOLD,
                        )
                        if similarity > MIN_SIMILARITY_SATELLITE_THRESHOLD:
                            # we found a similar satellite so we'll use this
                            dropoff_location["planet"] = orbit.get("code", "")
                            dropoff_location["satellite"] = ""

                    # Check location name similarity
                    similarity = _calculate_similarity(
                        dropoff_location_name.lower(),
                        validated_name.lower(),
                        MIN_SIMILARITY_THRESHOLD,
                    )
                    if similarity > max_dropoff_similarity:
                        matched_dropoff_location = outpost
                        max_dropoff_similarity = similarity

            _process_matched_location(
                pickup_location, matched_pickup_location, unknown_outposts, "pickup"
            )
            _process_matched_location(
                dropoff_location, matched_dropoff_location, unknown_outposts, "dropoff"
            )

            with open(filename, 'w', encoding="UTF-8") as file:
                json.dump(unknown_outposts, file, indent=3)
    
    @staticmethod
    def validate_associated_location_name(location_name, terminal, min_similarity=80):
        if not terminal or not location_name:
            print_debug(f"cannot validate kiosk location, as terminal or location name not provided.")
            return False
        
        print_debug(f'checking {location_name} against given terminal {terminal["nickname"]}')

        # usually, the terminal name of commodity kiosk matches the location name, therefore, we expact a high similarity
        matching_result, success = find_best_match.find_best_match(location_name, terminal, attributes=["nickname", "name", "space_station_name", "outpost_name", "city_name"], score_cutoff=min_similarity)
        
        
        if not success:
            print_debug(f"Kiosk location name '{location_name}' doesn't match the terminal \n{json.dumps(terminal['nickname'], indent=2)}")
            return False
        
        return True


def _calculate_similarity(str1, str2, threshold):
    str1 = re.sub(r'[^\S ]', '', str1)
    str2 = re.sub(r'[^\S ]', '', str2)
    distance = Levenshtein.distance(str1, str2)
    similarity = 100 - (100 * distance / max(len(str1), len(str2), 1))
    print_debug(f"Levenshtein distance '{str1}'->'{str2}'={distance}, similarity={similarity}")
    return similarity if similarity >= threshold else 0


def _process_matched_location(location, matched_location, unknown_outposts, location_type):
    if matched_location:
        location["name"] = matched_location["name"]
        location["code"] = matched_location["id"]
        location["satellite"] = matched_location["moon_name"]
        location["planet"] = matched_location["orbit_name"]
        return
    
    # unknown location, check if we have a similar name on the same moon in the unknown_outposts. If yes, we assume the same location
    for name, values in unknown_outposts.items():
        similarity = _calculate_similarity(location["name"].lower(), name.lower(), 90)
        if similarity > 90:
            moons_matching = _calculate_similarity(location['satellite'], values['satellite'], 90)
            if moons_matching > 90:  # we found a similar location on the same moon, we assume the same outpost
                location["name"] = values["name"]
                location["code"] = values["code"]
                location["satellite"] = values["satellite"]
                return
        
    # new unknown location on this moon (no tradeport found at uex), create a unique code of the location
    location["code"] = ''.join(word[0] for word in location["name"].split()).upper()
    location["code"] += str(random.randint(300, 400))
    unknown_outposts[location['name']] = location
