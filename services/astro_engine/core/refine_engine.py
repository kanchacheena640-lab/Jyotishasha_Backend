from datetime import timedelta
from services.astro_engine.core.rashi_pair_engine import is_same_rashi


# -----------------------------
# BINARY REFINE
# -----------------------------

def refine_same_rashi_entry(planet1, planet2, date):
    """
    Refine exact entry time (hour/minute level)
    """

    start = date - timedelta(days=1)
    end = date + timedelta(days=1)

    for _ in range(20):  # precision loops
        mid = start + (end - start) / 2

        if is_same_rashi(planet1, planet2, mid):
            end = mid
        else:
            start = mid

    return end


def refine_same_rashi_exit(planet1, planet2, date):
    """
    Refine exit time
    """

    start = date
    end = date + timedelta(days=2)

    for _ in range(20):
        mid = start + (end - start) / 2

        if is_same_rashi(planet1, planet2, mid):
            start = mid
        else:
            end = mid

    return start