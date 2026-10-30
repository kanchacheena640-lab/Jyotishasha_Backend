"""Regression tests for F12-P3.10 / P3.10.1: delivery-first focused-report output validation and the untimed-prompt fix.

Valid examples are hand-written, realistic answers grounded in the REAL prompts (frozen clock, fixture chart) for every
archetype, EN and HI, including both buyer roles of kundali_match_for_marriage. Invalid examples are the P3.9 probe
outputs plus single, targeted mutations of the valid ones. No database, network, AI, payment or email.
"""
import contextlib
import copy
import io
import json
import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_focused_promotion_prototype import frozen_clock, FIXTURE
from full_kundali_api import calculate_full_kundali
from modules.focused_reports import dispatcher, paid_report_router as router
from modules.focused_reports import relationship_evidence as relationship_collector
from modules.focused_reports.dispatcher import resolve_focused_handler
from modules.focused_reports.master_contract import TIMING_SECTIONS, is_timed, output_contract, report_sections
from modules.focused_reports import output_validation
from modules.focused_reports.output_validation import HARD_CODES, WARNING_CODES, FocusedOutputValidationError, validate_focused_output
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.intents.question_catalog import QUESTIONS
from modules.payments.report_date_format import format_customer_date

USER = {**FIXTURE, "lng": FIXTURE["lon"]}
PARTNER = {**USER, "name": "Partner Fixture", "dob": "1992-08-20", "tob": "09:15"}
CASES = {  # case -> question key
    "timing": "promotion_timing", "direction": "natural_strengths", "diagnostic": "marriage_delay_reason",
    "obstacles": "major_kundali_obstacles", "strengths": "major_kundali_strengths",
    "match_bride": "kundali_match_for_marriage", "match_groom": "kundali_match_for_marriage",
    "conflict_bride": "conflict_areas",
}


def report(language, sections, body):
    return "\n\n".join(f"**{heading}**\n{text}" for heading, text in zip(sections, body))


def raw_answer(hero_label, hero, actions, narrative):
    meta = {"answer_hero": {"label": hero_label, **hero}, "action_items": actions}
    return "===META===\n" + json.dumps(meta, ensure_ascii=False) + "\n===REPORT===\n" + narrative


