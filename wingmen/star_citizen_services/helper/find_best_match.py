import json
from fuzzywuzzy import process


DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


def find_best_match(search_term, search_space, attribute=None, score_cutoff=80):
    if search_term is None:
        return "No search term", False

    if search_space is None:
        return "No search space available", False

    if DEBUG:

        serialized_object = json.dumps(search_space, indent=2)
        # Now, slicing the string to only include the first N characters
        truncated_serialized_object = serialized_object[:150]
        print(f'Searching "{search_term}" within attribute "{attribute}" of search space \n{truncated_serialized_object}...')

    best = __find_best_match(search_term, search_space, attribute=attribute, score_cutoff=score_cutoff)
    if best is None:
        return f"No match for {search_term} found", False

    return best, True


def __find_best_match(search_term, search_space, attribute=None, path=None, current_best=None, score_cutoff=80):
    """
    Recursively searches through a nested data structure (dictionary or list) to find the best match for a given search term.
    The search can be optionally focused on a specific attribute within dictionaries in the data structure.
    
    Parameters:
    - search_term (str): The term to search for within the search space.
    - search_space (dict or list): The data structure to search through. It can be a nested combination of dictionaries and lists.
    - attribute (str, optional): The specific attribute within dictionaries to match against the search term. If None, all values are considered.
    - path (list, optional): Used internally to track the recursive path of keys/indexes to the current point in the search space.
    - current_best (dict, optional): Used internally to track the best match found so far during the search. It stores:
    - score_cutoff (number, optional, default=80) -> allows to control how exact a match should be (0 - 100)

    Returns:
    A dictionary with details of the best match found in the search space, including:
    - The root object containing the match ('root_object')
    - The similarity score of the match ('score')
    - The path to the matched attribute/value ('matching_path')
    - The matched value ('matched_value')
    - The key or index of the root object in the immediate enclosing structure ('key_or_index')

    The function utilizes fuzzy string matching to compare the search term with values or specified attributes in the search space.
    It recursively explores nested dictionaries and lists to identify the most similar match based on the provided search term.
    """
    if current_best is None:
        current_best = {'score': 0, 'matching_path': '', 'matched_value': None, 'key_or_index': None, 'root_object': None}
    if path is None:
        path = []

    if isinstance(search_space, dict):
        for key, value in search_space.items():
            current_path = path + [str(key)]

            if isinstance(value, dict):
                if attribute in value:
                    # Ensure we only search where the attribute exists
                    match = process.extractOne(search_term, [str(value.get(attribute, ''))], score_cutoff=score_cutoff)
                    if match:
                        score = match[1]
                        if score > current_best['score']:
                            current_best.update({
                                'score': score,
                                'matching_path': '.'.join(current_path + [attribute]),
                                'matched_value': value[attribute],
                                'key_or_index': key,
                                'root_object': value
                            })
                __find_best_match(search_term, value, attribute, current_path, current_best, score_cutoff)
                
            elif attribute is None or key == attribute:
                # Handle non-dictionary values directly when no specific attribute is targeted
                targets = [str(value)] if not isinstance(value, (dict, list)) else []
                match = process.extractOne(search_term, targets, score_cutoff=score_cutoff)
                if match:
                    score = match[1]
                    if score > current_best['score']:
                        current_best.update({
                            'score': score,
                            'matching_path': '.'.join(current_path),
                            'matched_value': value,
                            'key_or_index': path[0] if path else key,
                            'root_object': search_space
                        })
 
    elif isinstance(search_space, list):
        for index, item in enumerate(search_space):
            current_path = path + [str(index)]
            if isinstance(item, dict) and attribute and attribute in item:
                # Direct search within list items if they are dictionaries with the target attribute
                match = process.extractOne(search_term, [str(item.get(attribute, ''))], score_cutoff=score_cutoff)
                if match:
                    score = match[1]
                    if score > current_best['score']:
                        current_best.update({
                            'score': score,
                            'matching_path': '.'.join(current_path + [attribute]),
                            'matched_value': item[attribute],
                            'key_or_index': index,
                            'root_object': item
                        })
            else:
                # Recursive search for items that are dictionaries or lists themselves
                __find_best_match(search_term, item, attribute, current_path, current_best, score_cutoff)

    return current_best


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
    best_test = __find_best_match(search_term, data, "space_station_name")
    print(f"Key/Index of the root object: {best_test['key_or_index']}")
    print(f"Root Object: {best_test['root_object']}")
    print(f"Score of match: {best_test['score']}")
    print(f"Path to the matched attribute: {best_test['matching_path']}")
    print(f"Matched value: {best_test['matched_value']}")

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

    best_test = __find_best_match(search_term, data, "space_station_name")
    print(f"Key/Index of the root object: {best_test['key_or_index']}")
    print(f"Root Object: {best_test['root_object']}")
    print(f"Score of match: {best_test['score']}")
    print(f"Path to the matched attribute: {best_test['matching_path']}")
    print(f"Matched value: {best_test['matched_value']}")

