#!/usr/bin/env bash
set -e
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
command -v tesseract >/dev/null || echo "WARNING: Tesseract not found - install it for OCR (sudo apt install tesseract-ocr / brew install tesseract)"
python manage.py makemigrations verification
python manage.py migrate
python manage.py seed_demo
echo "Starting on http://127.0.0.1:8000  (admin / admin12345)"
python manage.py runserver
