# ashtakoot_love.py
from __future__ import annotations
from typing import Dict, Any, Optional

# ============================================================
# SINGLE SOURCE OF TRUTH (NO DUPLICATES)
# ============================================================

# Moon Rashi → Lord (LOCKED)
RASHI_LORD = {
    "Aries": "Mars", "Scorpio": "Mars",
    "Taurus": "Venus", "Libra": "Venus",
    "Gemini": "Mercury", "Virgo": "Mercury",
    "Cancer": "Moon",
    "Leo": "Sun",
    "Sagittarius": "Jupiter", "Pisces": "Jupiter",
    "Capricorn": "Saturn", "Aquarius": "Saturn",
}

# Natural relationships (LOCKED)
FRIEND = {
    "Sun": {"Moon", "Mars", "Jupiter"},
    "Moon": {"Sun", "Mercury"},
    "Mars": {"Sun", "Moon", "Jupiter"},
    "Mercury": {"Sun", "Venus"},
    "Jupiter": {"Sun", "Moon", "Mars"},
    "Venus": {"Mercury", "Saturn"},
    "Saturn": {"Mercury", "Venus"},
}

ENEMY = {
    "Sun": {"Venus", "Saturn"},
    "Moon": set(),
    "Mars": {"Mercury"},
    "Mercury": {"Moon"},
    "Jupiter": {"Venus", "Mercury"},
    "Venus": {"Sun", "Moon"},
    "Saturn": {"Sun", "Moon"},
}

# ============================================================
# 1) VARNA KOOTA (MAX = 1) — LOCKED
# ============================================================

VARNA_ORDER = {"Brahmin": 4, "Kshatriya": 3, "Vaishya": 2, "Shudra": 1}

RASHI_TO_VARNA = {
    # Brahmin
    "Cancer": "Brahmin", "Scorpio": "Brahmin", "Pisces": "Brahmin",
    # Kshatriya
    "Aries": "Kshatriya", "Leo": "Kshatriya", "Sagittarius": "Kshatriya",
    # Vaishya
    "Taurus": "Vaishya", "Virgo": "Vaishya", "Capricorn": "Vaishya",
    # Shudra
    "Gemini": "Shudra", "Libra": "Shudra", "Aquarius": "Shudra",
}

def varna_koota(boy_moon: Dict, girl_moon: Dict) -> Dict:
    boy_rashi = boy_moon.get("rashi")
    girl_rashi = girl_moon.get("rashi")

    boy_varna = RASHI_TO_VARNA.get(boy_rashi) if boy_rashi else None
    girl_varna = RASHI_TO_VARNA.get(girl_rashi) if girl_rashi else None

    if not boy_varna or not girl_varna:
        return {"score": 0, "max": 1, "status": "invalid", "note": "Rashi not mapped to Varna"}

    score = 1 if VARNA_ORDER[boy_varna] >= VARNA_ORDER[girl_varna] else 0
    return {
        "boy_varna": boy_varna,
        "girl_varna": girl_varna,
        "score": score,
        "max": 1,
        "status": "pass" if score == 1 else "fail",
    }

# ============================================================
# 2) VASHYA KOOTA (MAX = 2) — LOCKED (0/1/1.5/2)
# ============================================================

RASHI_TO_VASHYA = {
    "Aries": "Chatushpada",
    "Taurus": "Chatushpada",
    "Gemini": "Nara",
    "Virgo": "Nara",
    "Libra": "Nara",
    "Aquarius": "Nara",
    "Cancer": "Jalchar",
    "Pisces": "Jalchar",
    "Leo": "Vanacara",
    "Scorpio": "Keeta",
}

def _resolve_sagittarius_capricorn_group(rashi: str, degree: float) -> str:
    # LOCKED RULE
    if rashi == "Sagittarius":
        return "Nara" if degree < 15 else "Chatushpada"
    if rashi == "Capricorn":
        return "Chatushpada" if degree < 15 else "Jalchar"
    raise ValueError("Invalid rashi")

