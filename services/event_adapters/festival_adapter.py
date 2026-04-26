import re

# -------------------------------
# 🔹 HELPERS
# -------------------------------
def clean_meta_dates(meta):
    for key in ["date", "tithi_start", "tithi_end"]:
        if key in meta and meta[key]:
            val = str(meta[key])
            val = re.sub(r"\s+", " ", val)
            val = val.replace("22026", "2026")
            val = val.replace("20 026", "2026")
            val = val.replace("20   026", "2026")
            val = val.replace(" 5-", "-")
            meta[key] = val.strip()
    return meta


# -------------------------------
# 🔹 TYPE NORMALIZATION
# -------------------------------
def normalize_type(raw_type: str) -> str:
    if not raw_type:
        return "festival"

    t = raw_type.lower().strip()

    if t in [
        "pradosh", "sankashti", "shivratri",
        "masik_shivratri", "chaturthi", "vinayaka_chaturthi", "ekadashi"
    ]:
        return "vrat"

    elif t in ["amavasya", "purnima"]:
        return "festival"

    elif t in ["transit"]:
        return "transit"

    return "festival"


# -------------------------------
# 🔹 MAIN NORMALIZER
# -------------------------------
def normalize_event(raw_event):
    if not raw_event:   # 🔥 FIX 2 (ADD HERE)
        return None
    raw_date = raw_event.get("date")

    # 🔥 date fix
    if hasattr(raw_date, "strftime"):
        clean_date = raw_date.strftime("%Y-%m-%d")
    else:
        val = str(raw_date)
        val = val.replace("20   026", "2026").replace("20 026", "2026").replace("22026", "2026")
        clean_date = val.strip()[:10]

    # 🔥 meta clean
    meta_raw = raw_event.get("meta") or {}
    meta = clean_meta_dates(meta_raw.copy())

    # 🔥 TYPE
    normalized_type = normalize_type(raw_event.get("type") or "")

    # 🔥 NAME (CRITICAL FIX)
    name = (raw_event.get("name_en") or "").strip()
    # 🔥 FIX: Ekadashi naming enforce
    raw_type = (raw_event.get("type") or "").lower()

    if raw_type == "ekadashi" and "ekadashi" not in name.lower():
        name = f"{name} Ekadashi"

    # ❌ reject junk names
    if not name or name.lower().strip() in ["vrat", "festival"]:
        return None

    name = name.strip()

    print(f"🔄 {name} | {raw_event.get('type')} → {normalized_type}")

    return {
        "name": name,
        "date": clean_date,
        "type": normalized_type,
        "priority": 3,
        "notify_before_days": 1,
        "notify_same_day": True,
        "meta": meta
    }


# -------------------------------
# 🔹 LIST NORMALIZER + DEDUP
# -------------------------------
def normalize_events(events_list):
    seen = set()
    cleaned = []

    for e in events_list:
        if not e:   # 🔥 FIX 1 (skip None)
            continue

        norm = normalize_event(e)
        if not norm:
            continue

        key = (norm["date"], norm["name"])

        if key in seen:
            continue

        seen.add(key)
        cleaned.append(norm)

    return cleaned