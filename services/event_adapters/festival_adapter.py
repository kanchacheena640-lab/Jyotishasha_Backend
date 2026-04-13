import re


# 🔹 helper function
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


# 🔹 TYPE NORMALIZATION (🔥 FIXED COMPLETE)
def normalize_type(raw_type: str) -> str:
    if not raw_type:
        return "festival"

    t = raw_type.lower().strip()

    # 🔥 ALL VRAT TYPES
    if t in [
        "pradosh",
        "sankashti",
        "shivratri",
        "masik_shivratri",   # 🔥 ADDED
        "chaturthi",
        "vinayaka_chaturthi"
    ]:
        return "vrat"

    # 🔥 FESTIVAL TYPES
    elif t in [
        "amavasya",
        "purnima"
    ]:
        return "festival"
    
    # 🔥 TRANSIT
    elif t in ["transit"]:
        return "transit"

    # 🔥 DEFAULT SAFETY
    return "festival"


# 🔹 main normalize function
def normalize_event(raw_event):
    raw_date = raw_event.get("date")

    # 🔥 FIX DATE PROPERLY
    if hasattr(raw_date, "strftime"):
        clean_date = raw_date.strftime("%Y-%m-%d")
    else:
        val = str(raw_date)

        val = val.replace("20   026", "2026")
        val = val.replace("20 026", "2026")
        val = val.replace("22026", "2026")

        clean_date = val.strip()[:10]

    # 🔥 meta clean
    meta = clean_meta_dates(raw_event.get("meta", {}).copy())

    # 🔥 extra safety
    if "date" in meta:
        meta["date"] = (
            str(meta["date"])
            .replace("20   026", "2026")
            .replace("20 026", "2026")
            .replace("22026", "2026")
        )

    # 🔥 TYPE FIX
    normalized_type = normalize_type(raw_event.get("type"))

    print(f"🔄 TYPE NORMALIZED: {raw_event.get('type')} → {normalized_type}")

    return {
        "name": raw_event.get("name_en") or raw_event.get("type") or "Unknown Event",
        "date": clean_date,
        "type": normalized_type,
        "priority": 3,
        "notify_before_days": 1,
        "notify_same_day": True,
        "meta": meta
    }


# 🔹 multiple helper
def normalize_events(events_list):
    return [normalize_event(e) for e in events_list if e]