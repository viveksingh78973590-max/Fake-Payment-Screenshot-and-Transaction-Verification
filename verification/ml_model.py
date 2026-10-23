"""Step 3b - ML classifier (scikit-learn) that scores how likely a screenshot is manipulated."""
import logging
from functools import lru_cache

from django.conf import settings

from .image_analysis import FEATURE_NAMES

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model():
    path = settings.ML_MODEL_PATH
    try:
        import joblib
        return joblib.load(path)
    except Exception as exc:
        log.warning("ML model not loaded (%s). Using heuristic fallback.", exc)
        return None


def _heuristic(f: dict) -> float:
    """Simple rule-based score used when no trained model exists."""
    s = 0.05
    if f["exif_edited"]:
        s += 0.55
    if f["ela_hot_ratio"] > 0.04:
        s += 0.25
    if f["ela_std"] > 6:
        s += 0.15
    if f["ocr_field_count"] < 2:
        s += 0.10
    return min(s, 0.99)


def predict_fake_probability(features: dict) -> tuple[float, str]:
    """Return (probability_fake, method)."""
    model = _load_model()
    if model is None:
        return _heuristic(features), "heuristic"
    try:
        import pandas as pd
        row = pd.DataFrame([[features[n] for n in FEATURE_NAMES]], columns=FEATURE_NAMES)
        return float(model.predict_proba(row)[0][1]), "random_forest"
    except Exception as exc:  # pragma: no cover
        log.warning("Prediction failed (%s). Using heuristic.", exc)
        return _heuristic(features), "heuristic"