VASHYA_SCORE_MATRIX = {
    "Chatushpada": {"Chatushpada": 2, "Nara": 1, "Jalchar": 1.5, "Vanacara": 0, "Keeta": 0},
    "Nara":        {"Chatushpada": 1, "Nara": 2, "Jalchar": 1.5, "Vanacara": 0, "Keeta": 0},
    "Jalchar":     {"Chatushpada": 1.5, "Nara": 1.5, "Jalchar": 2, "Vanacara": 0, "Keeta": 0},
    "Vanacara":    {"Chatushpada": 0, "Nara": 0, "Jalchar": 0, "Vanacara": 2, "Keeta": 0},
    "Keeta":       {"Chatushpada": 0, "Nara": 0, "Jalchar": 0, "Vanacara": 0, "Keeta": 2},
}

def vashya_koota(bride_moon: dict, groom_moon: dict) -> dict:
    def get_group(moon: Dict[str, Any]) -> Optional[str]:
        rashi = moon.get("rashi")
        degree = moon.get("degree")
        if not rashi:
            return None
        if rashi in ("Sagittarius", "Capricorn"):
            if degree is None:
                return None
            return _resolve_sagittarius_capricorn_group(rashi, float(degree))
        return RASHI_TO_VASHYA.get(rashi)

    bride_group = get_group(bride_moon)
    groom_group = get_group(groom_moon)

    if not bride_group or not groom_group:
        return {
            "bride_group": bride_group,
            "groom_group": groom_group,
            "score": 0,
            "max": 2,
            "status": "invalid",
            "note": "Vashya group could not be resolved",
        }

    score = VASHYA_SCORE_MATRIX[bride_group][groom_group]
    return {
        "bride_group": bride_group,
        "groom_group": groom_group,
        "score": score,
        "max": 2,
        "status": "pass" if score > 0 else "fail",
    }

# ============================================================
# 3) TARA KOOTA (MAX = 3) — LOCKED
# ============================================================

NAKSHATRAS_27 = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula",
    "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]
NAK_INDEX = {n: i for i, n in enumerate(NAKSHATRAS_27)}

def _tara_remainder(from_nak: str, to_nak: str) -> int:
    if from_nak not in NAK_INDEX or to_nak not in NAK_INDEX:
        raise ValueError("Invalid nakshatra")
    start = NAK_INDEX[from_nak]
    end = NAK_INDEX[to_nak]
    dist = (end - start) % 27
    count_inclusive = dist + 1
    rem = count_inclusive % 9
    return 9 if rem == 0 else rem

def tara_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    b = bride_moon.get("nakshatra")
    g = groom_moon.get("nakshatra")
    if not b or not g:
        return {"score": 0, "max": 3, "status": "invalid", "note": "Missing nakshatra"}
    try:
        rem_bg = _tara_remainder(b, g)
        rem_gb = _tara_remainder(g, b)
    except ValueError:
        return {"score": 0, "max": 3, "status": "invalid", "note": "Invalid nakshatra"}

    even_bg = (rem_bg % 2 == 0)
    even_gb = (rem_gb % 2 == 0)

    if even_bg and even_gb:
        score, status = 3, "excellent"
    elif (not even_bg) and (not even_gb):
        score, status = 0, "challenging"
    else:
        score, status = 1.5, "mixed"

    return {
        "bride_to_groom_remainder": rem_bg,
        "groom_to_bride_remainder": rem_gb,
        "score": score,
        "max": 3,
        "status": status,
    }

# ============================================================
# 4) YONI KOOTA (MAX = 4) — LOCKED
# ============================================================

FEMALE_NAK_TO_YONI = {
    "Ashwini": "Ashwa", "Bharani": "Gaja", "Krittika": "Mesha",
    "Rohini": "Sarpa", "Mrigashira": "Sarpa", "Ardra": "Shwan",
    "Punarvasu": "Marjar", "Pushya": "Marjar", "Ashlesha": "Marjar",
    "Magha": "Mushak", "Purva Phalguni": "Mushak",
    "Uttara Phalguni": "Go", "Hasta": "Mahish",
    "Chitra": "Vyaghra", "Swati": "Mahish",
    "Vishakha": "Vyaghra", "Anuradha": "Mriga",
    "Jyeshtha": "Mriga", "Mula": "Vanar",
    "Purva Ashadha": "Vanar", "Uttara Ashadha": "Nakul",
    "Shravana": "Simha", "Dhanishta": "Simha", "Shatabhisha": "Simha",
    "Purva Bhadrapada": "Ashwa", "Uttara Bhadrapada": "Go", "Revati": "Gaja",
}

MALE_NAK_TO_YONI = dict(FEMALE_NAK_TO_YONI)  # locked mapping in your file

