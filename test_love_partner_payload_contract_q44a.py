"""
Q4.4A -- relationship_future_report: the LIVE partner payload shape must reach the engine as a full dual-Kundali.

Bug (found in Q4.4): the frontend form and OrderService store the partner's coordinates as
`latitude` / `longitude`, but service_love.detect_case() only enters A_FULL_DUAL when the partner
has `lat` / `lng`. With the live shape every paid order silently became B_DOB_ONLY_HYBRID: the
partner's Moon was derived from the DOB alone (Aquarius/Dhanishta instead of Libra/Vishakha) and the
Ashtakoot total was 34.5/36 instead of 32.5/36.

These tests use the SAME shape the live order flow stores (no lat/lng added by hand), run the real
Kundali + Ashtakoot engines (nothing mocked), and make no AI call.
"""
import copy
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from full_kundali_api import calculate_full_kundali  # noqa: E402
from modules.love.ashtakoot_love import compute_ashtakoot  # noqa: E402
from modules.love.love_data_collector import (  # noqa: E402
    collect_love_report_data, _pick_partner, LoveCollectorError,
)
from modules.love.love_prompt_builder import build_love_premium_prompt  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


# ---- the exact shape OrderService stores: Order columns for the primary person (strings), partner_payload for the partner
ORDER_PRIMARY = dict(
    name="Aarav Sharma", dob="1990-06-15", tob="14:30", pob="Lucknow, Uttar Pradesh, India",
    latitude="26.8467", longitude="80.9462", language="en",
)
PARTNER_LIVE = dict(
    name="Ananya Verma", dob="1992-03-22", tob="10:45", pob="New Delhi, India",
    latitude=28.6139, longitude=77.2090,
)
EXPECTED_KOOTAS = {"varna": 1, "vashya": 2, "tara": 1.5, "yoni": 2, "graha_maitri": 5, "gana": 6, "bhakoot": 7, "nadi": 8}
EXPECTED_TOTAL = 32.5

_user_kundali_cache = {}


def user_kundali(language="en"):
    if language not in _user_kundali_cache:
        _user_kundali_cache[language] = calculate_full_kundali(
            name=ORDER_PRIMARY["name"], dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"],
            lat=float(ORDER_PRIMARY["latitude"]), lon=float(ORDER_PRIMARY["longitude"]), language=language,
        )
    return copy.deepcopy(_user_kundali_cache[language])


def collect(partner, language="en", **order_extra):
    order = {**ORDER_PRIMARY, "language": language, "partner": partner, **order_extra}
    return collect_love_report_data(order=order, user_kundali=user_kundali(language), language=language, boy_is_user=True)


def moon_of(kundali):
    return next(p for p in kundali["planets"] if p["name"] == "Moon")


print("\n=== 1: the exact live payload (latitude/longitude only) -> A_FULL_DUAL, real engine ===")
partner_before = copy.deepcopy(PARTNER_LIVE)
payload = collect(PARTNER_LIVE)
compat = payload["compatibility"]
a = compat["ashtakoot"]
check("1: mode is A_FULL_DUAL", compat["case"] == "A_FULL_DUAL")
check("1: analysis label is the full dual-Kundali one", compat["labels"].get("analysis") == "Full Dual-Kundali Vedic")
check("1: no DOB-only limitation note is emitted", compat["notes"] == [])
check("1: no fallback (DOB-only 5th-house) analysis is attached", compat.get("fallback") is None)

ananya = calculate_full_kundali(name="Ananya Verma", dob="1992-03-22", tob="10:45", lat=28.6139, lon=77.2090, language="en")
aarav = user_kundali()
check("1: Ananya (independent full Kundali): Lagna Taurus", ananya["lagna_sign"] == "Taurus")
check("1: Ananya: Moon Libra", moon_of(ananya)["sign"] == "Libra")
check("1: Ananya: Nakshatra Vishakha", moon_of(ananya)["nakshatra"] == "Vishakha")
check("1: Aarav (independent full Kundali): Lagna Libra, Moon Aquarius, Shatabhisha",
      aarav["lagna_sign"] == "Libra" and moon_of(aarav)["sign"] == "Aquarius" and moon_of(aarav)["nakshatra"] == "Shatabhisha")

# Ashtakoot recomputed independently from the two full Kundalis with the SAME engine and the SAME role mapping
# (boy_is_user=True -> Aarav is the groom).
def moon_view(k):
    m = moon_of(k)
    return {"rashi": m["sign"], "degree": m.get("degree"), "nakshatra": m.get("nakshatra")}


independent = compute_ashtakoot(bride_moon=moon_view(ananya), groom_moon=moon_view(aarav))
check("1: total equals the independently computed Ashtakoot total", a["total_score"] == independent["total_score"])
for name, expected in EXPECTED_KOOTAS.items():
    check(f"1: koota {name} = {expected} and equals the independent engine result",
          a["kootas"][name]["score"] == expected and a["kootas"][name]["score"] == independent["kootas"][name]["score"])
