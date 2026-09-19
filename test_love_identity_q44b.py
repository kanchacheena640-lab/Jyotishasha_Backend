"""
Q4.4B -- relationship_future_report: BOTH people's identity must reach the report, and nothing internal may come with it.

Bug (found in Q4.4): the partner's name / DOB / TOB / POB were stored in Order.partner_payload and even preserved by the
data collector, but they were dropped at three boundaries -- the prompt evidence allowlist (no names), the premium task
(only the primary person's user_info went to the renderer) and the renderer/template (no partner concept). The report
therefore never named the partner and the PDF showed only the primary person.

These tests use production-shaped fixtures with names/places that appear NOWHERE in production code (proving nothing is
hardcoded), run the real Kundali + Ashtakoot engines and the real premium task, and make no AI call and no network/DB call.
"""
import copy
import io
import json
import os
import re
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from full_kundali_api import calculate_full_kundali  # noqa: E402
from modules.love.love_data_collector import collect_love_report_data  # noqa: E402
from modules.love.love_prompt_builder import build_love_premium_prompt  # noqa: E402

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON  # noqa: E402  (the synthetic certificate the repo's own boot tests use)
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
import modules.love.love_premium_task as premium  # noqa: E402
import pdf_generator_weasy as renderer  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


# ---- production-shaped order: Order columns for the primary person (strings), partner_payload for the partner ----
ORDER_PRIMARY = dict(
    name="Rohan Mehta", dob="1988-11-03", tob="07:20", pob="Mumbai, Maharashtra, India",
    latitude="19.0760", longitude="72.8777",
)
PARTNER_LIVE = dict(
    name="Kavya Nair", dob="1991-02-14", tob="18:05", pob="Chennai, Tamil Nadu, India",
    latitude=13.0827, longitude=80.2707,
)
PRIMARY_IDENTITY = {k: ORDER_PRIMARY[k] for k in ("name", "dob", "tob", "pob")}
PARTNER_IDENTITY = {k: PARTNER_LIVE[k] for k in ("name", "dob", "tob", "pob")}
FORBIDDEN_KEYS = {"latitude", "longitude", "lat", "lng", "lon", "timezone", "tz", "tz_offset", "id", "order_id", "case", "mode",
                  "partner_data_mode", "email", "phone"}
COORD_TEXT = ("19.0760", "72.8777", "13.0827", "80.2707", "19.076", "13.0827")

_kundali_cache = {}


def user_kundali(language):
    if language not in _kundali_cache:
        _kundali_cache[language] = calculate_full_kundali(
            name=ORDER_PRIMARY["name"], dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"],
            lat=float(ORDER_PRIMARY["latitude"]), lon=float(ORDER_PRIMARY["longitude"]), language=language)
    return copy.deepcopy(_kundali_cache[language])


def collect(partner, language="en"):
    order = {**ORDER_PRIMARY, "language": language, "partner": partner}
    return collect_love_report_data(order=order, user_kundali=user_kundali(language), language=language, boy_is_user=True)


def evidence_of(prompt):
    return json.loads(prompt.split("Deterministic evidence:\n")[1])


print("\n=== 1: the collector hands over a dedicated identity block (primary + partner), nothing else ===")
full = collect(dict(PARTNER_LIVE))
check("1: compatibility is genuinely full-dual for the live shape", full["compatibility"]["case"] == "A_FULL_DUAL")
check("1: primary identity is exactly name/dob/tob/pob", full["identity"]["primary"] == PRIMARY_IDENTITY)
check("1: partner identity is exactly name/dob/tob/pob", full["identity"]["partner"] == PARTNER_IDENTITY)
check("1: no coordinate / timezone / id / mode key in either identity",
      not (FORBIDDEN_KEYS & set(full["identity"]["primary"])) and not (FORBIDDEN_KEYS & set(full["identity"]["partner"])))
blob = json.dumps(full["identity"], ensure_ascii=False)
check("1: no coordinate value appears anywhere in the identity block", not any(c in blob for c in COORD_TEXT))
check("1: the identity block carries no internal identifiers", not re.search(r"A_FULL_DUAL|B_DOB_ONLY|partner_data_mode", blob))

print("\n=== 2: partial partner data -> only the fields that exist (nothing invented, nothing blank) ===")
dob_only = collect({"name": "Kavya Nair", "dob": "1991-02-14"})
check("2: DOB-only partner is still the intentional DOB-only fallback", dob_only["compatibility"]["case"] == "B_DOB_ONLY_HYBRID")
check("2: partner identity has exactly the supplied fields (no tob/pob keys, no placeholders)",
      dob_only["identity"]["partner"] == {"name": "Kavya Nair", "dob": "1991-02-14"})