YONI_RELATION = {
    "Ashwa": {"Ashwa": 4, "Gaja": 2, "Mesha": 2, "Sarpa": 1},
    "Gaja": {"Gaja": 4, "Ashwa": 2, "Simha": 1},
    "Mesha": {"Mesha": 4, "Sarpa": 1},
    "Sarpa": {"Sarpa": 4, "Mesha": 1},
    "Shwan": {"Shwan": 4, "Marjar": 0},
    "Marjar": {"Marjar": 4, "Shwan": 0},
    "Mushak": {"Mushak": 4, "Vyaghra": 0},
    "Go": {"Go": 4, "Vyaghra": 1},
    "Mahish": {"Mahish": 4, "Vyaghra": 2},
    "Vyaghra": {"Vyaghra": 4, "Mushak": 0},
    "Mriga": {"Mriga": 4, "Vanar": 2},
    "Vanar": {"Vanar": 4, "Mriga": 2},
    "Nakul": {"Nakul": 4, "Sarpa": 1},
    "Simha": {"Simha": 4, "Gaja": 1},
}

def yoni_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    b_nak = bride_moon.get("nakshatra")
    g_nak = groom_moon.get("nakshatra")
    if not b_nak or not g_nak:
        return {"score": 0, "max": 4, "status": "invalid", "note": "Missing nakshatra"}

    bride_yoni = FEMALE_NAK_TO_YONI.get(b_nak)
    groom_yoni = MALE_NAK_TO_YONI.get(g_nak)

    if not bride_yoni or not groom_yoni:
        return {"score": 0, "max": 4, "status": "invalid", "note": "Yoni not resolved"}

    if bride_yoni == groom_yoni:
        score, status = 4, "same"
    else:
        score = YONI_RELATION.get(bride_yoni, {}).get(groom_yoni, 2)
        status = (
            "friendly" if score == 3 else
            "neutral" if score == 2 else
            "enemy" if score == 1 else
            "sworn_enemy" if score == 0 else
            "unknown"
        )

    return {
        "bride_yoni": bride_yoni,
        "groom_yoni": groom_yoni,
        "score": score,
        "max": 4,
        "status": status,
    }

# ============================================================
# 5) GRAHA MAITRI (MAX = 5) — LOCKED
# ============================================================

def _relation(p1: str, p2: str) -> str:
    if p2 in FRIEND.get(p1, set()):
        return "friend"
    if p2 in ENEMY.get(p1, set()):
        return "enemy"
    return "neutral"

def graha_maitri_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    b_rashi = bride_moon.get("rashi")
    g_rashi = groom_moon.get("rashi")
    if not b_rashi or not g_rashi:
        return {"score": 0, "max": 5, "status": "invalid", "note": "Missing rashi"}

    b_lord = RASHI_LORD.get(b_rashi)
    g_lord = RASHI_LORD.get(g_rashi)
    if not b_lord or not g_lord:
        return {"score": 0, "max": 5, "status": "invalid", "note": "Lord not resolved"}

    if b_lord == g_lord:
        score, status = 5, "excellent"
    else:
        rel_bg = _relation(b_lord, g_lord)
        rel_gb = _relation(g_lord, b_lord)

        if rel_bg == "friend" and rel_gb == "friend":
            score, status = 5, "friendly"
        elif ((rel_bg == "friend" and rel_gb == "neutral") or (rel_bg == "neutral" and rel_gb == "friend")):
            score, status = 4, "mixed_friendly"
        elif rel_bg == "neutral" and rel_gb == "neutral":
            score, status = 3, "neutral"
        else:
            enemy_count = (1 if rel_bg == "enemy" else 0) + (1 if rel_gb == "enemy" else 0)
            if enemy_count == 2:
                score = 0
            elif enemy_count == 1:
                score = 1
            else:
                score = 0.5
            status = "enemy"

    return {"bride_lord": b_lord, "groom_lord": g_lord, "score": score, "max": 5, "status": status}

# ============================================================
# 6) GANA KOOTA (MAX = 6) — LOCKED
# ============================================================

