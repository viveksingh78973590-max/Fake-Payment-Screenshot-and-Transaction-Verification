"""Decision engine (explainable). Pure Python: no database access.

Merges both original projects:
  * PayVerify AI - provider/ledger data outranks the screenshot, reuse + amount checks, ML score.
  * PayGuard AI  - "promise vs reality" (claimed vs expected), scam-message check,
                   seller confirmation, risk score and plain-language reasons.
"""
import re
from decimal import Decimal

from django.conf import settings

CONFIRMED, PENDING, FAILED, SUSPICIOUS = "confirmed", "pending", "failed", "suspicious"
AMOUNT_TOLERANCE = Decimal("0.01")

URL_RE = re.compile(r"(?:https?://|www\.|\b(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|cutt\.ly|rb\.gy)/)\S*", re.I)
SCAM_WORDS = ("refund", "kyc", "otp", "click", "claim", "urgent", "blocked", "verify now",
              "wrongly sent", "send back", "reversed", "cashback", "lottery", "prize", "pin")


def scan_message(text: str) -> list:
    """Reasons to distrust a message/link the seller attached. Any attached message is a soft flag."""
    text = (text or "").strip()
    if not text:
        return []
    out = ["A suspicious link or message was attached to this payment."]
    urls = URL_RE.findall(text)
    if urls:
        out.append("The message contains a link (" + urls[0][:60] + ") - never open links sent with payment proofs.")
    low = text.lower()
    hits = sorted({w for w in SCAM_WORDS if re.search(rf"\b{re.escape(w)}\b", low)})
    if hits:
        out.append("Scam-style wording found: " + ", ".join(hits[:5]) + ".")
    return out


def decide(record, data, provider, flags, duplicate_msgs):
    """Return (result, reasons) and set ``record.risk_score``.

    Verified provider data outranks the screenshot. ``record`` needs: expected_amount,
    fake_probability, fake_percent, suspicious_message, merchant_confirm.
    """
    reasons, hard, soft = [], [], []

    hard += duplicate_msgs
    if provider.found and provider.already_used:
        hard.append("This transaction reference was already claimed by another verification.")

    claimed = Decimal(str(data.amount)) if data.amount is not None else None
    if provider.found and claimed is not None and provider.amount is not None \
            and abs(claimed - provider.amount) > AMOUNT_TOLERANCE:
        hard.append(f"Amount mismatch: screenshot shows {claimed}, provider record shows {provider.amount}.")
    if record.expected_amount is not None and claimed is not None \
            and abs(claimed - record.expected_amount) > AMOUNT_TOLERANCE:
        hard.append(f"Screenshot amount {claimed} differs from the expected amount {record.expected_amount}.")
    if provider.found and provider.status == "failed" and data.status_text == "success":
        hard.append("Screenshot claims success but the provider shows the payment failed.")

    if record.fake_probability >= settings.FAKE_PROBABILITY_THRESHOLD:
        soft.append(f"ML model rates this screenshot {record.fake_percent}% likely to be manipulated.")
    soft += flags
    soft += scan_message(getattr(record, "suspicious_message", ""))

    merchant = getattr(record, "merchant_confirm", "none")
    confirmed_by_provider = provider.found and provider.status == "success" and not hard
    if merchant == "no" and confirmed_by_provider:
        soft.append("Provider says paid, but the seller's own records say the money was not received - check manually.")

    # PayGuard-style numeric risk score (explainability aid, not the decision itself)
    risk = 3 * len(hard) + len(soft)
    if provider.found and provider.status == "pending":
        risk += 1
    if not provider.found and merchant != "yes":
        risk += 1
    record.risk_score = min(risk, 99)

    if hard:
        return SUSPICIOUS, hard + soft
    if confirmed_by_provider:
        reasons.append(f"Provider ({provider.source}) confirms a successful payment of {provider.amount}.")
        if soft:
            reasons.append("Note - warnings were raised, but the payment itself is verified:")
            reasons += soft
        return CONFIRMED, reasons
    if merchant == "no":
        return FAILED, ["The seller's own bank/merchant records do not show this payment."] + soft
    if soft:
        return SUSPICIOUS, soft
    if provider.found and provider.status == "failed":
        return FAILED, ["The provider reports this transaction as failed."]
    if provider.found and provider.status == "pending":
        return PENDING, ["The provider reports this transaction as still pending."]
    if data.status_text == "failed":
        return FAILED, ["The screenshot itself shows a failed payment."]
    if merchant == "yes" and not provider.found:
        return CONFIRMED, ["The seller confirmed the payment in their own records (self-reported, "
                           "no provider record was available to cross-check)."]
    if not data.ocr_available:
        return PENDING, data.notes
    if not data.readable:
        return PENDING, data.notes + ["Upload a clearer screenshot."]
    msg = provider.message or "No matching transaction found."
    return PENDING, [msg, "Payment cannot be verified - do not release goods yet."]
