"""Step 2 - Extract transaction details from a payment screenshot using OCR."""
import re
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


@dataclass
class ExtractedData:
    raw_text: str = ""
    amount: float | None = None
    reference: str = ""
    date_text: str = ""
    status_text: str = ""        # success / failed / pending / ""
    upi_id: str = ""
    confidence: float = 0.0      # mean OCR word confidence 0-100
    ocr_available: bool = True
    readable: bool = True
    notes: list = field(default_factory=list)

    @property
    def field_count(self) -> int:
        return sum(bool(x) for x in (self.amount, self.reference, self.date_text, self.status_text))

    def as_dict(self):
        return asdict(self)


def _configure_tesseract():
    try:
        from django.conf import settings
        if getattr(settings, "TESSERACT_CMD", "") and pytesseract:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
    except Exception:
        pass


def preprocess(img_bgr: np.ndarray) -> np.ndarray:
    """Upscale, grayscale, denoise and binarise for better OCR."""
    h, w = img_bgr.shape[:2]
    if w < 1000:
        scale = 1000 / w
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 15, 7, 21)
    # Dark-mode screenshots: invert so text is dark on light
    if gray.mean() < 110:
        gray = cv2.bitwise_not(gray)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 15)


# ----------------------------------------------------------------- parsing
AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR|\$|USD)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
UPI_RE = re.compile(r"\b[\w.\-]{2,}@[a-z]{2,}\b", re.I)
REF_PATTERNS = [
    re.compile(r"(?:UPI\s*(?:Ref(?:erence)?|Transaction)\s*(?:No\.?|ID|#)?|UTR|RRN|Ref(?:erence)?\s*(?:No\.?|ID|#)?|"
               r"Transaction\s*(?:ID|No\.?|#)|Txn\s*(?:ID|No\.?)|Order\s*ID)\s*[:\-]?\s*([A-Z0-9]{8,24})", re.I),
    re.compile(r"\b(\d{12})\b"),                 # UPI reference numbers are 12 digits
    re.compile(r"\b(T\d{18,24})\b"),             # PhonePe style
]
DATE_RE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}(?:,?\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)?"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?:,?\s*\d{1,2}:\d{2}(?:\s*(?:AM|PM))?)?"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}(?:,?\s*\d{1,2}:\d{2}\s*(?:AM|PM)?)?)", re.I)
STATUS_WORDS = {
    "failed": ("failed", "failure", "declined", "unsuccessful", "reversed", "cancelled", "canceled"),
    "pending": ("pending", "processing", "in progress", "initiated"),
    "success": ("successful", "success", "completed", "paid", "sent", "received", "credited", "debited"),
}


def parse_text(text: str) -> ExtractedData:
    data = ExtractedData(raw_text=text)
    low = text.lower()

    amounts = [float(a.replace(",", "")) for a in AMOUNT_RE.findall(text)]
    if amounts:
        data.amount = max(amounts)

    for pat in REF_PATTERNS:
        m = pat.search(text)
        if m:
            data.reference = m.group(1).upper()
            break

    m = DATE_RE.search(text)
    if m:
        data.date_text = m.group(1).strip()

    m = UPI_RE.search(text)
    if m:
        data.upi_id = m.group(0).lower()

    for status, words in STATUS_WORDS.items():       # failed/pending take priority
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            data.status_text = status
            break
    return data


def extract_details(image_path: str) -> ExtractedData:
    """Run OCR on an image file and return structured fields."""
    _configure_tesseract()
    img = cv2.imread(str(image_path))
    if img is None:
        return ExtractedData(readable=False, notes=["Image could not be decoded."])
    if pytesseract is None:
        return ExtractedData(ocr_available=False, readable=False,
                             notes=["pytesseract is not installed."])
    try:
        processed = preprocess(img)
        cfg = "--oem 3 --psm 6"
        text = pytesseract.image_to_string(processed, config=cfg)
        d = pytesseract.image_to_data(processed, config=cfg, output_type=pytesseract.Output.DICT)
        confs = [float(c) for c in d["conf"] if str(c) not in ("-1", "")]
        # Retry on the raw image if the first pass found very little
        if len(text.strip()) < 25:
            text = pytesseract.image_to_string(img, config=cfg)
    except pytesseract.TesseractNotFoundError:
        return ExtractedData(ocr_available=False, readable=False,
                             notes=["Tesseract OCR engine not found. Install it and set TESSERACT_CMD."])
    except Exception as exc:  # pragma: no cover
        return ExtractedData(readable=False, notes=[f"OCR error: {exc}"])

    data = parse_text(text)
    data.confidence = round(sum(confs) / len(confs), 1) if confs else 0.0
    if len(text.strip()) < 15 or data.confidence < 35:
        data.readable = False
        data.notes.append("Screenshot is blurry or unreadable.")
    return data
