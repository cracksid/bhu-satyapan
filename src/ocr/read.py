"""Read the text inside each detected cell, and keep how sure Tesseract was.

One Tesseract call per cell, rather than one per page. It is slower, but each
piece of text then comes back with a position and its own confidence, which is
what lets the UI shade a doubtful field instead of quietly publishing it.

Three choices here were measured, not guessed, by scoring cells whose correct
text the ground truth already holds:

  * crop INSIDE the cell borders (INSET pixels). Including the printed rule
    turns it into stray "|" and "___" characters: 41% character error rate
    with the borders in, 9% with them cropped away.
  * feed Tesseract the GRAYSCALE crop, not our binarised one. Sauvola is what
    finds the table lines, but Tesseract's own thresholding reads the soft
    grey edges better: 9% binarised against 3% grayscale.
  * enlarge 3x. Devanagari matras and the decimal point in "१.२४" are a few
    pixels tall at the original size: 3% at 2x, 2% at 3x.

A digit whitelist for numeric cells was tried too and made things far worse
(29%), so it is not used: the LSTM engine reads better with its own language
model intact.
"""

import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .preprocess import PreparedPage
from .tables import Cell


def _locate_tesseract():
    """Find tesseract.exe even when PATH is stale.

    A program started before Tesseract was added to PATH - an editor, or a
    server left running - keeps the old PATH for its whole life. Rather than
    failing with "tesseract is not installed" when it plainly is, look in the
    two places the installer puts it.
    """
    if shutil.which("tesseract"):
        return
    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return


_locate_tesseract()

LANGUAGES = "mar+eng"
UPSCALE = 3              # Devanagari needs about 60 px a line to read reliably
INSET = 7                # crop this far inside the cell, to miss the printed rule
PAD = 12                 # white margin added around the crop
SINGLE_LINE_HEIGHT = 46  # cells shorter than this hold one line of text


@dataclass
class CellText:
    """What was read from one cell."""
    cell: Cell
    text: str
    confidence: float        # 0-100; -1.0 when nothing readable was found

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def crop_cell(page: PreparedPage, cell: Cell) -> np.ndarray:
    """The inside of a cell, padded and enlarged, ready for Tesseract."""
    height, width = page.gray.shape
    top = min(max(cell.y + INSET, 0), height - 1)
    bottom = max(min(cell.bottom - INSET, height), top + 1)
    left = min(max(cell.x + INSET, 0), width - 1)
    right = max(min(cell.right - INSET, width), left + 1)

    patch = page.gray[top:bottom, left:right]
    patch = cv2.copyMakeBorder(patch, PAD, PAD, PAD, PAD,
                               cv2.BORDER_CONSTANT, value=255)
    return cv2.resize(patch, None, fx=UPSCALE, fy=UPSCALE,
                      interpolation=cv2.INTER_CUBIC)


def read_patch(patch: np.ndarray, mode: int, languages: str = LANGUAGES):
    """Run Tesseract and return (words with their line numbers, mean confidence)."""
    config = f"--psm {mode} --oem 1"                    # oem 1 = the LSTM engine
    data = pytesseract.image_to_data(patch, lang=languages, config=config,
                                     output_type=Output.DICT)

    words, confidences = [], []
    for word, confidence, line in zip(data["text"], data["conf"], data["line_num"]):
        word = word.strip()
        if not word:
            continue
        words.append((int(line), word))
        value = float(confidence)
        if value >= 0:
            confidences.append(value)

    return words, (float(np.mean(confidences)) if confidences else -1.0)


def is_blank(page: PreparedPage, cell: Cell) -> bool:
    """Is there essentially no ink inside this cell?

    Tesseract invents text from paper grain - an empty column came back as
    'Poh Ve a". as = » t' - so empty cells are never sent to it. This uses the
    binarised image with the rules removed, which is what it is good for.
    """
    patch = page.text_ink[cell.y + INSET:cell.bottom - INSET,
                          cell.x + INSET:cell.right - INSET]
    if patch.size == 0:
        return True
    return float(np.count_nonzero(patch)) / patch.size < 0.004


def read_cell(page: PreparedPage, cell: Cell, languages: str = LANGUAGES) -> CellText:
    """OCR one cell. Returns its text and the mean word confidence."""
    if is_blank(page, cell):
        return CellText(cell=cell, text="", confidence=-1.0)
    mode = 7 if cell.height < SINGLE_LINE_HEIGHT else 6   # one line, or a block
    words, confidence = read_patch(crop_cell(page, cell), mode, languages)
    return CellText(cell=cell, text=" ".join(word for _line, word in words),
                    confidence=confidence)


def read_lines(page: PreparedPage, cell: Cell, languages: str = LANGUAGES,
               best: bool = False):
    """OCR a tall cell and return its text one line at a time.

    The area block on the left of the form is a list of label/value pairs, and
    keeping the lines apart is what lets the extractor tell "एकूण" (cultivable)
    from "एकूण क्षेत्र" (the total).
    """
    if best and best_model_available():
        with _using_best_model():
            words, confidence = read_patch(crop_cell(page, cell), 6, "mar")
    else:
        words, confidence = read_patch(crop_cell(page, cell), 6, languages)
    lines = {}
    for line_number, word in words:
        lines.setdefault(line_number, []).append(word)
    return [" ".join(words) for _line, words in sorted(lines.items())], confidence


def read_cells(page: PreparedPage, cells: list, languages: str = LANGUAGES) -> list:
    """OCR every cell, in reading order."""
    return [read_cell(page, cell, languages) for cell in cells]


# --------------------------------------------------------------------------
# numbers: the same page, read with the more accurate model
# --------------------------------------------------------------------------
BEST_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "tessdata_best"


def best_model_available() -> bool:
    return (BEST_MODEL_DIR / "mar.traineddata").exists()


@contextmanager
def _using_best_model():
    """Point Tesseract at the tessdata_best folder for the calls inside.

    TESSDATA_PREFIX is used rather than --tessdata-dir because pytesseract
    cannot pass a path containing a space through its config string, and this
    project's folder has one.
    """
    previous = os.environ.get("TESSDATA_PREFIX")
    os.environ["TESSDATA_PREFIX"] = str(BEST_MODEL_DIR)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = previous


def read_number(page: PreparedPage, cell: Cell) -> CellText:
    """Read a cell that should hold a number, using the more accurate model.

    Measured on the owner-share, mutation-number and mutation-area columns of
    six records: the model the installer ships (tessdata_fast) reads 63% of
    them exactly, the slower tessdata_best model 86%. Names go the other way
    - fast reads them slightly better - so text cells keep the fast model and
    only numbers pay the extra time.

    Falls back to the ordinary read when the best model has not been
    downloaded, so the pipeline always works; it just reads numbers less well.
    """
    if is_blank(page, cell):
        return CellText(cell=cell, text="", confidence=-1.0)
    if not best_model_available():
        return read_cell(page, cell)

    mode = 7 if cell.height < SINGLE_LINE_HEIGHT else 6
    with _using_best_model():
        words, confidence = read_patch(crop_cell(page, cell), mode, languages="mar")
    return CellText(cell=cell, text=" ".join(word for _line, word in words),
                    confidence=confidence)
