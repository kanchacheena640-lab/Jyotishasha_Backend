# test_kundali_chart.py

from kundali_chart_generator import generate_kundali_image

sample_planets = [
    {"name": "Sun", "house": 7},
    {"name": "Moon", "house": 11},
    {"name": "Mars", "house": 6},
    {"name": "Mercury", "house": 7},
    {"name": "Jupiter", "house": 9},
    {"name": "Venus", "house": 5},
    {"name": "Saturn", "house": 3},
    {"name": "Rahu", "house": 2},
    {"name": "Ketu", "house": 8},
]

lagna_rashi = 1  # Assume Aries Ascendant for test

generate_kundali_image(planets=sample_planets, lagna_rashi=lagna_rashi, output_path="reports/kundali_TEST.png")
