from django.contrib import admin
from .models import TrustedTransaction, VerificationRecord


@admin.register(TrustedTransaction)
class TrustedTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount", "status", "merchant", "used", "created_at")
    list_filter = ("status", "used")
    search_fields = ("reference", "merchant")


@admin.register(VerificationRecord)
class VerificationRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "extracted_reference", "extracted_amount", "result",
                    "fake_probability", "risk_score", "created_at")
    list_filter = ("result", "created_at", "is_demo")
    search_fields = ("extracted_reference", "user__username")
    readonly_fields = ("sha256", "phash", "ocr_text", "features", "image_flags", "reasons",
                       "timeline", "similar")
