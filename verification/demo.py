"""Demo data (PayGuard's "Load demo data" button) - runs through the REAL pipeline.

Synthetic screenshots are generated with Pillow, so every feature (family tree, fraud chain,
timeline, duplicate detection) can be explored without uploading anything. References and image
patterns are unique per user so demo users never trigger each other's duplicate checks."""
import io
import random
from decimal import Decimal

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw

from .engine import run_pipeline
from .models import TrustedTransaction, VerificationRecord
from .ocr_engine import ExtractedData


def _prefix(user):
    return f"9{user.pk:04d}"            # + 7 digits = 12-digit reference


def make_screenshot(seed, lines, patch=False) -> bytes:
    """Deterministic fake app screen. ``patch=True`` makes a tiny edit (same 'family')."""
    rng = random.Random(seed)
    im = Image.new("RGB", (1080, 1800), (245, 247, 250))
    d = ImageDraw.Draw(im)
    for _ in range(10):
        x, y = rng.randint(0, 800), rng.randint(0, 1500)
        d.rectangle([x, y, x + rng.randint(150, 450), y + rng.randint(150, 450)],
                    fill=tuple(rng.randint(40, 230) for _ in range(3)))
    d.rectangle([60, 180, 1020, 180 + 110 * len(lines) + 40], fill="white")
    for i, line in enumerate(lines):
        d.text((100, 200 + i * 110), line, fill="black")
    if patch:
        d.rectangle([1000, 1780, 1015, 1795], fill=(10, 10, 10))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _data(amount, ref, status, date="23 Oct 2026, 12:03 PM"):
    return ExtractedData(raw_text="(demo data)", amount=float(amount), reference=ref, date_text=date,
                         status_text=status, upi_id="demostore@okaxis", confidence=88.0)


def create_demo_records(user):
    """Create 5 scenarios for ``user``. Returns the list of records (empty if already loaded)."""
    if VerificationRecord.objects.filter(user=user, is_demo=True).exists():
        return []
    p = _prefix(user)
    ref = lambda n: f"{p}{n:07d}"
    base = user.pk * 100

    ledger = [(ref(1), "500.00", "success"), (ref(3), "750.00", "failed"),
              (ref(4), "2999.00", "pending"), (ref(5), "300.00", "failed")]
    for r, amt, st in ledger:
        TrustedTransaction.objects.update_or_create(
            reference=r, defaults={"amount": Decimal(amt), "status": st, "merchant": "Demo Store", "used": False})

    def lines(amount, r, status):
        return [f"Payment {status.title()}", f"Rs. {amount}", f"UPI Ref No: {r}", "23 Oct 2026, 12:03 PM"]

    scenarios = [
        # 1 genuine payment -> Confirmed
        dict(seed=base + 1, patch=False, amount=500, ref=ref(1), status="success", expected=Decimal("500")),
        # 2 near-copy of #1 reused for a bigger amount -> Suspicious (family tree + duplicate)
        dict(seed=base + 1, patch=True, amount=900, ref=ref(1), status="success", expected=Decimal("900")),
        # 3 "success" screenshot for a failed payment + scam message -> Suspicious
        dict(seed=base + 3, patch=False, amount=750, ref=ref(3), status="success", expected=Decimal("750"),
             msg="bit.ly/refund-now your refund is ready, click to claim"),
        # 4 pending at provider -> Pending
        dict(seed=base + 4, patch=False, amount=2999, ref=ref(4), status="pending", expected=Decimal("2999")),
        # 5 failed everywhere -> Failed
        dict(seed=base + 5, patch=False, amount=300, ref=ref(5), status="failed", expected=Decimal("300")),
    ]
    out = []
    for i, s in enumerate(scenarios, 1):
        png = make_screenshot(s["seed"], lines(s["amount"], s["ref"], s["status"]), s["patch"])
        out.append(run_pipeline(
            user, ContentFile(png, name=f"demo_{user.pk}_{i}.png"), s["expected"],
            suspicious_message=s.get("msg", ""),
            data_override=_data(s["amount"], s["ref"], s["status"]), is_demo=True))
    return out


def clear_demo_records(user) -> int:
    recs = VerificationRecord.objects.filter(user=user, is_demo=True)
    n = recs.count()
    for r in recs:
        r.image.delete(save=False)
    recs.delete()
    TrustedTransaction.objects.filter(reference__startswith=_prefix(user)).delete()
    return n
