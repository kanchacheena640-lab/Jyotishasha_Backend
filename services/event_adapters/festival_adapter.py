import re

# 🔹 helper function (PEHLE define hoga)
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


# 🔹 main normalize function
def normalize_event(raw_event):
    raw_date = raw_event.get("date")

    # 🔥 FIX DATE PROPERLY
    if hasattr(raw_date, "strftime"):
        clean_date = raw_date.strftime("%Y-%m-%d")
    else:
        val = str(raw_date)

        # fix broken year formats
        val = val.replace("20   026", "2026")
        val = val.replace("20 026", "2026")
        val = val.replace("22026", "2026")

        clean_date = val.strip()[:10]

    # 🔥 meta clean
    meta = clean_meta_dates(raw_event.get("meta", {}).copy())

    # 🔥 FORCE FIX (important)
    if "date" in meta:
        meta["date"] = (
            str(meta["date"])
            .replace("20   026", "2026")
            .replace("20 026", "2026")
            .replace("22026", "2026")
        )

    return {
        "name": raw_event.get("name_en") or raw_event.get("type") or "Unknown Event",
        "date": clean_date,
        "type": raw_event.get("type"),
        "priority": 3,
        "notify_before_days": 1,
        "notify_same_day": True,
        "meta": meta
    }


# 🔹 multiple helper
def normalize_events(events_list):
    return [normalize_event(e) for e in events_list if e]