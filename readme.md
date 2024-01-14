## Original Repository Credits:
This script is inspired by and adapted from the [moon-phase-background](https://github.com/desertplant/moon-phase-background) repository by [desertplant](https://github.com/desertplant). The original script was designed for Linux Mint Cinnamon, and this adaptation brings similar functionality to Windows using Python.

# moon-phase-background
Change background picture to high resolution picture of the current moon phase from NASA

This Python script downloads a high-resolution image of the current moon phase from NASA's Dial-A-Moon website [NASA Dial-A-Moon](https://svs.gsfc.nasa.gov/5187/), overlays it onto a background image of stars, labels the image with the phase in percent and the age of the current moon cycle, and sets it as a background image on Windows.

**best.tif** is an example picture. (Resolution 5641x3650 by default, 8192x5641 is possible too.)

For automatic desktop background updates, it is recommended to run the script on a schedule using Task Scheduler.

The downloaded images are deleted immediately to avoid polluting storage.

## Requirements:
- Python 3.x.x
- ImageMagick (Ensure 'magick' is in the system's PATH)

## Installation:
1. Clone the repository wherever you want to.
2. Execute `setup_environment.bat`
3. Wait for the time to be a close hour. Ex: 12:00

It will download a moon image file, change your desktop background, and then delete the downloaded image again (to avoid polluting storage space). The file back.tif is your new background image now.

## Configuration:
- **Resolution**:
  - Default resolution: 5631x3640
  - For 8192x5641: Set `isBig = true` in the script.
  - For lower resolutions, more complex changes may be needed.

- **Positioning**:
  - Size and position of moon and text field customizable by changing ImageMagick commands.

- **Background Image**:
  - best_small.tif is the default background image for `isBig = false` (best.tif for `isBig = true`).
  - Can be replaced with a different background image.

- **System**:
  - Made for Windows.
  - No adjustment needed for system compatibility.

## Uninstall
To uninstall, simply delete the folder with all the files you downloaded. Don't forget to remove any Task Scheduler tasks or references you may have created.

## Image Credits:
The moon phase image is downloaded from NASA's Dial-A-Moon website: [NASA Dial-A-Moon](https://svs.gsfc.nasa.gov/5187/). Thank you to NASA's Scientific Visualization Studio for creating these high-resolution visualizations of the moon and making them available to the public. For more information about how these images were created and on the moon itself, see the link above.

## Example Image:

![back](https://user-images.githubusercontent.com/87530028/126072284-342387cc-6c75-4d2e-8200-64035ced6952.jpg)
