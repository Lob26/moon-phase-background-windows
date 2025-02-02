import logging
import os
import shutil
import subprocess
from ctypes import windll
from datetime import datetime

import requests

logging.basicConfig(
    filename=".log", level=logging.INFO, format="%(asctime)s - %(message)s"
)
logger = logging.getLogger(__name__)


def set_wallpaper(file_path: str | os.PathLike[str]):
    windll.user32.SystemParametersInfoW(20, 0, file_path, 3)


def generate_wallpaper(is_big: bool = False):
    CURRENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
    MAGICK_EXE = shutil.which("magick")

    if not MAGICK_EXE:
        logger.error("ImageMagick not found")
        raise SystemError

    BACK_TIF_PATH = os.path.join(CURRENT_DIRECTORY, "back.tif")
    BEST_TIF_PATH = os.path.join(CURRENT_DIRECTORY, "best.tif" if is_big else "best_small.tif")  # fmt:skip

    # Get current hour of the year
    now = datetime.now()
    num = (now.timetuple().tm_yday) * 24 + now.hour

    # Get phase/illumination% from text file edited from "https://svs.gsfc.nasa.gov/vis/a000000/a005100/a005187/mooninfo_2024.txt"
    data_dir = os.path.join(CURRENT_DIRECTORY, "data")

    with (
        open(os.path.join(data_dir, "phase.txt")) as phase_file,
        open(os.path.join(data_dir, "age.txt")) as age_file,
    ):
        phase = phase_file.readlines()[num].strip()
        age = age_file.readlines()[num].strip()

    # Caption
    label = f"Phase: {phase}% Days: {age}"

    # Filename for downloaded image
    im = f"moon.{num:04d}.tif"
    im_path = os.path.join(CURRENT_DIRECTORY, im)

    # URLs updated for 2025
    base_url = "https://svs.gsfc.nasa.gov/vis/a000000/a005400/a005415/frames"
    image_url = (
        f"{base_url}/5760x3240_16x9_30p/plain/{im}"
        if is_big
        else f"{base_url}/3840x2160_16x9_30p/plain/{im}"
    )

    response = requests.get(image_url, stream=True)
    response.raise_for_status()
    with open(im_path, "wb") as image_file:
        shutil.copyfileobj(response.raw, image_file)
    del response

    # Replace original file with designated background file and add background and caption with ImageMagick
    try:
        subprocess.run(
            [MAGICK_EXE, "composite", "-gravity", "center", im_path, BEST_TIF_PATH, BACK_TIF_PATH],
            check=True,
        )  # fmt:skip
    except subprocess.CalledProcessError as e:
        logger.error(e)
        raise SystemError

    font_size = 80 if is_big else 50
    try:
        subprocess.run(
            [MAGICK_EXE, "convert", "-font", "Verdana", "-fill", "white", "-pointsize", str(font_size), "-gravity", "east", "-draw", f"text {'150,1800' if is_big else '100,1200'} '{label}'", BACK_TIF_PATH, BACK_TIF_PATH],
            check=True,
        )  # fmt:skip
    except subprocess.CalledProcessError as e:
        logger.error(e)
        raise SystemError

    # Set wallpaper
    set_wallpaper(BACK_TIF_PATH)

    logger.info(label)

    # Clean up
    os.remove(im_path)


if __name__ == "__main__":
    generate_wallpaper()
