"""Train the fake-screenshot classifier.

Usage:
  python ml/train_model.py                      # train from dataset/sample_metadata.csv
  python ml/train_model.py --generate-demo      # (re)create a SYNTHETIC demo CSV first
  python ml/train_model.py --from-images dataset/genuine dataset/fake
                                                # extract real features from your own labelled
                                                # screenshot folders, append to the CSV, then train
Replace the synthetic demo data with real labelled screenshots for production use.
"""
import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from verification.image_analysis import FEATURE_NAMES, analyse_image  # noqa: E402

CSV_PATH = ROOT / "dataset" / "sample_metadata.csv"
MODEL_PATH = ROOT / "ml" / "saved_model.pkl"


def generate_demo(n=600, seed=42):
    """Synthetic data that mimics typical differences. NOT real evidence - demo only."""
    rng = np.random.default_rng(seed)
    rows = []
    for label in (0, 1):
        for _ in range(n // 2):
            if label == 0:   # genuine
                r = dict(blur_score=rng.normal(900, 400), ela_mean=rng.normal(0.9, 0.4),
                         ela_std=rng.normal(2.2, 0.9), ela_hot_ratio=abs(rng.normal(0.008, 0.008)),
                         noise_std=rng.normal(3.0, 1.0), edge_density=rng.normal(0.07, 0.025),
                         exif_edited=int(rng.random() < 0.02), ocr_confidence=rng.normal(80, 8),
                         ocr_field_count=rng.choice([3, 4], p=[0.3, 0.7]))
            else:            # manipulated
                r = dict(blur_score=rng.normal(650, 450), ela_mean=rng.normal(2.1, 0.9),
                         ela_std=rng.normal(5.4, 1.8), ela_hot_ratio=abs(rng.normal(0.07, 0.04)),
                         noise_std=rng.normal(4.2, 1.5), edge_density=rng.normal(0.085, 0.03),
                         exif_edited=int(rng.random() < 0.35), ocr_confidence=rng.normal(68, 12),
                         ocr_field_count=rng.choice([1, 2, 3, 4], p=[0.1, 0.25, 0.4, 0.25]))
            w = int(rng.choice([720, 1080, 1170, 1284, 1440]))
            h = int(w * rng.choice([2.0, 2.16, 2.22, 2.17]))
            r.update(width=w, height=h, aspect_ratio=round(w / h, 4), label=label)
            rows.append(r)
    df = pd.DataFrame(rows)
    flip = rng.random(len(df)) < 0.08          # 8% label noise so the demo is not unrealistically perfect
    df.loc[flip, "label"] = 1 - df.loc[flip, "label"]
    df[["blur_score", "ela_mean", "ela_std", "noise_std", "edge_density"]] = \
        df[["blur_score", "ela_mean", "ela_std", "noise_std", "edge_density"]].clip(lower=0.01)
    df["ocr_confidence"] = df["ocr_confidence"].clip(0, 100)
    df = df[FEATURE_NAMES + ["label"]].round(4)
    df.to_csv(CSV_PATH, index=False)
    print(f"Wrote synthetic demo dataset: {CSV_PATH} ({len(df)} rows)")


def from_images(genuine_dir, fake_dir):
    rows = []
    for folder, label in ((genuine_dir, 0), (fake_dir, 1)):
        for p in Path(folder).glob("*"):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                try:
                    f = analyse_image(p)["features"]
                    f["label"] = label
                    rows.append(f)
                except Exception as exc:
                    print("skip", p.name, exc)
    new = pd.DataFrame(rows)
    old = pd.read_csv(CSV_PATH) if CSV_PATH.exists() else pd.DataFrame()
    pd.concat([old, new], ignore_index=True).to_csv(CSV_PATH, index=False)
    print(f"Added {len(new)} real samples to {CSV_PATH}")


def train():
    df = pd.read_csv(CSV_PATH)
    X, y = df[FEATURE_NAMES], df["label"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    model = RandomForestClassifier(n_estimators=250, max_depth=10, min_samples_leaf=3,
                                   class_weight="balanced", random_state=42, n_jobs=-1)
    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    print(classification_report(yte, pred, target_names=["genuine", "manipulated"]))
    print("Confusion matrix:\n", confusion_matrix(yte, pred))
    imp = sorted(zip(FEATURE_NAMES, model.feature_importances_), key=lambda t: -t[1])
    print("Top features:", [(n, round(v, 3)) for n, v in imp[:5]])
    joblib.dump(model, MODEL_PATH)
    print("Saved model ->", MODEL_PATH)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate-demo", action="store_true")
    ap.add_argument("--from-images", nargs=2, metavar=("GENUINE_DIR", "FAKE_DIR"))
    args = ap.parse_args()
    if args.generate_demo or not CSV_PATH.exists():
        generate_demo()
    if args.from_images:
        from_images(*args.from_images)
    train()
