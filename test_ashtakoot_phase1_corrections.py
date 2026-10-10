"""
Ashtakoot Phase 1 corrections (2026-10) -- engine rules, truthful result text, shared-consumer contract.

Source of truth: the Phase 1 Ashtakoot correctness audit (onlinejyotish.com per-koota tables, the aaps.space
yoni grid's Mahavaira zeros, BPHS 3.55 relationship rule, Muhurta Chintamani yoni list as quoted there).

  * "verified" cases: every fetched reference agrees -> asserted exactly.
  * "pending" cases: references disagree (Vashya matrix, Gana score table, Maitri neutral+enemy,
    Bhakoot/Nadi cancellation, Yoni non-enemy grid cells). These PIN today's convention so a future
    change has to be deliberate; they are NOT claims that today's value is the correct tradition.

Synthetic Moon positions / synthetic birth details only. No network, no database, no AI call.
Run:  python test_ashtakoot_phase1_corrections.py
"""
import itertools
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

import modules.love.ashtakoot_love as AK  # noqa: E402
from modules.love.love_prompt_builder import _customer_ashtakoot  # noqa: E402
from modules.love.love_report_compiler import LoveReportCompiler, compile_love_report  # noqa: E402
from modules.love.routes_love import love_bp  # noqa: E402
from modules.love.service_love import _extract_moon, normalize_koota_status  # noqa: E402

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
NAKS = AK.NAKSHATRAS_27
STATUS_VOCAB = {"pass", "partial", "dosha", "fail"}  # what the website and the Flutter app render


def moon(sign, nak, deg):
    return {"rashi": sign, "nakshatra": nak, "degree": deg}


