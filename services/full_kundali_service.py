"""
Full Kundali Service (Aggregator)
---------------------------------
Single entry-point that stitches together all sub-modules and returns a
frontend-ready JSON for the Modern Kundali Report (Jyotishasha Version).

Design choices:
- Chart is rendered on the frontend → we return structured chart_data only.
- Houses Overview is generated here by mixing static house traits with
  actual placements/aspects so content feels practical & concise.
- Dasha: we expose the full Mahadasha→Antardasha table (if available) and
  a psychological current-dasha snippet to drive upsell.
- Planet Overview: we keep backend text from planet_overview_logic (if any)
  and enrich each planet with a short remedy+benefit line.
- We **omit empty houses** in planet-by-house lists per product rule.

Inputs (form_data expected):
{
  "name": str,
  "gender": Optional[str],
  "dob": "YYYY-MM-DD",
  "tob": "HH:MM",
  "place_name": str,
  "lat": float,
  "lng": float,
  "timezone": str,      # e.g. "+05:30"
  "ayanamsa": str       # e.g. "Lahiri"
}

Usage:
from services.full_kundali_service import generate_full_kundali_payload
payload = generate_full_kundali_payload(form_data)

This file is logic-only (no Flask routes). Wire it in full_kundali_api.py
or a new controller to expose /api/full-kundali.
"""
from __future__ import annotations

import os, sys
from typing import Any, Dict, List, Optional, Tuple
import json
from datetime import date
from data.name_mappings import planet_labels_hi, sign_labels_hi, nakshatra_names_hi


# ✅ Ensure root directory (C:\test_backend) is visible to Python
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

DATA_DIR = os.path.join(ROOT_DIR, "data")
if DATA_DIR not in sys.path:
    sys.path.append(DATA_DIR)
# ------------------------------------------------------------------
# ✅ VERIFIED IMPORTS (final, no duplicates, correct paths)
# ------------------------------------------------------------------

try:
    # Main birth chart + yogas engine (root)
    from full_kundali_api import calculate_full_kundali
except Exception as e:
    print(f"⚠️ Import error for calculate_full_kundali: {e}")
    calculate_full_kundali = None

try:
    # Smart Transit Engine (root) → get any planet’s position on date
    from smart_transit_engine import get_planet_position_on as get_current_transit
except Exception as e:
    print(f"⚠️ Import error for smart_transit_engine: {e}")
    get_current_transit = None

try:
    # Legacy Transit Engine (root) → all planets' current positions
    from transit_engine import get_current_positions as get_current_transits_legacy
except Exception as e:
    print(f"⚠️ Import error for transit_engine: {e}")
    get_current_transits_legacy = None

try:
    # Planet Overview Logic (services/) → generate text overview
    from services.planet_overview_logic import get_planet_overview as build_planet_overview
except Exception as e:
    print(f"⚠️ Import error for services.planet_overview_logic: {e}")
    build_planet_overview = None

# Files in repo
HOUSE_TRAITS_PATH = os.path.join(os.path.dirname(__file__), "..", "house_traits_en.json")

# --------------------------- Helpers ---------------------------

