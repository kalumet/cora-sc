import datetime
import random
import os
import traceback
import cv2
import pygetwindow
import pyautogui

DEBUG = False
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


def take_screenshot(data_dir_path, *subdirectories, **image_name_placeholders):
    """
    Captures and saves a screenshot of the active window if it meets specific criteria,
    optionally returning a random image from a directory in test mode.

    This function captures the entire area of the currently active window, if the window title
    contains "Star Citizen". The screenshot is saved to a directory that is constructed from
    the provided path components. The filename is generated using a combination of provided
    placeholders and a timestamp.

    In test mode, instead of taking a screenshot, a random image from the "examples" directory
    is returned if existing.

    Args:
        data_dir_path (str): The root directory path where the screenshots directory exists or will be created.
        *subdirectories (str): Variable length argument list specifying subdirectories under the root directory.
        test (bool, optional): If True, function operates in test mode and returns a random image. Defaults to False.
        **image_name_placeholders (dict): Keyword arguments that are used to construct the filename of the screenshot
                                          with key-value pairs joined by dashes. Each key-value pair is separated by an underscore.

    Returns:
        str: The full path to the saved screenshot, or a random image if in test mode. None if conditions aren't met.
    """
    
    # Format the path for subdirectories correctly
    subdir_path = "/".join(subdirectories)
    path = data_dir_path
    
    if TEST:
        path = os.path.join(path, 'examples', subdir_path)
        return random_image_from_directory(path)
    
    path = os.path.join(data_dir_path, 'screenshots', subdir_path)

    if not os.path.exists(path):
        os.makedirs(path)

    active_window = pygetwindow.getActiveWindow()
    if active_window and "Star Citizen" in active_window.title:
        # Capture the current time
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")  # Format: YearMonthDay_HourMinuteSecond_Milliseconds

        # Process placeholders in the filename
        placeholder_part = "_".join(f"{key}-{value}" for key, value in image_name_placeholders.items())

        # Create the full path and filename
        filename = f"screenshot_{placeholder_part}_{timestamp}.png"
        full_path = os.path.normpath(os.path.join(path, filename))

        # Determine window position and size
        x, y, width, height = active_window.left, active_window.top, active_window.width, active_window.height
        # Take a screenshot of the specified area
        screenshot = pyautogui.screenshot(region=(x, y, width, height))
        screenshot.save(full_path)
        return full_path
    return None


def random_image_from_directory(data_dir_path):
    """
    Selects a random image from a specified directory.

    Args:
    directory (str): Path to the directory containing images.
    image_extensions (list, optional): List of acceptable image file extensions.

    Returns:
    str: Path to a randomly selected image.
    """
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    # List all files in the directory
    files = os.listdir(data_dir_path)

    # Filter files to get only those with the specified extensions
    images = [file for file in files if any(file.endswith(ext) for ext in image_extensions)]

    if not images:
        return None  # No images found

    # Randomly select an image
    image = random.choice(images)
    full_path = os.path.join(data_dir_path, image)
    print_debug(f"returning random image {full_path}")
    return full_path


def debug_show_screenshot(image, show_screenshot):
    if not show_screenshot or image is None:
        return
    print_debug("displaying image, press Enter to continue")
    try:
        # Zeige den zugeschnittenen Bereich an
        cv2.imshow("Cropped Screenshot", image)
        while True:
            if cv2.waitKey(0) == 13:  # Warten auf die Eingabetaste (Enter)
                break
        cv2.destroyAllWindows()
    except Exception:
        traceback.print_exc()
        print_debug("could not display image")
        return


def __get_best_template_matching_coordinates(data_dir_path, screenshot, area, requested_corner_coordinates):
    highest_score = -1
    matching_coordinates = None
    next_template_index = 1

    while True:
        filename = f"{data_dir_path}/templates/template_{area.lower()}_{next_template_index}.png"
        if not os.path.exists(filename):
            break  # Exit the loop if the template file does not exist

        template = cv2.imread(filename, cv2.IMREAD_COLOR)
        if template is None:
            break  # If the template could not be read, perhaps log an error

        # debug_show_screenshot(template, DEBUG)
        # Perform the template matching
        proof_position = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(proof_position)

        # Update the best match if the current score is higher
        if max_val > highest_score:
            highest_score = max_val
            h, w, _ = template.shape
            # Adjust the coordinates based on the requested corner
            if requested_corner_coordinates == "LOWER_LEFT":
                matching_coordinates = (max_loc[0], max_loc[1] + h)
            elif requested_corner_coordinates == "LOWER_RIGHT":
                matching_coordinates = (max_loc[0] + w, max_loc[1] + h)
            elif requested_corner_coordinates == "UPPER_RIGHT":
                matching_coordinates = (max_loc[0] + w, max_loc[1])
            elif requested_corner_coordinates == "UPPER_LEFT":
                matching_coordinates = max_loc
            else:
                raise ValueError(f"Unknown requested_corner_coordinates: {requested_corner_coordinates}")

        next_template_index += 1

    return matching_coordinates