check(f"1: total = {EXPECTED_TOTAL}/36", a["total_score"] == EXPECTED_TOTAL and a["max_score"] == 36)
check("1: the 8 koota scores sum to the displayed total", sum(v["score"] for v in a["kootas"].values()) == a["total_score"])
check("1: locked Ashtakoot maxima are 1/2/3/4/5/6/7/8 (total 36)",
      [a["kootas"][n]["max"] for n in ("varna", "vashya", "tara", "yoni", "graha_maitri", "gana", "bhakoot", "nadi")] == [1, 2, 3, 4, 5, 6, 7, 8])
check("1: the partner's Moon is NOT the DOB-only approximation (Aquarius/Dhanishta)",
      moon_view(ananya)["rashi"] == "Libra" and moon_view(ananya)["nakshatra"] == "Vishakha")

blob = json.dumps({"compiled": payload["compiled_report"], "compat": compat}, ensure_ascii=False).lower()
for bad in ("birth time/place not provided", "not provided", "partial analysis", "moon derived from dob", "dob only", "dob-only"):
    check(f"1: full-payload report data carries no DOB-only limitation text ({bad!r})", bad not in blob)
check("1: the collector did not mutate the caller's partner payload", PARTNER_LIVE == partner_before)

print("\n=== 1b: what the model is actually shown (real prompt builder, no AI call) ===")
prompt = build_love_premium_prompt(payload)
evidence = json.loads(prompt.split("Deterministic evidence:\n")[1])
check("1b: prompt evidence says the partner's birth data is full (plain words, no internal mode name)", evidence["partner_birth_data"]["completeness"] == "full" and "A_FULL_DUAL" not in json.dumps(evidence))
check("1b: prompt evidence carries the 32.5/36 total", evidence["ashtakoot"]["total_score"] == 32.5 and evidence["ashtakoot"]["max_score"] == 36)
check("1b: prompt evidence carries the 8 real koota scores",
      {k: v["score"] for k, v in evidence["ashtakoot"]["kootas"].items()} == EXPECTED_KOOTAS)

print("\n=== 2: canonical latitude/longitude only -> A_FULL_DUAL (string coordinates as stored in JSON) ===")
p = collect({**PARTNER_LIVE, "latitude": "28.6139", "longitude": "77.2090"})
check("2: string latitude/longitude -> A_FULL_DUAL with the same total", p["compatibility"]["case"] == "A_FULL_DUAL" and p["compatibility"]["ashtakoot"]["total_score"] == EXPECTED_TOTAL)

print("\n=== 3: legacy/internal lat/lng only -> A_FULL_DUAL (backward compatible) ===")
legacy = {k: v for k, v in PARTNER_LIVE.items() if k not in ("latitude", "longitude")}
legacy.update(lat=28.6139, lng=77.2090)
p = collect(legacy)
check("3: lat/lng only -> A_FULL_DUAL", p["compatibility"]["case"] == "A_FULL_DUAL")
check("3: lat/lng result is identical to the latitude/longitude result", p["compatibility"]["ashtakoot"] == a)
check("3: the legacy dict is passed through with lat/lng intact", _pick_partner({"partner": legacy})["lat"] == 28.6139 and _pick_partner({"partner": legacy})["lng"] == 77.2090)

print("\n=== 4: DOB-only partner still -> B_DOB_ONLY_HYBRID (intentional fallback preserved) ===")
for label, dob_only in (
    ("name+dob", {"name": "Ananya Verma", "dob": "1992-03-22"}),
    ("name+dob+tob, no coordinates", {"name": "Ananya Verma", "dob": "1992-03-22", "tob": "10:45", "pob": "New Delhi, India"}),
):
    p = collect(dob_only)
    check(f"4: {label} -> B_DOB_ONLY_HYBRID", p["compatibility"]["case"] == "B_DOB_ONLY_HYBRID")
    check(f"4: {label} -> the DOB-only limitation note is still emitted", any("not provided" in n for n in p["compatibility"]["notes"]))
    check(f"4: {label} -> fallback analysis still attached", p["compatibility"].get("fallback") is not None)
check("4: DOB-only Moon is the approximation (Aquarius) -- proving the two modes really differ",
      collect({"name": "Ananya Verma", "dob": "1992-03-22"})["compatibility"]["ashtakoot"]["total_score"] != EXPECTED_TOTAL)

