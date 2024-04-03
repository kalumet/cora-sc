import datetime
import random
import os
import traceback
import cv2
import pygetwindow
import pyautogui

from services.printr import Printr

DEBUG = True
TEST = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


printr = Printr()


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
    if not show_screenshot:
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
