from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from PIL import Image


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class UploadForm(forms.Form):
    image = forms.ImageField(label="Payment screenshot")
    expected_amount = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2,
        label="Expected amount (optional)",
        help_text="Amount you expect to have received - mismatches are flagged.")
    # --- optional PayGuard-style inputs (OCR fills these automatically when left empty) ---
    claimed_amount = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2, label="Amount claimed by payer (optional)",
        help_text="Overrides the amount OCR reads from the screenshot.")
    manual_reference = forms.CharField(
        required=False, max_length=24, label="UPI reference / transaction ID (optional)",
        help_text="Use this if OCR cannot read the reference number.")
    merchant_confirm = forms.ChoiceField(
        required=False, label="Your own bank / merchant record",
        choices=[("none", "Not checked / unavailable"), ("yes", "Confirmed in my bank / merchant records"),
                 ("no", "Not found in my bank / merchant records")])
    suspicious_message = forms.CharField(
        required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}),
        label="Suspicious link or scam message (optional)")

    def clean_manual_reference(self):
        ref = self.cleaned_data.get("manual_reference", "").strip()
        if ref and not ref.isalnum():
            raise forms.ValidationError("Reference may contain only letters and digits.")
        return ref

    def clean_merchant_confirm(self):
        return self.cleaned_data.get("merchant_confirm") or "none"

    def clean_image(self):
        f = self.cleaned_data["image"]
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
            raise forms.ValidationError(f"Allowed formats: {', '.join(settings.ALLOWED_IMAGE_EXTENSIONS)}")
        if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"Max file size is {settings.MAX_UPLOAD_MB} MB.")
        f.seek(0)
        img = Image.open(f)
        w, h = img.size
        if w < 200 or h < 200:
            raise forms.ValidationError("Image is too small (min 200x200 px).")
        if w * h > 40_000_000:
            raise forms.ValidationError("Image dimensions are too large.")
        f.seek(0)
        return f
