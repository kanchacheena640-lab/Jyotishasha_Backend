"""SNR-2D -- Spouse Nature Report (rep_026): product registration + generation wiring.

Runs against the local DB only, reusing Step 2's isolated fixture/environment
(fake FCM, dummy OpenAI/Razorpay keys). Every outward boundary is mocked: the
report AI client, the PDF writer and email delivery. No live OpenAI call, no
real payment, no PDF written, no email sent.

Run: python -m unittest test_snr_2d_spouse_report_integration -v
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import test_report_platform_suresh_webhook_first as incident
from sqlalchemy.exc import IntegrityError

import tasks
from config.pricing import PRODUCT_PRICES
from full_kundali_api import calculate_full_kundali
from modules.payments import purchase_measurement as pm
from modules.payments import report_ai_client
from modules.payments import spouse_narrative as sn
from modules.payments.report_product_intelligence import REGISTRY, get_product_intelligence
from modules.payments.report_product_registry import ReportProduct
from modules.payments.report_structured_output import ReportMetadataError
from modules.payments.spouse_evidence import SpouseEvidenceError, build_spouse_evidence

SLUG = "spouse_nature_report"
ORIGINAL_GENERATORS = ("standard_v1", "love_premium_v1")
# The published sample persona -- the same deterministic chart the SNR-2C contract tests use.
PERSONA = dict(name="Aarav Sharma", dob="1990-06-15", tob="14:30", lat=26.8467, lon=80.9462)
EVIDENCE = build_spouse_evidence(calculate_full_kundali(language="en", **PERSONA))
AI_HERO_VALUE = "AI value that must be overridden"

SAFE_BODY = {
    "en": {
        "snapshot": "Your chart strongly suggests an expressive, dynamic and independent partner.",
        "nature": "A prominent tendency is an energetic, self-directed temperament. Different factors point in different directions for approach to life.",
        "communication": "Communication strongly suggests openness in conversation. Emotional style shows a combination of private and open sides.",
        "chart_basis": "The 7th-house sign and its lord shape these themes, with Venus placed in the 7th house adding warmth.",
        "navamsa": "The Navamsa supports and reinforces the birth-chart picture, while the Darakaraka adds a supporting note.",
        "health": "Mixed indicators suggest that wellbeing may depend more on lifestyle, routine and circumstances.",
        "wealth": "A relatively steady resource-building tendency appears, and the path to resources may involve non-traditional channels.",
        "integrated": "Together these themes describe an energetic partner; patient, open conversation will help you both.",
    },
    "hi": {
        "snapshot": "आपकी कुंडली स्पष्ट रूप से संकेत देती है कि जीवनसाथी अभिव्यक्तिशील, ऊर्जावान और स्वतंत्र विचारों वाला हो सकता है।",
        "nature": "एक प्रमुख प्रवृत्ति ऊर्जावान और आत्मनिर्भर स्वभाव की है। जीवन के प्रति दृष्टिकोण पर अलग-अलग कारक अलग दिशाओं की ओर संकेत करते हैं।",
        "communication": "संवाद में खुलापन एक स्पष्ट विषय है। भावनात्मक शैली में निजी और खुले, दोनों पक्षों के संकेत हैं।",
        "chart_basis": "सप्तम भाव की राशि और सप्तमेश इन विषयों को आकार देते हैं, और सप्तम भाव में स्थित शुक्र आत्मीयता जोड़ता है।",
        "navamsa": "नवांश जन्मकुंडली के संकेत का समर्थन करता है, और दाराकारक एक सहायक संकेत जोड़ता है।",
        "health": "मिले-जुले संकेत बताते हैं कि स्वास्थ्य जीवनशैली, दिनचर्या और परिस्थितियों पर अधिक निर्भर कर सकता है।",
        "wealth": "संसाधन जुटाने की अपेक्षाकृत स्थिर प्रवृत्ति दिखती है, और रास्ता गैर-पारंपरिक माध्यमों से भी हो सकता है।",
        "integrated": "ये सभी विषय मिलकर एक ऊर्जावान जीवनसाथी का चित्र बनाते हैं; धैर्य और खुली बातचीत आप दोनों के लिए सहायक होगी।",
    },
}


def spouse_response(lang="en", meta_patch=None, bodies=None):
    """A mocked Luna reply in the SNR-2C wire format for EVIDENCE."""
    _, allowed = sn.build_evidence_block(EVIDENCE)
    nature = [r for r in allowed if r.startswith("nature.")]
    refs = {
        "snapshot": nature[:1], "nature": nature[:1], "communication": nature[:1],
        "chart_basis": ["chart_facts.d1.seventh_sign", "chart_facts.d1.seventh_lord"],
        "navamsa": ["chart_facts.d9.seventh_sign", "chart_facts.darakaraka"],
        "health": ["health.class"], "wealth": ["wealth.class"], "integrated": nature[:1],
    }
    meta = {
        "answer_hero": {"label": sn.HERO_LABEL[lang], "value": AI_HERO_VALUE,
                        "interpretation": SAFE_BODY[lang]["snapshot"], "evidence": ["The 7th-house sign is read first."],
                        "evidence_refs": ["chart_facts.d1.seventh_sign"]},
        "classes": {"health": EVIDENCE["health"]["class"], "wealth": EVIDENCE["wealth"]["class"]},
        "traits_discussed": [{"dimension": t["dimension"], "class": t["class"],
                              "direction": None if t["class"] == "MIXED" else t["direction"]}
                             for t in EVIDENCE["nature"]["traits"] if t["reportable"]],
        "sections": [{"key": k, "evidence_refs": r} for k, r in refs.items()],
        "action_items": ["Share expectations calmly.", "Make room for each other's independence."]
                        if lang == "en" else ["अपेक्षाओं पर शांति से बात करें।", "एक-दूसरे की स्वतंत्रता का सम्मान करें।"],
    }
    if meta_patch:
        meta_patch(meta)
    body = dict(SAFE_BODY[lang], **(bodies or {}))
    parts = [f"**{i}. {sn.SECTION_TITLES[lang][key]}**\n{body[key]}" for i, key in enumerate(sn.SECTION_KEYS, start=1)]
    return "===META===\n" + json.dumps(meta, ensure_ascii=False) + "\n===REPORT===\n" + "\n\n".join(parts)


def _other_class(value, vocabulary):
    return next(v for v in vocabulary if v != value)


class _NoLiveOpenAI(unittest.TestCase):
    """AA: the real OpenAI client can never be constructed during these tests."""

    def setUp(self):
        guard = patch.object(report_ai_client, "_get_client",
                             side_effect=AssertionError("live OpenAI client requested in a test"))
        self.live_client = guard.start()
        self.addCleanup(guard.stop)


class RegistrationTests(_NoLiveOpenAI):
    def test_rep_026_identity_price_category_and_catalogue_counts(self):
        # A-H: one canonical product, no alias.
        self.assertEqual(PRODUCT_PRICES[SLUG], 51)
        for registry in (PRODUCT_PRICES, pm.ORIGINAL_REPORT_CATEGORIES, REGISTRY):
            self.assertNotIn("rep_026", registry)
        self.assertEqual(pm.ORIGINAL_REPORT_CATEGORIES[SLUG], "marriage")
        intel = get_product_intelligence(SLUG)
        self.assertIs(intel, REGISTRY[SLUG])
        self.assertEqual(intel.generator, "standard_v1")
        self.assertEqual(pm.MEASURED_GENERATORS[intel.generator], ("original_report", "standard"))  # Main Report
        self.assertEqual(intel.gemstone_policy, "disabled")                  # W
        self.assertFalse(intel.components_enabled["gemstone"])               # W
        self.assertFalse(intel.components_enabled["timeline"])               # X
        self.assertTrue(intel.components_enabled["disclaimer"])              # Y
        for lang in ("en", "hi"):
            self.assertTrue(Path(f"prompts/{SLUG}_{lang}.txt").is_file())
        with incident.app.app_context():
            rows = ReportProduct.query.filter_by(report_slug=SLUG).all()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual((row.name, row.price, row.currency, row.active, row.generator, row.prompt_template_id),
                             ("Spouse Nature Report", 51, "INR", True, "standard_v1", SLUG))
            # I/J: backend original catalogue = 26; focused population unchanged and separate.
            originals = ReportProduct.query.filter(ReportProduct.generator.in_(ORIGINAL_GENERATORS)).all()
            self.assertEqual({r.report_slug: r.price for r in originals}, PRODUCT_PRICES)
            self.assertEqual(len(PRODUCT_PRICES), 26)
            self.assertEqual(ReportProduct.query.filter_by(generator="focused_v1").count(), 54)
            self.assertEqual(ReportProduct.query.filter_by(generator="focused_dual_v1").count(), 9)
        self.assertEqual(len(REGISTRY), 26)
        self.assertEqual(set(pm.ORIGINAL_REPORT_CATEGORIES), set(PRODUCT_PRICES))

    def test_duplicate_registration_is_detected_and_rejected(self):
        # AB (source): a duplicate dict key would silently override -- each
        # canonical registry declares the slug exactly once.
        for path, name in (("config/pricing.py", "PRODUCT_PRICES"),
                           ("modules/payments/purchase_measurement.py", "ORIGINAL_REPORT_CATEGORIES"),
                           ("modules/payments/report_product_intelligence.py", "REGISTRY")):
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            node = next(n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
                        and getattr(n.targets[0] if isinstance(n, ast.Assign) else n.target, "id", None) == name)
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            self.assertEqual(keys.count(SLUG), 1, f"{path}::{name}")
            self.assertEqual(len(keys), len(set(keys)), f"{path}::{name} has a duplicate key")
        with incident.app.app_context():
            # AB (database): the primary key rejects a second row ...
            incident.db.session.add(ReportProduct(report_slug=SLUG, name="dup", price=1, generator="standard_v1",
                                                  prompt_template_id=SLUG))
            with self.assertRaises(IntegrityError):
                incident.db.session.commit()
            incident.db.session.rollback()
            # ... and re-running the seed migration is a no-op (ON CONFLICT DO NOTHING).
            path = next(Path("migrations/versions").glob("ec4f2103b154*.py"))
            spec = importlib.util.spec_from_file_location("snr_2d_seed", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.down_revision, "a7c3d91b2f40")
            with patch.object(module, "op", SimpleNamespace(get_bind=lambda: incident.db.session.connection())):
                module.upgrade()
            self.assertEqual(ReportProduct.query.filter_by(report_slug=SLUG).count(), 1)
            self.assertEqual(ReportProduct.query.get(SLUG).price, 51)
            incident.db.session.rollback()

    def test_order_creation_payment_recognition_and_dispatch(self):
        # K/L/M through the real local routes, Razorpay mocked (Step 2 fixture).
        fixture = incident.SureshWebhookFirstRegression()
        try:
            fixture.setUp()
            fixture.fetch_remote.return_value["amount"] = 5100
            response = fixture.client.post("/api/razorpay-order",
                                           json=dict(fixture.payload, product=SLUG, price=1, amount=1, amount_paise=1))
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["amount"], 5100)
            fixture.order_id = response.get_json()["internal_order_id"]
            fixture.assert_success(fixture.server_callback(), "success")
            incident.db.session.remove()
            order = incident.db.session.get(incident.Order, fixture.order_id)
            self.assertEqual((order.product, order.amount_paise, order.payment_status, order.report_stage),
                             (SLUG, 5100, "PAID", "Queued"))
            self.assertEqual(fixture.dispatches, [incident.Dispatch.DISPATCHED])
            fixture.thread.assert_called_once_with(target=fixture.generator, args=(order.id,), daemon=True)
            fixture.generator.assert_not_called()
            measured = pm.build_purchase_measurement(order.id)
            self.assertEqual({k: measured[k] for k in ("item_id", "item_name", "item_category", "value", "currency",
                                                       "product_family", "report_type")},
                             {"item_id": SLUG, "item_name": "Spouse Nature Report", "item_category": "marriage",
                              "value": 51, "currency": "INR", "product_family": "original_report",
                              "report_type": "standard"})
        finally:
            self.assertTrue(fixture.doCleanups(), "fixture cleanup failed")


class GenerationTests(_NoLiveOpenAI):
    """The real tasks._generate_and_send_report_core, with the AI client, PDF
    writer, email delivery, chart drawing and analytics events mocked."""

    def run_task(self, *, product=SLUG, language="en", response=None, kundali_patch=None):
        calls = []
        real_build = tasks.build_spouse_evidence
        evidence_errors = []

        def build_evidence(kundali):
            calls.append("evidence")
            try:
                return real_build(kundali)
            except SpouseEvidenceError as exc:
                evidence_errors.append(exc)
                raise

        def completion(prompt):
            calls.append("ai")
            return SimpleNamespace(content=response if response is not None else spouse_response(language),
                                   model="mocked-model", input_tokens=1, output_tokens=1, total_tokens=2,
                                   duration_seconds=0.01)

        real_assemble = tasks.assemble_spouse_report
        validation_errors = []

        def assemble(*args):
            try:
                return real_assemble(*args)
            except ReportMetadataError as exc:
                validation_errors.append(exc)
                raise

        real_kundali = tasks.calculate_full_kundali

        def kundali_fn(**kwargs):
            kundali = real_kundali(**kwargs)
            if kundali_patch:
                kundali_patch(kundali)
            return kundali

        with incident.app.app_context():
            order = incident.Order(name=PERSONA["name"], email=f"snr2d-{uuid.uuid4().hex[:10]}@example.com",
                                   product=product, dob=PERSONA["dob"], tob=PERSONA["tob"], pob="Lucknow, India",
                                   latitude=str(PERSONA["lat"]), longitude=str(PERSONA["lon"]), language=language,
                                   status="PAID", payment_status="PAID", report_stage="Queued")
            incident.db.session.add(order)
            incident.db.session.commit()
            order_id = order.id

        def cleanup():
            with incident.app.app_context():
                row = incident.db.session.get(incident.Order, order_id)
                if row is not None:
                    incident.db.session.delete(row)
                    incident.db.session.commit()
        self.addCleanup(cleanup)

        mocks = SimpleNamespace(ai=MagicMock(side_effect=completion), pdf=MagicMock(), deliver=MagicMock())
        with patch.object(tasks, "generate_report_completion", mocks.ai), \
                patch.object(tasks, "build_spouse_evidence", side_effect=build_evidence) as mocks.evidence, \
                patch.object(tasks, "calculate_full_kundali", side_effect=kundali_fn), \
                patch.object(tasks, "assemble_spouse_report", side_effect=assemble), \
                patch.object(tasks, "generate_pdf_report", mocks.pdf), \
                patch.object(tasks, "deliver_generated_report", mocks.deliver), \
                patch.object(tasks, "generate_kundali_drawing", return_value="<svg/>"), \
                patch.object(tasks, "_emit_report_event"):
            tasks._generate_and_send_report_core(order_id)

        with incident.app.app_context():
            mocks.stage = incident.db.session.get(incident.Order, order_id).report_stage
        mocks.calls = calls
        mocks.evidence_errors = evidence_errors
        mocks.validation_errors = validation_errors
        mocks.pdf_kwargs = mocks.pdf.call_args.kwargs if mocks.pdf.called else None
        return mocks

    def assert_spouse_ready(self, run, lang):
        self.assertEqual(run.stage, "Ready")
        self.assertEqual(run.calls, ["evidence", "ai"])                                    # N
        self.assertEqual(run.ai.call_count, 1)
        prompt = run.ai.call_args.args[0]
        self.assertEqual(prompt, sn.build_spouse_prompt(EVIDENCE, lang))                    # U / V
        for raw_marker in ('"planets"', "longitude", "house_aspects", "Mahadasha"):
            self.assertNotIn(raw_marker, prompt)                                            # no raw Kundali to Luna
        kw = run.pdf_kwargs
        self.assertEqual(kw["product"], SLUG)
        self.assertEqual(kw["language"], lang)
        self.assertEqual(kw["answer_hero"]["value"], sn.deterministic_hero_value(EVIDENCE, lang))  # R
        self.assertNotEqual(kw["answer_hero"]["value"], AI_HERO_VALUE)
        self.assertEqual(kw["answer_hero"]["label"], sn.HERO_LABEL[lang])
        self.assertIsNone(kw["gemstone"])                                                   # W
        self.assertIsNone(kw["timeline"])                                                   # X
        self.assertEqual(kw["disclaimer"], sn.combined_disclaimer(lang))                    # Y
        for kind in ("general", "health", "financial"):
            self.assertIn(sn.DISCLAIMERS[kind][lang], kw["disclaimer"])
        self.assertIn(f"**9. {sn.SECTION_TITLES[lang]['limitations']}**", kw["gpt_response"])
        self.assertIn(sn.LIMITATIONS_TEXT[lang], kw["gpt_response"])
        for i, key in enumerate(sn.SECTION_KEYS, start=1):
            self.assertIn(f"**{i}. {sn.SECTION_TITLES[lang][key]}**", kw["gpt_response"])
        self.assertTrue(kw["action_list"]["items"])
        self.assertEqual(kw["used_placeholders"], ["birth_chart_summary"])
        run.deliver.assert_called_once()

    def test_valid_english_response_continues_to_pdf_and_delivery(self):
        self.assert_spouse_ready(self.run_task(language="en"), "en")                       # P

    def test_valid_hindi_response_uses_hindi_prompt_and_text(self):
        run = self.run_task(language="hi", response=spouse_response("hi"))
        self.assert_spouse_ready(run, "hi")                                                 # V
        prompt = run.ai.call_args.args[0]
        self.assertIn("जीवनसाथी स्वभाव रिपोर्ट", prompt)
        self.assertNotIn("You are a compassionate", prompt)                                 # no English fallback

    def test_evidence_failure_fails_closed_without_ai_call(self):
        def drop_longitudes(k):
            for p in k["planets"]:
                p.pop("longitude", None)

        def contradictory_lagna(k):
            signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
                     "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
            k["lagna_sign"] = signs[(signs.index(k["lagna_sign"]) + 1) % 12]

        def drop_venus(k):
            k["planets"] = [p for p in k["planets"] if p["name"] != "Venus"]

        for name, kundali_patch in (("missing longitude", drop_longitudes),
                                    ("contradictory Lagna", contradictory_lagna),
                                    ("missing planet", drop_venus)):
            with self.subTest(name):
                run = self.run_task(kundali_patch=kundali_patch)
                self.assertEqual(len(run.evidence_errors), 1)                               # evidence engine raised
                self.assertEqual(run.ai.call_count, 0)                                      # O: no Luna call
                self.assertEqual(run.stage, "Failed")
                run.pdf.assert_not_called()
                run.deliver.assert_not_called()

    def test_invalid_luna_response_fails_closed(self):
        health = EVIDENCE["health"]["class"]
        wealth = EVIDENCE["wealth"]["class"]
        reportable = next(t for t in EVIDENCE["nature"]["traits"] if t["reportable"])
        hidden = next(t for t in EVIDENCE["nature"]["traits"] if not t["reportable"])
        cases = {
            "health class changed": lambda m: m["classes"].__setitem__("health", _other_class(health, sn.HEALTH_CLASSES)),   # S
            "wealth class changed": lambda m: m["classes"].__setitem__("wealth", _other_class(wealth, sn.WEALTH_CLASSES)),   # T
            "trait upgraded": lambda m: m["traits_discussed"][0].__setitem__(
                "class", "DOMINANT" if reportable["class"] != "DOMINANT" else "SUPPORTED"),
            "trait invented": lambda m: m["traits_discussed"].append(
                {"dimension": hidden["dimension"], "class": "DOMINANT", "direction": "steady"}),
            "evidence ref invented": lambda m: m["sections"][0]["evidence_refs"].append("chart_facts.d1.upapada"),
        }
        bodies = {
            "probability claim": {"snapshot": "There is an 80% probability your spouse will be expressive."},
            "medical claim": {"health": "Your spouse may suffer from diabetes."},
            "D9 overrides D1": {"navamsa": "The Navamsa overrides the birth chart here."},
        }
        for name in list(cases) + list(bodies):
            with self.subTest(name):
                response = spouse_response(meta_patch=cases.get(name), bodies=bodies.get(name))
                run = self.run_task(response=response)
                self.assertEqual(run.ai.call_count, 1)                                      # Q: no retry, no repair
                self.assertEqual(len(run.validation_errors), 1)                             # rejected by SNR-2C
                self.assertEqual(run.stage, "Failed")
                run.pdf.assert_not_called()
                run.deliver.assert_not_called()

    def test_existing_main_report_keeps_its_original_path(self):
        # Z: marriage_report still uses its template + summary_blocks prompt,
        # AI-authored hero value, Dasha timeline -- the spouse code never runs.
        template = Path("prompts/marriage_report_en.txt").read_text(encoding="utf-8")
        response = ("===META===\n" + json.dumps({"answer_hero": {
            "label": "Marriage Outlook", "value": "Supportive, With Steady Effort",
            "interpretation": "A calm reading.", "evidence": ["The 7th house is read first."]}})
            + "\n===REPORT===\n**1. Overview**\nA calm, supportive reading.")
        with patch.object(tasks, "assemble_spouse_report") as spouse_assemble, \
                patch.object(tasks, "build_spouse_prompt") as spouse_prompt:
            run = self.run_task(product="marriage_report", response=response)
        self.assertEqual(run.stage, "Ready")
        self.assertEqual(run.calls, ["ai"])
        spouse_assemble.assert_not_called()
        spouse_prompt.assert_not_called()
        prompt = run.ai.call_args.args[0]
        self.assertTrue(prompt.startswith(template.split("{", 1)[0]))
        kw = run.pdf_kwargs
        self.assertEqual(kw["answer_hero"]["value"], "Supportive, With Steady Effort")
        self.assertIsNotNone(kw["timeline"])
        self.assertIsNone(kw["disclaimer"])
        self.assertIn("birth_chart_summary", kw["used_placeholders"])


if __name__ == "__main__":
    unittest.main()
