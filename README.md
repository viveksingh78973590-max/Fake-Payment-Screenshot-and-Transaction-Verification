# PayGuard AI - Fake Payment Detection (unified project)

One project built from **PayVerify AI** (Django + OCR + OpenCV + ML backend) and **PayGuard AI**
(investigation features + 3D voice bot). Verify the **actual payment status**, not the screenshot.

## Pipeline
1. Upload payment screenshot (type / size / dimension validation)
2. OCR (`ocr_engine.py`): amount, reference, date, UPI ID, status
3. Image analysis (`image_analysis.py`: blur, ELA, noise, EXIF, hashes) + ML score (`ml_model.py`)
4. Trusted ledger / provider API check (`transaction_api.py`)
5. Explainable result (`decision.py`): **Confirmed / Pending / Failed / Suspicious** + risk score + timeline

Verified provider data outranks the screenshot. Duplicate images, reused references, amount mismatches,
"success" screenshots for failed payments and scam messages are always flagged.

## What came from where
| From PayVerify AI (kept as-is) | From PayGuard AI (rebuilt on Django) |
|---|---|
| Auth, dashboard, history, admin dashboard | Payment Promise vs Reality (claimed / expected / seller record) |
| OCR, image forensics, ML model + training script | Explainable verification with risk score |
| Trusted ledger + gateway adapter, reuse blocking | Screenshot Family Tree (perceptual-hash clusters) |
| Django admin, seed command, tests | Fraud Chain graph (SVG) |
| `dataset/`, `ml/saved_model.pkl` | Payment Dispute Time Machine (+ CSV export) |
| | Fraud What-If Simulator (runs the real engine) |
| | 3D voice bot: hover help, page intros, login guidance, tour |
| | Demo data loader |

The original browser-only PayGuard prototype is still included untouched at
`static/standalone/payguard/index.html` (linked from the About page).

## Setup
```bash
# Linux / macOS                    # Windows
./setup.sh                         setup.bat
```
or manually:
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Tesseract OCR engine: Ubuntu `sudo apt install tesseract-ocr` | macOS `brew install tesseract`
#                       Windows https://github.com/UB-Mannheim/tesseract/wiki  (then set TESSERACT_CMD)
python manage.py makemigrations verification
python manage.py migrate
python manage.py seed_demo          # admin / admin12345 + sample trusted transactions
python manage.py runserver
```
Open http://127.0.0.1:8000 - the pages load Bootstrap from a CDN, so the browser needs internet access.

## Try it
* Register, open the **Dashboard** and click **Load demo data**: five scenarios (genuine, reused near-copy,
  fake success + scam link, pending, failed) appear in Timeline, Family Tree and Fraud Chain.
* Or upload a screenshot showing `Rs. 499.00` and `UPI Ref No: 412345678901` -> **Confirmed** (ledger from `seed_demo`).
  Same reference with another amount -> **Suspicious**. Unknown reference -> **Pending**.
  `412345678904` is failed in the ledger, `412345678903` is pending.
* **What-If** is public: flip the switches, no login needed.
* Click **Start bot tour** (bottom right). Hover over anything for spoken help. Voice needs Chrome/Edge and a click first.

## Differences from the original PayGuard prototype
* Real backend (Django, DB, OCR, ML, provider API) instead of in-browser localStorage.
* Passwords use Django's hashing; there is **no self-service "Admin" role** at registration. Staff accounts come from
  `seed_demo` / `createsuperuser` and see all users' records.
* Screenshots are served through an authenticated view (owner or staff only).
* CSV export neutralises spreadsheet formula injection.

## Production
* Real gateway: set `PAYMENT_API_URL` and `PAYMENT_API_KEY` (adapt `_lookup_remote` in `transaction_api.py`).
* PostgreSQL: set `DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT`.
* Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`; run `collectstatic`;
  serve with gunicorn (`gunicorn payguard_ai.wsgi`). See `.env.example`. Change the demo admin password.
* A `Dockerfile` is included (untested).

## ML note
`dataset/sample_metadata.csv` is **synthetic demo data**; the ML score is only a supporting signal.
Train on your own labelled screenshots: `python ml/train_model.py --from-images dataset/genuine dataset/fake`.

## Tests
`python manage.py test verification` - decision rules, what-if, demo/family/chain, views, permissions, CSV.
OCR end-to-end tests run only when Tesseract is installed.

## Notes
* Seller confirmation ("my bank shows it") is self-reported: it can confirm a payment only when no provider record
  exists and no warnings were raised, and the result says so.
* Bot speech: browsers may block speech after a page change without a fresh click; the tour then continues silently with text bubbles.
