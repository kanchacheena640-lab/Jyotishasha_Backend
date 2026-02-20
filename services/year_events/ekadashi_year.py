from functools import lru_cache
from services.year_events.year_engine import calculate_event_for_year
from services.events_engine import build_ekadashi_json


@lru_cache(maxsize=5)
def calculate_ekadashi_year(year, lat, lon, language="en"):
    return calculate_event_for_year(
        year,
        lat,
        lon,
        build_ekadashi_json,
        language
    )