"""Regression tests: standard (base) reports Rs51 -> Rs99 and the related-focused-reports PDF CTA.

No database server, network, AI, payment or email: the migration runs on an in-memory SQLite copy of the registry,
and PDFs are rendered locally (needs the WeasyPrint runtime, like test_focused_pdf.py).
"""
import importlib.util
import pathlib
import re
import tempfile
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pypdf import PdfReader

from app_config import JYOTISHASHA_PLAY_STORE_URL
from config.google_play_report_products import (
    LEGACY_STANDARD_REPORT_PRODUCT_ID, RELATIONSHIP_REPORT_PRODUCT_ID, STANDARD_REPORT_PRODUCT_ID,
    accepted_report_product_ids, expected_report_product_id,
)
from config.pricing import PRODUCT_PRICES
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.intents.question_catalog import get_question
from modules.intents.question_catalog import QUESTIONS
from modules.payments.base_report_focused_links import BASE_TO_FOCUSED, focused_report_url, related_focused_reports
from modules.payments.report_i18n_labels import get_label
from pdf_generator_weasy import generate_pdf_report_weasy

ROOT = pathlib.Path(__file__).resolve().parent
STANDARD_SLUGS = sorted(slug for slug in PRODUCT_PRICES if slug != "relationship_future_report")
FOCUSED_KEYS = [q.question_key for q in QUESTIONS]


def load_migration():
    path = ROOT / "migrations" / "versions" / "c5e1d7a9b2f4_standard_reports_price_99.py"
    spec = importlib.util.spec_from_file_location("price_99_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_engine(standard_price=51, standard_count=25):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE report_products (report_slug TEXT PRIMARY KEY, generator TEXT, price INTEGER)"))
        rows = [(s, "standard_v1", standard_price) for s in STANDARD_SLUGS[:standard_count]]
        rows += [(k, "focused_dual_v1" if q.person_mode == "dual" else "focused_v1", 51) for k, q in zip(FOCUSED_KEYS, QUESTIONS)]
        rows.append(("relationship_future_report", "love_premium_v1", 199))
        conn.execute(sa.text("INSERT INTO report_products VALUES (:s, :g, :p)"), [dict(s=s, g=g, p=p) for s, g, p in rows])
    return engine


def run(engine, step):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(load_migration(), step)()


def prices(engine):
    with engine.connect() as conn:
        return dict(conn.execute(sa.text("SELECT report_slug, price FROM report_products")).fetchall())


class PriceMigrationTests(unittest.TestCase):
    def test_upgrade_moves_only_the_25_standard_reports_to_99_and_downgrade_restores_51(self):
        engine = registry_engine()
        before = prices(engine)
        run(engine, "upgrade")
        after = prices(engine)
        self.assertEqual({s: after[s] for s in STANDARD_SLUGS}, {s: 99 for s in STANDARD_SLUGS})
        self.assertEqual({k: after[k] for k in FOCUSED_KEYS}, {k: 51 for k in FOCUSED_KEYS})
        self.assertEqual(after["relationship_future_report"], 199)
        run(engine, "downgrade")
        self.assertEqual(prices(engine), before)

    def test_unexpected_registry_state_is_refused_and_nothing_changes(self):
        for engine in (registry_engine(standard_count=24), registry_engine(standard_price=99)):
            before = prices(engine)
            with self.assertRaises(RuntimeError):
                run(engine, "upgrade")
            self.assertEqual(prices(engine), before)