def examples(D):
    """Valid answers, keyed (case, language). D(iso, language) formats a date exactly like the evidence."""
    e = D
    return {
        ("timing", "en"): (
            {"value": "Supportive in phases", "interpretation": "Jupiter in Leo, your 11th house, supports gains from effort.",
             "evidence": ["Saturn in Capricorn in the 4th house (Shasha Yog)", f"Mercury Mahadasha - Mercury Antardasha until {e('2027-11-28', 'en')}"]},
            ["Take on one visible responsibility.", "Keep a record of results for reviews."],
            ["Yes, this is a reasonably supportive period for promotion, though it moves in phases rather than one straight line.",
             f"You have a Libra Ascendant, and Saturn sits in your 4th house in its own sign, which forms Shasha Yog within the Panch Mahapurush Yog. You are running the Mercury Mahadasha - Mercury Antardasha from {e('2025-07-01', 'en')} to {e('2027-11-28', 'en')}, a phase that rewards clear communication and skill.",
             f"From {e('2026-10-31', 'en')} to {e('2027-01-24', 'en')}, Jupiter is in Leo, your 11th house, which supports recognition and gains from effort. Jupiter returns to Leo from {e('2027-06-26', 'en')}.",
             f"From {e('2026-12-14', 'en')} to {e('2027-04-13', 'en')} Jupiter is retrograde, a slower review phase inside the same supportive stretch.",
             "Take on one visible responsibility before the end of January. Keep a short record of results you can show in reviews.",
             "The period supports promotion, especially while Jupiter is in your 11th house; steady effort, not haste, is what this chart rewards."]),
        ("timing", "hi"): (
            {"value": "चरणों में अनुकूल", "interpretation": "Jupiter (Guru) आपके 11th House में मेहनत का फल देते हैं।",
             "evidence": ["Saturn आपके 4th House में (Shasha Yog)", f"Mercury Mahadasha – Mercury Antardasha {e('2027-11-28', 'hi')} तक"]},
            ["कोई एक नई ज़िम्मेदारी लें।", "अपने काम के नतीजे लिखकर रखें।"],
            ["हाँ, यह समय Promotion के लिए काफ़ी हद तक अच्छा है, लेकिन यह एक सीधी रेखा नहीं, बल्कि चरणों में आगे बढ़ेगा। सबसे मज़बूत सहारा तब मिलता है जब Jupiter (Guru) आपके 11th House में रहते हैं।",
             f"आपका Libra Lagna है। Saturn (Shani) आपके 4th House में अपनी ही राशि में बैठे हैं, जिससे Shasha Yog बनता है। अभी Mercury Mahadasha – Mercury Antardasha चल रही है, जो {e('2025-07-01', 'hi')} से {e('2027-11-28', 'hi')} तक है।",
             f"{e('2026-10-31', 'hi')} से {e('2027-01-24', 'hi')} तक Jupiter Leo राशि में, यानी आपके 11th House में रहेंगे — मेहनत की पहचान और फ़ायदे के लिए यह अच्छा समय है। {e('2027-06-26', 'hi')} से Jupiter फिर Leo राशि में आते हैं।",
             f"{e('2026-12-14', 'hi')} से {e('2027-04-13', 'hi')} तक Jupiter Retrograde रहेंगे। यह उसी अच्छे समय के अंदर का धीमा, review वाला हिस्सा है।",
             "अपने काम के नतीजे लिखकर रखें और review में साफ़ बताएँ। जनवरी से पहले कोई एक नई ज़िम्मेदारी लें।",
             "Promotion के लिए समय अच्छा है, ख़ासकर जब Jupiter आपके 11th House में हैं; जल्दबाज़ी नहीं, लगातार मेहनत काम आएगी।"]),
        ("direction", "en"): (
            {"value": "Disciplined and thoughtful", "interpretation": "Saturn in your 4th house gives patience and staying power.",
             "evidence": ["Libra Ascendant", "Moon in Aquarius in the 5th house"]},
            ["Choose roles that reward patience.", "Teach or write about what you learn."],
            ["Your natural strengths are steady discipline, original thinking and a gift for learning through communication.",
             "With a Libra Ascendant, you look for balance and fairness. Saturn is placed in your 4th house in Capricorn, its own sign, which gives patience and the ability to build slowly. Moon in Aquarius in the 5th house brings independent, inventive thinking.",
             "Jupiter and the Sun together in your 9th house point toward teaching, advising, law, travel or any work that shares knowledge. Mercury, the lord of the 9th house, sits in the 8th house, adding a liking for research.",
             "Choose roles where patience is rewarded. Write, teach or explain what you learn.",
             "Your chart points to disciplined, thoughtful strength; it grows best through learning and sharing knowledge."]),
        ("direction", "hi"): (
            {"value": "अनुशासन और समझदारी", "interpretation": "Saturn आपके 4th House में धैर्य और टिके रहने की ताकत देते हैं।",
             "evidence": ["Libra Lagna", "Moon आपके 5th House में"]},
            ["ऐसा काम चुनें जहाँ धैर्य का फल मिले।", "जो सीखें, उसे दूसरों को समझाएँ।"],
            ["आपकी सबसे बड़ी ताकत है अनुशासन, नई सोच और सीखने-सिखाने की क्षमता।",
             "आपका Libra Lagna है, इसलिए आप balance और fairness पसंद करते हैं। Saturn (Shani) आपके 4th House में अपनी राशि में हैं, जिससे धैर्य और धीरे-धीरे मज़बूत नींव बनाने की ताकत मिलती है। Moon आपके 5th House में है, जो आपकी सोच को नया और स्वतंत्र बनाता है।",
             "Jupiter और Sun दोनों आपके 9th House में हैं, इसलिए teaching, guidance, law या ज्ञान बाँटने वाला काम आपके लिए अच्छा है। Mercury 8th House में है, जिससे research में रुचि बढ़ती है।",
             "ऐसा काम चुनें जहाँ धैर्य का फल मिलता है। जो सीखें, उसे लिखें या दूसरों को समझाएँ।",
             "आपकी chart अनुशासन और समझदारी वाली ताकत दिखाती है; यह सीखने और ज्ञान बाँटने से सबसे ज़्यादा बढ़ती है।"]),
        ("diagnostic", "en"): (
            {"value": "A slower rhythm, not a denial", "interpretation": "Venus in your 7th house with its lord in the 6th asks for practical settling first.",
             "evidence": ["Venus in the 7th house", f"Saturn moves into Aries from {e('2027-06-03', 'en')}"]},
            ["Talk openly with family about expectations.", "Meet people through trusted circles."],
            ["Marriage is not denied; the delay comes from a cautious, slow-moving pattern rather than a block.",
             "Venus is placed in your 7th house in Aries, and its sign lord Mars sits in the 6th house, so relationships tend to need practical settling before commitment. Saturn in your 4th house adds caution about home and family.",
             f"In the Mercury Mahadasha - Mercury Antardasha, from {e('2025-07-01', 'en')} to {e('2027-11-28', 'en')}, attention leans toward work and learning. Saturn is in Pisces, your 6th house, through {e('2027-06-02', 'en')}, which keeps daily duties heavy.",
             f"From {e('2027-06-03', 'en')} Saturn moves into Aries, your 7th house, bringing commitment themes forward, and the Mercury Mahadasha - Ketu Antardasha begins on {e('2027-11-28', 'en')}.",
             "Talk openly with family about expectations. Meet people through trusted circles.",
             "The delay is a slower rhythm, not a denial; mid-2027 brings clearer movement."]),
        ("diagnostic", "hi"): (
            {"value": "धीमी रफ़्तार, इनकार नहीं", "interpretation": "Venus (Shukra) आपके 7th House में हैं, इसलिए पहले practical बातें तय होती हैं।",
             "evidence": ["Venus आपके 7th House में", f"{e('2027-06-03', 'hi')} से Saturn Aries राशि में"]},
            ["परिवार से उम्मीदों पर खुलकर बात करें।", "भरोसेमंद लोगों के ज़रिए रिश्ते देखें।"],
            ["शादी से इनकार नहीं है; देरी सावधानी और धीमी गति की वजह से है, किसी रुकावट से नहीं।",
             "Venus (Shukra) आपके 7th House में Aries राशि में है और इसके Lord Mars 6th House में हैं, इसलिए रिश्ते में commitment से पहले practical बातें तय करनी पड़ती हैं। Saturn आपके 4th House में घर-परिवार को लेकर सावधानी बढ़ाते हैं।",
             f"{e('2025-07-01', 'hi')} से {e('2027-11-28', 'hi')} तक Mercury Mahadasha – Mercury Antardasha चल रही है, जिसमें ध्यान काम और पढ़ाई पर ज़्यादा रहता है। {e('2027-06-02', 'hi')} तक Saturn Pisces राशि में, यानी आपके 6th House में रहेंगे।",
             f"{e('2027-06-03', 'hi')} से Saturn Aries राशि में, यानी आपके 7th House में आते हैं, और {e('2027-11-28', 'hi')} से Mercury Mahadasha – Ketu Antardasha शुरू होती है।",
             "परिवार से उम्मीदों पर खुलकर बात करें। भरोसेमंद लोगों के ज़रिए रिश्ते देखें।",
             "यह देरी धीमी रफ़्तार है, इनकार नहीं; 2027 के बीच से चीज़ें साफ़ होने लगती हैं।"]),
        ("obstacles", "en"): (
            {"value": "Real but workable", "interpretation": "Rahu and Saturn in the 4th house bring restlessness about home.",
             "evidence": ["Saturn in the 4th house", f"Rahu moves into Capricorn from {e('2026-12-05', 'en')}"]},
            ["Keep a weekly routine for home matters.", "Save carefully."],
            ["Your chart's main obstacles are inner caution and an uneven work-versus-home balance; both can be managed.",
             "Rahu and Saturn together in your 4th house can bring restlessness about home and inner peace. Mercury, your 9th and 12th house lord, is placed in the 8th house, so plans sometimes change at short notice.",
             f"You are in the Mercury Mahadasha - Mercury Antardasha until {e('2027-11-28', 'en')}. Rahu moves into Capricorn, your 4th house, from {e('2026-12-05', 'en')}, which can stir the same home-related restlessness again.",
             "Keep a simple weekly routine for home matters. On Saturdays, a small act of charity linked to Saturn can help you stay steady. Kuber Rajyog in your chart supports careful saving.",
             "These obstacles are real but workable; routine and patience turn them into strengths."]),
        ("obstacles", "hi"): (
            {"value": "असली, पर संभलने लायक", "interpretation": "Saturn आपके 4th House में घर को लेकर बेचैनी दे सकते हैं।",
             "evidence": ["Saturn आपके 4th House में", f"{e('2026-12-05', 'hi')} से Rahu Capricorn राशि में"]},
            ["घर के कामों का weekly routine रखें।", "सोच-समझकर बचत करें।"],
            ["आपकी chart की मुख्य बाधाएँ हैं मन की बेचैनी और काम-घर के बीच संतुलन की कमी; दोनों को संभाला जा सकता है।",
             "Rahu और Saturn दोनों आपके 4th House में हैं, जिससे घर और मन की शांति को लेकर बेचैनी आ सकती है। Mercury 8th House में है, इसलिए योजनाएँ कभी-कभी अचानक बदलती हैं।",
             f"{e('2027-11-28', 'hi')} तक Mercury Mahadasha – Mercury Antardasha चल रही है। {e('2026-12-05', 'hi')} से Rahu Capricorn राशि में, यानी आपके 4th House में आते हैं, जिससे वही बेचैनी फिर उभर सकती है।",
             "घर के कामों के लिए हर हफ़्ते एक तय routine रखें। शनिवार को Saturn से जुड़ा छोटा दान आपको स्थिर रखने में मदद कर सकता है। आपकी chart का Kuber Rajyog सोच-समझकर बचत करने में साथ देता है।",
             "ये बाधाएँ असली हैं लेकिन संभाली जा सकती हैं; routine और धैर्य इन्हें ताकत में बदल देते हैं।"]),
        ("strengths", "en"): (
            {"value": "Steady and active now", "interpretation": "Shasha Yog gives disciplined endurance.",
             "evidence": ["Panch Mahapurush Yog (Shasha Yog)", "Sun in the 9th house"]},
            ["Commit to one course.", "Share your knowledge publicly."],
            ["Your chart's biggest strengths are disciplined endurance and a gift for learning, and both are active now.",
             "Saturn in its own sign in your 4th house forms Shasha Yog, part of Panch Mahapurush Yog. Jupiter and Sun together in the 9th house give wisdom and good mentors.",
             f"The Mercury Mahadasha - Mercury Antardasha, from {e('2025-07-01', 'en')} to {e('2027-11-28', 'en')}, favours skill and study. Jupiter in Leo, your 11th house, from {e('2026-10-31', 'en')} to {e('2027-01-24', 'en')} supports gains from effort.",
             "Commit to one course or certification. Share your knowledge publicly.",
             "Your strengths are steady and active now; use them deliberately."]),
        ("strengths", "hi"): (
            {"value": "स्थिर और अभी सक्रिय", "interpretation": "Shasha Yog अनुशासन और धैर्य देता है।",
             "evidence": ["Panch Mahapurush Yog (Shasha Yog)", "Sun 9th House में"]},
            ["कोई एक course पूरा करें।", "अपना ज्ञान दूसरों के साथ बाँटें।"],
            ["आपकी chart की सबसे बड़ी ताकतें हैं धैर्य और सीखने की क्षमता, और दोनों अभी सक्रिय हैं।",
             "Saturn आपके 4th House में अपनी राशि में होकर Shasha Yog बनाते हैं, जो Panch Mahapurush Yog का हिस्सा है। Jupiter और Sun दोनों 9th House में हैं, जिससे समझदारी और अच्छे mentors मिलते हैं।",
             f"{e('2025-07-01', 'hi')} से {e('2027-11-28', 'hi')} तक की Mercury Mahadasha – Mercury Antardasha skill और पढ़ाई के लिए अच्छी है। {e('2026-10-31', 'hi')} से {e('2027-01-24', 'hi')} तक Jupiter Leo राशि में, यानी 11th House में रहकर मेहनत से फ़ायदा दिलाते हैं।",
             "कोई एक course या certification पूरा करें। अपना ज्ञान दूसरों के साथ बाँटें।",
             "आपकी ताकतें स्थिर हैं और अभी सक्रिय हैं; इन्हें सोच-समझकर इस्तेमाल करें।"]),
        ("match_bride", "en"): (
            {"value": "Workable, needs patience", "interpretation": "Nadi and Bhakoot score in full.",
             "evidence": ["24.5 out of 36 Ashtakoot points", "Nadi 8 of 8"]},
            ["Agree on how you decide together.", "Respect each other's pace."],
            ["Your match is workable, with 24.5 out of 36 Ashtakoot points and clear strengths in Nadi and Bhakoot.",
             "Nadi scores the full 8 of 8 and Bhakoot the full 7 of 7, the two most important factors. As the bride, your Moon is in Aquarius, and your partner's Moon is in Aries; Gana gives 3 of 6.",
             "Graha Maitri gives only 1 of 5, so your Moon lords, Saturn and Mars, see things differently. Patience in daily decisions helps.",
             "Agree on how you make decisions together. Respect each other's pace.",
             "With 24.5/36 and strong Nadi and Bhakoot, this is a workable match that needs patience, not a doubtful one."]),
        ("match_bride", "hi"): (
            {"value": "ठीक मिलान, धैर्य ज़रूरी", "interpretation": "Nadi और Bhakoot में पूरे अंक हैं।",
             "evidence": ["36 में से 24.5 गुण", "Nadi में 8 में से 8"]},
            ["साथ मिलकर फ़ैसले लेने का तरीका तय करें।", "एक-दूसरे की रफ़्तार का सम्मान करें।"],
            ["आपका मिलान ठीक-ठाक है: 36 में से 24.5 गुण मिलते हैं, और Nadi तथा Bhakoot दोनों मज़बूत हैं।",
             "Nadi में पूरे 8 में से 8 और Bhakoot में पूरे 7 में से 7 अंक हैं — ये दोनों सबसे अहम बातें हैं। वधू के रूप में आपका Moon Aquarius राशि में है और आपके साथी का Moon Aries राशि में है।",
             "Graha Maitri में 5 में से सिर्फ़ 1 अंक है, यानी आपके Moon के स्वामी Saturn और साथी के Moon के स्वामी Mars अलग नज़रिए रखते हैं। रोज़ के फ़ैसलों में धैर्य रखें।",
             "साथ मिलकर फ़ैसले लेने का तरीका तय करें। एक-दूसरे की रफ़्तार का सम्मान करें।",
             "36 में से 24.5 गुण और मज़बूत Nadi-Bhakoot के साथ यह एक ठीक मिलान है, जिसमें धैर्य की ज़रूरत है।"]),
        ("match_groom", "en"): (
            {"value": "Workable, needs patience", "interpretation": "Nadi and Bhakoot score in full.",
             "evidence": ["23.5 out of 36 Ashtakoot points", "Varna 0 of 1"]},
            ["Agree on how you decide together.", "Respect each other's pace."],
            ["Your match is workable, with 23.5 out of 36 Ashtakoot points and clear strengths in Nadi and Bhakoot.",
             "Nadi scores the full 8 of 8 and Bhakoot the full 7 of 7. As the groom, your Moon is in Aquarius, and your partner's Moon is in Aries.",
             "Varna gives 0 of 1 and Graha Maitri only 1 of 5, so daily priorities can differ. Patience helps.",
             "Agree on how you make decisions together. Respect each other's pace.",
             "With 23.5/36 and strong Nadi and Bhakoot, this is a workable match that needs patience."]),
        ("match_groom", "hi"): (
            {"value": "ठीक मिलान, धैर्य ज़रूरी", "interpretation": "Nadi और Bhakoot में पूरे अंक हैं।",
             "evidence": ["36 में से 23.5 गुण", "Varna में 1 में से 0"]},
            ["साथ मिलकर फ़ैसले लेने का तरीका तय करें।", "एक-दूसरे की रफ़्तार का सम्मान करें।"],
            ["आपका मिलान ठीक-ठाक है: 36 में से 23.5 गुण मिलते हैं, और Nadi तथा Bhakoot दोनों मज़बूत हैं।",
             "Nadi में पूरे 8 में से 8 और Bhakoot में पूरे 7 में से 7 अंक हैं। वर के रूप में आपका Moon Aquarius राशि में है और आपके साथी का Moon Aries राशि में है।",
             "Varna में 1 में से 0 और Graha Maitri में 5 में से सिर्फ़ 1 अंक है, इसलिए रोज़ की प्राथमिकताएँ अलग हो सकती हैं। धैर्य रखें।",
             "साथ मिलकर फ़ैसले लेने का तरीका तय करें। एक-दूसरे की रफ़्तार का सम्मान करें।",
             "36 में से 23.5 गुण और मज़बूत Nadi-Bhakoot के साथ यह एक ठीक मिलान है, जिसमें धैर्य की ज़रूरत है।"]),
    }


class FocusedOutputValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompts, cls.handlers = {}, {}
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock():
            charts = {p["name"]: calculate_full_kundali(name=p["name"], dob=p["dob"], tob=p["tob"], lat=p["lat"],
                                                        lon=p["lng"], language="en") for p in (USER, PARTNER)}
            for language in ("en", "hi"):
                for case, key in CASES.items():
                    _, handler = resolve_focused_handler(key)
                    cls.handlers[case] = handler
                    if case.endswith(("_bride", "_groom")):
                        data = {"user": USER, "partner": PARTNER, "boy_is_user": case.endswith("_groom")}
                        with patch.object(relationship_collector, "calculate_full_kundali",
                                          side_effect=lambda **kw: copy.deepcopy(charts[kw["name"]])):
                            built = handler.build_prompt(data, language)
                    else:
                        built = handler.build_prompt(copy.deepcopy(charts[USER["name"]]), language)
                    cls.prompts[(case, language)] = built.prompt
        cls.valid = {}
        for (case, language), (hero, actions, body) in examples(format_customer_date).items():
            spec = get_prompt_spec(CASES[case])
            sections = [pair[language == "hi"] for pair in report_sections(spec)]
            label = "Promotion Outlook" if CASES[case] == "promotion_timing" else spec.title.get(language)
            cls.valid[(case, language)] = raw_answer(label, hero, actions, report(language, sections, body))

    def check(self, case, language, raw):
        """Real finalizer, then the validator: returns (hard codes, warning codes)."""
        output = self.handlers[case].finalize(raw, language)
        try:
            return set(), set(validate_focused_output(CASES[case], language, self.prompts[(case, language)], output))
        except FocusedOutputValidationError as exc:
            return set(exc.codes), set()

    def mutate(self, case, language, old, new):
        raw = self.valid[(case, language)]
        self.assertIn(old, raw, f"{case}/{language}: mutation anchor missing")
        return self.check(case, language, raw.replace(old, new, 1))

    # -------------------------------------------------------------- classification is explicit and closed
    def test_hard_and_warning_codes_are_disjoint_and_hard_is_contradictions_only(self):
        self.assertEqual(HARD_CODES, {"role_contradiction", "score_contradiction"})
        self.assertFalse(HARD_CODES & WARNING_CODES)

    # -------------------------------------------------------------- valid examples and variations
    def test_valid_examples_pass_cleanly_for_every_archetype_in_en_and_hi(self):
        self.assertEqual(len(self.valid), 14)
        for (case, language), raw in self.valid.items():
            with self.subTest(case=case, language=language):
                self.assertEqual(self.check(case, language, raw), (set(), set()))

    def test_realistic_variations_are_never_blocked(self):
        variations = [  # (case, language, old, new) -- legitimate model behaviour that must still be delivered cleanly
            ("timing", "en", "**Direct Answer**", "**Direct Answer:**"),
            ("timing", "en", "**Why Your Chart Says This**", "**why your chart says this**"),
            ("timing", "en", "**Slower or Watch Period**\n", "**Key point:**\n"),
            ("timing", "hi", "**धीमा या ध्यान रखने वाला समय**\n", ""),
            ("diagnostic", "en", "\n\n**What You Can Do**", "\n\n\n**What You Can Do**"),
            ("direction", "hi", "आपकी सबसे बड़ी ताकत", "Overall, आपकी सबसे बड़ी strength"),
            ("timing", "en", "a phase that rewards clear communication",
             "a phase (roughly Oct 31st onward, or 31/10/2026) that rewards clear communication"),
            ("match_bride", "en", "Patience in daily decisions helps.",
             "Patience in daily decisions helps, and your role as the bride is honoured."),
        ]
        for case, language, old, new in variations:
            with self.subTest(case=case, language=language, new=new[:40]):
                self.assertEqual(self.mutate(case, language, old, new), (set(), set()))

    def test_unrecognised_wording_produces_no_code_at_all(self):
        additions = {
            ("direction", "en"): "Jupiter is not in your 10th house, so leadership comes through knowledge instead. Your guru may be a book.",
            ("match_bride", "hi"): "इसमें किसी का दोष नहीं है। मंगलवार या शनिवार को साथ समय बिताएँ।",
            ("timing", "en"): "Saturn in Capricorn gives strength in the 10th house matters you handle. Around the 31st, review goals.",
            ("obstacles", "hi"): "हर मंगलवार थोड़ा समय अपने लिए रखें।",
            ("strengths", "en"): "Many people find this chart pattern, which some call a blessing, quietly reliable.",
        }
        for (case, language), sentence in additions.items():
            with self.subTest(case=case, language=language):
                raw = self.valid[(case, language)]
                self.assertEqual(self.check(case, language, raw.rstrip() + " " + sentence), (set(), set()))

    # -------------------------------------------------------------- warnings (still delivered)
    def test_heuristic_findings_are_warnings_never_hard(self):
        warnings = [
            ("timing", "en", "From 31 October 2026", "From 3 November 2026", "date_not_in_evidence"),
            ("direction", "en", "Choose roles where patience is rewarded.",
             "Choose roles where patience is rewarded, especially in 2028.", "date_not_in_evidence"),
            ("timing", "en", "Saturn sits in your 4th house", "Saturn sits in your 10th house", "placement_not_in_evidence"),
            ("timing", "en", "Jupiter is in Leo", "Jupiter is in Virgo", "placement_not_in_evidence"),
            ("diagnostic", "hi", "Saturn आपके 4th House में घर-परिवार", "Saturn आपके 9th House में घर-परिवार", "placement_not_in_evidence"),
            ("obstacles", "en", "Rahu moves into Capricorn", "Rahu moves into Sagittarius", "placement_not_in_evidence"),
            ("direction", "en", "Libra Ascendant, you", "Scorpio Ascendant, you", "lagna_not_in_evidence"),
            ("direction", "en", "brings independent, inventive thinking.",
             "brings independent thinking, and Gajakesari Yog adds fame.", "yoga_not_in_evidence"),
            ("diagnostic", "en", "Talk openly with family", "Sade Sati is active, so talk openly with family", "dosha_not_in_evidence"),
            ("direction", "hi", "**व्यावहारिक ध्यान**", "**अभी के समय का संदर्भ**\nअभी समय अच्छा है।\n\n**व्यावहारिक ध्यान**",
             "timing_section_without_dated_evidence"),
            ("timing", "hi", "**सबसे मजबूत समय**\n", "", "heading_missing"),
        ]
        for case, language, old, new, code in warnings:
            with self.subTest(case=case, language=language, code=code):
                hard, found = self.mutate(case, language, old, new)
                self.assertEqual(hard, set())
                self.assertIn(code, found)
        swapped = self.valid[("timing", "en")]
        a, b = "**Strongest Periods**", "**What You Should Do**"
        swapped = swapped.replace(a, "\x00").replace(b, a).replace("\x00", b)
        self.assertEqual(self.check("timing", "en", swapped), (set(), {"heading_order"}))
        hard, found = self.check("direction", "en", self.valid[("direction", "hi")])
        self.assertEqual(hard, set())
        self.assertIn("language_share", found)
        hard, found = self.check("conflict_bride", "en", raw_answer(
            "x", {"value": "v", "interpretation": "i", "evidence": ["a", "b"]}, ["Act"], "**Direct Answer**\nYou score 24.5 out of 36."))
        self.assertEqual(hard, set())
        self.assertIn("total_score_not_supplied", found)

    def test_p39_probe_outputs_classified(self):
        meta = {"value": "Steady", "interpretation": "One sentence.", "evidence": ["Libra Ascendant", "Moon in 5th house"]}
        probes = [
            ("A English for a HINDI order", "direction", "hi",
             "**Direct Answer**\nYour chart shows steady strengths.\n\n**Bottom Line**\nYou are capable.", "language_share"),
            ("B invented placement", "direction", "en", "**Direct Answer**\nJupiter in your 10th house gives you leadership.",
             "placement_not_in_evidence"),
            ("C timing section in an untimed report", "direction", "en",
             "**Direct Answer**\nStrong.\n\n**Current Timing Context**\nFrom 3 March 2027 to 9 May 2027 is your best window.",
             "timing_section_without_dated_evidence"),
            ("E headings missing", "timing", "en", "Promotion looks fine.", "heading_missing"),
            ("F Manglik dosha", "diagnostic", "en", "**Direct Answer**\nYour Manglik dosha delays marriage.", "dosha_not_in_evidence"),
        ]
        for label, case, language, narrative, code in probes:
            with self.subTest(label):
                hard, found = self.check(case, language, raw_answer(get_prompt_spec(CASES[case]).title.get(language), meta, ["Act"], narrative))
                self.assertEqual(hard, set())
                self.assertIn(code, found)
        hard, _ = self.check("match_bride", "en", raw_answer("x", meta, ["Act"], "**Direct Answer**\nAs the groom, your Moon in Aquarius ..."))
        self.assertEqual(hard, {"role_contradiction"})

    # -------------------------------------------------------------- hard failures (blocked)
    def test_proven_contradictions_are_hard_failures(self):
        hard_cases = [
            ("match_bride", "en", "with 24.5 out of 36", "with 23.5 out of 36", "score_contradiction"),
            ("match_bride", "en", "this is a workable match", "this is 24.5/35, a workable match", "score_contradiction"),
            ("match_bride", "hi", "36 में से 24.5 गुण मिलते हैं", "36 में से 26 गुण मिलते हैं", "score_contradiction"),
            ("match_bride", "en", "As the bride, your Moon", "As the groom, your Moon", "role_contradiction"),
            ("match_groom", "hi", "वर के रूप में आपका", "वधू के रूप में आपका", "role_contradiction"),
            ("match_groom", "en", "Patience helps.", "Patience helps; you are the bride here.", "role_contradiction"),
            ("match_groom", "en", "Patience helps.", "Patience helps; your partner is the groom.", "role_contradiction"),
        ]
        for case, language, old, new, code in hard_cases:
            with self.subTest(case=case, language=language, code=code):
                hard, _ = self.mutate(case, language, old, new)
                self.assertEqual(hard, {code})

    def test_existing_meta_and_empty_output_hard_failures_are_unchanged(self):
        from modules.payments.report_structured_output import ReportMetadataError
        for raw in ("===META===\n{not json}\n===REPORT===\n**Direct Answer**\nx",
                    raw_answer("x", {"value": "y", "interpretation": "z"}, ["Act"], "**Direct Answer**\nx"),
                    raw_answer("x", {"value": "v", "interpretation": "i", "evidence": ["a"]}, ["Act"], "   ")):
            with self.assertRaises(ReportMetadataError):
                self.handlers["direction"].finalize(raw, "en")

    def test_a_crash_inside_a_check_never_blocks_delivery(self):
        output = self.handlers["match_bride"].finalize(self.valid[("match_bride", "en")], "en")
        with patch.object(output_validation, "_dual_codes", side_effect=RuntimeError("bug")), \
             patch.object(output_validation, "_placement_codes", side_effect=RuntimeError("bug")):
            warnings = validate_focused_output("kundali_match_for_marriage", "en", self.prompts[("match_bride", "en")], output)
        self.assertEqual(warnings, ("check_error",))

    # -------------------------------------------------------------- prompt contract (P3.10 Step 1, unchanged)
    def test_untimed_questions_never_ask_for_a_timing_section(self):
        untimed = [q.question_key for q in QUESTIONS if not is_timed(get_prompt_spec(q.question_key))]
        self.assertEqual(sorted(untimed), sorted(["conflict_areas", "emotional_communication_fit", "kundali_match_for_marriage",
                                                  "life_direction", "long_term_compatibility", "natural_strengths",
                                                  "relationship_strengths_risks", "strengthen_relationship"]))
        for key in untimed:
            spec = get_prompt_spec(key)
            for language in ("en", "hi"):
                contract = output_contract(spec, language)
                headings = re.findall(r"(?m)^\*\*(.+?)\*\*$", contract)
                self.assertFalse({pair[0] for pair in report_sections(spec)} & TIMING_SECTIONS, key)
                self.assertNotIn("Current Timing Context", headings)
                self.assertNotIn("अभी के समय का संदर्भ", headings)
                self.assertIn("No dated evidence is supplied for this question", contract)
        self.assertIn("MUST NOT calculate, change or invent any planetary position", self.prompts[("direction", "en")])
        self.assertIn("**Current Timing Context**", output_contract(get_prompt_spec("study_abroad"), "en"))

    # -------------------------------------------------------------- integration
    def test_dispatcher_delivers_warned_output_and_raises_only_on_contradiction(self):
        warned = self.valid[("direction", "en")].replace("Saturn is placed in your 4th house", "Saturn is placed in your 10th house")
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock():
            kundali = calculate_full_kundali(name=USER["name"], dob=USER["dob"], tob=USER["tob"], lat=USER["lat"], lon=USER["lng"], language="en")
            with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=warned)):
                result = dispatcher.generate_focused_report("natural_strengths", kundali, "en")
        self.assertEqual(result["output_warnings"], ("placement_not_in_evidence",))
        self.assertIn("10th house", result["report"])
        contradiction = self.valid[("match_bride", "en")].replace("with 24.5 out of 36", "with 30 out of 36")
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock(), \
             patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=contradiction)):
            with self.assertRaises(FocusedOutputValidationError) as ctx:
                dispatcher.generate_focused_report("kundali_match_for_marriage", {"user": USER, "partner": PARTNER, "boy_is_user": False}, "en")
        self.assertEqual(ctx.exception.codes, ("score_contradiction",))
        self.assertNotIn(USER["name"], str(ctx.exception))

    def _route(self, generate):
        order = SimpleNamespace(id=7, product="natural_strengths", name="Asha Verma", dob=USER["dob"], tob=USER["tob"],
                                pob=USER["pob"], latitude=USER["lat"], longitude=USER["lng"], language="en",
                                partner_payload=None, report_stage="Queued", processing_started_at=None, pdf_url=None)
        log = io.StringIO()
        with patch.object(router, "Order") as orders, patch.object(router, "ReportProduct") as products, \
             patch.object(router, "db"), patch.object(router, "calculate_full_kundali", return_value={}), \
             patch.object(router, "generate_focused_report", **generate), \
             patch.object(router, "render_focused_report_pdf", return_value="x.pdf") as render, \
             patch.object(router, "deliver_generated_report") as deliver, \
             patch.object(router, "report_output_path", return_value="out/x.pdf"), patch.object(router.os, "makedirs"), \
             contextlib.redirect_stdout(log):
            orders.query.get.return_value = order
            products.query.get.return_value = SimpleNamespace(generator="focused_v1")
            error = None
            try:
                router.route_focused_report_generation(order.id)
            except FocusedOutputValidationError as exc:
                error = exc
        return order, render, deliver, log.getvalue(), error

    def test_paid_router_delivers_despite_warnings_and_logs_codes_only(self):
        result = {"question_key": "natural_strengths", "report": "x", "output_warnings": ("date_not_in_evidence", "language_share")}
        order, render, deliver, log, error = self._route({"return_value": result})
        self.assertIsNone(error)
        render.assert_called_once()
        deliver.assert_called_once()
        self.assertEqual(order.report_stage, "Ready")
        self.assertIn("[FOCUSED REPORT OUTPUT WARNINGS] order=7 date_not_in_evidence,language_share", log)
        for private in ("Asha", USER["dob"], USER["tob"], "Lucknow"):
            self.assertNotIn(private, log)

    def test_paid_router_blocks_only_a_hard_contradiction(self):
        order, render, deliver, log, error = self._route({"side_effect": FocusedOutputValidationError(["role_contradiction"])})
        self.assertIsInstance(error, FocusedOutputValidationError)
        render.assert_not_called()
        deliver.assert_not_called()
        self.assertEqual(order.report_stage, "Failed")
        self.assertIn("[FOCUSED REPORT OUTPUT REJECTED] order=7 role_contradiction", log)
        for private in ("Asha", USER["dob"], USER["tob"], "Lucknow"):
            self.assertNotIn(private, log)

    def test_validation_is_wired_only_into_focused_reports(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent
        users = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.py")
                       if "venv" not in p.parts and not p.name.startswith("test_")
                       and "output_validation" in p.read_text(encoding="utf-8", errors="ignore"))
        self.assertEqual(users, ["modules/focused_reports/dispatcher.py", "modules/focused_reports/paid_report_router.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
