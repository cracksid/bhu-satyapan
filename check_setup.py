"""
check_setup.py - Phase 0: confirm the development setup works.

Run it from the project folder, with the virtual environment active:

    python check_setup.py

It runs five checks in order and stops at the first problem:
  1. Python is 3.11 or newer and running inside the virtual environment
  2. The packages in requirements.txt are installed
  3. The Tesseract OCR program is installed and on PATH
  4. Tesseract's Marathi (mar) and English (eng) language packs are installed
  5. Tesseract can actually read a line of Marathi text
"""

import importlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Make sure Marathi text can be printed even if the output is saved to a file.
sys.stdout.reconfigure(encoding="utf-8")

MIN_PYTHON = (3, 11)

# The packages we need. Left: the name used in "import". Right: the name used
# in "pip install" (they are not always the same).
REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "pytesseract": "pytesseract",
    "streamlit": "streamlit",
    "pytest": "pytest",
}

# Where the Tesseract installer puts tesseract.exe: the first folder if you
# chose "install for anyone using this computer", the second for "just for me".
TESSERACT_FOLDERS = [
    Path(r"C:\Program Files\Tesseract-OCR"),
    Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR",
]

# The Marathi test line: "land owner village". These words have no conjuncts
# (like क्ष) and no ि matra, so they draw correctly with any font setup.
# Full Devanagari rendering is tested properly in Phase 1.
MARATHI_SAMPLE = "जमीन मालक गाव"

# Nirmala UI is a font with Devanagari letters that comes with Windows 10 and 11.
FONT_PATH = Path(r"C:\Windows\Fonts\Nirmala.ttc")


def show(status, message, fix=None):
    """Print one result line, e.g. '[PASS] Python 3.14.7', plus a fix if given."""
    print(f"[{status}] {message}")
    if fix:
        print(f"       How to fix: {fix}")


def check_python():
    """Python must be new enough and running inside a virtual environment."""
    version = platform.python_version()  # e.g. "3.14.7"
    if sys.version_info < MIN_PYTHON:
        show("FAIL", f"Python {version} is too old. This project needs 3.11 or newer.",
             fix="install a newer Python, then create .venv again (README step 2).")
        return False
    show("PASS", f"Python {version}")

    # Inside a virtual environment, sys.prefix is the .venv folder, which is
    # different from sys.base_prefix (the Python it was created from).
    if sys.prefix == sys.base_prefix:
        show("FAIL", "Not running inside the virtual environment.",
             fix=r"run  .\.venv\Scripts\Activate.ps1  and try again "
                 "(no .venv folder yet? Do README step 2 first).")
        return False
    show("PASS", f"Virtual environment: {sys.prefix}")
    return True


def check_packages():
    """Every package in REQUIRED_PACKAGES must be importable."""
    all_installed = True
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            module = importlib.import_module(import_name)
            show("PASS", f"{pip_name} {module.__version__}")
        except ImportError:
            show("FAIL", f"{pip_name} is not installed.")
            all_installed = False
    if not all_installed:
        print("       How to fix: python -m pip install -r requirements.txt")
    return all_installed


def find_tesseract_folder():
    """Return the folder that contains tesseract.exe, or None if not found."""
    for folder in TESSERACT_FOLDERS:
        if (folder / "tesseract.exe").exists():
            return folder
    return None


def check_tesseract():
    """The tesseract program must be on PATH and be version 4 or newer."""
    import pytesseract

    # shutil.which searches PATH, just like typing "tesseract" in a terminal.
    exe_path = shutil.which("tesseract")
    if exe_path is None:
        folder = find_tesseract_folder()
        if folder is None:
            show("FAIL", "Tesseract is not installed.",
                 fix="install it with the UB Mannheim installer (README step 3).")
        else:
            show("FAIL", f"Tesseract is installed in {folder}, but that folder is not on PATH.",
                 fix="add it to PATH (README step 4), then close this terminal and open a new one.")
        return False

    version = pytesseract.get_tesseract_version()
    if version.major < 4:
        show("FAIL", f"Tesseract {version} is too old. This project needs 4.0 or newer.",
             fix="install the latest version (README step 3).")
        return False
    show("PASS", f"Tesseract {version} ({exe_path})")
    return True


def check_language_packs():
    """Tesseract must have the Marathi (mar) and English (eng) language packs."""
    # Run the same command as README step 4 and capture what it prints.
    # The first line is a heading; every line after it is one installed language.
    result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    installed = [line.strip() for line in result.stdout.splitlines()[1:]]
    missing = [lang for lang in ("mar", "eng") if lang not in installed]
    if missing:
        show("FAIL", f"Missing language pack: {', '.join(missing)} "
                     f"(installed: {', '.join(installed) or 'none'}).",
             fix="re-run the Tesseract installer and tick Marathi under "
                 "'Additional language data (download)' (README step 3).")
        return False
    show("PASS", f"Language packs installed: {', '.join(installed)}")
    return True


def check_marathi_reading():
    """Draw a line of Marathi text, ask Tesseract to read it, and compare."""
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont

    if not FONT_PATH.exists():
        show("WARN", f"Font {FONT_PATH} not found, so the reading test was skipped.")
        return True  # the language pack is installed; this test is only a bonus

    # 1. Draw black text on a white image, with a 20-pixel margin all round.
    #    getbbox gives the text's box in pixels: (left, top, right, bottom).
    font = ImageFont.truetype(str(FONT_PATH), size=48)
    _, _, right, bottom = font.getbbox(MARATHI_SAMPLE)
    image = Image.new("L", (right + 40, bottom + 40), color=255)  # "L" = grayscale, 255 = white
    ImageDraw.Draw(image).text((20, 20), MARATHI_SAMPLE, font=font, fill=0)

    # 2. Read it back. "--psm 7" tells Tesseract the image is one line of text.
    raw_text = pytesseract.image_to_string(image, lang="mar", config="--psm 7")
    text_read = " ".join(raw_text.split())  # tidy up extra spaces and line breaks

    print(f"       Drew: {MARATHI_SAMPLE}")
    print(f"       Read: {text_read}")
    if text_read == MARATHI_SAMPLE:
        show("PASS", "Tesseract read the Marathi test line correctly.")
        return True
    # Devanagari letters live in the Unicode block U+0900 to U+097F.
    if any("\u0900" <= char <= "\u097f" for char in text_read):
        show("WARN", "Tesseract read Marathi letters, but not exactly the test line. "
                     "The pack works; Phase 4 measures accuracy properly.")
        return True
    show("FAIL", "Tesseract did not read any Marathi letters.",
         fix="mar.traineddata may be damaged: download it again (README troubleshooting).")
    return False


def main():
    print("Land Record Validation System - setup check\n")

    # Each check returns True (all good) or False (problem). Later checks need
    # the earlier ones, so we stop at the first problem.
    checks = [check_python, check_packages, check_tesseract,
              check_language_packs, check_marathi_reading]
    for check in checks:
        if not check():
            print("\nSetup is NOT complete. Fix the [FAIL] above, then run this script again.")
            sys.exit(1)

    print("\nAll checks passed. Phase 0 setup is complete.")


if __name__ == "__main__":
    main()
