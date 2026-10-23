"""Step 4 - Check trusted transaction records or a payment-provider API."""
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings

from .models import TrustedTransaction


@dataclass
class ProviderResult:
    found: bool = False
    status: str = ""             # success / pending / failed
    amount: Decimal | None = None
    merchant: str = ""
    source: str = "sandbox"
    already_used: bool = False
    message: str = ""


def _lookup_remote(reference: str) -> ProviderResult:
    """Generic REST lookup. Adapt the URL/response mapping to your gateway
    (Razorpay, Cashfree, PayU, Stripe...). Expected JSON:
        {"status": "success|pending|failed", "amount": 499.0, "merchant": "My Shop"}
    """
    try:
        resp = requests.get(
            f"{settings.PAYMENT_API_URL.rstrip('/')}/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYMENT_API_KEY}"}, timeout=8)
        if resp.status_code == 404:
            return ProviderResult(found=False, source="gateway", message="Reference not found at provider.")
        resp.raise_for_status()
        j = resp.json()
        return ProviderResult(found=True, status=str(j.get("status", "")).lower(),
                              amount=Decimal(str(j.get("amount", 0))),
                              merchant=j.get("merchant", ""), source="gateway")
    except Exception as exc:
        return ProviderResult(found=False, source="gateway", message=f"Provider unreachable: {exc}")


def _lookup_sandbox(reference: str) -> ProviderResult:
    txn = TrustedTransaction.objects.filter(reference__iexact=reference).first()
    if not txn:
        return ProviderResult(found=False, message="Reference not found in trusted records.")
    return ProviderResult(found=True, status=txn.status, amount=txn.amount,
                          merchant=txn.merchant, already_used=txn.used)


def verify_transaction(reference: str) -> ProviderResult:
    if not reference:
        return ProviderResult(found=False, message="No transaction reference could be read.")
    if settings.PAYMENT_API_URL:
        return _lookup_remote(reference)
    return _lookup_sandbox(reference)
