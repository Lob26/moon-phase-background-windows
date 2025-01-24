import ctypes
import datetime
import math
import os
import shutil
import subprocess
import time

import requests

current_directory = os.path.dirname(os.path.abspath(__file__))
magick_exe = shutil.which("magick")


def set_wallpaper(file_path: str):
    ctypes.windll.user32.SystemParametersInfoW(20, 0, file_path, 3)


def generate_wallpaper(is_big: bool = False):
    if not magick_exe:
        print("ImageMagick not found")
        raise SystemError
    back_tif_path = os.path.join(current_directory, "back.tif")
    best_tif_path = os.path.join(
        current_directory, "best.tif" if is_big else "best_small.tif"
    )
    # Get current hour of the year
    now = datetime.datetime.now()
    num = math.floor((now.timetuple().tm_yday) * 24 + now.hour)
    # Get phase/illumination% from text file edited from "https://svs.gsfc.nasa.gov/vis/a000000/a005100/a005187/mooninfo_2024.txt"
    with open(os.path.join(current_directory, "data", "phase.txt")) as phase_file:
        phase = phase_file.readlines()[num].strip()

    # Get age: days in moon cycle so far
    with open(os.path.join(current_directory, "data", "age.txt")) as age_file:
        age = age_file.readlines()[num].strip()

    # Caption
    text = f"Phase: {phase}% Days: {age}"

    # Filename for downloaded image
    im = f"moon.{num:04d}.tif"
    im_path = os.path.join(current_directory, im)

    # URLs updated for 2025
    base_url = "https://svs.gsfc.nasa.gov/vis/a000000/a005400/a005415/frames"
    image_url = (
        f"{base_url}/5760x3240_16x9_30p/plain/{im}"
        if is_big
        else f"{base_url}/3840x2160_16x9_30p/plain/{im}"
    )
    response = requests.get(image_url)
    with open(im_path, "wb") as image_file:
        image_file.write(response.content)

    # Wait for the download to complete
    time.sleep(2)

    # Replace original file with designated background file and add background and caption with ImageMagick
    subprocess.run(
        [
            magick_exe,
            "composite",
            "-gravity",
            "center",
            im_path,
            best_tif_path,
            back_tif_path,
        ]
    )  # type:ignore

    font_size = 80 if is_big else 50
    subprocess.run(
        [
            magick_exe,
            "magick convert",
            "-font",
            "Verdana",
            "-fill",
            "#b1ada7",
            "-pointsize",
            str(font_size),
            "-gravity",
            "east",
            "-draw",
            f"text {'150,1800' if is_big else '100,1200'} '{text}'",
            back_tif_path,
            back_tif_path,
        ]
    )  # type:ignore

    # Set desktop background using ctypes
    set_wallpaper(back_tif_path)

    # Print to .log file
    log_file_path = os.path.join(current_directory, ".log")
    with open(log_file_path, "a") as log_file:
        log_file.write(f"{now} - {text}\n")

    # Remove downloaded moon file to avoid using up storage
    os.remove(im_path)


if __name__ == "__main__":
    generate_wallpaper()
