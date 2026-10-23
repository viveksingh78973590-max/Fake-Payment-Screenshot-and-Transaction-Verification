@echo off
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
where tesseract >nul 2>nul || echo WARNING: Tesseract not found - install it and set TESSERACT_CMD
python manage.py makemigrations verification
python manage.py migrate
python manage.py seed_demo
echo Starting on http://127.0.0.1:8000  (admin / admin12345)
python manage.py runserver
