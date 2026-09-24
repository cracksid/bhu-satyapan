"""Make a crisp render look like a page that has been scanned or photocopied.

Real 7/12 scans are never clean: the page sits slightly crooked on the
scanner, the light falls unevenly, the sensor adds speckle, and JPEG
compression smears the edges of the letters. Phase 4's OCR has to survive all
of that, so the generator produces it on purpose.

Everything is driven by the same random generator as the rest of the batch,
so a given --seed always produces exactly the same images.
"""

import random

import cv2
import numpy as np


def _decode_grey(png_bytes: bytes) -> np.ndarray:
    """PNG bytes -> a grayscale image (a 2-D array of 0-255 values)."""
    buffer = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("could not decode the rendered PNG")
    return image


def _rotate(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """Tilt the page by up to about a degree, like paper laid down by hand."""
    padded = cv2.copyMakeBorder(image, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
    height, width = padded.shape
    angle = rng.uniform(-1.2, 1.2)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(padded, matrix, (width, height),
                          flags=cv2.INTER_LINEAR, borderValue=255)


def _uneven_light(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """Darken one part of the page, as a lamp or a phone camera would."""
    height, width = image.shape
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    centre_x = width * rng.uniform(0.2, 0.8)
    centre_y = height * rng.uniform(0.2, 0.8)
    radius = max(height, width) * rng.uniform(0.85, 1.4)
    distance = np.sqrt((xs - centre_x) ** 2 + (ys - centre_y) ** 2) / radius
    shade = 1.0 - rng.uniform(0.08, 0.22) * np.clip(distance, 0, 1) ** 2
    return np.clip(image * shade, 0, 255).astype(np.uint8)


def _blur(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """Soften the edges slightly, like a scanner that is not quite in focus."""
    return cv2.GaussianBlur(image, (0, 0), rng.uniform(0.3, 0.9))


def _noise(image: np.ndarray, rng: random.Random) -> np.ndarray:
    """Add sensor speckle."""
    np_rng = np.random.default_rng(rng.randrange(2 ** 32))
    noise = np_rng.normal(0.0, rng.uniform(2.0, 7.0), image.shape)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def _to_jpeg(image: np.ndarray, quality: int) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("could not encode the image as JPEG")
    return buffer.tobytes()


def degrade(png_bytes: bytes, rng: random.Random) -> bytes:
    """Run the whole wear-and-tear chain. Returns JPEG bytes."""
    image = _decode_grey(png_bytes)
    image = _rotate(image, rng)
    image = _uneven_light(image, rng)
    image = _blur(image, rng)
    image = _noise(image, rng)
    return _to_jpeg(image, rng.randint(45, 80))     # low quality = JPEG artefacts


def clean_jpeg(png_bytes: bytes) -> bytes:
    """No wear at all: used by --no-degrade, and for demo screenshots."""
    return _to_jpeg(_decode_grey(png_bytes), 95)