print("\n=== 5: precedence when BOTH forms are present: canonical latitude/longitude wins ===")
both = {**PARTNER_LIVE, "lat": 19.0760, "lng": 72.8777}   # stale Mumbai alias next to the real Delhi canonical values
picked = _pick_partner({"partner": both})
check("5: canonical latitude/longitude overrides the stale lat/lng alias", picked["lat"] == 28.6139 and picked["lng"] == 77.2090)
check("5: end-to-end result equals the canonical-only result", collect(both)["compatibility"]["ashtakoot"] == a)
check("5: canonical values are copied without coercion (type preserved)", _pick_partner({"partner": {**PARTNER_LIVE, "latitude": "28.6139", "longitude": "77.2090"}})["lat"] == "28.6139")
check("5: an INVALID canonical pair never overrides a valid legacy pair",
      _pick_partner({"partner": {**legacy, "latitude": "abc", "longitude": "xyz"}})["lat"] == 28.6139)
mixed = _pick_partner({"partner": {**legacy, "latitude": 12.0}})   # canonical pair incomplete
check("5: a half canonical pair is never mixed with alias values", mixed["lat"] == 28.6139 and mixed["lng"] == 77.2090)

print("\n=== 6: partner data is preserved, nothing is mutated ===")
rich = {**PARTNER_LIVE, "gender": "female", "timezone": "Asia/Kolkata", "custom_note": {"k": [1, 2]}, "email": "x@example.invalid"}
rich_before = copy.deepcopy(rich)
order = {**ORDER_PRIMARY, "partner": rich}
order_before = copy.deepcopy(order)
picked = _pick_partner(order)
check("6: every original partner field is preserved unchanged", all(picked[k] == v for k, v in rich_before.items()))
check("6: the only additions are the engine's lat/lng aliases", set(picked) - set(rich_before) == {"lat", "lng"})
check("6: latitude/longitude themselves are unchanged", picked["latitude"] == 28.6139 and picked["longitude"] == 77.2090)
check("6: the stored partner_payload dict is not mutated", rich == rich_before)
check("6: the whole order dict is not mutated", order == order_before)
check("6: the returned partner is a copy, not the stored object", picked is not rich)

print("\n=== 7: the primary person is untouched ===")
p = collect(PARTNER_LIVE)
check("7: primary lat/lng come straight from the order's latitude/longitude, unchanged",
      p["client"]["lat"] == "26.8467" and p["client"]["lng"] == "80.9462")
check("7: primary identity unchanged", (p["client"]["name"], p["client"]["dob"], p["client"]["tob"]) == ("Aarav Sharma", "1990-06-15", "14:30"))
check("7: the primary is the groom/user, the partner is the bride/partner (production boy_is_user=True mapping)",
      p["partner"]["name"] == "Ananya Verma" and p["compatibility"]["meta"] == {"user_name": "Aarav Sharma", "partner_name": "Ananya Verma"})

print("\n=== 8: invalid / missing coordinates are never fabricated ===")
def alias_added(partner):
    r = _pick_partner({"partner": partner})
    return "lat" in r or "lng" in r

base = {k: v for k, v in PARTNER_LIVE.items() if k not in ("latitude", "longitude")}
cases = {
    "non-numeric strings": {"latitude": "abc", "longitude": "xyz"},
    "latitude only": {"latitude": 28.6139},
    "longitude only": {"longitude": 77.2090},
    "None values": {"latitude": None, "longitude": None},
    "blank strings": {"latitude": "  ", "longitude": ""},
    "out-of-range latitude": {"latitude": 95.0, "longitude": 77.2090},
    "out-of-range longitude": {"latitude": 28.6139, "longitude": 190.0},
    "NaN": {"latitude": float("nan"), "longitude": 77.2090},
    "boolean": {"latitude": True, "longitude": True},
    "(0, 0) placeholder (the form's default when no place was picked)": {"latitude": 0, "longitude": 0},
    "(0, 0) as strings": {"latitude": "0", "longitude": "0.0"},
}
for label, coords in cases.items():
    check(f"8: {label}: no lat/lng alias is fabricated", not alias_added({**base, **coords}))
for label, coords in (("invalid", cases["non-numeric strings"]), ("(0, 0) placeholder", cases["(0, 0) placeholder (the form's default when no place was picked)"]), ("missing", {})):
    p = collect({**base, **coords})
    check(f"8: {label} coordinates -> existing DOB-only mode applies, not a wrong-place full analysis", p["compatibility"]["case"] == "B_DOB_ONLY_HYBRID")
check("8: a genuine equator latitude of 0 with a real longitude IS accepted", alias_added({**base, "latitude": 0, "longitude": 77.2090}))
check("8: a genuine prime-meridian longitude of 0 with a real latitude IS accepted", alias_added({**base, "latitude": 51.5, "longitude": 0}))
try:
    collect_love_report_data(order={**ORDER_PRIMARY, "partner": {"name": "Ananya Verma"}}, user_kundali=user_kundali(), language="en")
    raised = False
except LoveCollectorError:
    raised = True