class GooglePlayPolicyTests(unittest.TestCase):
    def test_standard_reports_honour_both_play_products_at_either_price(self):
        for price in (51, 99):
            self.assertEqual(accepted_report_product_ids("career_report", price, "standard_v1"),
                             {STANDARD_REPORT_PRODUCT_ID, LEGACY_STANDARD_REPORT_PRODUCT_ID})
        self.assertEqual(STANDARD_REPORT_PRODUCT_ID, "reports99")
        self.assertEqual(LEGACY_STANDARD_REPORT_PRODUCT_ID, "reports51")

    def test_relationship_and_focused_tiers_are_unchanged(self):
        self.assertEqual(accepted_report_product_ids("relationship_future_report", 199, "love_premium_v1"),
                         {RELATIONSHIP_REPORT_PRODUCT_ID})
        self.assertEqual(accepted_report_product_ids("promotion_timing", 51, "focused_v1"), {"reports51"})
        self.assertEqual(expected_report_product_id("promotion_timing", 51), "reports51")
        for bad in ((("relationship_future_report", 99, "love_premium_v1")), ("career_report", 120, "standard_v1")):
            with self.assertRaises(ValueError):
                accepted_report_product_ids(*bad)


class RelatedFocusedMappingTests(unittest.TestCase):
    def test_every_base_report_maps_to_at_most_three_distinct_real_focused_reports(self):
        self.assertEqual(sorted(BASE_TO_FOCUSED), STANDARD_SLUGS)
        self.assertNotIn("relationship_future_report", BASE_TO_FOCUSED)
        for slug, keys in BASE_TO_FOCUSED.items():
            self.assertLessEqual(len(keys), 3, slug)
            self.assertEqual(len(set(keys)), len(keys), slug)
            self.assertTrue(set(keys) <= set(FOCUSED_KEYS), slug)

    def test_content_rules_for_sensitive_base_reports(self):
        # No buyer-chart topic presented as a child analysis, and no generic stand-ins for a legal report.
        self.assertEqual(BASE_TO_FOCUSED["children_parenting_report"], ())
        self.assertEqual(BASE_TO_FOCUSED["legal_disputes_report"], ())
        self.assertEqual(BASE_TO_FOCUSED["lifestyle_analysis_report"], ())
        self.assertEqual(BASE_TO_FOCUSED["love_disappointment_report"], ("current_phase_meaning",))
        self.assertEqual(BASE_TO_FOCUSED["gemstone_consultation"], ("major_kundali_strengths",))
        # Heartbreak: never assume a current partner.
        self.assertTrue(all(get_question(k).person_mode != "dual" for k in BASE_TO_FOCUSED["love_disappointment_report"]))
        # Money: never assume debt or financial distress.
        money = BASE_TO_FOCUSED["financial_report"] + BASE_TO_FOCUSED["financial_stability_report"]
        self.assertFalse({"debt_pressure_easing", "financial_pressure_easing"} & set(money))
        # A base report never re-sells its own question.
        self.assertNotIn("marriage_delay_reason", BASE_TO_FOCUSED["delay_in_marriage_report"])

    def test_two_person_reports_are_flagged(self):
        for slug, keys in BASE_TO_FOCUSED.items():
            for key, item in zip(keys, related_focused_reports(slug, "en")):
                self.assertEqual(item["two_person"], get_question(key).person_mode == "dual", (slug, key))

    def test_titles_prices_and_live_urls_match_the_pdf_language(self):
        for language, prefix in (("en", "https://www.jyotishasha.com/reports/focused/"),
                                 ("hi", "https://www.jyotishasha.com/hi/reports/focused/")):
            items = related_focused_reports("career_report", language)
            self.assertEqual([i["url"] for i in items], [prefix + k.replace("_", "-") for k in BASE_TO_FOCUSED["career_report"]])
            self.assertEqual([i["title"] for i in items], [get_prompt_spec(k).title.get(language) for k in BASE_TO_FOCUSED["career_report"]])
            self.assertTrue(all(i["price"] == 51 for i in items))
        self.assertEqual(related_focused_reports("relationship_future_report", "en"), [])
        self.assertEqual(focused_report_url("kundali_match_for_marriage", "hi"),
                         "https://www.jyotishasha.com/hi/reports/focused/kundali-match-for-marriage")

    def test_only_the_standard_pipeline_passes_related_reports(self):
        tasks_src = (ROOT / "tasks.py").read_text(encoding="utf-8")
        self.assertIn("related_reports=related_focused_reports(product_slug, language)", tasks_src)
        for other in ("modules/love/love_premium_task.py", "modules/focused_reports/pdf_adapter.py"):
            self.assertNotIn("related_reports", (ROOT / other).read_text(encoding="utf-8"), other)


