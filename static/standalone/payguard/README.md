# PayGuard AI

Detect suspicious payment screenshots and verify real transaction status.

## Run
Open `index.html` in any modern browser (Chrome/Edge recommended for the voice bot). No install needed.

1. Click "Start bot tour" once (browsers need a click before speech works).
2. Register -> Login -> Verify. Or click "Load demo data" on Home after logging in.

## Features
Payment Promise vs Reality, Screenshot Family Tree, Explainable Verification, Fraud Chain graph,
Payment Dispute Time Machine (timeline + CSV), Fraud What-If Simulator, 3D voice bot (hover help, page tour, login guidance).

## Notes
- Backend logic runs in the browser (localStorage). Passwords are only base64-encoded: demo only.
- OCR and real payment-API checks are not included; fields are entered manually.
- Next step for production: Django + DRF + PostgreSQL + Tesseract/EasyOCR + a payment provider API.