def _safe_get(d: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur

def _load_house_traits(path: str = HOUSE_TRAITS_PATH) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Minimal fallback traits if json not found
        return {
            "1": "Self, health, personality",
            "2": "Wealth, family, speech",
            "3": "Courage, communication, siblings",
            "4": "Home, mother, peace",
            "5": "Creativity, education, children, romance",
            "6": "Obstacles, diseases, debts, service",
            "7": "Marriage, partnerships, contracts",
            "8": "Transformation, longevity, secrets",
            "9": "Luck, dharma, long journeys",
            "10": "Career, reputation, responsibilities",
            "11": "Income, gains, networks",
            "12": "Expenses, losses, moksha, foreign travel",
        }

REMEDY_TEMPLATES = {
    "Sun": ("Sun mantra on Sundays; mindful leadership.", "Confidence & recognition"),
    "Moon": ("Moon mantra / hydration & sleep routine.", "Emotional balance"),
    "Mars": ("Hanuman Chalisa on Tuesdays; disciplined workouts.", "Courage & timely action"),
    "Mercury": ("Budh mantra; journaling, clear communication.", "Clarity & learning"),
    "Jupiter": ("Guru mantra / Thursday charity.", "Wisdom & growth"),
    "Venus": ("Shukra mantra; aesthetic discipline.", "Harmony & relationships"),
    "Saturn": ("Shani mantra; Saturday seva/charity.", "Stability & long-term gains"),
    "Rahu": ("Grounding breath-work; avoid excess.", "Focus & smart risk"),
    "Ketu": ("Meditation & detachment rituals.", "Clarity & inner peace"),
}

# -------------------- Core content builders --------------------

def _group_planets_by_house(planets: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Return {house_no: [planets...]}, omitting empty houses (product rule)."""
    result: Dict[int, List[Dict[str, Any]]] = {}
    for p in planets or []:
        h = p.get("house")
        if not isinstance(h, int):
            continue
        result.setdefault(h, []).append(p)
    return dict(sorted(result.items(), key=lambda kv: kv[0]))

def _generate_houses_overview(lagna_sign: str, planets: List[Dict[str, Any]],
                              traits: Dict[str, str]) -> List[Dict[str, Any]]:
    """Return concise 12-house overview blocks, blending static traits with live placements.
    We keep it light + practical, and mention only present placements/aspects.
    """
    by_house = _group_planets_by_house(planets)
    blocks: List[Dict[str, Any]] = []
    for h in range(1, 13):
        theme = traits.get(str(h), "")
        present = by_house.get(h, [])
        planets_txt = ", ".join([p.get("name", "") for p in present]) if present else "None"
        summary = f"Focus: {theme}."
        if present:
            summary += f" Notable placements: {planets_txt}."
        blocks.append({
            "house": h,
            "focus": theme,
            "notable_placements": [
                {
                    "planet": p.get("name"),
                    "sign": p.get("sign"),
                    "degree": p.get("degree"),
                    "nakshatra": p.get("nakshatra"),
                    "pada": p.get("pada"),
                } for p in present
            ],
            "summary": summary.strip(),
        })
    return blocks
# --------------------------
# Helper to replace placeholders dynamically
# --------------------------
def replace_house_lords(aspect_text, chart):
    if not chart or "lords" not in chart:
        return aspect_text

    from data.name_mappings import planet_labels_hi  # ✅ use existing Hindi mapping

    for k, v in chart["lords"].items():
        if not v:
            continue

        # Get Hindi translation if available
        v_hi = planet_labels_hi.get(v, v)

        # Replace placeholders with both English and Hindi forms
        aspect_text = aspect_text.replace(f"{{{k}}}", v)
        aspect_text = aspect_text.replace(f"{{{k}_hi}}", v_hi)

    # Clean up unwanted parentheses or extra spaces
    aspect_text = (
        aspect_text.replace("( ", "")
        .replace(" )", "")
        .replace("()", "")
        .replace(" ,", ",")
        .replace("  ", " ")
    )

    return aspect_text


def generate_life_aspects(chart_data: Dict[str, Any], houses_overview: List[Dict[str, Any]], yogas: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Static + explainers table to show 'which houses/planets/yogas' affect each life aspect.
    We keep it deterministic (frontend shows table), and attach a CTA for upsell.
    """
    BASE = BASE = [
                    {
                        "aspect": "Personality & Outlook",
                        "aspect_hi": "व्यक्तित्व और दृष्टिकोण",
                        "houses": "1st",
                        "planets": "Sun, Moon, {lagna_lord}",
                        "planets_hi": "सूर्य, चंद्र, {lagna_lord_hi}",
                        "yogas": "—",
                        "summary": "Your Ascendant lord {lagna_lord}, along with the Sun and Moon, defines your core personality, vitality, and confidence. It shapes how you think, act, and express yourself to the world. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "लग्न स्वामी {lagna_lord_hi}, सूर्य और चंद्रमा के साथ मिलकर आपके व्यक्तित्व, आत्मविश्वास और अभिव्यक्ति को निर्धारित करता है। यह तय करता है कि आप दुनिया के सामने कैसे प्रस्तुत होते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A strong Ascendant lord gives charisma, courage and leadership.",
                        "example_hi": "मजबूत लग्नेश व्यक्ति को आकर्षक व्यक्तित्व, साहस और नेतृत्व क्षमता प्रदान करता है।"
                    },
                    {
                        "aspect": "Wealth & Finances",
                        "aspect_hi": "धन और आर्थिक स्थिति",
                        "houses": "2nd, 11th",
                        "planets": "Jupiter, Venus, {second_house_lord}, {eleventh_house_lord}",
                        "planets_hi": "गुरु, शुक्र, {second_house_lord_hi}, {eleventh_house_lord_hi}",
                        "yogas": "Dhan Yog, Lakshmi Yog",
                        "summary": "Your 2nd and 11th house lords {second_house_lord}, {eleventh_house_lord} supported by Jupiter and Venus, govern income, wealth accumulation, and long-term prosperity. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "द्वितीय और एकादश भाव के स्वामी {second_house_lord_hi}, {eleventh_house_lord_hi}, गुरु और शुक्र के साथ मिलकर आपकी आय, धन-संग्रह और दीर्घकालिक समृद्धि को प्रभावित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A strong 2nd and 11th house brings financial growth and prosperity.",
                        "example_hi": "मजबूत द्वितीय और एकादश भाव आर्थिक वृद्धि और समृद्धि सुनिश्चित करते हैं।"
                    },
                    {
                        "aspect": "Communication & Siblings",
                        "aspect_hi": "संवाद और भाई-बहन",
                        "houses": "3rd",
                        "planets": "Mercury, Mars, {third_house_lord}",
                        "planets_hi": "बुध, मंगल, {third_house_lord_hi}",
                        "yogas": "—",
                        "summary": "Your 3rd house lord {third_house_lord} with Mercury and Mars indicates communication, courage, and relations with siblings. It shows how you express ideas and handle challenges. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "तृतीय भाव के स्वामी {third_house_lord_hi}, बुध और मंगल के साथ संवाद, साहस और भाई-बहनों के साथ संबंध को प्रभावित करते हैं। यह दर्शाता है कि आप विचार कैसे व्यक्त करते हैं और चुनौतियों का सामना कैसे करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Strong Mercury brings clarity; Mars adds assertiveness in communication.",
                        "example_hi": "मजबूत बुध स्पष्टता देता है, जबकि मंगल संवाद में आत्मविश्वास और दृढ़ता बढ़ाता है।"
                    },
                    {
                        "aspect": "Home & Family",
                        "aspect_hi": "घर और परिवार",
                        "houses": "4th",
                        "planets": "Moon, Venus, {fourth_house_lord}",
                        "planets_hi": "चंद्र, शुक्र, {fourth_house_lord_hi}",
                        "yogas": "—",
                        "summary": "Your 4th house lord {fourth_house_lord} along with Moon and Venus, governs emotional peace, home comfort, and connection with mother or roots. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "चतुर्थ भाव के स्वामी {fourth_house_lord_hi}, चंद्र और शुक्र के साथ गृहस्थ सुख, मानसिक शांति और मातृ संबंधों को नियंत्रित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Strong 4th house ensures domestic peace and emotional support.",
                        "example_hi": "मजबूत चतुर्थ भाव गृहस्थ जीवन में शांति और भावनात्मक संतुलन लाता है।"
                    },
                    {
                        "aspect": "Creativity & Children",
                        "aspect_hi": "रचनात्मकता और संतान",
                        "houses": "5th",
                        "planets": "Sun, Jupiter, {fifth_house_lord}",
                        "planets_hi": "सूर्य, गुरु, {fifth_house_lord_hi}",
                        "yogas": "Putra Yog, Saraswati Yog",
                        "summary": "Your 5th house lord {fifth_house_lord} with Sun and Jupiter enhances creativity, intellect, and relationships with children. It also shows talent in education or artistic fields. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "पंचम भाव के स्वामी {fifth_house_lord_hi}, सूर्य और गुरु के साथ आपकी रचनात्मकता, शिक्षा में सफलता और संतान से जुड़े शुभ फलों को दर्शाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A powerful 5th house brings creativity, fame, and inspiration to others.",
                        "example_hi": "मजबूत पंचम भाव व्यक्ति को रचनात्मक, प्रेरणादायक और प्रसिद्ध बनाता है।"
                    },
                    {
                        "aspect": "Health & Challenges",
                        "aspect_hi": "स्वास्थ्य और चुनौतियाँ",
                        "houses": "6th",
                        "planets": "Mars, Saturn, {sixth_house_lord}",
                        "planets_hi": "मंगल, शनि, {sixth_house_lord_hi}",
                        "yogas": "Shatru Yog",
                        "summary": "Your 6th house lord {sixth_house_lord} along with Mars and Saturn governs health, stamina, and your ability to overcome stress, debts, or rivals. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "षष्ठ भाव के स्वामी {sixth_house_lord_hi}, मंगल और शनि के साथ आपके स्वास्थ्य, धैर्य और विपरीत स्थितियों से निपटने की क्षमता को प्रभावित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Strong Mars gives energy and drive; Saturn adds discipline and endurance.",
                        "example_hi": "मजबूत मंगल ऊर्जा और प्रेरणा देता है, जबकि शनि अनुशासन और सहनशीलता बढ़ाता है।"
                    },
                    {
                        "aspect": "Marriage & Partnerships",
                        "aspect_hi": "विवाह और साझेदारी",
                        "houses": "7th",
                        "planets": "Venus, Jupiter, {seventh_house_lord}",
                        "planets_hi": "शुक्र, गुरु, {seventh_house_lord_hi}",
                        "yogas": "Kalatr Sukh Yog",
                        "summary": "Your 7th house lord {seventh_house_lord} with Venus and Jupiter defines marriage, long-term partnerships, and emotional bonding. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "सप्तम भाव के स्वामी {seventh_house_lord_hi}, शुक्र और गुरु के साथ विवाह, दीर्घकालिक साझेदारी और भावनात्मक संबंधों की दिशा निर्धारित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Balanced Venus and Jupiter bring love, trust and mutual growth.",
                        "example_hi": "संतुलित शुक्र और गुरु प्रेम, विश्वास और आपसी विकास प्रदान करते हैं।"
                    },
                    {
                        "aspect": "Transformation & Longevity",
                        "aspect_hi": "परिवर्तन और दीर्घायु",
                        "houses": "8th",
                        "planets": "Saturn, Ketu, {eighth_house_lord}",
                        "planets_hi": "शनि, केतु, {eighth_house_lord_hi}",
                        "yogas": "Ayush Yog",
                        "summary": "Your 8th house lord {eighth_house_lord} together with Saturn and Ketu reveals deep transformation, hidden matters and spiritual strength. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "अष्टम भाव के स्वामी {eighth_house_lord_hi}, शनि और केतु के साथ जीवन के गहरे परिवर्तन, गूढ़ विषय और आध्यात्मिक शक्ति को दर्शाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "This house teaches resilience through ups and downs; every crisis leads to renewal.",
                        "example_hi": "यह भाव उतार-चढ़ाव के माध्यम से धैर्य सिखाता है; हर संकट नई शुरुआत लाता है।"
                    },
                    {
                        "aspect": "Luck & Spiritual Growth",
                        "aspect_hi": "भाग्य और आध्यात्मिक विकास",
                        "houses": "9th",
                        "planets": "Jupiter, Sun, {ninth_house_lord}",
                        "planets_hi": "गुरु, सूर्य, {ninth_house_lord_hi}",
                        "yogas": "Bhagya Yog",
                        "summary": "Your 9th house lord {ninth_house_lord} along with Jupiter and Sun brings faith, ethics, higher learning and divine protection. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "नवम भाव के स्वामी {ninth_house_lord_hi}, गुरु और सूर्य के साथ भाग्य, नैतिकता, उच्च ज्ञान और दैवी संरक्षण प्रदान करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A strong 9th house gives optimism, faith and higher wisdom.",
                        "example_hi": "मजबूत नवम भाव आशावाद, विश्वास और उच्च ज्ञान प्रदान करता है।"
                    },
                    {
                        "aspect": "Career & Public Life",
                        "aspect_hi": "कैरियर और सार्वजनिक जीवन",
                        "houses": "10th",
                        "planets": "Sun, Saturn, Mercury, {tenth_house_lord}",
                        "planets_hi": "सूर्य, शनि, बुध, {tenth_house_lord_hi}",
                        "yogas": "Raj Yog, Karma Yog",
                        "summary": "Your 10th house lord {tenth_house_lord} together with the Sun, Saturn and Mercury shapes your profession, authority and social recognition. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "दशम भाव के स्वामी {tenth_house_lord_hi}, सूर्य, शनि और बुध के साथ आपके पेशा, नेतृत्व और सामाजिक प्रतिष्ठा को निर्धारित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A powerful 10th house brings recognition, leadership and career stability.",
                        "example_hi": "मजबूत दशम भाव व्यवसाय में नेतृत्व और स्थिरता प्रदान करता है।"
                    },
                    {
                        "aspect": "Gains & Social Network",
                        "aspect_hi": "लाभ और सामाजिक नेटवर्क",
                        "houses": "11th",
                        "planets": "Jupiter, Mercury, {eleventh_house_lord}",
                        "planets_hi": "गुरु, बुध, {eleventh_house_lord_hi}",
                        "yogas": "Labha Yog",
                        "summary": "Your 11th house lord {eleventh_house_lord} along with Jupiter and Mercury governs income sources, social influence, and long-term achievements. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "एकादश भाव के स्वामी {eleventh_house_lord_hi}, गुरु और बुध के साथ आपकी आय के स्रोत, सामाजिक प्रभाव और दीर्घकालिक उपलब्धियों को नियंत्रित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "A strong 11th house brings loyal friends, wide networks and financial stability.",
                        "example_hi": "मजबूत एकादश भाव विश्वसनीय मित्र, व्यापक नेटवर्क और आर्थिक स्थिरता देता है।"
                    },
                    {
                        "aspect": "Expenses",
                        "aspect_hi": "खर्च",
                        "houses": "12th",
                        "planets": "Ketu, Venus, Saturn, {twelfth_house_lord}",
                        "planets_hi": "केतु, शुक्र, शनि, {twelfth_house_lord_hi}",
                        "yogas": "Moksha Yog",
                        "summary": "Your 12th house lord {twelfth_house_lord} with Ketu, Venus and Saturn reveals expenditure, isolation, and the path toward spiritual liberation. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "द्वादश भाव के स्वामी {twelfth_house_lord_hi}, केतु, शुक्र और शनि के साथ खर्च, एकांत और आध्यात्मिक मुक्ति के मार्ग को दर्शाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "This placement inspires detachment, charity and mystical learning.",
                        "example_hi": "यह स्थिति वैराग्य, दान-धर्म और रहस्यमय ज्ञान की प्रेरणा देती है।"
                    },
                    {
                        "aspect": "Mind & Emotions",
                        "aspect_hi": "मन और भावनाएँ",
                        "houses": "4th",
                        "planets": "Moon, Mercury, {fourth_house_lord}",
                        "planets_hi": "चंद्र, बुध, {fourth_house_lord_hi}",
                        "yogas": "Chandra Yog",
                        "summary": "Your 4th house lord {fourth_house_lord} along with Moon and Mercury controls emotional stability, thought patterns and inner happiness. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "चतुर्थ भाव के स्वामी {fourth_house_lord_hi}, चंद्र और बुध के साथ आपकी भावनात्मक स्थिरता, विचार प्रक्रिया और आंतरिक सुख को निर्धारित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Balanced Moon and Mercury give calm mind and emotional wisdom.",
                        "example_hi": "संतुलित चंद्र और बुध शांत मन तथा भावनात्मक बुद्धि प्रदान करते हैं।"
                    },
                    {
                        "aspect": "Family & Domestic Life",
                        "aspect_hi": "परिवार और गृहस्थ जीवन",
                        "houses": "2nd, 4th",
                        "planets": "Moon, Venus, {second_house_lord}, {fourth_house_lord}",
                        "planets_hi": "चंद्र, शुक्र, {second_house_lord_hi}, {fourth_house_lord_hi}",
                        "yogas": "Griha Sukh Yog",
                        "summary": "Your 2nd and 4th house lords {second_house_lord}, {fourth_house_lord} with Moon and Venus influence family harmony, love and emotional comfort. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "द्वितीय और चतुर्थ भाव के स्वामी {second_house_lord_hi}, {fourth_house_lord_hi}, चंद्र और शुक्र के साथ पारिवारिक सौहार्द, प्रेम और भावनात्मक शांति को प्रभावित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Supportive family environment and caring nature indicated.",
                        "example_hi": "सहायक पारिवारिक वातावरण और देखभाल-पूर्ण स्वभाव का संकेत मिलता है।"
                    },
                    {
                        "aspect": "Spiritual Growth & Karma",
                        "aspect_hi": "आध्यात्मिक विकास और कर्म",
                        "houses": "9th, 12th",
                        "planets": "Jupiter, Ketu, {ninth_house_lord}, {twelfth_house_lord}",
                        "planets_hi": "गुरु, केतु, {ninth_house_lord_hi}, {twelfth_house_lord_hi}",
                        "yogas": "Moksha-Dharma Yog",
                        "summary": "Your 9th and 12th house lords {ninth_house_lord}, {twelfth_house_lord} with Jupiter and Ketu bring divine wisdom, detachment and insight from past-life karma. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "नवम और द्वादश भाव के स्वामी {ninth_house_lord_hi}, {twelfth_house_lord_hi}, गुरु और केतु के साथ दिव्य ज्ञान, वैराग्य और पूर्व-जन्म के कर्मों से प्राप्त अंतर्दृष्टि प्रदान करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Encourages meditation, forgiveness and higher consciousness.",
                        "example_hi": "ध्यान, क्षमा और उच्च चेतना की प्रवृत्ति को प्रोत्साहित करता है।"
                    },

                    {
                        "aspect": "Social Circle & Gains",
                        "aspect_hi": "सामाजिक दायरा और लाभ",
                        "houses": "11th",
                        "planets": "Mercury, Saturn, {eleventh_house_lord}",
                        "planets_hi": "बुध, शनि, {eleventh_house_lord_hi}",
                        "yogas": "Labha Yog",
                        "summary": "Your 11th house lord {eleventh_house_lord} with Mercury and Saturn shows profits through contacts, teamwork and social reputation. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "एकादश भाव के स्वामी {eleventh_house_lord_hi}, बुध और शनि के साथ आपके सामाजिक संबंधों, सहयोग और प्रतिष्ठा से लाभ के अवसर दर्शाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Networking brings opportunities and sustained income.",
                        "example_hi": "सामाजिक नेटवर्क नए अवसर और स्थायी आय प्रदान करता है।"
                    },
                    {
                        "aspect": "Property & Assets",
                        "aspect_hi": "संपत्ति और भौतिक साधन",
                        "houses": "4th, 11th",
                        "planets": "Mars, Moon, {fourth_house_lord}, {eleventh_house_lord}",
                        "planets_hi": "मंगल, चंद्र, {fourth_house_lord_hi}, {eleventh_house_lord_hi}",
                        "yogas": "Vastu Yog",
                        "summary": "Your 4th and 11th house lords {fourth_house_lord}, {eleventh_house_lord} with Mars and Moon indicate property gains, real-estate luck and domestic assets. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "चतुर्थ और एकादश भाव के स्वामी {fourth_house_lord_hi}, {eleventh_house_lord_hi}, मंगल और चंद्र के साथ भूमि, संपत्ति और गृह-संबंधी लाभ के योग बनाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Real-estate or parental assets bring comfort and security.",
                        "example_hi": "भूमि या पारिवारिक संपत्ति से स्थिरता और सुख प्राप्त होता है।"
                    },
                    {
                        "aspect": "Children & Creativity",
                        "aspect_hi": "संतान और सृजनात्मकता",
                        "houses": "5th",
                        "planets": "Jupiter, Venus, {fifth_house_lord}",
                        "planets_hi": "गुरु, शुक्र, {fifth_house_lord_hi}",
                        "yogas": "Putra Yog",
                        "summary": "Your 5th house lord {fifth_house_lord} with Jupiter and Venus supports joy from children, intellect and artistic creation. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "पंचम भाव के स्वामी {fifth_house_lord_hi}, गुरु और शुक्र के साथ संतान सुख, बुद्धि और रचनात्मकता को प्रबल बनाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Blessed with bright and creative offspring.",
                        "example_hi": "संतानें प्रतिभाशाली और रचनात्मक होती हैं।"
                    },
                    {
                        "aspect": "Work & Service",
                        "aspect_hi": "कार्य और सेवा",
                        "houses": "6th",
                        "planets": "Saturn, Mercury, {sixth_house_lord}",
                        "planets_hi": "शनि, बुध, {sixth_house_lord_hi}",
                        "yogas": "Seva Yog",
                        "summary": "Your 6th house lord {sixth_house_lord} with Saturn and Mercury indicates professional discipline, analytical skills and steady service growth. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "षष्ठ भाव के स्वामी {sixth_house_lord_hi}, शनि और बुध के साथ पेशेवर अनुशासन, विश्लेषणात्मक क्षमता और सेवा क्षेत्र में स्थिरता देते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Hard-working and consistent; excels in research or administration.",
                        "example_hi": "आप परिश्रमी और निरंतर हैं; अनुसंधान या प्रबंधन में श्रेष्ठ प्रदर्शन करते हैं।"
                    },
                    {
                        "aspect": "Marriage & Partnership",
                        "aspect_hi": "विवाह और साझेदारी",
                        "houses": "7th",
                        "planets": "Venus, Rahu, Ketu, {seventh_house_lord}",
                        "planets_hi": "शुक्र, राहु, केतु, {seventh_house_lord_hi}",
                        "yogas": "Kalatr Sukh Yog",
                        "summary": "Your 7th house lord {seventh_house_lord} with Venus, Rahu and Ketu shapes marriage dynamics, attraction and karmic bonds. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "सप्तम भाव के स्वामी {seventh_house_lord_hi}, शुक्र, राहु और केतु के साथ विवाहिक जीवन, आकर्षण और कर्मिक संबंधों को प्रभावित करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Strong Venus ensures harmony; Rahu–Ketu bring karmic lessons.",
                        "example_hi": "मजबूत शुक्र संतुलन देता है, राहु–केतु कर्म से जुड़ी सीखें लाते हैं।"
                    },
                    {
                        "aspect": "Justice & Wisdom",
                        "aspect_hi": "न्याय और ज्ञान",
                        "houses": "9th",
                        "planets": "Jupiter, Sun, {ninth_house_lord}",
                        "planets_hi": "गुरु, सूर्य, {ninth_house_lord_hi}",
                        "yogas": "Dharma Yog",
                        "summary": "Your 9th house lord {ninth_house_lord} with Jupiter and Sun promotes righteousness, morality and sound judgement. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "नवम भाव के स्वामी {ninth_house_lord_hi}, गुरु और सूर्य के साथ नैतिकता, धर्म और सही निर्णय की शक्ति देते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Fair-minded, guided by truth and karma.",
                        "example_hi": "आप न्यायप्रिय और सत्य के मार्ग पर चलने वाले व्यक्ति हैं।"
                    },
                    {
                        "aspect": "Father & Authority",
                        "aspect_hi": "पिता और अधिकार",
                        "houses": "9th, 10th",
                        "planets": "Sun, Jupiter, {ninth_house_lord}, {tenth_house_lord}",
                        "planets_hi": "सूर्य, गुरु, {ninth_house_lord_hi}, {tenth_house_lord_hi}",
                        "yogas": "Pitru Yog",
                        "summary": "Your 9th and 10th house lords {ninth_house_lord}, {tenth_house_lord} with Sun and Jupiter show paternal guidance and legacy in career. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "नवम और दशम भाव के स्वामी {ninth_house_lord_hi}, {tenth_house_lord_hi}, सूर्य और गुरु के साथ पैतृक मार्गदर्शन और कैरियर में विरासत को दर्शाते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Strong fatherly influence shaping ethics and leadership.",
                        "example_hi": "पिता का प्रभाव आपके नैतिकता और नेतृत्व को आकार देता है।"
                    },
                    {
                        "aspect": "Past Life Karma",
                        "aspect_hi": "पूर्व जन्म का कर्मफल",
                        "houses": "8th, 12th",
                        "planets": "Ketu, Saturn, {eighth_house_lord}, {twelfth_house_lord}",
                        "planets_hi": "केतु, शनि, {eighth_house_lord_hi}, {twelfth_house_lord_hi}",
                        "yogas": "Karma Yog",
                        "summary": "Your 8th and 12th house lords {eighth_house_lord}, {twelfth_house_lord} with Ketu and Saturn reveal past-life debts, detachment and soul learning. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "अष्टम और द्वादश भाव के स्वामी {eighth_house_lord_hi}, {twelfth_house_lord_hi}, केतु और शनि के साथ पूर्व-जन्म के कर्म, वैराग्य और आत्मिक सीखों को उजागर करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Introspective; learns detachment and forgiveness.",
                        "example_hi": "आत्मचिंतन में रुचि रखते हैं; वैराग्य और क्षमा की सीख प्राप्त करते हैं।"
                    },
                    {
                        "aspect": "Mother & Comfort",
                        "aspect_hi": "माता और सुख-सुविधा",
                        "houses": "4th",
                        "planets": "Moon, Venus, {fourth_house_lord}",
                        "planets_hi": "चंद्र, शुक्र, {fourth_house_lord_hi}",
                        "yogas": "Matru Sukh Yog",
                        "summary": "Your 4th house lord {fourth_house_lord} with Moon and Venus grants maternal support, comfort and aesthetic surroundings. For a detailed personal report, check your full horoscope.",
                        "summary_hi": "चतुर्थ भाव के स्वामी {fourth_house_lord_hi}, चंद्र और शुक्र के साथ मातृ सहारा, सुख-सुविधा और सौंदर्यपूर्ण परिवेश प्रदान करते हैं। अपने जीवन पर ग्रहों के प्रभाव की विस्तृत जानकारी के लिए रिपोर्ट ले।",
                        "example": "Close bond with mother; peace-loving domestic nature.",
                        "example_hi": "माता से गहरा लगाव और शांतिप्रिय गृहस्थ स्वभाव।"
                    },
    
    ]

     # Attach CTA (one place for upsell link)
    out = []
    for row in BASE:
        # make a safe copy
        aspect_row = row.copy()

        # replace placeholders in both languages
        aspect_row["summary"] = replace_house_lords(aspect_row["summary"], chart_data)
        aspect_row["summary_hi"] = replace_house_lords(aspect_row["summary_hi"], chart_data)
        aspect_row["planets"] = replace_house_lords(aspect_row["planets"], chart_data)
        aspect_row["planets_hi"] = replace_house_lords(aspect_row["planets_hi"], chart_data)

        # final CTA
        aspect_row["cta"] = {
            "title": f"✨ Detailed {aspect_row['aspect']} Report",
            "button": "Explore on Jyotishasha →",
            "link": "https://www.jyotishasha.com/tools",
        }
        out.append(aspect_row)

    return out


def _enrich_planet_overview(base_overview: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add a short remedy + expected benefit for each planet card.
    If the structure already contains remedy, we leave it as is.
    """
    enriched: List[Dict[str, Any]] = []
    for item in base_overview or []:
        planet_name = item.get("planet") or item.get("name")
        # Skip if already present
        if not item.get("remedy") and planet_name in REMEDY_TEMPLATES:
            remedy, benefit = REMEDY_TEMPLATES[planet_name]
            item = {**item, "remedy": remedy, "benefit_area": benefit}
        enriched.append(item)
    return enriched

def _build_current_dasha_snippet(kundali: Dict[str, Any], language: str = "en") -> Dict[str, Any]:
    """Create a psychological, actionable snippet for the currently active Mahadasha/Antardasha."""
    cur = kundali.get("current_mahadasha") or {}
    cur_antar = kundali.get("current_antardasha") or {}

    if not cur and not cur_antar:
        gdb = kundali.get("grah_dasha_block") or {}
        return {
            "mahadasha": gdb.get("mahadasha_planet"),
            "antardasha": gdb.get("antardasha_planet"),
            "period": None,
            "impact_snippet": gdb.get("grah_dasha_text"),
            "impact_snippet_hi": gdb.get("grah_dasha_text_hi"),
        }

    period = None
    antar_start = cur_antar.get("start")
    antar_end = cur_antar.get("end")
    if antar_start and antar_end:
        period = f"{antar_start} – {antar_end}"

    mplanet = cur.get("mahadasha") or (kundali.get("grah_dasha_block") or {}).get("mahadasha_planet")
    aplanet = cur_antar.get("planet") or (kundali.get("grah_dasha_block") or {}).get("antardasha_planet")

    psyche_map = {
        "Rahu": ("expansion of desires, networking, unconventional paths", "इच्छाओं का विस्तार, नेटवर्किंग और असामान्य मार्ग"),
        "Ketu": ("detachment, spiritual seeking, minimalism", "वैराग्य, आध्यात्मिक खोज और सादगी"),
        "Saturn": ("discipline, responsibility, long-term building", "अनुशासन, जिम्मेदारी और दीर्घकालिक निर्माण"),
        "Jupiter": ("wisdom, growth, guidance & protection", "ज्ञान, विकास, मार्गदर्शन और सुरक्षा"),
        "Mars": ("action, courage, conflict-resolution needs", "कर्मठता, साहस और संघर्ष समाधान की प्रवृत्ति"),
        "Mercury": ("analysis, communication, learning curve", "विश्लेषण, संवाद और सीखने की प्रक्रिया"),
        "Venus": ("relationships, harmony, aesthetics & comfort", "संबंध, सामंजस्य, सौंदर्य और सुख-सुविधा"),
        "Sun": ("identity, confidence, leadership & ego balance", "पहचान, आत्मविश्वास, नेतृत्व और अहं का संतुलन"),
        "Moon": ("emotions, stability, nurturing & habits", "भावनाएँ, स्थिरता, देखभाल और आदतें"),
    }

    theme_en, theme_hi = psyche_map.get(mplanet, ("", ""))
    sub_en, sub_hi = psyche_map.get(aplanet, ("", ""))

    # English
    impact_en = (
        f"You are under {mplanet}–{aplanet} dasha. "
        f"You are facing some ups & downs in areas related to {theme_en} and {sub_en}. "
        f"Balance your reactions, act with clarity, and turn insights into small practical actions."
    )

    # Hindi
    impact_hi = (
        f"आप वर्तमान में {mplanet}–{aplanet} दशा में हैं। "
        f"आपके जीवन में {theme_hi} और {sub_hi} से जुड़े कुछ उतार-चढ़ाव चल रहे हैं। "
        f"धैर्य रखें, स्पष्ट सोचें और छोटी व्यावहारिक क्रियाओं से संतुलन बनाए रखें।"
    )

    return {
        "mahadasha": mplanet,
        "antardasha": aplanet,
        "period": period,
        "impact_snippet": impact_en,
        "impact_snippet_hi": impact_hi,
    }


# -----------------------------------
# 🔮 House Lord Resolver (Fallback)
# -----------------------------------
SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

def derive_house_lords(lagna_sign: str) -> Dict[str, str]:
    """Given Ascendant sign → return all 12 house lords with Hindi names."""
    from data.name_mappings import planet_labels_hi

    SIGNS = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    ORDINALS = [
        "first", "second", "third", "fourth", "fifth", "sixth",
        "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth"
    ]

    if not lagna_sign or lagna_sign not in SIGNS:
        return {}

    # Rotate zodiac from Ascendant
    start = SIGNS.index(lagna_sign)
    rotated = SIGNS[start:] + SIGNS[:start]

    out = {}
    for i, sign in enumerate(rotated, start=1):
        lord = SIGN_LORDS.get(sign, "")
        ord_key = ORDINALS[i - 1]  # like 'first', 'second', etc.

        out[f"{i}_house_lord"] = lord
        out[f"{i}_house_lord_hi"] = planet_labels_hi.get(lord, lord)
        out[f"{ord_key}_house_lord"] = lord
        out[f"{ord_key}_house_lord_hi"] = planet_labels_hi.get(lord, lord)

    out["lagna_lord"] = SIGN_LORDS.get(lagna_sign)
    out["lagna_lord_hi"] = planet_labels_hi.get(SIGN_LORDS.get(lagna_sign), SIGN_LORDS.get(lagna_sign))
    return out


# ------------------------ Public API ------------------------

def generate_full_kundali_payload(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Master aggregator that returns frontend-ready payload for the Modern Kundali UI.

    This function is **pure** (no Flask). Controller should validate inputs and call
    this function, then jsonify the result.
    """
    if calculate_full_kundali is None:
        raise RuntimeError("calculate_full_kundali() not available. Ensure imports are correct.")

    # 1) Base kundali from existing engine
    base: Dict[str, Any] = calculate_full_kundali(
        name=form_data.get("name"),
        dob=form_data.get("dob"),
        tob=form_data.get("tob"),
        lat=form_data.get("lat"),
        lon=form_data.get("lng"),  # ✅ use lon instead of lng
        language=form_data.get("language", "en"),
    )
     # ✅ Validate & Load Lagna Trait content (with placeholder fix)
    try:
        import json
        lang = form_data.get("language", "en")
        lang_file = "lagna_traits_hi.json" if lang == "hi" else "lagna_traits_en.json"
        traits_path = os.path.join(os.path.dirname(__file__), "..", "data", lang_file)

        if os.path.exists(traits_path):
            with open(traits_path, "r", encoding="utf-8") as f:
                lagna_traits = json.load(f)
            sign = base.get("lagna_sign")
            trait_text = lagna_traits.get(sign, "")
            if trait_text:
                base["lagna_trait"] = trait_text

                # 🧭 Replace placeholders dynamically
                try:
                    lagna_p = base.get("ascendant", {}) or {}
                    nakshatra = lagna_p.get("nakshatra") or ""
                    pada = lagna_p.get("pada") or ""
                    aspect_effects = base.get("aspect_effects", "")
                    base["lagna_trait"] = (
                        base["lagna_trait"]
                        .replace("{nakshatra}", str(nakshatra))
                        .replace("{pada}", str(pada))
                        .replace("{aspect_effects}", str(aspect_effects))
                    )
                except Exception as e:
                    print("⚠️ Placeholder replacement failed:", e)
            else:
                print(f"⚠️ Missing lagna trait for {sign} in {lang_file}")
        else:
            print(f"⚠️ Lagna trait file not found: {traits_path}")
    except Exception as e:
        print("⚠️ Lagna trait loading failed:", e)

    # 2) Chart data for frontend (only structured, no image)
    planets_arr: List[Dict[str, Any]] = base.get("planets") or base.get("Planets") or []
    chart_data = {
        "ascendant": base.get("lagna_sign") or base.get("ascendant", {}).get("sign"),
        "planets": [
            {
                "name": p.get("name"),
                "sign": p.get("sign"),
                "house": p.get("house"),
                "degree": p.get("degree"),
                "nakshatra": p.get("nakshatra"),
                "pada": p.get("pada"),
            }
            for p in planets_arr
            if isinstance(p.get("house"), int)
        ],
    }

    # ✅ inject house lords for placeholder replacement
    chart_data["lords"] = base.get("lords") or derive_house_lords(chart_data.get("ascendant"))

    # (optional debug)
    print("DEBUG LORDS →", chart_data.get("lords"))

    # 3) Planet Overview (prefer explicit module, else fallback to existing field)
    if build_planet_overview is not None:
        try:
            planet_overview = build_planet_overview(base)
        except Exception:
            planet_overview = base.get("planet_overview") or []
    else:
        planet_overview = base.get("planet_overview") or []
    planet_overview = _enrich_planet_overview(planet_overview)

    # 4) Houses Overview (12 cards), using house traits JSON + live placements
    house_traits = _load_house_traits()
    houses_overview = _generate_houses_overview(
        lagna_sign=chart_data.get("ascendant") or "",
        planets=chart_data["planets"],
        traits=house_traits,
    )

    # 5) Transit (current-day only)
    transit_analysis: List[Dict[str, Any]] = []
    try:
        if get_current_transit is not None:
            transit_analysis = get_current_transit(
                lat=form_data.get("lat"),
                lng=form_data.get("lng"),
                tz=form_data.get("timezone")
            ) or []
        elif get_current_transits_legacy is not None:
            transit_analysis = get_current_transits_legacy(
                lat=form_data.get("lat"),
                lng=form_data.get("lng"),
                tz=form_data.get("timezone")
            ) or []
    except Exception:
        transit_analysis = base.get("transit_analysis", []) or []

        # 6) Dasha — full table + current snippet
    dasha_summary = {
        "mahadashas": base.get("Mahadasha") or base.get("mahadasha") or [],
        "current_mahadasha": base.get("current_mahadasha"),
        "current_antardasha": base.get("current_antardasha"),
        "current_block": _build_current_dasha_snippet(base, form_data.get("language", "en")),
    }

    # 🧭 AUTO-COLLECT all Yogas & Doshas from base (even if not nested)
    possible_yogs = [
        "adhi_rajyog", "budh_aditya_yog", "chandra_mangal_yog",
        "dhan_yog", "dharma_karmadhipati_rajyog", "gajakesari_yog",
        "kuber_rajyog", "lakshmi_yog", "neechbhang_rajyog",
        "panch_mahapurush_yog", "parashari_rajyog", "rajya_sambandh_rajyog",
        "shubh_kartari_yog", "vipreet_rajyog"
    ]

    base["yogas"] = {}
    for key in possible_yogs:
        val = base.get(key)
        if isinstance(val, dict) and (val.get("is_active") or val.get("heading")):
            base["yogas"][key] = val

    
    # 7) Yogas / Doshas & gemstone suggestion  ✅ FIXED
    yogas = {}

    # 1️⃣ nested yogas inside base["yogas"]
    if isinstance(base.get("yogas"), dict):
        for yk, yv in base["yogas"].items():
            if not isinstance(yv, dict):
                continue
            if yv.get("is_active") or yv.get("heading") or yv.get("description"):
                yogas[yk] = yv

    # 2️⃣ direct-level doshas
    for dk in ["kaalsarp_dosh", "manglik_dosh", "sadhesati"]:
        val = base.get(dk)
        if isinstance(val, dict):
            yogas[dk] = val

    # 3️⃣ preserve is_active flag
    for yk, yv in yogas.items():
        if isinstance(base.get("yogas", {}).get(yk), dict) and \
        "is_active" in base["yogas"][yk]:
            yv["is_active"] = base["yogas"][yk]["is_active"]

    # 8) Life aspects – always build enriched table for frontend
    try:
        life_aspects = base.get("life_aspects")
        if not life_aspects:
            life_aspects = generate_life_aspects(chart_data, houses_overview, yogas)
    except Exception:
        life_aspects = generate_life_aspects(chart_data, houses_overview, yogas)

        # ✅ Hindi mapping for planets, signs, nakshatras (only if Hindi mode)
    if form_data.get("language") == "hi" and "planets" in chart_data:
        try:
            from data.name_mappings import planet_labels_hi, sign_labels_hi, nakshatra_names_hi
            for p in chart_data["planets"]:
                p["name_hi"] = planet_labels_hi.get(p.get("name"), p.get("name"))
                p["sign_hi"] = sign_labels_hi.get(p.get("sign"), p.get("sign"))
                p["nakshatra_hi"] = nakshatra_names_hi.get(p.get("nakshatra"), p.get("nakshatra"))
        except Exception as e:
            print("⚠️ Hindi mapping failed:", e)


    # 9) Compose final payload
    payload: Dict[str, Any] = {
        "profile": {
            "name": form_data.get("name"),
            "gender": form_data.get("gender"),
            "dob": form_data.get("dob"),
            "tob": form_data.get("tob"),
            "place": form_data.get("place_name"),
            "timezone": form_data.get("timezone"),
            "ayanamsa": form_data.get("ayanamsa", "Lahiri"),
        },
        "lagna_sign": base.get("lagna_sign"),
        "lagna_trait": base.get("lagna_trait"),
        "rashi": base.get("rashi"),
        "chart_data": chart_data,
        "planet_overview": planet_overview,
        "houses_overview": houses_overview,
        "dasha_summary": dasha_summary,
        "transit_analysis": transit_analysis,
        "yogas": yogas,
        "gemstone_suggestion": base.get("gemstone_suggestion"),
        "life_aspects": life_aspects,  # ← NEW
        # reserved for future PDF usage (frontend will ignore None)
        "chart_image": None,
        # pass-throughs that your frontend already uses
        "grah_dasha_block": base.get("grah_dasha_block"),
        "moon_traits": base.get("moon_traits"),
    }
    return payload


# -------------------------- Quick self-test --------------------------
if __name__ == "__main__":
    # Minimal dry run to verify imports and shaping (does not print large data)
    demo_form = {
        "name": "Demo User",
        "gender": "",
        "dob": "1997-08-16",
        "tob": "23:01",
        "place_name": "Warangal, Telangana, India",
        "lat": 17.9787,
        "lng": 79.5581,
        "timezone": "+05:30",
        "ayanamsa": "Lahiri",
        "language": "en",
    }
    try:
        out = generate_full_kundali_payload(demo_form)
        print("OK: payload keys →", list(out.keys()))
        print("OK: chart ascendant →", out.get("chart_data", {}).get("ascendant"))
        print("OK: planets count →", len(out.get("chart_data", {}).get("planets", [])))
        print("OK: houses_overview →", len(out.get("houses_overview", [])))
    except Exception as e:
        print("ERROR:", e)
