"""PayGuard features rebuilt on the Django data model:
Screenshot Family Tree, Fraud Chain graph and the Fraud What-If Simulator."""
from decimal import Decimal

from .image_analysis import hamming

FAMILY_DISTANCE = 12          # dHash Hamming distance (of 64 bits) treated as "same family"
MAX_FAMILY_RECORDS = 300      # keeps the O(n^2) comparison cheap


# ------------------------------------------------------------ family tree
def family_groups(records):
    """Group records whose perceptual hashes are close. Returns (families, singletons).

    families: list of {"members": [record...], "edges": [{"a", "b", "similarity", "label"}]}
    """
    recs = [r for r in records if r.phash][:MAX_FAMILY_RECORDS]
    parent = list(range(len(recs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = []
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            d = hamming(recs[i].phash, recs[j].phash)
            if d <= FAMILY_DISTANCE:
                parent[find(i)] = find(j)
                sim = round(100 - d / 64 * 100)
                exact = recs[i].sha256 and recs[i].sha256 == recs[j].sha256
                label = "exact copy" if exact else ("near-identical" if sim >= 95 else "possibly edited / cropped")
                edges.append((i, j, sim, label))

    groups = {}
    for i in range(len(recs)):
        groups.setdefault(find(i), []).append(i)

    families, singletons = [], 0
    for members in groups.values():
        if len(members) == 1:
            singletons += 1
            continue
        families.append({
            "members": [recs[i] for i in members],
            "edges": [{"a": recs[i], "b": recs[j], "similarity": s, "label": lab}
                      for i, j, s, lab in edges if i in members],
        })
    families.sort(key=lambda f: -len(f["members"]))
    return families, singletons


# ------------------------------------------------------------ fraud chain
def _short(text, n=26):
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def chain_graph(record, similar_count=None):
    """Nodes/edges (with pixel coordinates) for the server-rendered SVG fraud-chain graph."""
    nodes = [
        {"label": "👤 " + _short(record.user.username, 20), "x": 320, "y": 40},
        {"label": "🖼️ Screenshot #%s" % record.pk, "x": 130, "y": 150},
        {"label": "🔢 Ref: " + _short(record.extracted_reference or "—", 20), "x": 130, "y": 290},
        {"label": "🏦 %s: %s" % (record.provider_source or "provider",
                               record.provider_status or ("not found" if not record.provider_found else "?")),
         "x": 510, "y": 290},
        {"label": "🤖 ML risk: %s%%" % record.fake_percent, "x": 320, "y": 150},
    ]
    links = [(0, 1, False), (1, 2, False), (1, 3, False), (1, 4, False)]
    if record.suspicious_message:
        nodes.append({"label": "🔗 Link / message", "x": 510, "y": 150})
        links += [(0, len(nodes) - 1, True), (len(nodes) - 1, 1, True)]
    sims = record.similar or []
    for k, s in enumerate(sims[:5]):
        nodes.append({"label": "♻️ Similar #%s (%s%%)" % (s.get("id"), round(100 - s.get("distance", 0) / 64 * 100)),
                      "x": 320, "y": 230 + k * 40})
        links.append((1, len(nodes) - 1, False))
    if similar_count is not None and similar_count > 5:
        nodes.append({"label": "… +%d more copies" % (similar_count - 5), "x": 320, "y": 230 + 5 * 40})
        links.append((1, len(nodes) - 1, False))
    edges = [{"x1": nodes[a]["x"], "y1": nodes[a]["y"], "x2": nodes[b]["x"], "y2": nodes[b]["y"], "danger": d}
             for a, b, d in links]
    height = max(360, max(n["y"] for n in nodes) + 50)
    return {"nodes": nodes, "edges": edges, "height": height}


# ------------------------------------------------------------ what-if
WHATIF_SWITCHES = [
    ("amount_mismatch", "Amount mismatch (claimed ≠ expected)"),
    ("duplicate", "Duplicate screenshot"),
    ("missing_confirmation", "No provider / bank confirmation"),
    ("unclear_reference", "Unclear reference number"),
    ("scam_message", "Suspicious link / scam message"),
    ("fake_success", "Screenshot says success, payment actually failed"),
    ("pending_payment", "Provider reports payment still pending"),
    ("edited_image", "Image shows signs of editing"),
]


def simulate(flags: dict) -> dict:
    """Run the REAL decision engine on a synthetic Rs. 1000 payment with the chosen problems switched on."""
    from types import SimpleNamespace

    from .decision import decide
    from .ocr_engine import ExtractedData
    from .transaction_api import ProviderResult

    on = lambda k: bool(flags.get(k))
    expected = Decimal("1000.00")
    claimed = Decimal("900.00") if on("amount_mismatch") else expected

    if on("missing_confirmation") or on("unclear_reference"):
        provider = ProviderResult(found=False, message=("No transaction reference could be read."
                                  if on("unclear_reference") else "Reference not found in trusted records."))
    else:
        status = "failed" if on("fake_success") else "pending" if on("pending_payment") else "success"
        provider = ProviderResult(found=True, status=status, amount=expected, source="sandbox")

    edited = on("edited_image")
    prob = 0.85 if edited else 0.08
    record = SimpleNamespace(
        expected_amount=expected, fake_probability=prob, fake_percent=round(prob * 100),
        suspicious_message="bit.ly/refund-now your refund is ready" if on("scam_message") else "",
        merchant_confirm="none", risk_score=0)
    data = ExtractedData(raw_text="", amount=float(claimed), status_text="success", confidence=90.0,
                         reference="" if on("unclear_reference") else "123456789012")
    image_flags = ["Image metadata shows editing software (Photoshop)."] if edited else []
    dups = ["This exact screenshot was already submitted before."] if on("duplicate") else []

    result, reasons = decide(record, data, provider, image_flags, dups)
    labels = {"confirmed": "Payment confirmed", "pending": "Pending / unverifiable",
              "failed": "Failed", "suspicious": "Suspicious"}
    return {"result": result, "label": labels[result], "risk": record.risk_score, "reasons": reasons}
