import json
import Levenshtein


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


def find_best_match(search_term: str, search_space, attribute=None, score_cutoff=80):
    if search_term is None:
        return "No search term", False

    if search_space is None:
        return "No search space available", False

    if DEBUG:
        serialized_object = json.dumps(search_space, indent=2)
        truncated_serialized_object = serialized_object[:150]
        print(f'Searching "{search_term}" within attribute "{attribute}" of search space \n{truncated_serialized_object}...')

    best = __find_best_match(search_term.lower(), search_space, attribute=attribute, score_cutoff=score_cutoff)
    if best["matched_value"] is None:
        return f"No match for {search_term} found", False

    return best, True


def __find_best_match(search_term, search_space, attribute=None, path=None, current_best=None, score_cutoff=80):
    if current_best is None:
        current_best = {'score': 0, 'matching_path': '', 'matched_value': None, 'key_or_index': None, 'root_object': None}
    if path is None:
        path = []

    if isinstance(search_space, dict):
        for key, value in search_space.items():
            current_path = path + [str(key)]

            if isinstance(value, dict) or isinstance(value, list):
                __find_best_match(search_term, value, attribute, current_path, current_best, score_cutoff)
            else:
                if attribute is None or key == attribute:
                    compare = str(value).lower()
                    lev_distance = Levenshtein.distance(search_term, compare)
                    score = __normalized_score(lev_distance, search_term, compare)
                    print_debug(f"comparing: {search_term} <-> {compare}, score: {score}")
                    if score >= score_cutoff and score > current_best['score']:
                        current_best.update({
                            'score': score,
                            'matching_path': '.'.join(current_path),
                            'matched_value': value,
                            'key_or_index': key,
                            'root_object': search_space
                        })
    
    elif isinstance(search_space, list):
        for index, item in enumerate(search_space):
            current_path = path + [str(index)]
            if isinstance(item, list) or isinstance(item, dict):
                __find_best_match(search_term, item, attribute, current_path, current_best, score_cutoff)
            elif isinstance(item, str):
                compare = item.lower()
                lev_distance = Levenshtein.distance(search_term, compare)
                score = __normalized_score(lev_distance, search_term, compare)
                print_debug(f"comparing: {search_term} <-> {compare}, score: {score}")
                if score >= score_cutoff and score > current_best['score']:
                    current_best.update({
                        'score': score,
                        'matching_path': str(index),
                        'matched_value': item,
                        'key_or_index': index,
                        'root_object': search_space
                    })

    return current_best


def __normalized_score(lev_distance, search_term, target):
    max_length = max(len(search_term), len(target))
    if max_length == 0:
        return 100  # Perfekte Übereinstimmung, wenn beide Strings leer sind
    score = max(0, (1 - lev_distance / max_length) * 100)
    return score


# Example usage
if __name__ == "__main__":
    data = {
        "242": {
            "id": 242,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 339,
            "id_moon": 0,
            "id_space_station": 17,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L1",
            "nickname": "MIC-L1",
            "code": "REFINE-MICL1",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937380,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 1",
            "moon_name": None,
            "space_station_name": "MIC-L1 Shallow Frontier Station",
            "outpost_name": None,
            "city_name": None
        },
        "243": {
            "id": 243,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 340,
            "id_moon": 0,
            "id_space_station": 18,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L2",
            "nickname": "MIC-L2",
            "code": "REFINE-MICL2",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937199,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 2",
            "moon_name": None,
            "space_station_name": "MIC-L2 Long Forest Station",
            "outpost_name": None,
            "city_name": None
        },
        "244": {
            "id": 244,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 343,
            "id_moon": 0,
            "id_space_station": 21,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L5",
            "nickname": "MIC-L5",
            "code": "REFINE-MICL5",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937210,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 5",
            "moon_name": None,
            "space_station_name": "MIC-L5 Modern Icarus Station",
            "outpost_name": None,
            "city_name": None
        }
    }
    search_term = "MIC-L2 Long Forest Station"

    print(f"\n======Test 1========")
    best_test, success = find_best_match(search_term, data, "space_station_name")
    if success:
        print(f"Key/Index of the root object: {best_test['key_or_index']}")
        print(f"Root Object: {best_test['root_object']}")
        print(f"Score of match: {best_test['score']}")
        print(f"Path to the matched attribute: {best_test['matching_path']}")
        print(f"Matched value: {best_test['matched_value']}")
    else:
        print("Error test 1")

    print(f"\n======Test 2========")
    data = [
        {
            "id": 242,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 339,
            "id_moon": 0,
            "id_space_station": 17,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L1",
            "nickname": "MIC-L1",
            "code": "REFINE-MICL1",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937380,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 1",
            "moon_name": None,
            "space_station_name": "MIC-L1 Shallow Frontier Station",
            "outpost_name": None,
            "city_name": None
        },
        {
            "id": 243,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 340,
            "id_moon": 0,
            "id_space_station": 18,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L2",
            "nickname": "MIC-L2",
            "code": "REFINE-MICL2",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937199,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 2",
            "moon_name": None,
            "space_station_name": "MIC-L2 Long Forest Station",
            "outpost_name": None,
            "city_name": None
        },
        {
            "id": 244,
            "id_star_system": 68,
            "id_planet": 190,
            "id_orbit": 343,
            "id_moon": 0,
            "id_space_station": 21,
            "id_outpost": 0,
            "id_city": 0,
            "name": "Refinement Processing - MIC-L5",
            "nickname": "MIC-L5",
            "code": "REFINE-MICL5",
            "type": "refinery",
            "has_container_transfer": 0,
            "date_added": 1704937210,
            "date_modified": 0,
            "star_system_name": "Stanton",
            "planet_name": "MicroTech",
            "orbit_name": "microTech Lagrange Point 5",
            "moon_name": None,
            "space_station_name": "MIC-L5 Modern Icarus Station",
            "outpost_name": None,
            "city_name": None
        }
    ]

    best_test, success = find_best_match(search_term, data, "space_station_name")
    if success:
        print(f"Key/Index of the root object: {best_test['key_or_index']}")
        print(f"Root Object: {best_test['root_object']}")
        print(f"Score of match: {best_test['score']}")
        print(f"Path to the matched attribute: {best_test['matching_path']}")
        print(f"Matched value: {best_test['matched_value']}")
    else:
        print("Error test 2")

    print(f"\n======Test 3========")

    best_test, success = find_best_match(search_term, data)
    if success:
        print(f"Key/Index of the root object: {best_test['key_or_index']}")
        print(f"Root Object: {best_test['root_object']}")
        print(f"Score of match: {best_test['score']}")
        print(f"Path to the matched attribute: {best_test['matching_path']}")
        print(f"Matched value: {best_test['matched_value']}")
    else:
        print("Error test 3.")

    print(f"\n======Test 4========")
    data = [
        "ARCL1",
        "ARCL2",
        "ARCL4",
        "CRUL1",
        "HURL1",
        "HURL2",
        "MAGNG",
        "MICL1",
        "MICL2",
        "MICL5",
        "PYROG",
        "TERRG",
    ]

    best_test, success = find_best_match(search_term, data, score_cutoff=0)
    if success:
        print(f"Key/Index of the root object: {best_test['key_or_index']}")
        print(f"Root Object: {best_test['root_object']}")
        print(f"Score of match: {best_test['score']}")
        print(f"Path to the matched attribute: {best_test['matching_path']}")
        print(f"Matched value: {best_test['matched_value']}")
    else:
        print("Error test 4.")