NAKSHATRA_TO_GANA = {
    # Deva
    "Ashwini": "Deva", "Mrigashira": "Deva", "Punarvasu": "Deva",
    "Pushya": "Deva", "Hasta": "Deva", "Swati": "Deva",
    "Anuradha": "Deva", "Shravana": "Deva", "Revati": "Deva",
    # Manushya
    "Bharani": "Manushya", "Rohini": "Manushya", "Ardra": "Manushya",
    "Purva Phalguni": "Manushya", "Uttara Phalguni": "Manushya",
    "Purva Ashadha": "Manushya", "Uttara Ashadha": "Manushya",
    # Rakshasa
    "Krittika": "Rakshasa", "Ashlesha": "Rakshasa", "Magha": "Rakshasa",
    "Chitra": "Rakshasa", "Vishakha": "Rakshasa", "Jyeshtha": "Rakshasa",
    "Mula": "Rakshasa", "Dhanishta": "Rakshasa", "Shatabhisha": "Rakshasa",
    "Purva Bhadrapada": "Rakshasa", "Uttara Bhadrapada": "Rakshasa",
}

GANA_SCORE = {
    ("Deva", "Deva"): 6, ("Manushya", "Manushya"): 6, ("Rakshasa", "Rakshasa"): 6,
    ("Deva", "Manushya"): 5, ("Manushya", "Deva"): 5,
    ("Manushya", "Rakshasa"): 3, ("Rakshasa", "Manushya"): 3,
    ("Deva", "Rakshasa"): 1, ("Rakshasa", "Deva"): 1,
}

def gana_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    b_nak = bride_moon.get("nakshatra")
    g_nak = groom_moon.get("nakshatra")
    if not b_nak or not g_nak:
        return {"score": 0, "max": 6, "status": "invalid", "note": "Missing nakshatra"}

    bg = NAKSHATRA_TO_GANA.get(b_nak)
    gg = NAKSHATRA_TO_GANA.get(g_nak)
    if not bg or not gg:
        return {"score": 0, "max": 6, "status": "invalid", "note": "Gana not resolved"}

    score = GANA_SCORE.get((bg, gg), 0)
    return {"bride_gana": bg, "groom_gana": gg, "score": score, "max": 6, "status": "pass" if score >= 3 else "challenging"}

# ============================================================
# 7) BHAKOOT KOOTA (MAX = 7) — LOCKED + status fix
# ============================================================

RASHIS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
RASHI_INDEX = {r: i for i, r in enumerate(RASHIS)}

def _pos(a: str, b: str) -> int:
    return ((RASHI_INDEX[b] - RASHI_INDEX[a]) % 12) + 1

def _lords_friendly(l1: str, l2: str) -> bool:
    return (l2 in FRIEND.get(l1, set())) and (l1 in FRIEND.get(l2, set()))

def bhakoot_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    br = bride_moon.get("rashi")
    gr = groom_moon.get("rashi")

    if not br or not gr:
        return {"score": 0, "max": 7, "status": "invalid", "note": "Missing rashi"}
    if br not in RASHI_INDEX or gr not in RASHI_INDEX:
        return {"score": 0, "max": 7, "status": "invalid", "note": "Invalid rashi"}

    p_bg = _pos(br, gr)
    p_gb = _pos(gr, br)

    auspicious = (
        (p_bg == 1 and p_gb == 1) or
        ({p_bg, p_gb} == {1, 7}) or
        ({p_bg, p_gb} == {3, 11}) or
        ({p_bg, p_gb} == {4, 10})
    )
    if auspicious:
        return {"positions": {"bride_to_groom": p_bg, "groom_to_bride": p_gb}, "score": 7, "max": 7, "status": "auspicious"}

    dosha_type = None
    if {p_bg, p_gb} == {2, 12}:
        dosha_type = "Dwirdwadash"
    elif {p_bg, p_gb} == {5, 9}:
        dosha_type = "Nav Pancham"
    elif {p_bg, p_gb} == {6, 8}:
        dosha_type = "Shadashtaka"

    if dosha_type:
        bl = RASHI_LORD.get(br)
        gl = RASHI_LORD.get(gr)
        cancelled = (bl and gl and bl == gl) or (bl and gl and _lords_friendly(bl, gl))
        return {
            "positions": {"bride_to_groom": p_bg, "groom_to_bride": p_gb},
            "dosha": dosha_type,
            "cancelled": bool(cancelled),
            "score": 7 if cancelled else 0,
            "max": 7,
            "status": "cancelled" if cancelled else "dosha",
        }

    # ✅ FIXED naming: neutral but no dosha
    return {
        "positions": {"bride_to_groom": p_bg, "groom_to_bride": p_gb},
        "score": 0,
        "max": 7,
        "status": "neutral_no_dosha",
    }

