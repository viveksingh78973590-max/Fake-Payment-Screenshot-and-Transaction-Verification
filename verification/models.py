from django.conf import settings
from django.db import models


class TrustedTransaction(models.Model):
    """Sandbox / trusted ledger. In production this is replaced by a payment-gateway API."""
    STATUS = [("success", "Success"), ("pending", "Pending"), ("failed", "Failed")]
    reference = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS, default="success")
    merchant = models.CharField(max_length=100, blank=True)
    used = models.BooleanField(default=False, help_text="Already claimed by a verified screenshot")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.amount} ({self.status})"


class VerificationRecord(models.Model):
    CONFIRMED, PENDING, FAILED, SUSPICIOUS = "confirmed", "pending", "failed", "suspicious"
    RESULTS = [(CONFIRMED, "Payment confirmed"), (PENDING, "Pending / unverifiable"),
               (FAILED, "Failed"), (SUSPICIOUS, "Suspicious")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verifications")
    image = models.ImageField(upload_to="screenshots/%Y/%m/")
    sha256 = models.CharField(max_length=64, db_index=True, blank=True)
    phash = models.CharField(max_length=64, blank=True)

    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    extracted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    extracted_reference = models.CharField(max_length=40, blank=True, db_index=True)
    extracted_date = models.CharField(max_length=60, blank=True)
    extracted_status = models.CharField(max_length=20, blank=True)
    upi_id = models.CharField(max_length=80, blank=True)
    ocr_text = models.TextField(blank=True)
    ocr_confidence = models.FloatField(default=0)

    fake_probability = models.FloatField(default=0)
    ml_method = models.CharField(max_length=30, blank=True)
    image_flags = models.JSONField(default=list, blank=True)
    features = models.JSONField(default=dict, blank=True)

    provider_found = models.BooleanField(default=False)
    provider_status = models.CharField(max_length=20, blank=True)
    provider_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    provider_source = models.CharField(max_length=20, blank=True)

    # --- PayGuard-style evidence ------------------------------------------------
    MERCHANT = [("none", "Not checked / unavailable"), ("yes", "Confirmed in my bank / merchant records"),
                ("no", "Not found in my bank / merchant records")]
    suspicious_message = models.TextField(blank=True, help_text="Suspicious link or scam message sent with the payment")
    merchant_confirm = models.CharField(max_length=4, choices=MERCHANT, default="none")
    risk_score = models.PositiveSmallIntegerField(default=0)
    timeline = models.JSONField(default=list, blank=True)       # [[timestamp, event], ...]
    similar = models.JSONField(default=list, blank=True)        # [{"id": 3, "distance": 2}, ...]
    is_demo = models.BooleanField(default=False)

    result = models.CharField(max_length=12, choices=RESULTS, default=PENDING)
    reasons = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.user} - {self.result}"

    @property
    def badge_class(self):
        return {"confirmed": "success", "pending": "warning", "failed": "danger",
                "suspicious": "danger"}.get(self.result, "secondary")

    @property
    def fake_percent(self):
        return round(self.fake_probability * 100)

    @property
    def tag_class(self):
        """CSS class used by the PayGuard-style coloured tag."""
        return self.result
