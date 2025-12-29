# services/love/love_report_compiler.py
# Jyotishasha — Love Report Compiler (LOCKED PATH)
#
# What this file does:
# - Compiles FINAL Love → Marriage Life Report JSON (₹399/₹299)
# - Generates koota-wise short notes (8/8), overall verdict (Low/Medium/High)
# - Generates love→marriage flow, love vs arranged probability, strengths/risks/remedies
# - Provides 2 extra tools (non-repetitive) via compile_tool()
# - Enforces rule: DO NOT mention empty houses (only use occupied houses if needed)
# - Adds frontend-ready disclaimers (DOB-only vs full details)
#
# NOTE:
# - This file is intentionally conservative: it uses safe signals from payload.
# - You can later plug stronger astrology rules without changing the output structure.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


REPORT_KEY = "love_marriage_life"
REPORT_VERSION = "1.1"

# Tool IDs (LOCKED)
TOOL_MARRIAGE_TIMING = "marriage-timing-window"
TOOL_REL_STABILITY = "relationship-stability-check"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_get(d: Dict[str, Any], path: List[str], default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _non_empty_str(x: Any) -> bool:
    return isinstance(x, str) and x.strip() != ""


def _ensure_lang(lang: str) -> str:
    lang = (lang or "en").lower().strip()
    return "hi" if lang == "hi" else "en"


def _title(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------- Houses helpers (STRICT RULE: don't mention empty houses) ----------

def extract_house_planets(kundali: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Reads house->planets mapping from kundali payload, if present.
    Returns: {house_number: [planet_objects]}
    """
    hp = kundali.get("house_planets")
    if isinstance(hp, dict):
        out: Dict[int, List[Dict[str, Any]]] = {}
        for k, v in hp.items():
            try:
                hn = int(k)
            except Exception:
                continue
            if isinstance(v, list) and v:
                out[hn] = [p for p in v if isinstance(p, dict)]
        return out

    houses = kundali.get("houses")
    if isinstance(houses, list):
        out: Dict[int, List[Dict[str, Any]]] = {}
        for h in houses:
            if not isinstance(h, dict):
                continue
            hn = h.get("house") or h.get("number")
            try:
                hn = int(hn)
            except Exception:
                continue
            planets = h.get("planets")
            if isinstance(planets, list) and planets:
                out[hn] = [p for p in planets if isinstance(p, dict)]
        return out

    d1_houses = _safe_get(kundali, ["charts", "D1", "houses"], default=None)
    if isinstance(d1_houses, list):
        out: Dict[int, List[Dict[str, Any]]] = {}
        for h in d1_houses:
            if not isinstance(h, dict):
                continue
            hn = h.get("house") or h.get("number")
            try:
                hn = int(hn)
            except Exception:
                continue
            planets = h.get("planets")
            if isinstance(planets, list) and planets:
                out[hn] = [p for p in planets if isinstance(p, dict)]
        return out

    return {}


def only_nonempty_houses(house_planets: Dict[int, List[Dict[str, Any]]]) -> Dict[int, List[Dict[str, Any]]]:
    """Enforces: empty houses must not appear or be referenced."""
    return {h: ps for h, ps in house_planets.items() if isinstance(ps, list) and len(ps) > 0}


# ---------- Section model ----------

@dataclass
class Section:
    id: str
    title: str
    summary: str
    bullets: List[str]
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "bullets": self.bullets,
            "data": self.data,
        }


# ---------- Compiler ----------

class LoveReportCompiler:
    def compile_report(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full paid report compile (₹399 / ₹299 offer)
        """
        lang = _ensure_lang(payload.get("language", "en"))

        client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
        kundali = payload.get("kundali") if isinstance(payload.get("kundali"), dict) else {}
        ashtakoot = payload.get("ashtakoot") if isinstance(payload.get("ashtakoot"), dict) else {}
        dasha = payload.get("dasha") if isinstance(payload.get("dasha"), dict) else {}
        transits = payload.get("transits") if isinstance(payload.get("transits"), dict) else {}

        house_planets = only_nonempty_houses(extract_house_planets(kundali))

        disclaimers = self.build_disclaimers(lang, client)
        signals = self.build_signals(lang, kundali, ashtakoot, dasha, transits, house_planets)

        koota_notes = self.build_koota_notes(lang, ashtakoot)
        verdict = self.build_verdict(lang, ashtakoot, koota_notes)

        # Fixed sections (LOCKED order)
        sections: List[Section] = [
            self.section_ashtakoot_summary(lang, ashtakoot, verdict),
            self.section_koota_wise_notes(lang, koota_notes),
            self.section_love_to_marriage_flow(lang, signals),
            self.section_love_vs_arranged(lang, signals),
            self.section_strengths_risks(lang, signals),
            self.section_remedies(lang, signals),
            self.section_disclaimers(lang, disclaimers),
        ]

        return {
            "type": "report",
            "report_key": REPORT_KEY,
            "version": REPORT_VERSION,
            "generated_at": _utc_iso(),
            "client": client,
            "verdict": verdict,
            "ashtakoot": {
                "total_score": ashtakoot.get("total_score"),
                "max_score": ashtakoot.get("max_score", 36),
                "kootas": ashtakoot.get("kootas", {}) if isinstance(ashtakoot.get("kootas"), dict) else {},
            },
            "sections": [s.to_dict() for s in sections],
            "signals": signals,
            "disclaimers": disclaimers,
            # rule evidence (safe for debug/UI)
            "meta": {"houses_with_planets": sorted(list(house_planets.keys()))},
        }

    def compile_tool(self, tool_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Two additional tools (non-repetitive):
        1) marriage-timing-window
        2) relationship-stability-check
        """
        lang = _ensure_lang(payload.get("language", "en"))

        client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
        kundali = payload.get("kundali") if isinstance(payload.get("kundali"), dict) else {}
        ashtakoot = payload.get("ashtakoot") if isinstance(payload.get("ashtakoot"), dict) else {}
        dasha = payload.get("dasha") if isinstance(payload.get("dasha"), dict) else {}
        transits = payload.get("transits") if isinstance(payload.get("transits"), dict) else {}

        house_planets = only_nonempty_houses(extract_house_planets(kundali))
        disclaimers = self.build_disclaimers(lang, client)
        signals = self.build_signals(lang, kundali, ashtakoot, dasha, transits, house_planets)

        if tool_id == TOOL_MARRIAGE_TIMING:
            out = self.tool_marriage_timing_window(lang, dasha, transits, signals, disclaimers)
        elif tool_id == TOOL_REL_STABILITY:
            out = self.tool_relationship_stability_check(lang, ashtakoot, signals, disclaimers)
        else:
            out = {
                "type": "tool",
                "tool_id": tool_id,
                "generated_at": _utc_iso(),
                "title": _title(lang, "Unknown Tool", "अज्ञात टूल"),
                "main_line": _title(lang, "Tool id not supported.", "यह टूल आईडी सपोर्ट नहीं है।"),
                "bullets": [],
                "disclaimers": disclaimers,
            }

        out["client"] = client
        out["meta"] = {"houses_with_planets": sorted(list(house_planets.keys()))}
        return out

    # ------------------------- Disclaimers (Frontend-ready) -------------------------

    def build_disclaimers(self, lang: str, client: Dict[str, Any]) -> List[Dict[str, Any]]:
        missing = []
        if not _non_empty_str(client.get("dob")):
            missing.append("dob")
        if not _non_empty_str(client.get("tob")):
            missing.append("tob")
        if not _non_empty_str(client.get("pob")):
            missing.append("pob")

        d: List[Dict[str, Any]] = []

        # Accuracy disclaimer (LOCKED intent)
        if missing:
            d.append({
                "key": "dob_only_accuracy",
                "severity": "info",
                "text": _title(
                    lang,
                    "For more Vedic-astrology-accurate results, Time and Place of Birth are required.",
                    "अधिक वैदिक-ज्योतिष आधारित सटीक परिणाम के लिए जन्म समय और जन्म स्थान आवश्यक हैं।",
                )
            })
        else:
            d.append({
                "key": "full_details_accuracy",
                "severity": "info",
                "text": _title(
                    lang,
                    "Birth details are complete, so the report uses deeper Vedic timing and transit logic.",
                    "जन्म विवरण पूर्ण हैं, इसलिए रिपोर्ट में वैदिक टाइमिंग और गोचर लॉजिक अधिक सटीक रूप से लागू होता है।",
                )
            })

        # Guidance disclaimer
        d.append({
            "key": "guidance_not_guarantee",
            "severity": "note",
            "text": _title(
                lang,
                "This is guidance based on astrology indicators; outcomes depend on choices and circumstances.",
                "यह ज्योतिषीय संकेतों पर आधारित मार्गदर्शन है; वास्तविक परिणाम निर्णय और परिस्थितियों पर निर्भर करते हैं।",
            )
        })

        # Data disclaimer
        if missing:
            d.append({
                "key": "missing_inputs",
                "severity": "note",
                "text": _title(
                    lang,
                    f"Missing inputs: {', '.join(missing)}",
                    f"मिसिंग इनपुट: {', '.join(missing)}",
                )
            })

        return d

    # ------------------------- Koota-wise notes (8/8) -------------------------

    def build_koota_notes(self, lang: str, ashtakoot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Produces short, koota-specific notes (8/8) based strictly on
        score / status / dosha / cancelled. EN + HI locked templates.
        """
        kootas = ashtakoot.get("kootas")
        if not isinstance(kootas, dict):
            return []

        ordered_keys = ["varna", "vashya", "tara", "yoni", "graha_maitri", "gana", "bhakoot", "nadi"]
        notes: List[Dict[str, Any]] = []

        # Koota-wise templates (LOCKED)
        T = {
            "varna": {
                "strong": (
                    "Varna compatibility supports mutual respect, values, and social understanding.",
                    "वर्ण मिलान आपसी सम्मान, मूल्यों और सामाजिक समझ को मजबूत करता है।",
                ),
                "weak": (
                    "Varna mismatch may create differences in expectations or lifestyle outlook.",
                    "वर्ण असंगति अपेक्षाओं या जीवन-दृष्टि में अंतर ला सकती है।",
                ),
            },
            "vashya": {
                "strong": (
                    "Vashya harmony indicates ease in adjustment and mutual influence.",
                    "वश्य सामंजस्य आपसी तालमेल और समायोजन को आसान बनाता है।",
                ),
                "weak": (
                    "Weak vashya may cause control issues or difficulty in mutual adjustment.",
                    "कमजोर वश्य नियंत्रण या तालमेल की समस्या पैदा कर सकता है।",
                ),
            },
            "tara": {
                "strong": (
                    "Tara koota support shows favorable destiny flow and mutual growth.",
                    "तारा (नक्षत्र) कूट अनुकूल भाग्य प्रवाह और आपसी प्रगति दर्शाता है।",
                ),
                "weak": (
                    "Tara weakness may bring ups and downs affecting confidence or timing.",
                    "तारा (नक्षत्र) कमजोरी से आत्मविश्वास या समय से जुड़े उतार-चढ़ाव आ सकते हैं।",
                ),
            },
            "yoni": {
                "strong": (
                    "Yoni harmony supports emotional intimacy and physical compatibility.",
                    "योनि सामंजस्य भावनात्मक निकटता और शारीरिक अनुकूलता को मजबूत करता है।",
                ),
                "partial": (
                    "Partial yoni match shows attraction but requires emotional sensitivity.",
                    "आंशिक योनि मिलान आकर्षण दिखाता है, पर भावनात्मक समझ जरूरी है।",
                ),
                "dosha": (
                    "Yoni dosha may cause emotional mismatch or intimacy-related conflicts.",
                    "योनि दोष भावनात्मक असंगति या निकटता से जुड़े मतभेद ला सकता है।",
                ),
            },
            "graha_maitri": {
                "strong": (
                    "Graha maitri strength indicates strong mental bonding and understanding.",
                    "ग्रह मैत्री मजबूती मानसिक सामंजस्य और समझ को दर्शाती है।",
                ),
                "partial": (
                    "Partial graha maitri shows workable understanding with communication.",
                    "आंशिक ग्रह मैत्री संवाद के साथ संभालने योग्य समझ दर्शाती है।",
                ),
                "weak": (
                    "Weak graha maitri may lead to mindset clashes or communication gaps.",
                    "कमजोर ग्रह मैत्री सोच या संवाद में टकराव ला सकती है।",
                ),
            },
            "gana": {
                "strong": (
                    "Gana compatibility supports similar temperament and emotional rhythm.",
                    "गण मिलान स्वभाव और भावनात्मक तालमेल को समर्थन देता है।",
                ),
                "partial": (
                    "Partial gana match suggests differences manageable with maturity.",
                    "आंशिक गण मिलान अंतर दिखाता है, पर परिपक्वता से संभल सकता है।",
                ),
                "dosha": (
                    "Gana dosha may cause temperament clashes and reaction-based conflicts.",
                    "गण दोष स्वभाविक टकराव और प्रतिक्रिया-जनित विवाद ला सकता है।",
                ),
            },
            "bhakoot": {
                "strong": (
                    "Bhakoot harmony supports emotional balance and financial stability.",
                    "भकूट सामंजस्य भावनात्मक संतुलन और आर्थिक स्थिरता को बढ़ाता है।",
                ),
                "dosha": (
                    "Bhakoot dosha indicates emotional or financial imbalance patterns.",
                    "भकूट दोष भावनात्मक या आर्थिक असंतुलन के संकेत देता है।",
                ),
                "cancelled": (
                    "Bhakoot dosha is present, but cancellation reduces its negative impact.",
                    "भकूट दोष मौजूद है, लेकिन निरसन से उसका प्रभाव काफी कम हो जाता है।",
                ),
            },
            "nadi": {
                "strong": (
                    "Nadi compatibility supports health balance and family continuity.",
                    "नाड़ी मिलान स्वास्थ्य संतुलन और वंश निरंतरता को समर्थन देता है।",
                ),
                "dosha": (
                    "Nadi dosha may indicate health or progeny-related sensitivities.",
                    "नाड़ी दोष स्वास्थ्य या संतान से जुड़ी संवेदनशीलता दिखा सकता है।",
                ),
                "cancelled": (
                    "Nadi dosha exists, but cancellation minimizes health-related concerns.",
                    "नाड़ी दोष है, पर निरसन से स्वास्थ्य संबंधी चिंता कम हो जाती है।",
                ),
            },
        }

        for key in ordered_keys:
            v = kootas.get(key)
            if not isinstance(v, dict):
                continue

            sc = v.get("score")
            mx = v.get("max")
            status = (v.get("status") or "").lower().strip()
            dosha = v.get("dosha")
            cancelled = bool(v.get("cancelled", False))

            # Decide strength bucket
            pct = None
            if isinstance(sc, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
                pct = sc / mx

            # Pick line (FINAL – NO KeyError, NO ambiguity)
            if cancelled and key in T and "cancelled" in T[key]:
                en, hi = T[key]["cancelled"]
                line = _title(lang, en, hi)

            elif status in ("dosha", "fail"):
                # dosha-specific
                if key in T and "dosha" in T[key]:
                    en, hi = T[key]["dosha"]
                    line = _title(lang, en, hi)
                else:
                    line = _title(
                        lang,
                        f"Dosha detected ({dosha}). This may create friction unless balanced.",
                        f"दोष पाया गया ({dosha})। संतुलन न हो तो मतभेद बढ़ सकते हैं।",
                    )

            elif status == "partial" or (pct is not None and pct < 0.8):
                if key in T and "partial" in T[key]:
                    en, hi = T[key]["partial"]
                    line = _title(lang, en, hi)
                elif key in T and "weak" in T[key]:
                    en, hi = T[key]["weak"]
                    line = _title(lang, en, hi)
                elif key in T and "dosha" in T[key]:
                    en, hi = T[key]["dosha"]
                    line = _title(lang, en, hi)
                else:
                    line = _title(
                        lang,
                        "This koota shows mixed results and needs conscious handling.",
                        "यह कूट मिश्रित परिणाम दिखाता है और सचेत समझ की आवश्यकता है।",
                    )

            else:
                if key in T and "strong" in T[key]:
                    en, hi = T[key]["strong"]
                    line = _title(lang, en, hi)
                else:
                    line = _title(
                        lang,
                        "This koota is supportive overall.",
                        "यह कूट समग्र रूप से सहायक है।",
                    )

            notes.append({
                "key": key,
                "score": sc,
                "max": mx,
                "status": status or None,
                "dosha": dosha,
                "cancelled": cancelled,
                "note": line,
            })
            
        return notes

    # ------------------------- Verdict (Low/Medium/High) -------------------------

    def build_verdict(self, lang: str, ashtakoot: Dict[str, Any], koota_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = ashtakoot.get("total_score")
        max_score = ashtakoot.get("max_score", 36)

        # Hard-dosha keys weight (can be tuned later)
        hard_keys = {"nadi": 1.2, "bhakoot": 1.1, "gana": 1.0}
        hard_pressure = 0.0
        cancellations = 0

        for n in koota_notes:
            if not isinstance(n, dict):
                continue
            key = n.get("key")
            if key not in hard_keys:
                continue
            if n.get("cancelled") is True:
                cancellations += 1
                continue
            st = (n.get("status") or "").lower()
            if st in ("dosha", "fail"):
                hard_pressure += hard_keys.get(key, 1.0)

        # Score bands (simple, stable)
        if isinstance(total, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
            pct = (float(total) / float(max_score)) * 100.0
        else:
            pct = None

        level = "Medium"
        if pct is None:
            level = "Medium"
        else:
            if pct >= 70 and hard_pressure <= 0.5:
                level = "High"
            elif pct < 50 or hard_pressure >= 1.5:
                level = "Low"
            else:
                level = "Medium"

        reason_line = ""
        if level == "High":
            reason_line = _title(
                lang,
                "Overall compatibility looks strong with supportive koota pattern and low dosha pressure.",
                "कुल मिलान मजबूत दिखता है; कूट सपोर्टिव हैं और दोष दबाव कम है।",
            )
        elif level == "Low":
            reason_line = _title(
                lang,
                "Compatibility stress is notable due to low score and/or strong dosha pressure; careful handling is required.",
                "कम स्कोर और/या मजबूत दोष दबाव के कारण तनाव की संभावना अधिक है; संभलकर आगे बढ़ना चाहिए।",
            )
        else:
            reason_line = _title(
                lang,
                "Compatibility is workable; results improve with maturity, communication, and structured decision-making.",
                "मिलान संभालने योग्य है; परिपक्वता, संवाद और स्पष्ट निर्णय प्रक्रिया से परिणाम बेहतर होंगे।",
            )

        return {
            "level": level,                      # Low | Medium | High
            "score": total,
            "max_score": max_score,
            "score_pct": pct,
            "hard_dosha_pressure": round(hard_pressure, 2),
            "cancellations": cancellations,
            "reason_line": reason_line,
        }
    


    # ------------------------- Signals (safe + controlled) -------------------------

    def build_signals(
        self,
        lang: str,
        kundali: Dict[str, Any],
        ashtakoot: Dict[str, Any],
        dasha: Dict[str, Any],
        transits: Dict[str, Any],
        house_planets: Dict[int, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        signals: Dict[str, Any] = {
            "love_vs_arranged": {"love_pct": None, "arranged_pct": None, "reasons": []},
            "love_to_marriage_flow": {"status": "neutral", "line": "", "bullets": []},
            "strengths": [],
            "risks": [],
            "remedies": [],
            "stability_score": None,  # 0-100
            "timing": {"main_line": "", "bullets": []},
            "meta": {"houses_with_planets": sorted(list(house_planets.keys()))},
        }

        # 1) Timing snapshot (no assumptions)
        cur_md = _safe_get(dasha, ["current", "mahadasha"], default=None)
        cur_ad = _safe_get(dasha, ["current", "antardasha"], default=None)
        t_summary = transits.get("summary") if isinstance(transits.get("summary"), str) else None

        timing_parts = []
        if _non_empty_str(cur_md):
            timing_parts.append(_title(lang, f"Mahadasha: {cur_md}", f"महादशा: {cur_md}"))
        if _non_empty_str(cur_ad):
            timing_parts.append(_title(lang, f"Antardasha: {cur_ad}", f"अंतर्दशा: {cur_ad}"))
        if _non_empty_str(t_summary):
            timing_parts.append(_title(lang, f"Transit: {t_summary}", f"गोचर: {t_summary}"))

        signals["timing"]["main_line"] = " | ".join(timing_parts) if timing_parts else _title(
            lang,
            "Timing snapshot not available; add dasha/transit payload for sharper windows.",
            "टाइमिंग स्नैपशॉट उपलब्ध नहीं; बेहतर विंडो के लिए दशा/गोचर डेटा जोड़ें।",
        )

        # 2) Love vs Arranged probability (controlled, based on allowed indicators)
        # STRICT: we do not mention empty houses; we only check occupancy presence.
        base_love = 50.0
        base_arr = 50.0

        reasons: List[str] = []

        if 5 in house_planets:
            base_love += 15
            base_arr -= 15
            reasons.append(_title(lang, "Romance activation seen (occupied 5th house).", "रोमांस संकेत मजबूत (5वां भाव सक्रिय)।"))
        if 7 in house_planets:
            base_arr += 10
            base_love -= 10
            reasons.append(_title(lang, "Partnership focus present (occupied 7th house).", "साझेदारी संकेत (7वां भाव सक्रिय)।"))

        total = ashtakoot.get("total_score")
        if isinstance(total, (int, float)):
            if total >= 24:
                base_love += 5
                base_arr += 5
                reasons.append(_title(lang, "Overall compatibility support improves relationship stability.", "कुल मिलान सपोर्ट से स्थिरता बढ़ती है।"))
            elif total < 18:
                base_love -= 5
                base_arr -= 5
                reasons.append(_title(lang, "Lower compatibility score suggests more effort is required.", "कम स्कोर बताता है कि अधिक प्रयास जरूरी होगा।"))

        base_love = _clamp(base_love, 0, 100)
        base_arr = _clamp(base_arr, 0, 100)
        s = base_love + base_arr
        if s > 0:
            base_love = (base_love / s) * 100.0
            base_arr = (base_arr / s) * 100.0

        # Only publish if we have at least 1 reason or total score exists
        if reasons or isinstance(total, (int, float)):
            signals["love_vs_arranged"]["love_pct"] = round(base_love, 0)
            signals["love_vs_arranged"]["arranged_pct"] = round(base_arr, 0)
            signals["love_vs_arranged"]["reasons"] = reasons[:3]

        # 3) Love → Marriage Flow (short, non-repetitive, frontend-ready)
        flow_line = _title(
            lang,
            "Your relationship path improves when decisions are structured and timing is respected.",
            "जब निर्णय व्यवस्थित हों और सही समय का सम्मान हो, तब आपका रिलेशनशिप पथ बेहतर होता है।",
        )
        flow_bullets = [
            _title(lang, "Keep clarity: intentions → commitment → family alignment.", "स्पष्टता रखें: इरादा → कमिटमेंट → परिवार की सहमति।"),
            _title(lang, "Avoid rushed commitments during emotional spikes.", "भावनात्मक उतार-चढ़ाव में जल्दबाज़ कमिटमेंट न करें।"),
            _title(lang, "Use timing windows from dasha/transit when available.", "जहाँ संभव हो, दशा/गोचर की टाइमिंग विंडो का उपयोग करें।"),
        ]
        signals["love_to_marriage_flow"] = {"status": "guidance", "line": flow_line, "bullets": flow_bullets}

        # 4) Stability score (safe)
        stability = 50.0
        if isinstance(total, (int, float)):
            stability += (float(total) - 18.0) * 2.0
        if 7 in house_planets:
            stability += 5.0
        stability = _clamp(stability, 0, 100)
        signals["stability_score"] = round(stability, 0) if isinstance(total, (int, float)) or (7 in house_planets) else None

        # 5) Strengths / Risks / Remedies (short, non-crashy)
        strengths = []
        risks = []
        remedies = []

        if isinstance(total, (int, float)) and total >= 24:
            strengths.append(_title(lang, "Compatibility base is supportive; easier conflict resolution.", "कम्पैटिबिलिटी सपोर्टिव; विवाद सुलझाना आसान।"))
        elif isinstance(total, (int, float)) and total < 18:
            risks.append(_title(lang, "Compatibility pressure can trigger misunderstandings.", "कम्पैटिबिलिटी दबाव से गलतफहमियाँ बढ़ सकती हैं।"))

        if 5 in house_planets:
            strengths.append(_title(lang, "Emotional attraction and romance are naturally activated.", "भावनात्मक आकर्षण और रोमांस स्वाभाविक रूप से सक्रिय।"))
        if 7 in house_planets:
            strengths.append(_title(lang, "Partnership focus supports long-term bonding.", "साझेदारी फोकस से दीर्घकालिक बंधन मजबूत।"))

        # Generic but useful remedies
        remedies.extend([
            _title(lang, "Weekly communication check-in (fixed day/time).", "साप्ताहिक संवाद (फिक्स दिन/समय)।"),
            _title(lang, "Boundary rule: keep decisions between partners/family minimal and clear.", "सीमा नियम: निर्णय पार्टनर/परिवार के बीच स्पष्ट रखें।"),
            _title(lang, "If conflict repeats, agree on one resolution protocol.", "दोहराव वाले विवाद पर एक समाधान नियम तय करें।"),
        ])

        # Ensure minimum content
        if not strengths:
            strengths.append(_title(lang, "Potential is workable with consistent effort and clarity.", "लगातार प्रयास और स्पष्टता से स्थिति संभाली जा सकती है।"))
        if not risks:
            risks.append(_title(lang, "Main risk is inconsistency or mixed expectations.", "मुख्य जोखिम असंगति या अपेक्षाओं का मिश्रण है।"))

        signals["strengths"] = strengths[:5]
        signals["risks"] = risks[:5]
        signals["remedies"] = remedies[:6]

        return signals

    # ------------------------- Sections (Report) -------------------------

    def section_ashtakoot_summary(self, lang: str, ashtakoot: Dict[str, Any], verdict: Dict[str, Any]) -> Section:
        total = ashtakoot.get("total_score")
        mx = ashtakoot.get("max_score", 36)

        title = _title(lang, "Ashtakoot Score & Verdict", "अष्टकूट स्कोर और निर्णय")
        score_line = (
            _title(lang, f"Score: {total}/{mx}", f"स्कोर: {total}/{mx}")
            if isinstance(total, (int, float)) else
            _title(lang, "Ashtakoot score not available in payload.", "पेलोड में अष्टकूट स्कोर उपलब्ध नहीं है।")
        )

        summary = f"{score_line} | {verdict.get('reason_line','')}".strip()

        bullets = [
            _title(lang, f"Verdict: {verdict.get('level','Medium')}", f"निर्णय: {verdict.get('level','Medium')}"),
        ]
        if verdict.get("hard_dosha_pressure", 0) > 0:
            bullets.append(_title(lang, "Dosha pressure is present; apply remedies and structured approach.", "दोष दबाव मौजूद है; उपाय और संरचित दृष्टि अपनाएँ।"))

        data = {"total_score": total, "max_score": mx, "verdict": verdict}
        return Section("ashtakoot_top", title, summary, bullets, data)

    def section_koota_wise_notes(self, lang: str, koota_notes: List[Dict[str, Any]]) -> Section:
        title = _title(lang, "Koota-wise Notes (8)", "कूट-वार नोट्स (8)")
        summary = _title(
            lang,
            "Short notes are derived strictly from each koota’s score/status/dosha/cancellation flags.",
            "संक्षिप्त नोट्स हर कूट के स्कोर/स्टेटस/दोष/निरसन फ्लैग पर आधारित हैं।",
        )

        bullets = []
        for n in koota_notes:
            k = (n.get("key") or "").replace("_", " ").title()
            sc = n.get("score")
            mx = n.get("max")
            note = n.get("note") or ""
            if sc is not None and mx is not None:
                bullets.append(f"{k} ({sc}/{mx}): {note}")
            else:
                bullets.append(f"{k}: {note}")

        data = {"koota_notes": koota_notes}
        return Section("koota_notes", title, summary, bullets[:12], data)

    def section_love_to_marriage_flow(self, lang: str, signals: Dict[str, Any]) -> Section:
        title = _title(lang, "Love → Marriage Flow", "लव → मैरिज फ्लो")
        flow = signals.get("love_to_marriage_flow", {})
        summary = str(flow.get("line") or "")
        bullets = [str(x) for x in (flow.get("bullets") or [])][:6]
        return Section("love_to_marriage_flow", title, summary, bullets, {"flow": flow})

    def section_love_vs_arranged(self, lang: str, signals: Dict[str, Any]) -> Section:
        title = _title(lang, "Love vs Arranged Probability", "लव बनाम अरेंज्ड संभावना")
        lva = signals.get("love_vs_arranged", {})
        love = lva.get("love_pct")
        arr = lva.get("arranged_pct")

        if isinstance(love, (int, float)) and isinstance(arr, (int, float)):
            summary = _title(
                lang,
                f"Estimated split: Love {love:.0f}% vs Arranged {arr:.0f}%.",
                f"अनुमानित विभाजन: लव {love:.0f}% बनाम अरेंज्ड {arr:.0f}%。",
            )
        else:
            summary = _title(
                lang,
                "Percent split is not computed from current inputs; see reasons below.",
                "वर्तमान इनपुट से प्रतिशत नहीं निकला; नीचे कारण देखें।",
            )

        bullets = [str(x) for x in (lva.get("reasons") or [])][:3]
        return Section("love_vs_arranged", title, summary, bullets, {"love_vs_arranged": lva})

    def section_strengths_risks(self, lang: str, signals: Dict[str, Any]) -> Section:
        title = _title(lang, "Strengths & Risks", "ताकत और जोखिम")
        strengths = signals.get("strengths") or []
        risks = signals.get("risks") or []

        summary = _title(
            lang,
            "Key strengths to build on and risks to manage are listed below.",
            "नीचे मुख्य ताकतें और संभालने योग्य जोखिम दिए गए हैं।",
        )

        bullets = []
        for s in strengths[:4]:
            bullets.append(_title(lang, f"Strength: {s}", f"ताकत: {s}"))
        for r in risks[:4]:
            bullets.append(_title(lang, f"Risk: {r}", f"जोखिम: {r}"))

        data = {"strengths": strengths, "risks": risks, "stability_score": signals.get("stability_score")}
        return Section("strengths_risks", title, summary, bullets[:8], data)

    def section_remedies(self, lang: str, signals: Dict[str, Any]) -> Section:
        title = _title(lang, "Remedies & Guidance", "उपाय और मार्गदर्शन")
        remedies = signals.get("remedies") or []
        summary = _title(
            lang,
            "Practical-first remedies; can be extended with deeper Vedic remedies when timing logic is available.",
            "व्यावहारिक उपाय; टाइमिंग लॉजिक उपलब्ध होने पर इन्हें वैदिक उपायों से और मजबूत किया जा सकता है।",
        )
        bullets = [str(x) for x in remedies][:10]
        return Section("remedies", title, summary, bullets, {"remedies": remedies})

    def section_disclaimers(self, lang: str, disclaimers: List[Dict[str, Any]]) -> Section:
        title = _title(lang, "Notes & Disclaimers", "नोट्स और डिस्क्लेमर")
        summary = _title(
            lang,
            "These are frontend-ready disclaimers to keep output safe and clear.",
            "ये फ्रंटएंड-रेडी डिस्क्लेमर हैं ताकि आउटपुट सुरक्षित और स्पष्ट रहे।",
        )
        bullets = [str(d.get("text", "")) for d in disclaimers][:6]
        return Section("disclaimers", title, summary, bullets, {"disclaimers": disclaimers})

    # ------------------------- Tools -------------------------

    def tool_marriage_timing_window(
        self,
        lang: str,
        dasha: Dict[str, Any],
        transits: Dict[str, Any],
        signals: Dict[str, Any],
        disclaimers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        title = _title(lang, "Marriage Timing Window", "विवाह टाइमिंग विंडो")

        main = signals.get("timing", {}).get("main_line") or _title(
            lang,
            "Timing data not available; add dasha/transit payload to generate windows.",
            "टाइमिंग डेटा उपलब्ध नहीं; विंडो के लिए दशा/गोचर पेलोड जोड़ें।",
        )

        bullets: List[str] = []
        timeline = dasha.get("timeline")
        if isinstance(timeline, list) and timeline:
            for item in timeline[:5]:
                if not isinstance(item, dict):
                    continue
                label = item.get("label") or item.get("period")
                start = item.get("start")
                end = item.get("end")
                if label and start and end:
                    bullets.append(f"{label}: {start} → {end}")

        if not bullets:
            bullets = [
                _title(lang, "If you share TOB+POB, timing accuracy improves significantly.", "TOB+POB देने पर टाइमिंग सटीकता काफी बढ़ती है।"),
                _title(lang, "Use timing during stable commitment periods, not during conflicts.", "स्थिर कमिटमेंट पीरियड में निर्णय लें, विवाद के समय नहीं।"),
            ]

        return {
            "type": "tool",
            "tool_id": TOOL_MARRIAGE_TIMING,
            "generated_at": _utc_iso(),
            "title": title,
            "main_line": main,
            "bullets": bullets[:6],
            "disclaimers": disclaimers,
        }

    def tool_relationship_stability_check(
        self,
        lang: str,
        ashtakoot: Dict[str, Any],
        signals: Dict[str, Any],
        disclaimers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        title = _title(lang, "Relationship Stability Check", "रिलेशनशिप स्थिरता चेक")

        stability = signals.get("stability_score")
        if isinstance(stability, (int, float)):
            main = _title(
                lang,
                f"Stability score: {stability:.0f}/100 (higher is better).",
                f"स्थिरता स्कोर: {stability:.0f}/100 (जितना अधिक, उतना बेहतर)।",
            )
        else:
            main = _title(
                lang,
                "Stability score could not be computed from current inputs; see risks and fixes below.",
                "वर्तमान इनपुट से स्थिरता स्कोर नहीं निकला; नीचे जोखिम और सुधार देखें।",
            )

        risks = signals.get("risks") or []
        remedies = signals.get("remedies") or []

        bullets = []
        for r in risks[:3]:
            bullets.append(_title(lang, f"Risk: {r}", f"जोखिम: {r}"))
        for x in remedies[:3]:
            bullets.append(_title(lang, f"Fix: {x}", f"सुधार: {x}"))

        return {
            "type": "tool",
            "tool_id": TOOL_REL_STABILITY,
            "generated_at": _utc_iso(),
            "title": title,
            "main_line": main,
            "bullets": bullets[:6],
            "disclaimers": disclaimers,
        }


# ------------------------- Public convenience wrappers -------------------------

def compile_love_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Paid report compiler entrypoint."""
    return LoveReportCompiler().compile_report(payload)


def compile_love_tool(tool_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Tool compiler entrypoint."""
    return LoveReportCompiler().compile_tool(tool_id, payload)
