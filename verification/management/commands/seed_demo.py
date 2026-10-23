"""python manage.py seed_demo  -> creates demo admin + sample trusted transactions."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from verification.models import TrustedTransaction

SAMPLES = [
    ("412345678901", "499.00", "success", "Demo Store"),
    ("412345678902", "1250.00", "success", "Demo Store"),
    ("412345678903", "2999.00", "pending", "Demo Store"),
    ("412345678904", "750.00", "failed", "Demo Store"),
    ("T2410231234567890123", "5000.00", "success", "Demo Store"),
]


class Command(BaseCommand):
    help = "Create demo admin user and sample trusted transactions"

    def handle(self, *args, **opts):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin12345")
            self.stdout.write("Created admin / admin12345 (change this password!)")
        for ref, amt, st, m in SAMPLES:
            TrustedTransaction.objects.get_or_create(
                reference=ref, defaults={"amount": Decimal(amt), "status": st, "merchant": m})
        self.stdout.write(self.style.SUCCESS(f"{len(SAMPLES)} sample transactions ready."))
