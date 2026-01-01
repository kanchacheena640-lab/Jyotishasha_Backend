from services.mangalik_dosh_logic import build_manglik_dosh



def compare_mangal_dosh(kundali_boy, kundali_girl, language="en"):
    boy = build_manglik_dosh(kundali_boy, language)
    girl = build_manglik_dosh(kundali_girl, language)

    A = boy.get("evaluation", {}).get("final_strength")
    B = girl.get("evaluation", {}).get("final_strength")

    if not A or not B:
        return {
            "signal": "UNKNOWN",
            "boy": boy,
            "girl": girl,
            "summary": (
                "Insufficient data to evaluate Mangal Dosh."
                if language == "en"
                else "मंगल दोष विश्लेषण के लिए पर्याप्त जानकारी उपलब्ध नहीं है।"
            ),
        }


    # Normalize
    high = {"Strong", "Partial"}
    none = {"None", "Cancelled"}

    if A in high and B in high:
        signal = "GREEN"
        reason = (
            "Both charts carry similar Mangal energy; mutual balance is possible."
            if language == "en"
            else "दोनों कुंडलियों में मंगल दोष की प्रकृति समान है, आपसी संतुलन संभव है।"
        )
    elif A in none and B in none:
        signal = "GREEN"
        reason = (
            "Neither chart shows effective Mangal Dosh."
            if language == "en"
            else "दोनों कुंडलियों में प्रभावी मंगल दोष नहीं है।"
        )
    else:
        signal = "RED"
        reason = (
            "Mismatch in Mangal Dosh strength may cause adjustment issues."
            if language == "en"
            else "मंगल दोष की असमानता के कारण वैवाहिक समायोजन में कठिनाई आ सकती है।"
        )

    return {
        "signal": signal,  # GREEN | RED
        "boy": boy,
        "girl": girl,
        "summary": reason,
    }
