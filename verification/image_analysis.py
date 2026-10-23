"""Step 3 - Analyse the image for signs of editing and compute ML features."""
import hashlib
import io

import cv2
import numpy as np
from PIL import Image, ExifTags

EDITING_SOFTWARE = ("photoshop", "gimp", "canva", "picsart", "snapseed", "pixlr",
                    "paint", "lightroom", "facetune", "photopea", "editor")

FEATURE_NAMES = ["blur_score", "ela_mean", "ela_std", "ela_hot_ratio", "noise_std",
                 "edge_density", "width", "height", "aspect_ratio", "ocr_confidence",
                 "ocr_field_count", "exif_edited"]


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def perceptual_hash(img_gray: np.ndarray) -> str:
    """64-bit difference hash; near-identical screenshots give similar hashes."""
    small = cv2.resize(img_gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    return "".join("1" if v else "0" for v in diff.flatten())


def hamming(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    return sum(x != y for x, y in zip(a, b))


def _exif_info(path) -> dict:
    info = {"software": "", "has_exif": False}
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if exif:
                info["has_exif"] = True
                for tag_id, val in exif.items():
                    if ExifTags.TAGS.get(tag_id) == "Software":
                        info["software"] = str(val)
    except Exception:
        pass
    return info


def _ela(path, quality=90):
    """Error Level Analysis: re-save as JPEG and measure the difference.
    Edited regions often compress differently from the rest of the image."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        recompressed = Image.open(buf).convert("RGB")
        diff = np.abs(np.asarray(im, dtype=np.int16) - np.asarray(recompressed, dtype=np.int16))
    diff = diff.mean(axis=2)
    return float(diff.mean()), float(diff.std()), float((diff > 12).mean())


def analyse_image(path, ocr_confidence=0.0, ocr_field_count=0) -> dict:
    """Return a dict with hashes, feature vector, and human-readable red flags."""
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError("Unreadable image file")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float((edges > 0).mean())
    noise = gray.astype(np.float32) - cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    noise_std = float(noise.std())
    ela_mean, ela_std, ela_hot = _ela(path)
    exif = _exif_info(path)
    exif_edited = int(any(s in exif["software"].lower() for s in EDITING_SOFTWARE))

    features = {
        "blur_score": round(blur_score, 3), "ela_mean": round(ela_mean, 4),
        "ela_std": round(ela_std, 4), "ela_hot_ratio": round(ela_hot, 5),
        "noise_std": round(noise_std, 4), "edge_density": round(edge_density, 5),
        "width": w, "height": h, "aspect_ratio": round(w / h, 4),
        "ocr_confidence": float(ocr_confidence), "ocr_field_count": int(ocr_field_count),
        "exif_edited": exif_edited,
    }

    flags = []
    if exif_edited:
        flags.append(f"Image metadata shows editing software ({exif['software']}).")
    if ela_hot > 0.04 and ela_std > 4.5:
        flags.append("Uneven compression levels detected - regions may have been edited.")
    if min(w, h) < 400:
        flags.append("Very low resolution; real app screenshots are usually larger.")
    if blur_score < 40:
        flags.append("Image is very blurry.")
    if not exif["has_exif"]:
        pass  # Most screenshots have no EXIF; not suspicious on its own.

    return {
        "sha256": file_sha256(path),
        "phash": perceptual_hash(gray),
        "features": features,
        "flags": flags,
    }
