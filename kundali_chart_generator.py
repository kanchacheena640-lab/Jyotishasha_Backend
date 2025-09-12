from reportlab.graphics.shapes import Drawing, Rect, Line, String

BASE = 400
CENTER = BASE / 2

# ✅ Corrected anti-clockwise house layout with House 1 (Lagna) at top
HOUSE_CENTERS = {
    1: (CENTER, 245),             # Top-middle
    2: (CENTER - 100, 320),       # Top-right
    3: (CENTER - 130, CENTER - 95),
    4: (CENTER - 100, CENTER ),     # Right
    5: (CENTER - 130, CENTER - 95),
    6: (CENTER - 100, 80),        # Bottom-right
    7: (CENTER, CENTER - 50),     # Bottom-middle
    8: (CENTER + 100, 80),        # Bottom-left
    9: (CENTER + 130, CENTER - 95),
    10: (CENTER + 100, CENTER ),    # Left
    11: (CENTER + 130, CENTER - 95),
    12: (CENTER + 100, 320),      # Top-left
}

PLANET_SYMBOLS = {
    "sun": "Su", "moon": "Mo", "mars": "Ma", "mercury": "Me",
    "jupiter": "Ju", "venus": "Ve", "saturn": "Sa",
    "rahu": "Ra", "ketu": "Ke"
}

ALT = {
    "surya": "sun", "soorya": "sun", "ravi": "sun", "chandra": "moon",
    "soma": "moon", "mangal": "mars", "kuja": "mars", "budh": "mercury",
    "budha": "mercury", "guru": "jupiter", "brihaspati": "jupiter",
    "shukra": "venus", "shani": "saturn", "sani": "saturn", "raahu": "rahu"
}

def to_abbr(name):
    if not name:
        return ""
    key = str(name).lower().strip().replace(" ", "").replace("-", "")
    canon = ALT.get(key, key)
    return PLANET_SYMBOLS.get(canon, canon[:2].capitalize())

def get_rashis_by_house(lagna_rashi):
    return [((lagna_rashi - 1 + i) % 12) + 1 for i in range(12)]

def draw_kundali(planets, lagna_rashi):
    d = Drawing(BASE, BASE)
    d.add(Rect(0, 0, BASE, BASE, strokeWidth=2, fillColor=None))

    # Outer cross diagonals
    d.add(Line(0, 0, BASE, BASE))
    d.add(Line(BASE, 0, 0, BASE))

    # Diamond ring
    d.add(Line(CENTER, 0, 0, CENTER))
    d.add(Line(0, CENTER, CENTER, BASE))
    d.add(Line(CENTER, BASE, BASE, CENTER))
    d.add(Line(BASE, CENTER, CENTER, 0))

    rashis = get_rashis_by_house(lagna_rashi)
    by_house = {}
    for p in planets:
        name = p.get("name")
        if name and "ascendant" not in name.lower():
            h = int(p.get("house", 0))
            if 1 <= h <= 12:
                by_house.setdefault(h, []).append(to_abbr(name))

    for house, (x, y) in HOUSE_CENTERS.items():
        rashi = rashis[house - 1]
        d.add(String(x, y, str(rashi), fontSize=12, textAnchor="middle"))

        planets_here = by_house.get(house, [])
        if planets_here:
            dx, dy = 0, 0
            if house in [1, 12, 2]:
                dy = 28
            elif house in [3, 4, 5]:
                dx = 30
            elif house in [6, 7, 8]:
                dy = -28
            elif house in [9, 10, 11]:
                dx = -30

            d.add(String(x + dx, y + dy, ", ".join(planets_here),
                         fontSize=10, textAnchor="middle"))

    return d

def generate_kundali_drawing(planets, lagna_rashi):
    """
    Kundali chart ke liye Drawing object banata hai.
    PNG likhne ki zarurat nahi.
    """
    return draw_kundali(planets, lagna_rashi)
