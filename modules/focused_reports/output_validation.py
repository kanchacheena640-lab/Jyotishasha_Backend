"""Post-generation checks for focused reports (F12-P3.10, delivery-first since F12-P3.10.1).

Runs on the finalized customer output BEFORE any PDF or email exists, against the exact prompt the model received:
its evidence block (plus the stated evidence period) is the only source of supplied facts.

HARD (blocks delivery; the order fails safely and can be regenerated) -- only clearly proven contradictions:
  - role_contradiction: a two-person Ashtakoot report calls the buyer the other role, or the partner the buyer's role;
  - score_contradiction: a "/36" total that differs from the supplied total, or any total out of 35.
  (Empty output and invalid META are already hard failures in finalize_customer_output, before this module runs.)

WARNINGS (logged as codes only; never block the PDF, the email or order completion) -- heuristics that can miss
legitimate phrasing, so they are signals for review, never proof that anything was invented:
  language_share, heading_missing, heading_order, timing_section_without_dated_evidence, date_not_in_evidence,
  placement_not_in_evidence, lagna_not_in_evidence, dosha_not_in_evidence, yoga_not_in_evidence,
  total_score_not_supplied, check_error.
A text the patterns cannot recognise produces no code at all: nothing is flagged merely because a regex fails to
match it. Codes never carry customer text or birth details.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from modules.focused_reports.master_contract import OPTIONAL_SECTIONS, SECTIONS, TIMING_SECTIONS, is_timed, report_sections
from modules.focused_reports.prompt_assembler import language_key
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.payments.report_date_format import EN_MONTHS, HI_MONTHS


HARD_CODES = frozenset({"role_contradiction", "score_contradiction"})
WARNING_CODES = frozenset({
    "language_share", "heading_missing", "heading_order", "timing_section_without_dated_evidence",
    "date_not_in_evidence", "placement_not_in_evidence", "lagna_not_in_evidence", "dosha_not_in_evidence",
    "yoga_not_in_evidence", "total_score_not_supplied", "check_error"})


class FocusedOutputValidationError(ValueError):
    """Only for HARD_CODES."""
    code = "focused_output_invalid"

    def __init__(self, codes: Iterable[str]):
        self.codes = tuple(sorted(set(codes)))
        super().__init__("Focused report output failed validation: " + ", ".join(self.codes))


EVIDENCE_START = "Authoritative backend evidence:"
OUTPUT_START = "Return exactly the two markers"
PERIOD_LABEL = "The supplied evidence period is"

HI_MIN_DEVANAGARI = 0.40  # the HI style guide keeps many English terms (Career, House, Dasha); prose is still Devanagari
EN_MAX_DEVANAGARI = 0.05

SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn",
         "Aquarius", "Pisces")
HI_SIGNS = {"मेष": "Aries", "वृषभ": "Taurus", "वृष": "Taurus", "मिथुन": "Gemini", "कर्क": "Cancer", "सिंह": "Leo",
            "कन्या": "Virgo", "तुला": "Libra", "वृश्चिक": "Scorpio", "धनु": "Sagittarius", "मकर": "Capricorn",
            "कुंभ": "Aquarius", "कुम्भ": "Aquarius", "मीन": "Pisces"}
PLANETS = {
    "Sun": ("Sun", "Surya", "सूर्य"),
    "Moon": ("Moon", "Chandra", "Chandrama", "चंद्रमा", "चन्द्रमा", "चंद्र", "चन्द्र"),
    "Mars": ("Mars", "Mangal", "मंगल"),
    "Mercury": ("Mercury", "Budh", "Budha", "बुध"),
    "Jupiter": ("Jupiter", "Guru", "Brihaspati", "गुरु", "बृहस्पति"),
    "Venus": ("Venus", "Shukra", "शुक्र"),
    "Saturn": ("Saturn", "Shani", "शनि"),
    "Rahu": ("Rahu", "राहु"),
    "Ketu": ("Ketu", "केतु"),
}
_ALIAS = {alias.casefold(): name for name, aliases in PLANETS.items() for alias in aliases}
_W = r"[\wऀ-ॿ]"
_PLANET = re.compile(rf"(?<!{_W})({'|'.join(sorted(map(re.escape, _ALIAS), key=len, reverse=True))})(?!{_W})", re.I)
_SIGN_ALT = "|".join(SIGNS + tuple(HI_SIGNS))
_GAP = r"(?:'s)?(?:\s*\([^()\n]{1,24}\))?((?:\s+[^\s.,;:!?।()]+){0,3}?)"
_HOUSE_CLAIM = re.compile(
    _GAP + r"\s+(?:in\s+(?:your\s+|the\s+|its\s+)?(\d{1,2})(?:st|nd|rd|th)\s+house\b"
    r"|(\d{1,2})(?:st|nd|rd|th|वें|वे)?\s*(?:House|house|हाउस|भाव|घर)\s+में)", re.I)
_SIGN_CLAIM = re.compile(
    _GAP + rf"\s+(?:(?:in|into|enters|entering)\s+(?:the\s+sign\s+of\s+)?({'|'.join(SIGNS)})(?![\w])"
    rf"|({_SIGN_ALT})\s*(?:राशि\s*)?में)", re.I)
_NEGATION = re.compile(r"(?<![\w])(not|never|no|नहीं|न)(?![\wऀ-ॿ])", re.I)
_LAGNA_CLAIM = re.compile(
    rf"(?<!{_W})({_SIGN_ALT})\s*(?:Ascendant|Lagna|लग्न)(?!{_W})|(?:Ascendant|Lagna|लग्न)\s+(?:is\s+|of\s+|in\s+)?({_SIGN_ALT})(?!{_W})",
    re.I)

_EN_MONTH = "|".join(EN_MONTHS)
_HI_MONTH = "|".join(map(re.escape, HI_MONTHS))
_FULL_DATE = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_EN_MONTH}|{_HI_MONTH}),?\s+((?:19|20)\d{{2}})(?!\d)", re.I)
_ISO_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")
_MONTH_YEAR = re.compile(rf"(?<![\wऀ-ॿ])({_EN_MONTH}|{_HI_MONTH}),?\s+((?:19|20)\d{{2}})(?!\d)", re.I)
_YEAR = re.compile(r"(?<!\d)(?<!\d\.)((?:19|20)\d{2})(?!\d|\.\d)")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_DOSHA_TERMS = re.compile(
    r"(?<![\w])(Manglik|Mangal\s*dosh\w*|Kuja\s*dosh\w*|Ka+l\s*-?\s*Sarp\w*|Pit(?:r|ru|ri)\s*dosh\w*|Kem(?:a)?dr(?:u|o)m\w*"
    r"|Nadi\s*dosh\w*|Bhakoot\s*dosh\w*|Grahan\s*dosh\w*|Shrapit\w*|Guru\s*Chandal\w*|Sa+d(?:h)?e\s*-?\s*Sati|Dhaiya\w*|dosh(?:a|as)?)(?![\w])"
    r"|(मांगलिक|मंगल\s*दोष|कुज\s*दोष|काल\s*सर्प|कालसर्प|पितृ\s*दोष|केमद्रुम|नाड़ी\s*दोष|नाडी\s*दोष|भकूट\s*दोष|ग्रहण\s*दोष"
    r"|गुरु\s*चांडाल|साढ़े\s*साती|साढ़ेसाती|ढैय्या)", re.I)
_DOSHA_CANON = {"मांगलिक": "manglik", "मंगलदोष": "mangaldosh", "कुजदोष": "kujadosh", "कालसर्प": "kaalsarp",
                "पितृदोष": "pitradosh", "केमद्रुम": "kemdrum", "नाड़ीदोष": "nadidosh", "नाडीदोष": "nadidosh",
                "भकूटदोष": "bhakootdosh", "ग्रहणदोष": "grahandosh", "गुरुचांडाल": "guruchandal",
                "साढ़ेसाती": "sadesati", "ढैय्या": "dhaiya"}
_YOGA_NAMES = {
    "gajakesari": (r"Gaja\s*-?\s*Kesari", r"गजकेसरी"), "budhaditya": (r"Budh(?:a)?\s*-?\s*Aditya", r"बुधादित्य"),
    "chandramangal": (r"Chandra\s*-?\s*Mangal", r"चंद्र\s*मंगल"), "adhiraj": (r"Adhi\s*-?\s*Raj",),
    "rajyog": (r"Raj(?:a)?", r"राज"), "dhanyog": (r"Dhan(?:a)?", r"धन"), "kuber": (r"Kuber(?:a)?", r"कुबेर"),
    "lakshmi": (r"Lakshmi", r"लक्ष्मी"), "neechbhang": (r"Neech(?:a)?\s*-?\s*Bhang(?:a)?", r"नीचभंग"),
    "panchmahapurush": (r"Panch(?:a)?\s*-?\s*Mahapurush(?:a)?", r"पंच\s*महापुरुष"), "parashari": (r"Parashari",),
    "shasha": (r"Shasha|Sasa", r"शश"), "hamsa": (r"Hamsa|Hansa", r"हंस"), "ruchaka": (r"Ruchaka", r"रुचक"),
    "bhadra": (r"Bhadra", r"भद्र"), "malavya": (r"Malavya", r"मालव्य"), "vipreet": (r"Vip(?:a)?re+t(?:a)?|Viparita", r"विपरीत"),
    "saraswati": (r"Saraswati", r"सरस्वती"), "amala": (r"Amala",), "sunapha": (r"Sunapha",), "anapha": (r"Anapha",),
    "durudhara": (r"Durudhara",), "dharmakarmadhipati": (r"Dharma\s*-?\s*Karm(?:a)?adhipati",),
}
_YOGA = re.compile("|".join(
    rf"(?P<{key}>(?<![\wऀ-ॿ])(?:{'|'.join(alts)})\s*-?\s*(?:Yog(?:a|as)?|योग)(?![\w]))" for key, alts in _YOGA_NAMES.items()),
    re.I)

_ROLE_WORDS = {"en": {"groom": r"(?:bride)?groom", "bride": r"bride"},
               "hi": {"groom": r"(?:वर|दूल्हा)", "bride": r"(?:वधू|दुल्हन)"}}
_TOTAL_CLAIM = re.compile(r"(?<!\d)(?<!\d\.)(\d{1,2}(?:\.\d+)?)\s*(?:/|out\s+of|of|में\s+से)\s*36(?!\d|\.\d)|36\s*में\s*से\s*(\d{1,2}(?:\.\d+)?)", re.I)
_BAD_DENOMINATOR = re.compile(r"(?<!\d)(?<!\d\.)\d{1,2}(?:\.\d+)?\s*(?:/|out\s+of|of|में\s+से)\s*35(?!\d|\.\d)|35\s*में\s*से\s*\d", re.I)


# ---------------------------------------------------------------- evidence -------------------------------------------

def _evidence_text(prompt: str) -> str:
    block = prompt.split(EVIDENCE_START, 1)[1].split(OUTPUT_START, 1)[0] if EVIDENCE_START in prompt else ""
    period = [line for line in prompt.splitlines() if line.startswith(PERIOD_LABEL)]
    return "\n".join(period + [block]).translate(_DEVANAGARI_DIGITS)


def _month_number(name: str) -> int:
    lowered = name.casefold()
    for months in (EN_MONTHS, HI_MONTHS):
        for index, month in enumerate(months, 1):
            if month.casefold() == lowered:
                return index
    raise ValueError(name)


def _dates(text: str):
    """(full dates, month-years, years, text with dated spans blanked) -- dates as (y, m, d) tuples."""
    full, month_years = set(), set()
    for m in _FULL_DATE.finditer(text):
        full.add((int(m.group(3)), _month_number(m.group(2)), int(m.group(1))))
    for m in _ISO_DATE.finditer(text):
        full.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    rest = _ISO_DATE.sub(" ", _FULL_DATE.sub(" ", text))
    for m in _MONTH_YEAR.finditer(rest):
        month_years.add((int(m.group(2)), _month_number(m.group(1))))
    rest = _MONTH_YEAR.sub(" ", rest)
    years = {int(y) for y in _YEAR.findall(rest)}
    return full, month_years, years


def _placements(evidence: str):
    """{planet: {(house, sign)}}, natal and transit; plus the supplied Lagna signs."""
    allowed: dict[str, set] = {name: set() for name in PLANETS}
    for planet, house, sign in re.findall(r"(\w+) is placed in (\d+)\w\w house \((\w+)\)", evidence):
        allowed.setdefault(planet, set()).add((int(house), sign))
    for house, sign, occupants in re.findall(r"House (\d+) \((\w+)\): ([^;]+);", evidence):
        for planet in re.findall(r"\w+", occupants):
            if planet in allowed:
                allowed[planet].add((int(house), sign))
    for planet, sign, house in re.findall(r'\{"name": "(\w+)", "sign": "(\w+)", "house": (\d+)\}', evidence):
        allowed.setdefault(planet, set()).add((int(house), sign))
    for planet, house, sign in re.findall(r'"lord": "(\w+)", "lord_house": (\d+), "lord_sign": "(\w+)"', evidence):
        allowed.setdefault(planet, set()).add((int(house), sign))
    for planet, residence in re.findall(r"(?m)^(Jupiter|Saturn|Rahu)\nSign residence: (.+)$", evidence):
        for sign, house in re.findall(r"(\w+) \((\d+)\w\w house\)", residence):
            allowed[planet].add((int(house), sign))
            if planet == "Rahu":  # "Ketu is always in the sign directly opposite Rahu."
                allowed["Ketu"].add(((int(house) + 5) % 12 + 1, SIGNS[(SIGNS.index(sign) + 6) % 12]))
    lagnas = set(re.findall(r"You have an? (\w+) Ascendant", evidence)) | set(re.findall(r'"lagna": "(\w+)"', evidence))
    return allowed, lagnas


def _normalized(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.casefold()).replace("yoga", "yog").replace("dosha", "dosh")


# ---------------------------------------------------------------- checks ---------------------------------------------

def _devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters) if letters else 0.0


def _headings(report: str) -> list[str]:
    """Whole-line bold headings, in order (the shape convert_headings() renders as a section heading)."""
    found = []
    for line in report.splitlines():
        bold = re.fullmatch(r"\*\*(.+?)\*\*:?", line.strip())
        if bold:
            found.append(_heading_key(bold.group(1).rstrip(":")))
    return found


def _heading_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _section_codes(spec, lang: str, report: str) -> set[str]:
    codes = set()
    index = 1 if lang == "hi" else 0
    present = _headings(report)
    plain_lines = {_heading_key(line.strip().strip("*").rstrip(":")) for line in report.splitlines() if line.strip()}
    expected = report_sections(spec)
    positions = []
    for pair in expected:
        key = _heading_key(pair[index])
        if key in present:
            positions.append(present.index(key))
        elif pair[0] not in OPTIONAL_SECTIONS:
            codes.add("heading_missing")
    if positions != sorted(positions):
        codes.add("heading_order")
    if not is_timed(spec):
        timing = {_heading_key(pair[i]) for sections in SECTIONS.values() for pair in sections
                  if pair[0] in TIMING_SECTIONS for i in (0, 1)}
        if timing & plain_lines:
            codes.add("timing_section_without_dated_evidence")
    return codes


def _date_codes(text: str, evidence: str) -> set[str]:
    allowed_full, allowed_month_years, allowed_years = _dates(evidence)
    allowed_month_years |= {(y, m) for y, m, _ in allowed_full}
    allowed_years |= {y for y, _ in allowed_month_years}
    full, month_years, years = _dates(text)
    if full - allowed_full or month_years - allowed_month_years or years - allowed_years:
        return {"date_not_in_evidence"}
    return set()


def _claims(text: str, pattern):
    for planet in _PLANET.finditer(text):
        claim = pattern.match(text, planet.end())
        if not claim:
            continue
        gap = claim.group(1) or ""
        if _NEGATION.search(gap) or _PLANET.search(gap) or _NEGATION.match(text[claim.end():claim.end() + 8].strip()):
            continue
        yield _ALIAS[planet.group(1).casefold()], claim


def _placement_codes(text: str, evidence: str) -> set[str]:
    allowed, lagnas = _placements(evidence)
    codes = set()
    for planet, claim in _claims(text, _HOUSE_CLAIM):
        house = int(claim.group(2) or claim.group(3))
        if house not in {h for h, _ in allowed.get(planet, ())}:
            codes.add("placement_not_in_evidence")
    for planet, claim in _claims(text, _SIGN_CLAIM):
        raw = claim.group(2) or claim.group(3)
        sign = HI_SIGNS.get(raw, raw.title())
        if sign not in {s for _, s in allowed.get(planet, ())}:
            codes.add("placement_not_in_evidence")
    for claim in _LAGNA_CLAIM.finditer(text):
        raw = claim.group(1) or claim.group(2)
        if HI_SIGNS.get(raw, raw.title()) not in lagnas:
            codes.add("lagna_not_in_evidence")
    return codes


def _named_term_codes(text: str, evidence: str) -> set[str]:
    codes = set()
    plain_evidence = _normalized(evidence)
    for m in _DOSHA_TERMS.finditer(text):
        term = _normalized(m.group(0))
        term = _DOSHA_CANON.get(term, term)
        if term not in plain_evidence:
            codes.add("dosha_not_in_evidence")
    for m in _YOGA.finditer(text):
        if m.lastgroup not in plain_evidence:
            codes.add("yoga_not_in_evidence")
    return codes


def _dual_codes(text: str, lang: str, evidence: str) -> tuple[set[str], set[str]]:
    """(hard, warnings) for two-person Ashtakoot reports."""
    codes, warnings = set(), set()
    role = re.search(r"Groom role: (Primary person|Partner); bride role: (Primary person|Partner)", evidence)
    if role:
        buyer = "groom" if role.group(1) == "Primary person" else "bride"
        other = "bride" if buyer == "groom" else "groom"
        w = _ROLE_WORDS[lang]
        if lang == "en":
            wrong = (rf"\byou(?:'re|\s+are)\s+(?:the\s+)?{w[other]}\b", rf"\bas\s+the\s+{w[other]},\s+your?\b",
                     rf"\byou,\s+as\s+the\s+{w[other]}\b", rf"\byour\s+role\s+as\s+(?:the\s+)?{w[other]}\b",
                     rf"\byou\s+\((?:the\s+)?{w[other]}\)", rf"\b(?:the\s+)?{w[other]}\s+\(you\)",
                     rf"\byour\s+partner(?:'s)?\s+(?:is|as)\s+(?:the\s+)?{w[buyer]}\b",
                     rf"\byour\s+partner,\s+the\s+{w[buyer]}\b", rf"\b(?:the\s+)?{w[buyer]}\s+\(your\s+partner\)")
        else:
            partner = r"(?:आपके|आपकी)\s+(?:साथी|पार्टनर|partner|Partner)"
            wrong = (rf"आप\s+(?:ही\s+)?{w[other]}\s+(?:हैं|है)", rf"{w[other]}\s+के\s+रूप\s+में\s+आप",
                     rf"आप\s+{w[other]}\s+के\s+रूप\s+में", rf"आप\s+\({w[other]}\)", rf"{w[other]}\s+\(आप\)",
                     rf"{partner}\s+(?:ही\s+)?{w[buyer]}\s+(?:हैं|है)", rf"{w[buyer]}\s+\({partner}\)")
        if any(re.search(p, text, re.I) for p in wrong):
            codes.add("role_contradiction")
    total = re.search(r'"total_score": ([\d.]+)', evidence)
    claims = [float(m.group(1) or m.group(2)) for m in _TOTAL_CLAIM.finditer(text)]
    if claims and not total:
        warnings.add("total_score_not_supplied")  # no supplied number to contradict
    elif total and any(abs(c - float(total.group(1))) > 1e-9 for c in claims):
        codes.add("score_contradiction")
    if _BAD_DENOMINATOR.search(text):
        codes.add("score_contradiction")  # the frozen engine's total is always out of 36
    return codes, warnings


# ---------------------------------------------------------------- entry point ----------------------------------------

def _customer_text(output: dict[str, Any]) -> str:
    """Every customer-visible string except the hero label (supplied verbatim by the prompt)."""
    hero = output.get("hero") or {}
    parts = [hero.get("value"), hero.get("interpretation"), *(hero.get("evidence") or []),
             *(output.get("action_items") or []), output.get("report")]
    return "\n".join(p for p in parts if isinstance(p, str))


def _hard_codes(spec, lang: str, evidence: str, text: str) -> tuple[set[str], set[str]]:
    if spec.person_mode != "dual":
        return set(), set()
    return _dual_codes(text, lang, evidence)


def _warning_codes(spec, lang: str, evidence: str, text: str, report: str) -> set[str]:
    codes = set()
    share = _devanagari_share(text)
    if (lang == "hi" and share < HI_MIN_DEVANAGARI) or (lang == "en" and share > EN_MAX_DEVANAGARI):
        codes.add("language_share")
    codes |= _section_codes(spec, lang, report)
    codes |= _date_codes(text, evidence)
    codes |= _placement_codes(text, evidence)
    codes |= _named_term_codes(text, evidence)
    return codes


def validate_focused_output(question_key: str, language: str, prompt: str, output: dict[str, Any]) -> tuple[str, ...]:
    """Raise FocusedOutputValidationError only for a proven contradiction (HARD_CODES); otherwise return the sorted
    warning codes, which never block delivery. A failure inside a check is never blamed on the report: it becomes the
    warning "check_error" and the report is delivered."""
    spec = get_prompt_spec(question_key)
    lang = language_key(language)
    evidence = _evidence_text(prompt)
    report = output.get("report") or ""
    text = _customer_text(output).translate(_DEVANAGARI_DIGITS)
    warnings = set()
    try:
        hard, dual_warnings = _hard_codes(spec, lang, evidence, text)
        warnings |= dual_warnings
    except Exception:
        hard = set()
        warnings.add("check_error")
    try:
        warnings |= _warning_codes(spec, lang, evidence, text, report)
    except Exception:
        warnings.add("check_error")
    if hard:
        raise FocusedOutputValidationError(hard)
    return tuple(sorted(warnings))


__all__ = ["FocusedOutputValidationError", "HARD_CODES", "WARNING_CODES", "validate_focused_output"]