# ============================================================
# 8) NADI KOOTA (MAX = 8) — LOCKED
# ============================================================

NAKSHATRA_TO_NADI = {
    # Aadi
    "Ashwini": "Aadi", "Ardra": "Aadi", "Punarvasu": "Aadi",
    "Uttara Phalguni": "Aadi", "Hasta": "Aadi", "Jyeshtha": "Aadi",
    "Mula": "Aadi", "Shatabhisha": "Aadi", "Purva Bhadrapada": "Aadi",
    # Madhya
    "Bharani": "Madhya", "Mrigashira": "Madhya", "Pushya": "Madhya",
    "Purva Phalguni": "Madhya", "Chitra": "Madhya", "Anuradha": "Madhya",
    "Purva Ashadha": "Madhya", "Dhanishta": "Madhya", "Uttara Bhadrapada": "Madhya",
    # Antya
    "Krittika": "Antya", "Rohini": "Antya", "Ashlesha": "Antya",
    "Magha": "Antya", "Swati": "Antya", "Vishakha": "Antya",
    "Uttara Ashadha": "Antya", "Shravana": "Antya", "Revati": "Antya",
}

def nadi_koota(bride_moon: Dict, groom_moon: Dict) -> Dict:
    b_nak = bride_moon.get("nakshatra")
    g_nak = groom_moon.get("nakshatra")
    if not b_nak or not g_nak:
        return {"score": 0, "max": 8, "status": "invalid", "note": "Missing nakshatra"}

    b_nadi = NAKSHATRA_TO_NADI.get(b_nak)
    g_nadi = NAKSHATRA_TO_NADI.get(g_nak)
    if not b_nadi or not g_nadi:
        return {"score": 0, "max": 8, "status": "invalid", "note": "Nadi not resolved"}

    if b_nadi != g_nadi:
        return {"bride_nadi": b_nadi, "groom_nadi": g_nadi, "score": 8, "max": 8, "status": "pass"}

    b_rashi = bride_moon.get("rashi")
    g_rashi = groom_moon.get("rashi")

    cancelled = False
    if b_rashi and g_rashi:
        if b_rashi == g_rashi:
            cancelled = True
        elif RASHI_LORD.get(b_rashi) == RASHI_LORD.get(g_rashi):
            cancelled = True

    return {
        "bride_nadi": b_nadi,
        "groom_nadi": g_nadi,
        "cancelled": cancelled,
        "score": 8 if cancelled else 0,
        "max": 8,
        "status": "cancelled" if cancelled else "dosha",
    }

# ============================================================
# AGGREGATOR (TOTAL MAX = 36) — stable output
# ============================================================

def compute_ashtakoot(
    bride_moon: Dict[str, Any],
    groom_moon: Dict[str, Any],
    *,
    boy_is_groom: bool = True
) -> Dict[str, Any]:
    """
    bride_moon / groom_moon expected minimal fields:
      - rashi: str
      - nakshatra: str
      - degree: float (only needed for Sagittarius/Capricorn in Vashya)
    """

    # Varna needs boy/girl ordering (LOCKED). Default: groom=boy, bride=girl.
    if boy_is_groom:
        varna = varna_koota(groom_moon, bride_moon)
    else:
        varna = varna_koota(bride_moon, groom_moon)

    vashya = vashya_koota(bride_moon, groom_moon)
    tara = tara_koota(bride_moon, groom_moon)
    yoni = yoni_koota(bride_moon, groom_moon)
    maitri = graha_maitri_koota(bride_moon, groom_moon)
    gana = gana_koota(bride_moon, groom_moon)
    bhakoot = bhakoot_koota(bride_moon, groom_moon)
    nadi = nadi_koota(bride_moon, groom_moon)

    kootas = {
        "varna": varna,
        "vashya": vashya,
        "tara": tara,
        "yoni": yoni,
        "graha_maitri": maitri,
        "gana": gana,
        "bhakoot": bhakoot,
        "nadi": nadi,
    }

    total = 0.0
    max_total = 36.0
    invalids = []

    for k, v in kootas.items():
        score = float(v.get("score", 0) or 0)
        total += score
        if v.get("status") == "invalid":
            invalids.append(k)

    return {
        "total_score": total,
        "max_score": max_total,
        "invalid_kootas": invalids,
        "kootas": kootas,
    }
