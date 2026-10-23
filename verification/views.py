"""Views for PayGuard AI (merged PayVerify AI + PayGuard AI).
The verification pipeline lives in engine.py, the decision rules in decision.py."""
import csv
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decision import decide  # noqa: F401  (re-exported for backwards compatibility)
from .demo import clear_demo_records, create_demo_records
from .engine import run_pipeline  # noqa: F401  (re-exported: tests and other code import it from views)
from .forms import RegisterForm, UploadForm
from .insights import WHATIF_SWITCHES, chain_graph, family_groups, simulate
from .models import TrustedTransaction, VerificationRecord


def _visible(request):
    """Staff see every record; everyone else only their own."""
    qs = VerificationRecord.objects.select_related("user")
    return qs if request.user.is_staff else qs.filter(user=request.user)


def _counts(qs):
    c = {r["result"]: r["n"] for r in qs.values("result").annotate(n=Count("id"))}
    return {k: c.get(k, 0) for k in ("confirmed", "pending", "failed", "suspicious")}


# ------------------------------------------------------------------- public pages
def home(request):
    return render(request, "home.html")


def about(request):
    return render(request, "about.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Registration successful! Welcome to PayGuard AI.")
        return redirect("dashboard")
    return render(request, "register.html", {"form": form})


def whatif(request):
    return render(request, "whatif.html", {"switches": WHATIF_SWITCHES})


def whatif_api(request):
    """GET ?amount_mismatch=1&duplicate=1 ... -> decision from the real engine (no data stored)."""
    flags = {k: request.GET.get(k) == "1" for k, _ in WHATIF_SWITCHES}
    return JsonResponse(simulate(flags))


# ------------------------------------------------------------------- user pages
@login_required
def dashboard(request):
    qs = VerificationRecord.objects.filter(user=request.user)
    ctx = {"total": qs.count(), **_counts(qs), "recent": qs[:5],
           "has_demo": qs.filter(is_demo=True).exists()}
    return render(request, "dashboard.html", ctx)


@login_required
def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        record = run_pipeline(
            request.user, cd["image"], cd.get("expected_amount"),
            suspicious_message=cd.get("suspicious_message", ""),
            merchant_confirm=cd.get("merchant_confirm") or "none",
            manual_reference=cd.get("manual_reference", ""),
            claimed_amount=cd.get("claimed_amount"))
        return redirect("result", pk=record.pk)
    return render(request, "upload.html", {"form": form, "max_mb": settings.MAX_UPLOAD_MB})


@login_required
def result(request, pk):
    record = get_object_or_404(VerificationRecord.objects.select_related("user"), pk=pk)
    if record.user != request.user and not request.user.is_staff:
        return redirect("history")
    similar_ids = [s["id"] for s in (record.similar or [])]
    similar = list(_visible(request).filter(pk__in=similar_ids)) if similar_ids else []
    return render(request, "result.html", {"r": record, "similar": similar,
                                           "similar_hidden": len(similar_ids) - len(similar)})


@login_required
def screenshot(request, pk):
    """Serve an uploaded screenshot only to its owner / staff (works with DEBUG off, too)."""
    record = get_object_or_404(VerificationRecord, pk=pk)
    if record.user != request.user and not request.user.is_staff:
        raise Http404
    ctype = mimetypes.guess_type(record.image.name)[0] or "application/octet-stream"
    return FileResponse(record.image.open("rb"), content_type=ctype)


@login_required
def history(request):
    qs = VerificationRecord.objects.filter(user=request.user)
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(result=status)
    if q:
        qs = qs.filter(Q(extracted_reference__icontains=q) | Q(upi_id__icontains=q))
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "history.html", {"page": page, "status": status, "q": q,
                                            "choices": VerificationRecord.RESULTS})


@login_required
def timeline(request):
    """Payment Dispute Time Machine: every verification with its full evidence trail."""
    page = Paginator(_visible(request), 8).get_page(request.GET.get("page"))
    return render(request, "timeline.html", {"page": page, "counts": _counts(_visible(request))})


@login_required
def family(request):
    families, singletons = family_groups(list(_visible(request)))
    return render(request, "family.html", {"families": families, "singletons": singletons})


@login_required
def chain(request):
    records = list(_visible(request)[:50])
    selected = None
    if records:
        wanted = request.GET.get("id", "")
        selected = next((r for r in records if str(r.pk) == wanted), records[0])
    graph = chain_graph(selected, len(selected.similar or [])) if selected else None
    return render(request, "chain.html", {"records": records, "sel": selected, "graph": graph})


def _csv_safe(value):
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@login_required
def export_csv(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="payguard_report.csv"'
    w = csv.writer(resp)
    w.writerow(["id", "time", "user", "expected_amount", "screenshot_amount", "reference", "provider_status",
                "manipulation_risk_percent", "risk_score", "result"])
    for r in _visible(request):
        w.writerow([_csv_safe(x) for x in (
            r.pk, r.created_at.strftime("%Y-%m-%d %H:%M:%S"), r.user.username, r.expected_amount,
            r.extracted_amount, r.extracted_reference, r.provider_status, r.fake_percent, r.risk_score,
            r.get_result_display())])
    return resp


@login_required
@require_POST
def demo_load(request):
    made = create_demo_records(request.user)
    if made:
        messages.success(request, f"Demo data added ({len(made)} sample verifications). "
                                  "Explore the Timeline, Family Tree and Fraud Chain.")
        return redirect("timeline")
    messages.info(request, "Demo data is already loaded for your account.")
    return redirect("dashboard")


@login_required
@require_POST
def demo_clear(request):
    n = clear_demo_records(request.user)
    messages.info(request, f"Removed {n} demo verification(s).")
    return redirect("dashboard")


# ------------------------------------------------------------------- staff page
@user_passes_test(lambda u: u.is_active and u.is_staff, login_url="login")
def admin_dashboard(request):
    qs = VerificationRecord.objects.all()
    ctx = {
        "total": qs.count(), "users": qs.values("user").distinct().count(), **_counts(qs),
        "flagged": qs.filter(result="suspicious").select_related("user")[:10],
        "recent": qs.select_related("user")[:10],
        "ledger": TrustedTransaction.objects.all()[:10],
    }
    return render(request, "admin_dashboard.html", ctx)