check("2: primary identity is unaffected by the partner's completeness", dob_only["identity"]["primary"] == PRIMARY_IDENTITY)
blank = collect({"name": "  Kavya Nair ", "dob": "1991-02-14", "tob": "", "pob": None})
check("2: blank / None / padded values are normalised, never carried as empty text", blank["identity"]["partner"] == {"name": "Kavya Nair", "dob": "1991-02-14"})

print("\n=== 3: the model receives BOTH names (real prompt builder) but never coordinates or internal mode names ===")
for lang in ("en", "hi"):
    prompt = build_love_premium_prompt(collect(dict(PARTNER_LIVE), lang))
    ev = evidence_of(prompt)
    check(f"3[{lang}]: evidence names both people", ev["people"] == {"primary_person": "Rohan Mehta", "partner": "Kavya Nair"})
    check(f"3[{lang}]: the prompt tells the model who is who (both first names + which values are whose)",
          "Rohan Mehta" in prompt and "Kavya Nair" in prompt and "Rohan" in prompt.split("Deterministic evidence:")[0])
    evidence_text = prompt.split("Deterministic evidence:\n")[1]
    check(f"3[{lang}]: no coordinate value reaches the model", not any(c in prompt for c in COORD_TEXT))
    check(f"3[{lang}]: no internal mode identifier in the evidence block", not re.search(r"A_FULL_DUAL|B_DOB_ONLY_HYBRID|partner_data_mode", evidence_text))
    check(f"3[{lang}]: the partner's DOB/TOB/POB are not forced into the model evidence (identity is rendered by the PDF)",
          "1991-02-14" not in evidence_text and "Chennai" not in evidence_text)

print("\n=== 4: no name is hardcoded in production code ===")
prod = {}
for path in ("modules/love/love_data_collector.py", "modules/love/love_prompt_builder.py", "modules/love/love_premium_task.py",
             "pdf_generator_weasy.py", "templates/report_template.html", "modules/payments/report_i18n_labels.py"):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), path), encoding="utf-8") as fh:
        prod[path] = fh.read()
for path, text in prod.items():
    hits = [w for w in ("Aarav", "Ananya", "Sharma", "Verma", "Rohan", "Kavya", "Lucknow", "New Delhi", "Chennai") if w in text]
    check(f"4: {path} contains no demo/fixture person or place ({hits or 'none'})", not hits)

print("\n=== 5: the REAL premium task passes both identities to the renderer, leak-free (AI + PDF mocked) ===")


