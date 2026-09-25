"""Turn a scanned 7/12 page into something OCR can read.

The steps undo, roughly in reverse, what a scanner did to the page:

    grayscale -> deskew -> denoise -> Sauvola binarise -> lift off the ruling lines

Why Sauvola rather than one global threshold: our pages are darker in one
corner (uneven lamp light). A single threshold either keeps the shadow as ink
or wipes out the faint text in it. Sauvola picks a threshold for every pixel
from its own neighbourhood, so both corners come out clean.

The printed table lines are kept separately rather than thrown away: they are
exactly what tables.py needs to find the cells.
"""

from dataclasses import dataclass

import cv2
import numpy as np

SAUVOLA_WINDOW = 31      # pixels; about the height of a line of text here
SAUVOLA_K = 0.2          # standard value from the paper
SAUVOLA_R = 128.0        # dynamic range of the standard deviation

# Every page is scaled to this width before anything else happens.
#
# Several numbers downstream are in pixels and were tuned at this size: the
# Sauvola window, the smallest thing that counts as a cell, how far inside a
# border to crop, and how much to enlarge a cell for Tesseract. Hand the same
# page in at 4,500 px - which is what a PDF rendered at 200 dpi gives - and
# those numbers no longer describe it, so whole tables stop being found. A
# scan can arrive at any resolution, so normalise first and tune once.
TARGET_WIDTH = 1650


@dataclass
class PreparedPage:
    """Everything the later steps need, all the same size as the original."""
    gray: np.ndarray          # deskewed grayscale, for cropping readable text
    ink: np.ndarray           # binarised: ink is 255, paper is 0
    text_ink: np.ndarray      # the same, with the ruling lines removed
    horizontal: np.ndarray    # the horizontal ruling lines
    vertical: np.ndarray      # the vertical ruling lines
    angle: float              # degrees the page was rotated to straighten it


def deskew_angle(gray: np.ndarray) -> float:
    """How crooked is the page, in degrees?

    The long printed table lines are the strongest straight things on a 7/12,
    so we measure them instead of the text.
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_length = gray.shape[1] // 3
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=200,
                            minLineLength=min_length, maxLineGap=20)
    if lines is None:
        return 0.0

    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) < 10:                     # near-horizontal lines only
            angles.append(angle)
    return float(np.median(angles)) if angles else 0.0


def rotate(image: np.ndarray, angle: float, fill: int = 255) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(image, matrix, (width, height),
                          flags=cv2.INTER_CUBIC, borderValue=fill)


def sauvola(gray: np.ndarray, window: int = SAUVOLA_WINDOW,
            k: float = SAUVOLA_K, r: float = SAUVOLA_R) -> np.ndarray:
    """Sauvola's local threshold. Returns a mask where ink is 255.

    threshold = mean * (1 + k * (standard deviation / R - 1))

    Both the mean and the standard deviation are taken over a window around
    each pixel, which box filters give us quickly.
    """
    image = gray.astype(np.float32)
    mean = cv2.boxFilter(image, ddepth=cv2.CV_32F, ksize=(window, window),
                         normalize=True, borderType=cv2.BORDER_REPLICATE)
    mean_square = cv2.boxFilter(image * image, ddepth=cv2.CV_32F,
                                ksize=(window, window), normalize=True,
                                borderType=cv2.BORDER_REPLICATE)
    variance = np.maximum(mean_square - mean * mean, 0)
    std = np.sqrt(variance)
    threshold = mean * (1.0 + k * (std / r - 1.0))
    return np.where(image < threshold, 255, 0).astype(np.uint8)


def find_rules(ink: np.ndarray):
    """Separate the long printed lines from the text.

    A horizontal line survives being eroded with a long flat brush; letters do
    not. The same trick upright finds the vertical lines.
    """
    height, width = ink.shape
    horizontal_brush = cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 28, 12), 1))
    vertical_brush = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 45, 10)))

    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, horizontal_brush, iterations=1)
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vertical_brush, iterations=1)

    # Close small gaps where a line was broken by noise or a crossing letter.
    horizontal = cv2.dilate(horizontal, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    vertical = cv2.dilate(vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    return horizontal, vertical


def to_target_width(image: np.ndarray, width: int = TARGET_WIDTH) -> np.ndarray:
    """Scale a page to the width the rest of the pipeline expects."""
    current = image.shape[1]
    if abs(current - width) / width < 0.1:      # close enough already
        return image
    scale = width / current
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(image, (width, max(int(round(image.shape[0] * scale)), 1)),
                      interpolation=interpolation)


def prepare(image: np.ndarray) -> PreparedPage:
    """Run the whole chain on one page image (grayscale or colour)."""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image = to_target_width(image)

    angle = deskew_angle(image)
    gray = rotate(image, angle) if abs(angle) > 0.05 else image.copy()
    gray = cv2.medianBlur(gray, 3)                 # kill the scanner speckle

    ink = sauvola(gray)
    horizontal, vertical = find_rules(ink)

    rules = cv2.bitwise_or(horizontal, vertical)
    text_ink = cv2.bitwise_and(ink, cv2.bitwise_not(rules))
    # A letter touching a line loses a slice of itself; close the gap back up.
    text_ink = cv2.morphologyEx(text_ink, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))

    return PreparedPage(gray=gray, ink=ink, text_ink=text_ink,
                        horizontal=horizontal, vertical=vertical, angle=angle)


def load(path) -> np.ndarray:
    """Read an image file into an array, raising a clear error if it is not one."""
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"'{path}' could not be read as an image")
    return image
