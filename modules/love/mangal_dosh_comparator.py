from services.mangalik_dosh_logic import build_manglik_dosh

def compare_mangal_dosh(kundali_boy, kundali_girl, language="en"):
    boy = build_manglik_dosh(kundali_boy, language)
    girl = build_manglik_dosh(kundali_girl, language)

    A = boy["evaluation"]["final_strength"]
    B = girl["evaluation"]["final_strength"]

    # Normalize
    high = {"Strong", "Partial"}
    none = {"None", "Cancelled"}

    if A in high and B in high:
        signal = "GREEN"
        reason = "Both charts carry similar Mangal energy; mutual balance possible."
    elif A in none and B in none:
        signal = "GREEN"
        reason = "Neither chart shows effective Mangal Dosh."
    else:
        signal = "RED"
        reason = "Mismatch in Mangal Dosh strength may cause adjustment issues."

    return {
        "signal": signal,  # GREEN | RED
        "boy": boy,
        "girl": girl,
        "summary": reason,
    }