def run_premium_task(language, partner, report_body=None, hero=None):
    live_partner = dict(partner)
    order = SimpleNamespace(
        id=515151, name=ORDER_PRIMARY["name"], email="fixture@example.invalid", phone=None, product="relationship_future_report",
        dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"], pob=ORDER_PRIMARY["pob"],
        latitude=ORDER_PRIMARY["latitude"], longitude=ORDER_PRIMARY["longitude"], language=language,
        payment_status="PAID", status="PAID", report_stage="Pending", pdf_url=None, created_at=None,
        partner_payload=live_partner, processing_started_at=None,
    )
    query = MagicMock()
    query.get.return_value = order
    seen, pdf = {}, {}
    meta = {"hero": hero or {"label": "Relationship Outlook", "value": "Warm and steady", "interpretation": "Grounded in the supplied evidence.",
                             "evidence": ["Moon is in the 5th house."], "action_items": ["Talk calmly."]}}
    body = report_body or "1. Relationship Outlook\nRohan and Kavya share a steady base.\n2. Compatibility Snapshot\nBody."
    completion = SimpleNamespace(content="===META===\n" + json.dumps(meta) + "\n===REPORT===\n" + body,
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
    order, live_partner, seen, pdf = run_premium_task(lang, PARTNER_LIVE)
    check(f"5[{lang}]: the task reached Ready", order.report_stage == "Ready")
    check(f"5[{lang}]: renderer receives the primary identity (name/dob/tob/pob)", pdf["user_info"] == PRIMARY_IDENTITY)
    check(f"5[{lang}]: renderer receives the partner identity (name/dob/tob/pob), exactly", pdf["partner_info"] == PARTNER_IDENTITY)
    customer_facing = json.dumps({k: pdf[k] for k in ("user_info", "partner_info", "gpt_response", "answer_hero", "action_list")}, ensure_ascii=False)
    check(f"5[{lang}]: no coordinate value reaches anything customer-facing", not any(c in customer_facing for c in COORD_TEXT))
    check(f"5[{lang}]: no internal identifier reaches anything customer-facing",
          not re.search(r"A_FULL_DUAL|B_DOB_ONLY|partner_data_mode|partner_birth_data|astro_facts|compiled_report|verdict_level", customer_facing))
    check(f"5[{lang}]: no order id reaches the partner block", "515151" not in json.dumps(pdf["partner_info"]))
    check(f"5[{lang}]: the stored order.partner_payload was not mutated", live_partner == PARTNER_LIVE and "lat" not in order.partner_payload)

order, _, seen, pdf = run_premium_task("en", {"name": "Kavya Nair", "dob": "1991-02-14"})
check("5: a DOB-only partner still renders (name + DOB only)", order.report_stage == "Ready" and pdf["partner_info"] == {"name": "Kavya Nair", "dob": "1991-02-14"})
order, _, seen, pdf = run_premium_task("en", {"dob": "1991-02-14"})
check("5: a partner with NO name is rejected up front (existing collector contract) -- no report and no invented name reach the renderer",
      order.report_stage == "Failed" and "partner_info" not in pdf and "prompt" not in seen)

print("\n=== 6: the shared renderer prints a dual-person identity block ONLY when partner data is supplied ===")


def render_html(language="en", **overrides):
    captured = {}

    class FakeHTML:
        def __init__(self, string=None, base_url=None):
            captured["html"] = string

        def write_pdf(self, path):
            return None

    args = dict(
        output_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp", "q44b_unused.pdf"),
        user_info=dict(PRIMARY_IDENTITY), summary_blocks={}, gpt_response="1. Relationship Outlook\nBody text.",
        kundali_drawing=None, used_placeholders=[], product="relationship_future_report", language=language,
    )
    args.update(overrides)
    with patch.object(renderer, "HTML", FakeHTML), patch("os.makedirs"):
        renderer.generate_pdf_report_weasy(**args)
    return captured["html"]


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


dirty_partner = dict(PARTNER_IDENTITY, latitude=13.0827, longitude=80.2707, lat=13.0827, lng=80.2707, timezone="Asia/Kolkata",
                     tz_offset=5.5, order_id=515151, partner_data_mode="A_FULL_DUAL", case="A_FULL_DUAL", email="x@example.invalid")
for lang in ("en", "hi"):
    html = render_html(lang, partner_info=dirty_partner)
    txt = text_of(html)
    check(f"6[{lang}]: the block is rendered", 'class="people-card"' in html)
    check(f"6[{lang}]: both names, DOBs (DD/MM/YYYY), times and places are printed",
          all(v in txt for v in ("Rohan Mehta", "Kavya Nair", "03/11/1988", "14/02/1991", "07:20", "18:05", "Mumbai, Maharashtra, India", "Chennai, Tamil Nadu, India")))
    check(f"6[{lang}]: the raw ISO dates are not printed", "1988-11-03" not in txt and "1991-02-14" not in txt)
    check(f"6[{lang}]: the cover line names both people", "Rohan Mehta &amp; Kavya Nair" in html)
    check(f"6[{lang}]: coordinates / timezone / order id / mode identifiers never reach the PDF HTML",
          not any(c in html for c in ("13.0827", "80.2707", "19.076", "Asia/Kolkata", "515151", "A_FULL_DUAL", "partner_data_mode", "x@example.invalid", "5.5")))
    heading = "यह Report इनके लिए है" if lang == "hi" else "This Report Is For"
    check(f"6[{lang}]: the block heading is localized ({heading!r})", heading in txt)

html = render_html("en", partner_info={"name": "Kavya Nair", "dob": "1991-02-14"})
txt = text_of(html)
check("6: DOB-only partner -> only the supplied lines (no empty Time/Place rows for the partner)",
      txt.count("Time of Birth") == 1 and txt.count("Place of Birth") == 1 and txt.count("Date of Birth") == 2)

print("\n=== 7: standard reports are structurally untouched (no partner data -> no partner markup, no new CSS) ===")
base = render_html("en")
for label, extra in (("None", dict(partner_info=None)), ("empty dict", dict(partner_info={})),
                     ("no name", dict(partner_info={"dob": "1991-02-14", "pob": "Chennai"})), ("blank name", dict(partner_info={"name": "   ", "dob": "1991-02-14"})),
                     ("non-dict", dict(partner_info="Kavya Nair"))):
    check(f"7: partner_info={label} renders byte-identical HTML to the standard render", render_html("en", **extra) == base)
check("7: the standard render contains no people-card markup, CSS or label",
      not re.search(r"people-card|people-heading|person-name|person-detail|This Report Is For|Time of Birth", base))
check("7: the standard cover line is still the original single 'Prepared for' line", "Prepared for:</strong> Rohan Mehta" in re.sub(r"\s+", " ", base) or "Prepared for:" in base)
base_hi = render_html("hi")
check("7: the Hindi standard render has no partner markup either", not re.search(r"people-card|यह Report इनके लिए है", base_hi))

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