def moon_at(lon):
    return moon(SIGNS[int(lon // 30)], NAKS[int(lon // (40 / 3))], lon % 30)


PADAS = [i * (40 / 12) + (40 / 24) for i in range(108)]  # every Moon pada (midpoint)

# ---- the 39 audit cases: (id, koota, bride, groom, expected score, kind) --------------------------------------
AUDIT_CASES = [
    ("V1", "varna", ("Aries", "Ashwini", 5), ("Cancer", "Pushya", 10), 1, "verified"),  # groom Brahmin (Cancer) >= bride Kshatriya (Aries)
    ("V2", "varna", ("Cancer", "Pushya", 10), ("Gemini", "Ardra", 12), 0, "verified"),  # groom Shudra (Gemini) < bride Brahmin (Cancer)
    ("V3", "varna", ("Taurus", "Rohini", 15), ("Virgo", "Hasta", 15), 1, "verified"),  # same varna (Taurus vs Virgo, both Vaishya)
    ("S1", "vashya", ("Aries", "Bharani", 20), ("Scorpio", "Anuradha", 10), 0, "pending"),  # bride Aries (Chatushpada) vs groom Scorpio (Keeta)
    ("S2", "vashya", ("Leo", "Magha", 5), ("Cancer", "Pushya", 10), 0, "pending"),  # bride Leo (Vanachara) vs groom Cancer (Jalachara)
    ("S3", "vashya", ("Gemini", "Ardra", 12), ("Cancer", "Pushya", 10), 1.5, "pending"),  # bride Gemini (Nara) vs groom Cancer (Jalachara)
    ("S4", "vashya", ("Gemini", "Ardra", 12), ("Sagittarius", "Mula", 14.99), 2, "verified"),  # Sagittarius 14.99 deg (Nara) vs Gemini -- half-sign boundary
    ("S5", "vashya", ("Gemini", "Ardra", 12), ("Sagittarius", "Purva Ashadha", 15.0), 1, "verified"),  # Sagittarius 15.00 deg (Chatushpada) vs Gemini -- half-sign boundary
    ("T1", "tara", ("Taurus", "Rohini", 15), ("Taurus", "Rohini", 18), 3, "verified"),  # same nakshatra (Rohini/Rohini)
    ("T2", "tara", ("Aries", "Ashwini", 5), ("Leo", "Magha", 5), 3, "verified"),  # groom 9 nakshatras on (Ashwini -> Magha: counts 10/19, remainders 1/1)
    ("T3", "tara", ("Aries", "Ashwini", 5), ("Pisces", "Revati", 25), 3, "verified"),  # remainder 0/9 (Ashwini bride, Revati groom: counts 27/2)
    ("T4", "tara", ("Aries", "Ashwini", 5), ("Aries", "Krittika", 28), 1.5, "verified"),  # one bad: Ashwini -> Krittika (count 3 Vipat, reverse 26)
    ("Y1", "yoni", ("Aries", "Krittika", 28), ("Cancer", "Pushya", 10), 4, "verified"),  # Pushya groom vs Krittika bride (standard: both Sheep)
    ("Y2", "yoni", ("Virgo", "Uttara Phalguni", 5), ("Libra", "Vishakha", 25), 0, "verified"),  # cow (Uttara Phalguni) bride vs tiger (Vishakha) groom
    ("Y3", "yoni", ("Aries", "Ashwini", 5), ("Virgo", "Hasta", 15), 0, "verified"),  # horse (Ashwini) bride vs buffalo (Hasta) groom
    ("Y4", "yoni", ("Taurus", "Rohini", 15), ("Capricorn", "Uttara Ashadha", 5), 0, "verified"),  # serpent (Rohini) bride vs mongoose (Uttara Ashadha) groom
    ("Y5", "yoni", ("Capricorn", "Uttara Ashadha", 5), ("Taurus", "Rohini", 15), 0, "verified"),  # mongoose bride vs serpent groom (Y4 reversed -- asymmetry check)
    ("Y6", "yoni", ("Aries", "Ashwini", 5), ("Taurus", "Rohini", 15), 1, "pending"),  # horse (Ashwini) vs serpent (Rohini) -- friendly pair
    ("Y7", "yoni", ("Aries", "Ashwini", 5), ("Aquarius", "Shatabhisha", 12), 4, "verified"),  # Shatabhisha groom vs Ashwini bride (standard: both Horse)
    ("M1", "graha_maitri", ("Aries", "Ashwini", 5), ("Capricorn", "Shravana", 15), 1, "pending"),  # Aries (Mars) bride vs Capricorn (Saturn) groom
    ("M2", "graha_maitri", ("Gemini", "Ardra", 12), ("Sagittarius", "Mula", 5), 1, "pending"),  # Gemini (Mercury) bride vs Sagittarius (Jupiter) groom -- neutral+enemy
    ("M3", "graha_maitri", ("Cancer", "Pushya", 10), ("Gemini", "Ardra", 12), 1, "verified"),  # Cancer (Moon) bride vs Gemini (Mercury) groom -- friend+enemy
    ("M4", "graha_maitri", ("Leo", "Magha", 5), ("Capricorn", "Shravana", 15), 0, "verified"),  # Leo (Sun) bride vs Capricorn (Saturn) groom -- enemy+enemy
    ("G1", "gana", ("Pisces", "Purva Bhadrapada", 2), ("Aries", "Ashwini", 5), 5, "verified"),  # Purva Bhadrapada bride vs Ashwini (Deva) groom
    ("G2", "gana", ("Aries", "Bharani", 20), ("Taurus", "Krittika", 5), 3, "pending"),  # Bharani (Manushya) bride vs Krittika (Rakshasa) groom
    ("G3", "gana", ("Aries", "Ashwini", 5), ("Taurus", "Krittika", 5), 1, "pending"),  # Ashwini (Deva) bride vs Krittika (Rakshasa) groom
    ("G4", "gana", ("Taurus", "Krittika", 5), ("Aries", "Ashwini", 5), 1, "pending"),  # Krittika (Rakshasa) bride vs Ashwini (Deva) groom -- reversed
    ("B1", "bhakoot", ("Taurus", "Rohini", 15), ("Taurus", "Mrigashira", 25), 7, "verified"),  # same sign (Taurus/Taurus)
    ("B2", "bhakoot", ("Aries", "Ashwini", 5), ("Libra", "Swati", 10), 7, "verified"),  # 1/7 (Aries/Libra)
    ("B3", "bhakoot", ("Aries", "Ashwini", 5), ("Virgo", "Hasta", 15), 0, "verified"),  # 6/8 with enemy lords (Aries bride, Virgo groom)
    ("B4", "bhakoot", ("Aries", "Ashwini", 5), ("Scorpio", "Anuradha", 10), 7, "pending"),  # 6/8 same lord (Aries/Scorpio) -- cancellation
    ("B5", "bhakoot", ("Aries", "Ashwini", 5), ("Leo", "Magha", 5), 7, "pending"),  # 5/9 mutual-friend lords (Aries/Leo) -- cancellation
    ("B6", "bhakoot", ("Aries", "Bharani", 20), ("Taurus", "Rohini", 15), 0, "verified"),  # 2/12 neutral lords (Aries/Taurus)
    ("N1", "nadi", ("Aries", "Ashwini", 5), ("Aries", "Bharani", 20), 8, "verified"),  # different nadi
    ("N2", "nadi", ("Aries", "Ashwini", 3), ("Aries", "Ashwini", 9), 8, "pending"),  # same nakshatra AND same rashi (Ashwini/Ashwini)
    ("N3", "nadi", ("Gemini", "Ardra", 12), ("Gemini", "Punarvasu", 25), 8, "pending"),  # same nadi, same rashi, different nakshatra (Ardra/Punarvasu in Gemini)
    ("N4", "nadi", ("Aries", "Ashwini", 5), ("Scorpio", "Jyeshtha", 25), 8, "pending"),  # same nadi, different rashi, same lord (Ashwini Aries / Jyeshtha Scorpio)
    ("N5", "nadi", ("Aries", "Ashwini", 5), ("Pisces", "Purva Bhadrapada", 2), 0, "pending"),  # same nadi, different rashi, mutual-friend lords (Ashwini Aries / Purva Bhadrapada Pisces)
    ("N6", "nadi", ("Aries", "Ashwini", 5), ("Virgo", "Hasta", 15), 0, "verified"),  # same nadi, unrelated lords (Ashwini Aries / Hasta Virgo)
]

# ---- reference tables (audit section C) ------------------------------------------------------------------------
REF_YONI = {"Ashwini": "Ashwa", "Shatabhisha": "Ashwa", "Bharani": "Gaja", "Revati": "Gaja", "Pushya": "Mesha", "Krittika": "Mesha",
            "Rohini": "Sarpa", "Mrigashira": "Sarpa", "Mula": "Shwan", "Ardra": "Shwan", "Ashlesha": "Marjar", "Punarvasu": "Marjar",
            "Magha": "Mushak", "Purva Phalguni": "Mushak", "Uttara Phalguni": "Go", "Uttara Bhadrapada": "Go", "Swati": "Mahish",
            "Hasta": "Mahish", "Vishakha": "Vyaghra", "Chitra": "Vyaghra", "Jyeshtha": "Mriga", "Anuradha": "Mriga",
            "Shravana": "Vanar", "Purva Ashadha": "Vanar", "Uttara Ashadha": "Nakul", "Dhanishta": "Simha", "Purva Bhadrapada": "Simha"}
MAHAVAIRA = {frozenset(p) for p in [("Ashwa", "Mahish"), ("Gaja", "Simha"), ("Mesha", "Vanar"), ("Sarpa", "Nakul"),
                                     ("Shwan", "Mriga"), ("Marjar", "Mushak"), ("Go", "Vyaghra")]}
REF_GANA = {"Deva": ["Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Swati", "Anuradha", "Shravana", "Revati"],
            "Manushya": ["Bharani", "Rohini", "Ardra", "Purva Phalguni", "Uttara Phalguni", "Purva Ashadha", "Uttara Ashadha",
                         "Purva Bhadrapada", "Uttara Bhadrapada"],
            "Rakshasa": ["Krittika", "Ashlesha", "Magha", "Chitra", "Vishakha", "Jyeshtha", "Mula", "Dhanishta", "Shatabhisha"]}
REF_VARNA = {"Cancer": 4, "Scorpio": 4, "Pisces": 4, "Aries": 3, "Leo": 3, "Sagittarius": 3,
             "Taurus": 2, "Virgo": 2, "Capricorn": 2, "Gemini": 1, "Libra": 1, "Aquarius": 1}


class AuditCases(unittest.TestCase):
    def test_all_39_audit_cases(self):
        self.assertEqual(len(AUDIT_CASES), 39)
        for cid, koota, b, g, expected, kind in AUDIT_CASES:
            with self.subTest(case=cid, kind=kind):
                got = AK.compute_ashtakoot(bride_moon=moon(*b), groom_moon=moon(*g))["kootas"][koota]["score"]
                self.assertEqual(got, expected, f"{cid} ({kind}) {koota}")

    def test_verified_and_pending_split_is_the_audits(self):
        kinds = {kind for *_, kind in AUDIT_CASES}
        self.assertEqual(kinds, {"verified", "pending"})
        pending = {cid for cid, *_, kind in AUDIT_CASES if kind == "pending"}
        # Vashya table, Yoni non-enemy cell, Maitri N+E, Gana table, Bhakoot/Nadi cancellation.
        self.assertEqual(pending, {"S1", "S2", "S3", "Y6", "M1", "M2", "G2", "G3", "G4", "B4", "B5", "N2", "N3", "N4", "N5"})


class EngineRules(unittest.TestCase):
    def test_bhakoot_opposite_signs_score_7_for_all_12(self):
        for i, s in enumerate(SIGNS):
            opp = SIGNS[(i + 6) % 12]
            with self.subTest(sign=s):
                r = AK.bhakoot_koota(moon(s, "Ashwini", 5), moon(opp, "Ashwini", 5))
                self.assertEqual((r["score"], r["status"]), (7, "auspicious"))

    def test_bhakoot_all_144_sign_pairs(self):
        for bs, gs in itertools.product(SIGNS, SIGNS):
            p = (SIGNS.index(gs) - SIGNS.index(bs)) % 12 + 1
            q = (SIGNS.index(bs) - SIGNS.index(gs)) % 12 + 1
            r = AK.bhakoot_koota(moon(bs, "Ashwini", 5), moon(gs, "Ashwini", 5))
            with self.subTest(bride=bs, groom=gs):
                if {p, q} in ({1}, {7}, {3, 11}, {4, 10}):
                    self.assertEqual(r["score"], 7)
                else:
                    self.assertIn({p, q}, ({2, 12}, {5, 9}, {6, 8}))
                    lb, lg = AK.RASHI_LORD[bs], AK.RASHI_LORD[gs]
                    cancelled = lb == lg or AK._lords_friendly(lb, lg)  # pending convention: cancellation restores 7
                    self.assertEqual((r["score"], r["status"]), (7, "cancelled") if cancelled else (0, "dosha"))

    def test_tara_reference_rule_all_pairs_and_never_zero(self):
        for b, g in itertools.product(NAKS, NAKS):
            c1 = (NAKS.index(g) - NAKS.index(b)) % 27 + 1
            c2 = (NAKS.index(b) - NAKS.index(g)) % 27 + 1
            good = [(c % 9) not in (3, 5, 7) for c in (c1, c2)]
            expected = 3 if all(good) else 1.5 if any(good) else 0
            with self.subTest(bride=b, groom=g):
                score = AK.tara_koota({"nakshatra": b}, {"nakshatra": g})["score"]
                self.assertEqual(score, expected)
                self.assertNotEqual(score, 0)  # the two counts always sum to 29

    def test_tara_same_nakshatra_is_3(self):
        for n in NAKS:
            self.assertEqual(AK.tara_koota({"nakshatra": n}, {"nakshatra": n})["score"], 3)

    def test_yoni_map_matches_reference_for_all_27(self):
        self.assertEqual(AK.FEMALE_NAK_TO_YONI, REF_YONI)
        self.assertEqual(AK.MALE_NAK_TO_YONI, REF_YONI)

    def test_yoni_sworn_enemies_zero_both_directions(self):
        for pair in MAHAVAIRA:
            a, b = sorted(pair)
            self.assertEqual(AK.YONI_RELATION[a][b], 0)
            self.assertEqual(AK.YONI_RELATION[b][a], 0)

    def test_yoni_lookup_symmetric_and_zero_only_for_mahavaira(self):
        for b, g in itertools.product(NAKS, NAKS):
            s1 = AK.yoni_koota({"nakshatra": b}, {"nakshatra": g})
            s2 = AK.yoni_koota({"nakshatra": g}, {"nakshatra": b})
            with self.subTest(bride=b, groom=g):
                self.assertEqual(s1["score"], s2["score"])
                is_enemy = frozenset({REF_YONI[b], REF_YONI[g]}) in MAHAVAIRA
                self.assertEqual(s1["score"] == 0, is_enemy)
                self.assertEqual(s1["status"] == "sworn_enemy", is_enemy)

    def test_yoni_dog_cat_and_rat_tiger_are_not_sworn_enemies(self):
        self.assertEqual(AK.yoni_koota({"nakshatra": "Ardra"}, {"nakshatra": "Ashlesha"})["score"], 2)
        self.assertEqual(AK.yoni_koota({"nakshatra": "Magha"}, {"nakshatra": "Chitra"})["score"], 2)

    def test_gana_groups_match_reference(self):
        for gana, naks in REF_GANA.items():
            for n in naks:
                self.assertEqual(AK.NAKSHATRA_TO_GANA[n], gana, n)
        self.assertEqual(len(AK.NAKSHATRA_TO_GANA), 27)

    def test_graha_maitri_saturn_regards_mars_as_enemy(self):
        self.assertIn("Mars", AK.ENEMY["Saturn"])
        self.assertNotIn("Saturn", AK.ENEMY["Mars"])  # Mars regards Saturn as neutral (not reciprocal)
        r = AK.graha_maitri_koota({"rashi": "Aries"}, {"rashi": "Capricorn"})
        self.assertEqual(r["score"], 1)  # neutral + enemy: 1 is today's convention (0.5 pending decision)

    def test_varna_all_144(self):
        for bs, gs in itertools.product(SIGNS, SIGNS):
            r = AK.varna_koota({"rashi": gs}, {"rashi": bs})  # (boy/groom, girl/bride)
            self.assertEqual(r["score"], 1 if REF_VARNA[gs] >= REF_VARNA[bs] else 0, (bs, gs))

    def test_vashya_half_sign_boundaries(self):
        self.assertEqual(AK._resolve_sagittarius_capricorn_group("Sagittarius", 14.999), "Nara")
        self.assertEqual(AK._resolve_sagittarius_capricorn_group("Sagittarius", 15.0), "Chatushpada")
        self.assertEqual(AK._resolve_sagittarius_capricorn_group("Capricorn", 14.999), "Chatushpada")
        self.assertEqual(AK._resolve_sagittarius_capricorn_group("Capricorn", 15.0), "Jalchar")

    def test_nadi_base_rule(self):
        for b, g in itertools.product(NAKS, NAKS):
            r = AK.nadi_koota({"nakshatra": b, "rashi": "Aries"}, {"nakshatra": g, "rashi": "Taurus"})
            if AK.NAKSHATRA_TO_NADI[b] != AK.NAKSHATRA_TO_NADI[g]:
                self.assertEqual(r["score"], 8)

    def test_total_is_sum_of_kootas_max_36_and_versioned(self):
        for lb, lg in itertools.product(PADAS[::7], PADAS[::5]):
            a = AK.compute_ashtakoot(bride_moon=moon_at(lb), groom_moon=moon_at(lg))
            self.assertEqual(a["total_score"], sum(k["score"] for k in a["kootas"].values()))
            self.assertEqual(a["max_score"], 36.0)
            self.assertEqual([k["max"] for k in a["kootas"].values()], [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertEqual(a["invalid_kootas"], [])
            self.assertEqual(a["engine_version"], AK.ENGINE_VERSION)


class MoonExtraction(unittest.TestCase):
    def test_full_precision_longitude_keeps_vashya_boundary(self):
        k = {"planets": [{"name": "Moon", "sign": "Sagittarius", "degree": 15.0, "longitude": 254.996, "nakshatra": "Purva Ashadha"}]}
        m = _extract_moon(k)
        self.assertAlmostEqual(m["degree"], 14.996, places=6)
        self.assertEqual(AK.vashya_koota(m, moon("Gemini", "Ardra", 12))["bride_group"], "Nara")  # rounded 15.0 would say Chatushpada

    def test_falls_back_to_degree_without_longitude(self):
        k = {"planets": [{"name": "Moon", "sign": "Aries", "degree": 10.5, "nakshatra": "Ashwini"}]}
        self.assertEqual(_extract_moon(k)["degree"], 10.5)


def _normalized(ashtakoot):
    for v in ashtakoot["kootas"].values():
        v["status"] = normalize_koota_status(v)
    return ashtakoot


FORBIDDEN_FOR_FULL = {"en": ("weak", "partial", "dosha", "mismatch", "(None)"), "hi": ("कमजोर", "आंशिक", "दोष", "असंगति", "(None)")}


class TruthfulLabels(unittest.TestCase):
    def test_status_vocabulary_and_rules(self):
        cases = [
            ({"score": 7, "max": 7, "status": "auspicious"}, "pass"),
            ({"score": 3, "max": 3, "status": "excellent"}, "pass"),
            ({"score": 4, "max": 4, "status": "same"}, "pass"),
            ({"score": 5, "max": 5, "status": "friendly"}, "pass"),
            ({"score": 8, "max": 8, "status": "cancelled", "cancelled": True}, "pass"),
            ({"score": 0, "max": 7, "status": "dosha"}, "dosha"),
            ({"score": 0, "max": 4, "status": "sworn_enemy"}, "dosha"),
            ({"score": 0, "max": 1, "status": "fail"}, "fail"),
            ({"score": 1.5, "max": 3, "status": "mixed"}, "partial"),
            ({"score": 0, "max": 3, "status": "invalid"}, "fail"),
        ]
        for koota, expected in cases:
            self.assertEqual(normalize_koota_status(koota), expected, koota)

    def test_full_scores_are_never_described_as_weak_partial_or_dosha(self):
        for lb, lg in itertools.product(PADAS[::3], PADAS[::4]):
            a = _normalized(AK.compute_ashtakoot(bride_moon=moon_at(lb), groom_moon=moon_at(lg)))
            for lang in ("en", "hi"):
                for n in LoveReportCompiler().build_koota_notes(lang, a):
                    self.assertIn(n["status"], STATUS_VOCAB)
                    self.assertNotIn("(None)", n["note"])
                    if n["score"] >= n["max"]:
                        self.assertEqual(n["status"], "pass")
                        if n["cancelled"]:
                            self.assertTrue("cancelled" in n["note"] or "निरस्त" in n["note"], n)
                        else:
                            for word in FORBIDDEN_FOR_FULL[lang]:
                                self.assertNotIn(word, n["note"], (lang, n))

    def test_bhakoot_7_of_7_and_varna_0_text(self):
        same = moon("Taurus", "Rohini", 15)
        a = _normalized(AK.compute_ashtakoot(bride_moon=moon("Aries", "Ashwini", 5), groom_moon=moon("Libra", "Swati", 10)))
        notes = {n["key"]: n for n in LoveReportCompiler().build_koota_notes("en", a)}
        self.assertEqual(notes["bhakoot"]["score"], 7)
        self.assertIn("Bhakoot harmony", notes["bhakoot"]["note"])
        a2 = _normalized(AK.compute_ashtakoot(bride_moon=moon("Cancer", "Pushya", 10), groom_moon=moon("Gemini", "Ardra", 12)))
        n2 = {n["key"]: n for n in LoveReportCompiler().build_koota_notes("en", a2)}
        self.assertEqual((n2["varna"]["score"], n2["varna"]["status"]), (0, "fail"))
        self.assertIn("Varna mismatch", n2["varna"]["note"])
        a3 = _normalized(AK.compute_ashtakoot(bride_moon=same, groom_moon=same))
        self.assertEqual({n["key"]: n["status"] for n in LoveReportCompiler().build_koota_notes("en", a3)}["tara"], "pass")

    def test_cancelled_dosha_says_so_and_that_traditions_differ(self):
        a = _normalized(AK.compute_ashtakoot(bride_moon=moon("Aries", "Ashwini", 5), groom_moon=moon("Scorpio", "Anuradha", 10)))
        n = {x["key"]: x for x in LoveReportCompiler().build_koota_notes("en", a)}["bhakoot"]
        self.assertTrue(n["cancelled"])
        self.assertIn("treated as cancelled", n["note"])
        self.assertIn("Astrologers differ", n["note"])


def _report(ashtakoot, *, kundali=None, dasha=None, transits=None, lang="en"):
    return compile_love_report({"language": lang, "client": {"name": "SYNTHETIC", "dob": "1994-03-15", "tob": "08:30", "pob": "Delhi"},
                                "ashtakoot": ashtakoot, "kundali": kundali or {}, "dasha": dasha or {}, "transits": transits or {}})


class ReportText(unittest.TestCase):
    def setUp(self):
        self.a = _normalized(AK.compute_ashtakoot(bride_moon=moon("Taurus", "Rohini", 15), groom_moon=moon("Cancer", "Pushya", 10)))

    def test_no_unsupported_transit_claim(self):
        for lang in ("en", "hi"):
            r = _report(self.a, lang=lang)
            texts = " ".join(d["text"] for d in r["disclaimers"])
            self.assertNotIn("deeper Vedic timing and transit logic", texts)
            self.assertNotIn("गोचर लॉजिक अधिक सटीक", texts)
        r = _report(self.a)
        self.assertIn("Dasha and transit timing are not part of this result", " ".join(d["text"] for d in r["disclaimers"]))

    def test_timing_disclaimer_names_only_what_was_used(self):
        r = _report(self.a, dasha={"current": {"mahadasha": "Venus"}})
        text = next(d["text"] for d in r["disclaimers"] if d["key"] == "full_details_accuracy")
        self.assertIn("current Mahadasha", text)
        self.assertNotIn("transit", text.lower())

    def test_love_vs_arranged_is_not_published(self):
        kundali_with_houses = {"house_planets": {"5": [{"name": "Venus"}], "7": [{"name": "Jupiter"}]}}
        for kundali in ({}, kundali_with_houses):
            r = _report(self.a, kundali=kundali)
            lva = r["signals"]["love_vs_arranged"]
            self.assertEqual((lva["love_pct"], lva["arranged_pct"], lva["reasons"], lva["available"]), (None, None, [], False))
            sec = next(s for s in r["sections"] if s["id"] == "love_vs_arranged")
            self.assertIn("Not available", sec["summary"])
            self.assertNotIn("%", sec["summary"])

    def test_missing_partner_time_is_flagged_everywhere(self):
        a = dict(self.a, approximate=True, approximation_reason="partner_birth_time_or_place_missing")
        for lang in ("en", "hi"):
            r = _report(a, lang=lang)
            self.assertTrue(r["ashtakoot"]["approximate"])
            self.assertTrue(r["verdict"]["approximate"])
            self.assertEqual(r["disclaimers"][0]["key"], "partner_birth_time_missing")
            self.assertTrue(r["verdict"]["reason_line"].startswith("Approximate:" if lang == "en" else "अनुमानित:"))
        self.assertFalse(_report(self.a)["verdict"]["approximate"])

    def test_paid_report_prompt_evidence_never_sees_engine_bookkeeping(self):
        a = dict(self.a, approximate=True, approximation_reason="x", engine_version=AK.ENGINE_VERSION)
        cleaned = _customer_ashtakoot(a)
        for k in ("engine_version", "approximate", "approximation_reason"):
            self.assertNotIn(k, cleaned)
        self.assertEqual(cleaned["total_score"], a["total_score"])
        for v in cleaned["kootas"].values():
            self.assertNotIn("status", v)


class FreeEndpointContract(unittest.TestCase):
    """The free website tool and the Flutter app call these endpoints; keys must stay compatible."""

    USER = {"name": "SYNTHETIC Test Boy", "dob": "1994-03-15", "tob": "08:30", "pob": "New Delhi (synthetic)", "lat": 28.6139, "lng": 77.2090}
    PARTNER = {"name": "SYNTHETIC Test Girl", "dob": "1996-11-02", "tob": "17:45", "pob": "Mumbai (synthetic)", "lat": 19.0760, "lng": 72.8777}

    @classmethod
    def setUpClass(cls):
        app = Flask("ashtakoot_phase1_test")
        app.register_blueprint(love_bp)
        cls.client = app.test_client()

    def post(self, ep, partner, lang="en", boy_is_user=True):
        return self.client.post(f"/api/love/{ep}", json={"language": lang, "boy_is_user": boy_is_user, "user": self.USER, "partner": partner})

    def test_report_keys_statuses_and_sections(self):
        for lang in ("en", "hi"):
            r = self.post("report", self.PARTNER, lang)
            self.assertEqual(r.status_code, 200)
            d = r.get_json()["data"]
            for key in ("type", "report_key", "version", "client", "verdict", "ashtakoot", "sections", "signals", "mangal_dosh", "disclaimers"):
                self.assertIn(key, d)
            for key in ("level", "score", "max_score", "score_pct", "reason_line", "hard_dosha_pressure", "cancellations"):
                self.assertIn(key, d["verdict"])
            a = d["ashtakoot"]
            self.assertEqual(a["max_score"], 36.0)
            self.assertFalse(a["approximate"])
            self.assertEqual(a["engine_version"], AK.ENGINE_VERSION)
            self.assertEqual(set(a["kootas"]), {"varna", "vashya", "tara", "yoni", "graha_maitri", "gana", "bhakoot", "nadi"})  # JSON keys are sorted
            self.assertTrue(all(k["status"] in STATUS_VOCAB and "raw_status" not in k for k in a["kootas"].values()))
            self.assertEqual([s["id"] for s in d["sections"]], ["ashtakoot_top", "koota_notes", "love_to_marriage_flow", "love_vs_arranged",
                                                                "strengths_risks", "mangal_dosh", "remedies", "disclaimers"])
            notes = next(s for s in d["sections"] if s["id"] == "koota_notes")["data"]["koota_notes"]
            self.assertEqual(len(notes), 8)

    def test_dob_only_partner_is_flagged_approximate(self):
        r = self.post("report", {"name": "SYNTHETIC Test Girl", "dob": "1996-11-02"})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()["data"]
        self.assertTrue(d["ashtakoot"]["approximate"])
        self.assertTrue(d["verdict"]["reason_line"].startswith("Approximate:"))
        self.assertEqual(d["disclaimers"][0]["key"], "partner_birth_time_missing")

    def test_app_role_order_boy_is_partner(self):
        r = self.post("report", self.PARTNER, boy_is_user=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["data"]["ashtakoot"]["max_score"], 36.0)

    def test_other_free_tools_still_respond(self):
        r1 = self.post("truth-or-dare", self.PARTNER)
        r2 = self.post("love-marriage-probability", self.PARTNER)
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertIn(r1.get_json()["data"]["verdict"], ("TRUTH", "DARE"))
        self.assertIn("user_result", r2.get_json()["data"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
