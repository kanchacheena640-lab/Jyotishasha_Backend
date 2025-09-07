def build_love_life(kundali: dict, language: str = "en") -> dict:
    planets = kundali.get("planets", [])
    house_map = kundali.get("house_mapping", {})
    lagna_sign = kundali.get("lagna_sign", "")
    
    # Constants (self-contained)
    PLANET_HI = {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि",
        "Rahu": "राहु", "Ketu": "केतु"
    }

    HOUSE_HI = {
        1: "लग्न", 2: "द्वितीय", 3: "तृतीय", 4: "चतुर्थ", 5: "पंचम",
        6: "षष्ठ", 7: "सप्तम", 8: "अष्टम", 9: "नवम", 10: "दशम",
        11: "एकादश", 12: "द्वादश",
    }

    POSITIVE = []
    NEGATIVE = []

    # Venus or Moon in 5th or 7th → positive
    for p in planets:
        if p["name"] in ["Venus", "Moon"] and p["house"] in [5, 7]:
            POSITIVE.append({
                "en": f"{p['name']} in {p['house']} house supports love and emotional bonding.",
                "hi": f"{HOUSE_HI[p['house']]} भाव में {PLANET_HI[p['name']]} प्रेम और भावनात्मक संबंधों को मज़बूत करता है।"
            })

    # Saturn or Ketu in 5th/7th → negative
    for p in planets:
        if p["name"] in ["Saturn", "Ketu"] and p["house"] in [5, 7]:
            NEGATIVE.append({
                "en": f"{p['name']} in {p['house']} house creates emotional blocks in relationships.",
                "hi": f"{HOUSE_HI[p['house']]} भाव में {PLANET_HI[p['name']]} प्रेम संबंधों में रुकावटें उत्पन्न करता है।"
            })

    # Sun or Mars in 7th → temper issues
    for p in planets:
        if p["name"] in ["Sun", "Mars"] and p["house"] == 7:
            NEGATIVE.append({
                "en": f"{p['name']} in 7th house may cause ego clashes or control issues in love.",
                "hi": f"सप्तम भाव में {PLANET_HI[p['name']]} प्रेम में अहंकार या वर्चस्व की समस्याएं ला सकता है।"
            })

      # --- Fallbacks if no rules fired ---
    if not POSITIVE:
        POSITIVE.append({
            "en": "Venus is the planet of love and you need some remedy to make love life great.",
            "hi": "शुक्र प्रेम का ग्रह है; थोड़े उपायों से प्रेम जीवन बहुत बेहतर हो सकता है।"
        })

    if not NEGATIVE:
        NEGATIVE.append({
            "en": "Instead of everything good, love is all about care—so include delicacy in love matters.",
            "hi": "सब कुछ सही होते हुए भी प्रेम में सबसे ज़रूरी है रिश्तों में नर्मी और संवेदनशीलता, इसे शामिल करें।"
        })
    # --- end fallbacks ---

    # Summary heading
    heading = {
        "en": "Your romantic life and love compatibility as per your kundali.",
        "hi": "आपके कुंडली के अनुसार प्रेम जीवन और अनुकूलता का विश्लेषण।"
    }

    cta = {
        "en": "Get your detailed love compatibility report based on planetary influences.",
        "hi": "ग्रहों के प्रभाव पर आधारित अपनी विस्तृत लव लाइफ रिपोर्ट पाएं।"
    }

    verdict = {
        "en": "Remedies and maturity can greatly improve love life outcomes.",
        "hi": "उपाय और समझदारी से प्रेम जीवन में सुधार संभव है।"
    }

    return {
        "heading": heading[language],
        "positive_points": POSITIVE,
        "negative_points": NEGATIVE,
        "cta": cta[language],
        "verdict": verdict[language]
    }
