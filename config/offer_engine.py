from datetime import datetime
from config.offers import FESTIVAL_OFFERS

def get_active_offer():
    """
    Returns the currently active offer dict from FESTIVAL_OFFERS
    or None if no offer is active.
    """
    now = datetime.now()

    for offer in FESTIVAL_OFFERS:
        if offer["start"] <= now <= offer["end"]:
            return offer

    return None
