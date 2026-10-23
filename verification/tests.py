import io
import shutil
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont

from .decision import decide, scan_message
from .demo import clear_demo_records, create_demo_records
from .insights import chain_graph, family_groups, simulate
from .models import TrustedTransaction, VerificationRecord
from .ocr_engine import ExtractedData, parse_text
from .transaction_api import ProviderResult
from .views import run_pipeline

HAS_TESSERACT = shutil.which("tesseract") is not None


def make_shot(lines, name="shot.png"):
    """Synthetic payment screenshot. A large font keeps OCR reliable (Pillow's tiny default font is not)."""
    im = Image.new("RGB", (1080, 1800), "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=48)
    for i, line in enumerate(lines):
        d.text((100, 200 + i * 110), line, fill="black", font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def provider(found=True, status="success", amount="499.00", used=False, msg=""):
    return ProviderResult(found=found, status=status, amount=Decimal(amount) if amount else None,
                          already_used=used, message=msg)


class FakeRecord:
    def __init__(self, expected=None, prob=0.05, msg="", merchant="none"):
        self.expected_amount = Decimal(expected) if expected else None
        self.fake_probability, self.fake_percent = prob, round(prob * 100)
        self.suspicious_message, self.merchant_confirm, self.risk_score = msg, merchant, 0


def info(amount=499.0, status="success", ref="412345678901"):
    return ExtractedData(raw_text="x", amount=amount, reference=ref, status_text=status, confidence=90.0)


# ------------------------------------------------------------------ parsing
class ParserTests(TestCase):
    def test_parse_fields(self):
        d = parse_text("Payment Successful\nRs. 1,250.00\nUPI Ref No: 412345678902\n23 Oct 2026, 12:03 PM\nshop@okaxis")
        self.assertEqual(d.amount, 1250.0)
        self.assertEqual(d.reference, "412345678902")
        self.assertEqual(d.status_text, "success")
        self.assertEqual(d.upi_id, "shop@okaxis")

    def test_failed_beats_success(self):
        self.assertEqual(parse_text("Payment failed. Amount Rs. 5").status_text, "failed")


# ------------------------------------------------------------------ decision engine (no OCR needed)
class DecisionTests(TestCase):
    def run_decide(self, rec=None, data=None, prov=None, flags=(), dups=()):
        rec = rec or FakeRecord()
        res, reasons = decide(rec, data or info(), prov or provider(), list(flags), list(dups))
        return res, reasons, rec

    def test_provider_success_confirms(self):
        self.assertEqual(self.run_decide()[0], "confirmed")

    def test_amount_mismatch(self):
        self.assertEqual(self.run_decide(data=info(4990.0))[0], "suspicious")

    def test_expected_amount_mismatch(self):
        self.assertEqual(self.run_decide(rec=FakeRecord(expected="900"))[0], "suspicious")

    def test_fake_success_for_failed_payment(self):
        self.assertEqual(self.run_decide(prov=provider(status="failed"))[0], "suspicious")

    def test_provider_failed_and_screenshot_failed(self):
        self.assertEqual(self.run_decide(data=info(status="failed"), prov=provider(status="failed"))[0], "failed")

    def test_pending(self):
        self.assertEqual(self.run_decide(prov=provider(status="pending"))[0], "pending")

    def test_unknown_reference_is_pending(self):
        res, _, _ = self.run_decide(prov=provider(found=False, status="", amount=None, msg="not found"))
        self.assertEqual(res, "pending")

    def test_duplicate_is_hard_flag_even_if_provider_ok(self):
        self.assertEqual(self.run_decide(dups=["dup"])[0], "suspicious")

    def test_scam_message_without_provider_is_suspicious(self):
        res, reasons, rec = self.run_decide(rec=FakeRecord(msg="bit.ly/refund-now click"),
                                            prov=provider(found=False, status="", amount=None))
        self.assertEqual(res, "suspicious")
        self.assertGreaterEqual(rec.risk_score, 1)

    def test_scam_message_does_not_override_provider_confirmation(self):
        res, reasons, _ = self.run_decide(rec=FakeRecord(msg="bit.ly/x"))
        self.assertEqual(res, "confirmed")
        self.assertTrue(any("warnings were raised" in r for r in reasons))

    def test_seller_says_not_received(self):
        res, _, _ = self.run_decide(rec=FakeRecord(merchant="no"), prov=provider(found=False, status="", amount=None))
        self.assertEqual(res, "failed")

    def test_seller_confirmation_without_provider_is_self_reported(self):
        res, reasons, _ = self.run_decide(rec=FakeRecord(merchant="yes"),
                                          prov=provider(found=False, status="", amount=None))
        self.assertEqual(res, "confirmed")
        self.assertIn("self-reported", reasons[0])

    def test_scan_message(self):
        self.assertEqual(scan_message("   "), [])
        out = " ".join(scan_message("Click bit.ly/x to claim your refund"))
        self.assertIn("link", out)
        self.assertIn("refund", out)

    def test_whatif_clean_is_confirmed(self):
        self.assertEqual(simulate({})["result"], "confirmed")

    def test_whatif_each_problem_changes_the_verdict(self):
        self.assertEqual(simulate({"amount_mismatch": True})["result"], "suspicious")
        self.assertEqual(simulate({"duplicate": True})["result"], "suspicious")
        self.assertEqual(simulate({"fake_success": True})["result"], "suspicious")
        self.assertEqual(simulate({"pending_payment": True})["result"], "pending")
        self.assertEqual(simulate({"missing_confirmation": True})["result"], "pending")
        self.assertEqual(simulate({"missing_confirmation": True, "scam_message": True})["result"], "suspicious")


# ------------------------------------------------------------------ pipeline (OCR bypassed via data_override)
class PipelineOverrideTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("seller", password="x12345678")
        TrustedTransaction.objects.create(reference="412345678901", amount=Decimal("499.00"), status="success")

    def test_confirmed_then_reuse_blocked_and_timeline_written(self):
        lines = ["Payment Successful", "Rs. 499.00"]
        r1 = run_pipeline(self.user, make_shot(lines, "a.png"), data_override=info())
        self.assertEqual(r1.result, VerificationRecord.CONFIRMED)
        self.assertGreaterEqual(len(r1.timeline), 5)
        self.assertTrue(TrustedTransaction.objects.get(reference="412345678901").used)
        r2 = run_pipeline(self.user, make_shot(lines, "b.png"), data_override=info())
        self.assertEqual(r2.result, VerificationRecord.SUSPICIOUS)
        self.assertTrue(any(s["id"] == r1.pk for s in r2.similar))

    def test_manual_reference_and_claimed_amount_override_ocr(self):
        data = ExtractedData(raw_text="", confidence=90.0)       # OCR read nothing
        r = run_pipeline(self.user, make_shot(["x"]), manual_reference="412345678901",
                         claimed_amount=Decimal("499.00"), data_override=data)
        self.assertEqual(r.extracted_reference, "412345678901")
        self.assertEqual(r.result, VerificationRecord.CONFIRMED)

    def test_suspicious_message_is_stored(self):
        r = run_pipeline(self.user, make_shot(["x"]), suspicious_message="bit.ly/refund-now",
                         data_override=info(100.0, ref="999999999999"))
        self.assertEqual(r.result, VerificationRecord.SUSPICIOUS)
        self.assertEqual(r.suspicious_message, "bit.ly/refund-now")


# ------------------------------------------------------------------ full OCR pipeline (needs Tesseract)
@skipUnless(HAS_TESSERACT, "Tesseract OCR is not installed")
class PipelineOCRTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("seller", password="x12345678")
        TrustedTransaction.objects.create(reference="412345678901", amount=Decimal("499.00"), status="success")
        TrustedTransaction.objects.create(reference="412345678904", amount=Decimal("750.00"), status="failed")

    def test_matching_payment_confirmed_then_reuse_blocked(self):
        lines = ["Payment Successful", "Rs. 499.00", "UPI Ref No: 412345678901", "23 Oct 2026, 12:03 PM"]
        r1 = run_pipeline(self.user, make_shot(lines, "a.png"))
        self.assertEqual(r1.result, VerificationRecord.CONFIRMED)
        r2 = run_pipeline(self.user, make_shot(lines, "b.png"))
        self.assertEqual(r2.result, VerificationRecord.SUSPICIOUS)

    def test_amount_mismatch_is_suspicious(self):
        lines = ["Payment Successful", "Rs. 4990.00", "UPI Ref No: 412345678901", "23 Oct 2026, 12:03 PM"]
        self.assertEqual(run_pipeline(self.user, make_shot(lines)).result, VerificationRecord.SUSPICIOUS)

    def test_unknown_reference_is_pending(self):
        lines = ["Payment Successful", "Rs. 100.00", "UPI Ref No: 999999999999", "23 Oct 2026, 12:03 PM"]
        self.assertEqual(run_pipeline(self.user, make_shot(lines)).result, VerificationRecord.PENDING)

    def test_fake_success_for_failed_payment(self):
        lines = ["Payment Successful", "Rs. 750.00", "UPI Ref No: 412345678904", "23 Oct 2026, 12:03 PM"]
        self.assertEqual(run_pipeline(self.user, make_shot(lines)).result, VerificationRecord.SUSPICIOUS)


# ------------------------------------------------------------------ PayGuard features
class DemoAndInsightTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("demo", password="x12345678")

    def test_demo_creates_five_scenarios_with_expected_verdicts(self):
        recs = create_demo_records(self.user)
        self.assertEqual([r.result for r in recs],
                         ["confirmed", "suspicious", "suspicious", "pending", "failed"])
        self.assertEqual(create_demo_records(self.user), [])                # idempotent

    def test_demo_family_tree_groups_the_near_copy(self):
        create_demo_records(self.user)
        families, singletons = family_groups(list(VerificationRecord.objects.filter(user=self.user)))
        self.assertEqual(len(families), 1)
        self.assertEqual(len(families[0]["members"]), 2)
        self.assertEqual(singletons, 3)

    def test_chain_graph_marks_scam_message_edges(self):
        recs = create_demo_records(self.user)
        g = chain_graph(recs[2])
        self.assertTrue(any(e["danger"] for e in g["edges"]))
        self.assertTrue(any("Link" in n["label"] for n in g["nodes"]))

    def test_clear_demo(self):
        create_demo_records(self.user)
        self.assertEqual(clear_demo_records(self.user), 5)
        self.assertFalse(VerificationRecord.objects.filter(user=self.user).exists())
        self.assertFalse(TrustedTransaction.objects.filter(reference__startswith="9").exists())

    def test_two_demo_users_do_not_collide(self):
        other = User.objects.create_user("demo2", password="x12345678")
        create_demo_records(self.user)
        recs = create_demo_records(other)
        self.assertEqual([r.result for r in recs], ["confirmed", "suspicious", "suspicious", "pending", "failed"])


# ------------------------------------------------------------------ HTTP layer
class ViewTests(TestCase):
    def login(self, name="u", staff=False):
        u = User.objects.create_user(name, password="x12345678", is_staff=staff)
        self.client.login(username=name, password="x12345678")
        return u

    def test_pages_require_login(self):
        for name in ("dashboard", "upload", "history", "timeline", "family", "chain", "export_csv"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_public_pages(self):
        for name in ("home", "about", "register", "login", "whatif"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_register_and_login(self):
        r = self.client.post(reverse("register"), {"username": "bob", "email": "b@x.com",
                                                   "password1": "Str0ng!Pass99", "password2": "Str0ng!Pass99"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_admin_dashboard_staff_only(self):
        self.login("plain")
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 302)
        self.client.logout()
        self.login("boss", staff=True)
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)

    def test_whatif_api(self):
        d = self.client.get(reverse("whatif_api"), {"duplicate": "1"}).json()
        self.assertEqual(d["result"], "suspicious")
        self.assertTrue(d["reasons"])
        self.assertEqual(self.client.get(reverse("whatif_api")).json()["result"], "confirmed")

    def test_demo_flow_and_all_pages_render(self):
        self.login()
        r = self.client.post(reverse("demo_load"))
        self.assertRedirects(r, reverse("timeline"))
        for name in ("dashboard", "history", "timeline", "family", "chain", "upload"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        rec = VerificationRecord.objects.filter(is_demo=True).first()
        self.assertEqual(self.client.get(reverse("result", args=[rec.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("chain"), {"id": rec.pk}).status_code, 200)
        self.assertEqual(self.client.get(reverse("screenshot", args=[rec.pk])).status_code, 200)

    def test_demo_load_requires_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse("demo_load")).status_code, 405)

    def test_csv_export(self):
        self.login()
        self.client.post(reverse("demo_load"))
        r = self.client.get(reverse("export_csv"))
        self.assertEqual(r["Content-Type"], "text/csv")
        lines = r.content.decode().strip().splitlines()
        self.assertEqual(len(lines), 6)                                    # header + 5 demo rows
        self.assertTrue(lines[0].startswith("id,time,user"))

    def test_screenshot_is_private(self):
        owner = self.login("owner")
        rec = create_demo_records(owner)[0]
        self.client.logout()
        self.login("intruder")
        self.assertEqual(self.client.get(reverse("screenshot", args=[rec.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("result", args=[rec.pk])).status_code, 302)
        self.client.logout()
        self.login("boss", staff=True)
        self.assertEqual(self.client.get(reverse("screenshot", args=[rec.pk])).status_code, 200)

    def test_upload_view_with_overrides(self):
        self.login()
        TrustedTransaction.objects.create(reference="412345678901", amount=Decimal("499.00"), status="success")
        shot = make_shot(["Payment Successful", "Rs. 499.00"])
        r = self.client.post(reverse("upload"), {"image": shot, "expected_amount": "499",
                                                 "manual_reference": "412345678901", "claimed_amount": "499",
                                                 "merchant_confirm": "none", "suspicious_message": ""})
        self.assertEqual(r.status_code, 302)
        rec = VerificationRecord.objects.latest("pk")
        self.assertEqual(rec.extracted_reference, "412345678901")

    def test_csv_formula_injection_is_neutralised(self):
        from .views import _csv_safe
        self.assertEqual(_csv_safe("=1+1"), "'=1+1")
        self.assertEqual(_csv_safe("@x"), "'@x")
        self.assertEqual(_csv_safe(5), "5")