def crop_screenshot(data_dir_path, screenshot_file, areas_and_corners_and_cropstrat):
    """
    Crops a screenshot based on template matching against specified areas of the screenshot. This method supports 
    flexible cropping strategies, allowing for area-based, vertical, or horizontal cropping.

    Args:
    - data_dir_path (str): The directory path where template images are stored.
    - screenshot_file (str): The file path of the screenshot image to be cropped.
    - areas_and_corners_and_cropstrat (list of tuples): A list where each tuple contains:
        - area (str): The area name that corresponds to a template image ("UPPER_LEFT" or "LOWER_RIGHT").
        - corner (str): The corner of interest from the template matching result. Valid values are "UPPER_LEFT",
                        "LOWER_LEFT", "UPPER_RIGHT", and "LOWER_RIGHT".
        - crop_strategy (str): The cropping strategy to apply. Valid values are "AREA" for cropping based on the
                               area between two corners, "VERTICAL" for cropping vertically based on x-coordinates, 
                               and "HORIZONTAL" for cropping horizontally based on y-coordinates.

    Returns:
    - cropped_screenshot (ndarray or None): The cropped screenshot as a numpy ndarray. Returns None if the cropping 
                                            cannot be performed due to invalid dimensions or if no matching templates 
                                            are found.

    The function first checks if the screenshot file exists. It then reads the screenshot and initializes cropping 
    coordinates to the full image dimensions. For each specified area and corner, it attempts to match the corresponding 
    template within the screenshot. Depending on the cropping strategy, it adjusts the cropping coordinates accordingly.
    
    If only "VERTICAL" or "HORIZONTAL" strategies are applied without "AREA", it ensures that the cropping does not adjust 
    the unspecified dimension beyond the screenshot's bounds. The method finally crops the screenshot based on the determined 
    coordinates and returns the cropped image. If no valid crop dimensions are found, or if a matching template is not 
    detected, it logs an error and returns None.
    """
    if not os.path.exists(screenshot_file):
        print_debug(f"File not existing '{screenshot_file}'")
        return None  # Exit the loop if the template file does not exist

    screenshot = cv2.imread(screenshot_file, cv2.IMREAD_COLOR)
    
    # Assume full image dimensions initially
    x_min, y_min = 0, 0
    x_max, y_max = screenshot.shape[1], screenshot.shape[0]

    # Flags to check if any VERTICAL or HORIZONTAL strategy is applied
    vertical_applied = False
    horizontal_applied = False

    for area, corner, crop_strategy in areas_and_corners_and_cropstrat:
        matching_coordinates = __get_best_template_matching_coordinates(data_dir_path, screenshot, area, corner)
        if matching_coordinates:
            x, y = matching_coordinates

            if crop_strategy == "AREA":
                # Adjust based on the strategy
                x_min = min(x_max, x)
                x_max = max(x_min, x)
                y_min = min(y_max, y)
                y_max = max(y_min, y)

            elif crop_strategy == "VERTICAL":
                vertical_applied = True
                if corner in ["UPPER_LEFT", "LOWER_LEFT"]:
                    x_min = x
                if corner in ["UPPER_RIGHT", "LOWER_RIGHT"]:
                    x_max = x

            elif crop_strategy == "HORIZONTAL":
                horizontal_applied = True
                if corner in ["UPPER_LEFT", "UPPER_RIGHT"]:
                    y_min = y
                if corner in ["LOWER_LEFT", "LOWER_RIGHT"]:
                    y_max = y
        else:
            print_debug(f"No match found for {area} with {corner} corner.")
            continue

    # For VERTICAL strategy, if only one side is defined, don't adjust the other side
    if vertical_applied:
        x_max = screenshot.shape[1] if x_max == 0 else x_max
    # For HORIZONTAL strategy, if only one side is defined, don't adjust the other side
    if horizontal_applied:
        y_max = screenshot.shape[0] if y_max == 0 else y_max

    # Perform the cropping
    if x_max > x_min and y_max > y_min:
        cropped_screenshot = screenshot[y_min:y_max, x_min:x_max]
        return cropped_screenshot
    else:
        print_debug("Invalid crop dimensions.")
        return None


# Example usage
if __name__ == "__main__":
    data_dir_path_test = "star_citizen_data/mining-data/"
    screenshot_file_test = "star_citizen_data/mining-data/examples/ScreenShot-2024-04-02_09-36-15-B2C.jpg"
    areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    debug_show_screenshot(cropped_image, DEBUG)

    areas_and_corners = [("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"), ("LOWER_RIGHT", "LOWER_RIGHT", "VERTICAL")]
    cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    debug_show_screenshot(cropped_image, DEBUG)

    areas_and_corners = [("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"), ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL")]
    cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    debug_show_screenshot(cropped_image, DEBUG)

    areas_and_corners = [("UPPER_LEFT", "UPPER_LEFT", "HORIZONTAL"), ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL")]
    cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    debug_show_screenshot(cropped_image, DEBUG)
