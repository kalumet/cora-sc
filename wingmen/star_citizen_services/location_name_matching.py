import random
import Levenshtein

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

    @staticmethod
    def validate_tradeport_name(location_name):
        MIN_SIMILARITY_THRESHOLD = 50

        uex_service = UEXApi()
        tradeports = uex_service.get_data("tradeports")
        matched_tradeport = None
        max_location_similarity = 0
        for tradeport in tradeports.values():
            validated_name = tradeport["name"]

            # Check for exact match
            if validated_name == location_name:
                return validated_name, True

            similarity = _calculate_similarity(
                location_name.lower(),
                validated_name.lower(),
                MIN_SIMILARITY_THRESHOLD,
            )
            if similarity > max_location_similarity:
                matched_tradeport = tradeport
                max_location_similarity = similarity

        if matched_tradeport:
            return matched_tradeport, True
        return f"could not identify tradeport {location_name}", False
    
    @staticmethod
    def validate_associated_location_name(location_name, tradeport, min_similarity=50):
        if not tradeport or not location_name:
            return False
        
        MIN_SIMILARITY_THRESHOLD = min_similarity

        # first, check if you get the most likely tradeport name from the screenshort (location_name):
        location_name_tradeport, success = LocationNameMatching.validate_tradeport_name(location_name)

        if success is True:  # screenshot maps to a tradeport, but sal-5 and sal-2 could make a difference
            if tradeport["name"].lower() == location_name_tradeport["name"].lower():
                return True
            #else
                # actually we found a tradeport with what is written in the screenshot?
                # cities "inventories" have usually a very different name than a tradeport within them (i.e. Io North Tower vs Area 18, Central Business District vs Lorville, ...)
                # but stations have inventories and tradeports that are very close to each other ..

            
        # this case is, if the tradeport is at a station or a city. City is quite simple to validate, as we have knowledge about known city names
        # we don't have knowledge about station names. They are part of the tradeport api somehow ... so bit tricky to find the correct one

        uex_service = UEXApi()
        
        # next, we need to check if the tradeport matches the selected local inventory
        # this can either be a city, or a station with multiple trade kiosk
        # if there are multiple trade kiosk at one station, than the names are very similar
        city_code = tradeport.get("city", None)
        
        # easy, if it is a city tradeport
        if city_code:
            city = uex_service.get_data("cities")[city_code]
            # first check if the given name matches the tradeport name. Only a few characters could be different
            similarity = _calculate_similarity(
                    location_name.lower(),
                    city["name"].lower(),
                    MIN_SIMILARITY_THRESHOLD,
                )
            if similarity > 90:  # only 1 or 2 characters are allowed to be wrong
                return True
        
        if success is False:  # we have no tradeport found and no city matching ... no chance to validate
            return False

        satellite_code = location_name_tradeport.get("satellite", None)
        
        if satellite_code != tradeport["satellite"]:
            return False
        
        planet_code = location_name_tradeport.get("planet", None)

        if planet_code != tradeport["planet"]:
            return False
        
        if not planet_code and not location_name_tradeport["planet"]:
            similarity = _calculate_similarity(
                location_name_tradeport["name_short"].lower(),
                tradeport["name_short"].lower(),
                40,
            )
            if similarity > 40:
                return True
            else:
                return False
        
        return True  # basically a guess that chances are high, that it's the same location inventory, but: if player makes error, ai makes error or ocr makes error or any combination thereof -> match of not same tradeports could happen




        tradeport, success = LocationNameMatching.validate_tradeport_name(location_name)
        
        tradeports = uex_service.get_data("tradeports")
        matched_tradeport = None
        max_location_similarity = 0
        for tradeport in tradeports.values():
            validated_name = tradeport["name"]

            # Check for exact match
            if validated_name == location_name:
                return validated_name, True

            similarity = _calculate_similarity(
                location_name.lower(),
                validated_name.lower(),
                MIN_SIMILARITY_THRESHOLD,
            )
            if similarity > max_location_similarity:
                matched_tradeport = tradeport
                max_location_similarity = similarity

        if matched_tradeport:
            return matched_tradeport, True
        return f"could not identify tradeport {location_name}", False


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