check("8: existing validation is unchanged: a partner without a DOB still raises LoveCollectorError", raised)
try:
    collect_love_report_data(order={"name": "Aarav Sharma", "dob": "1990-06-15", "tob": "14:30", "partner": PARTNER_LIVE}, user_kundali=user_kundali(), language="en")
    raised = False
except LoveCollectorError:
    raised = True
check("8: existing validation is unchanged: a primary person without coordinates still raises", raised)
flat = _pick_partner({"partner_name": "Ananya Verma", "partner_dob": "1992-03-22", "partner_tob": "10:45", "partner_lat": 28.6139, "partner_lng": 77.2090})
check("8: the legacy flat partner_* fallback path is unchanged", flat["lat"] == 28.6139 and flat["lng"] == 77.2090 and flat["name"] == "Ananya Verma")

print("\n=== 9: the REAL premium task with the live order shape hands the model a full dual-Kundali (AI call mocked) ===")
import io  # noqa: E402
from contextlib import ExitStack, redirect_stdout, redirect_stderr  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON  # noqa: E402  (the synthetic certificate the repo's own boot tests use)
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
import modules.love.love_premium_task as premium  # noqa: E402


def run_premium_task(language):
    live_partner = dict(PARTNER_LIVE)     # exactly what Order.partner_payload holds -- no lat/lng
    order = SimpleNamespace(
        id=424242, name=ORDER_PRIMARY["name"], email="fixture@example.invalid", phone=None, product="relationship_future_report",
        dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"], pob=ORDER_PRIMARY["pob"],
        latitude=ORDER_PRIMARY["latitude"], longitude=ORDER_PRIMARY["longitude"], language=language,
        payment_status="PAID", status="PAID", report_stage="Pending", pdf_url=None, created_at=None,
        partner_payload=live_partner, processing_started_at=None,
    )
    query = MagicMock()
    query.get.return_value = order
    seen, pdf = {}, {}
    meta = {"hero": {"label": "Relationship Outlook", "value": "Warm and steady", "interpretation": "Grounded in the supplied evidence.",
                     "evidence": ["Moon is in the 5th house."], "action_items": ["Talk calmly."]}}
    completion = SimpleNamespace(content="===META===\n" + json.dumps(meta) + "\n===REPORT===\n1. Relationship Outlook\nBody.",
                                 model="gpt-5.6-luna", input_tokens=1, output_tokens=1, total_tokens=2, duration_seconds=0.1)

    def fake_ai(prompt):
        seen["prompt"] = prompt
        return completion

    reader = open

    def safe_open(path, mode="r", *args, **kwargs):
        return io.StringIO() if "w" in mode else reader(path, mode, *args, **kwargs)

    with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        stack.enter_context(patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("DB access forbidden")))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")))
        stack.enter_context(patch.object(premium, "Order", SimpleNamespace(query=query)))
        stack.enter_context(patch.object(premium, "db", SimpleNamespace(session=MagicMock())))
        stack.enter_context(patch.object(premium, "record_event"))
        stack.enter_context(patch.object(premium, "deliver_generated_report"))
        stack.enter_context(patch.object(premium, "generate_kundali_drawing", return_value=None))
        stack.enter_context(patch.object(premium, "generate_pdf_report", side_effect=lambda **kw: pdf.update(kw)))
        stack.enter_context(patch.object(premium, "generate_report_completion", side_effect=fake_ai))
        stack.enter_context(patch.object(premium, "open", safe_open, create=True))
        stack.enter_context(patch("os.makedirs"))
        premium.generate_love_premium_report(order.id)
    return order, live_partner, seen, pdf


for lang in ("en", "hi"):
    order, live_partner, seen, pdf = run_premium_task(lang)
    ev = json.loads(seen["prompt"].split("Deterministic evidence:\n")[1])
    check(f"9[{lang}]: the real task reached Ready", order.report_stage == "Ready")
    check(f"9[{lang}]: the model was shown full partner birth data", ev["partner_birth_data"]["completeness"] == "full")
    check(f"9[{lang}]: the model was shown the real 32.5/36 and the 8 real koota scores",
          ev["ashtakoot"]["total_score"] == 32.5 and {k: v["score"] for k, v in ev["ashtakoot"]["kootas"].items()} == EXPECTED_KOOTAS)
    check(f"9[{lang}]: the stored order.partner_payload was not mutated (no lat/lng written back)", live_partner == PARTNER_LIVE and "lat" not in order.partner_payload)
    label = "अष्टकूट अनुकूलता" if lang == "hi" else "Ashtakoot compatibility"
    check(f"9[{lang}]: the PDF hero's engine-owned supporting evidence carries the real total", pdf["answer_hero"]["evidence"][0] == f"{label}: 32.5/36")
    check(f"9[{lang}]: the PDF is rendered as the relationship product in the right language", pdf["product"] == "relationship_future_report" and pdf["language"] == lang)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
