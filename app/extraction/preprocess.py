"""Image clean-up before OCR. Found by measuring: see docs/adr/0002-ocr-preprocessing.md."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def estimate_skew(gray: Image.Image, limit: float = 3.0, step: float = 0.5) -> float:
    """Angle (degrees) that makes text rows line up best.

    Rotating a straight page makes the row sums of dark pixels spiky (text rows vs. white gaps),
    so the angle with the highest variance of row sums is the best deskew angle.
    """
    small = gray.resize((max(1, gray.width // 3), max(1, gray.height // 3)))
    ink = Image.fromarray(((np.asarray(small) < 128) * 255).astype(np.uint8))
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-limit, limit + 1e-9, step):
        rotated = np.asarray(ink.rotate(float(angle), fillcolor=0))
        score = float(np.var(rotated.sum(axis=1)))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def prepare_for_ocr(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(image.convert("L"))
    gray = gray.rotate(estimate_skew(gray), resample=Image.BICUBIC, fillcolor=255)
    return gray.filter(ImageFilter.MedianFilter(3))  # removes speckle noise