class BaseReportPdfCtaTests(unittest.TestCase):
    def render(self, language, related):
        app = {"heading": get_label("app_download_heading", language), "benefit_text": get_label("app_download_body", language),
               "play_store_url": JYOTISHASHA_PLAY_STORE_URL, "app_store_url": None}
        tmp = tempfile.mkdtemp()
        path = str(pathlib.Path(tmp) / f"base_{language}.pdf")
        generate_pdf_report_weasy(path, {"name": "Test Person", "dob": "1990-06-15", "tob": "14:30", "pob": "Lucknow"}, {},
                                  "1. Career Overview\n\nSteady effort is rewarded.", None, [], "Career Report",
                                  language=language, disclaimer="Disclaimer text.", app_download=app, related_reports=related)
        reader = PdfReader(path)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        uris = [a.get_object().get("/A", {}).get("/URI") for p in reader.pages for a in (p.get("/Annots") or [])]
        return text, [u for u in uris if u]

    def test_base_pdf_ends_with_three_clickable_focused_reports_and_the_app_cta(self):
        for language in ("en", "hi"):
            items = related_focused_reports("career_report", language)
            text, uris = self.render(language, items)
            for item in items:
                self.assertIn(item["url"], uris, language)
                self.assertIn(item["url"].split("/")[-1], text.replace("\n", ""))
            self.assertIn(JYOTISHASHA_PLAY_STORE_URL, uris)
            self.assertIn("₹51", text)
            self.assertIn("Jyotishasha App", text)
            if language == "en":
                for item in items:
                    self.assertIn(item["title"], text)
                self.assertIn(get_label("related_reports_heading", "en"), text)
                self.assertLess(text.index(get_label("related_reports_heading", "en")), text.index("Download Jyotishasha App"))

    def test_no_related_block_without_related_reports(self):
        for related in (None, [], related_focused_reports("legal_disputes_report", "en")):
            text, uris = self.render("en", related)
            self.assertNotIn(get_label("related_reports_heading", "en"), text)
            self.assertNotIn(get_label("related_reports_intro", "en"), text.replace("\n", " "))
            self.assertFalse(any("/reports/focused/" in u for u in uris))
            self.assertEqual(uris.count(JYOTISHASHA_PLAY_STORE_URL), 1)

    def test_intro_and_partner_note_render_only_where_they_apply(self):
        text, _ = self.render("en", related_focused_reports("marriage_report", "en"))
        flat = text.replace("\n", " ")
        self.assertIn(get_label("related_reports_intro", "en"), flat)
        dual = sum(i["two_person"] for i in related_focused_reports("marriage_report", "en"))
        self.assertEqual(flat.count(get_label("related_report_two_person", "en")), dual)
        text, _ = self.render("en", related_focused_reports("career_report", "en"))
        self.assertNotIn(get_label("related_report_two_person", "en"), text)

    def test_related_reports_labels_have_both_languages(self):
        for key in ("related_reports_heading", "related_reports_intro", "related_report_two_person"):
            self.assertTrue(get_label(key, "en") and get_label(key, "hi"), key)
            self.assertTrue(re.search(r"[ऀ-ॿ]", get_label(key, "hi")), key)
        self.assertEqual(get_label("related_reports_heading", "en"), "Questions You May Want to Explore Next")
        self.assertEqual(get_label("related_reports_heading", "hi"), "कुछ और सवाल, जिन्हें आप जानना चाहें")


if __name__ == "__main__":
    unittest.main(verbosity=2)
