"""5-step verification pipeline:
1 upload -> 2 OCR -> 3 image analysis + ML -> 4 trusted record / provider check -> 5 result.
Every step is written to the record's timeline (PayGuard's "Payment Dispute Time Machine")."""
from decimal import Decimal

from django.utils import timezone

from .decision import decide  # noqa: F401  (re-exported)
from .image_analysis import analyse_image, hamming
from .insights import FAMILY_DISTANCE
from .ml_model import predict_fake_probability
from .models import TrustedTransaction, VerificationRecord
from .ocr_engine import extract_details
from .transaction_api import verify_transaction

NEAR_DUPLICATE_DISTANCE = 3


def _ev(timeline, text):
    timeline.append([timezone.localtime(timezone.now()).strftime("%d %b %Y %H:%M:%S"), text])


def run_pipeline(user, image_file, expected_amount=None, *, suspicious_message="", merchant_confirm="none",
                 manual_reference="", claimed_amount=None, data_override=None,
                 is_demo=False) -> VerificationRecord:
    """Verify one screenshot. ``data_override`` (an ExtractedData) skips OCR - used by the demo loader."""
    tl = []
    _ev(tl, "Screenshot and form submitted")
    record = VerificationRecord(user=user, image=image_file, expected_amount=expected_amount,
                                suspicious_message=(suspicious_message or "").strip(),
                                merchant_confirm=merchant_confirm or "none", is_demo=is_demo)
    record.save()                                   # file must be on disk for OCR / OpenCV
    path = record.image.path

    if data_override is not None:                                    # step 2
        data = data_override
        _ev(tl, "Transaction details supplied (demo data, OCR skipped)")
    else:
        data = extract_details(path)
        _ev(tl, f"OCR finished: {data.field_count} field(s) read, confidence {data.confidence}%")
    if manual_reference:
        data.reference = manual_reference.strip().upper()
        _ev(tl, f"Reference entered manually: {data.reference}")
    if claimed_amount is not None:
        data.amount = float(claimed_amount)
        _ev(tl, f"Claimed amount entered manually: {claimed_amount}")

    analysis = analyse_image(path, data.confidence, data.field_count)  # step 3
    prob, method = predict_fake_probability(analysis["features"])
    _ev(tl, f"Image analysis done ({len(analysis['flags'])} warning(s)); ML manipulation risk "
            f"{round(prob * 100)}% [{method}]")

    duplicate_msgs, similar = [], []
    others = VerificationRecord.objects.exclude(pk=record.pk)
    if others.filter(sha256=analysis["sha256"]).exists():
        duplicate_msgs.append("This exact screenshot was already submitted before.")
    near = False
    for pk, ph in others.exclude(phash="").values_list("pk", "phash")[:2000]:
        d = hamming(ph, analysis["phash"])
        if d <= FAMILY_DISTANCE:
            similar.append({"id": pk, "distance": d})
        if d <= NEAR_DUPLICATE_DISTANCE:
            near = True
    if near and not duplicate_msgs:
        duplicate_msgs.append("A near-identical screenshot was already submitted.")
    if data.reference and others.filter(extracted_reference=data.reference,
                                        result=VerificationRecord.CONFIRMED).exists():
        duplicate_msgs.append("This transaction reference was already verified for another upload.")
    _ev(tl, f"Duplicate check: {len(similar)} similar screenshot(s) found")

    provider = verify_transaction(data.reference)                    # step 4
    _ev(tl, f"Provider check ({provider.source}): "
            f"{provider.status or ('not found' if not provider.found else 'unknown')}")

    record.sha256, record.phash = analysis["sha256"], analysis["phash"]
    record.features, record.image_flags = analysis["features"], analysis["flags"]
    record.ocr_text, record.ocr_confidence = data.raw_text, data.confidence
    record.extracted_amount = Decimal(str(data.amount)) if data.amount is not None else None
    record.extracted_reference, record.extracted_date = data.reference, data.date_text
    record.extracted_status, record.upi_id = data.status_text, data.upi_id
    record.fake_probability, record.ml_method = prob, method
    record.provider_found, record.provider_status = provider.found, provider.status
    record.provider_amount, record.provider_source = provider.amount, provider.source
    record.similar = similar

    record.result, record.reasons = decide(record, data, provider, analysis["flags"], duplicate_msgs)

    if record.result == VerificationRecord.CONFIRMED and provider.source == "sandbox" and provider.found:
        TrustedTransaction.objects.filter(reference__iexact=data.reference).update(used=True)
    _ev(tl, f"Analysis complete - risk score {record.risk_score}")
    _ev(tl, f"Final decision: {record.get_result_display()}")                    # step 5
    record.timeline = tl
    record.save()
    return record
