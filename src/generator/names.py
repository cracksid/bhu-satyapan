"""Marathi names and places for the synthetic 7/12 generator.

Everything generated from this file is fictional:

  * People are built by mixing common Marathi first names and surnames at
    random, so a generated name belongs to no particular real person.
  * Village names are invented compounds, not real Maharashtra villages.
  * District and taluka names are real administrative areas (they are not
    people), so the records still look plausible.

Real people's names must never appear in generated data, screenshots or demo
records.
"""

import random

# --- people ---------------------------------------------------------------
MALE_FIRST_NAMES = [
    "राम", "कृष्णा", "गणेश", "महादेव", "विठ्ठल", "संतोष", "दत्तात्रय", "नामदेव",
    "शिवाजी", "तुकाराम", "सखाराम", "रघुनाथ", "अनिल", "सुनील", "प्रकाश", "दिलीप",
    "अशोक", "रमेश", "सुरेश", "भास्कर", "केशव", "यशवंत", "बबन", "हरिभाऊ", "बाळासाहेब",
]

FEMALE_FIRST_NAMES = [
    "सुनंदा", "मंगल", "कमल", "लक्ष्मी", "सरस्वती", "शांता", "इंदुबाई", "पार्वती",
    "अनुसया", "वत्सला", "कलावती", "मीरा", "जिजाबाई", "रखमाबाई", "शोभा",
]

SURNAMES = [
    "पाटील", "जाधव", "शिंदे", "मोरे", "देशमुख", "कुलकर्णी", "पवार", "साळुंखे",
    "थोरात", "चव्हाण", "गायकवाड", "भोसले", "माने", "काळे", "सावंत", "राऊत",
    "शेलार", "निकम", "बनसोडे", "वाघमारे", "तांबे", "घाडगे", "कदम", "जगताप", "दाभाडे",
]

# --- places ---------------------------------------------------------------
# Invented village names (compounds that do not name a real village).
VILLAGES = [
    "रानतळेवाडी", "मोरचिंचोली", "सोनखेडवाडी", "तुळजामाळ", "हिवरतांडा",
    "कवठेमळा", "देवगव्हाणवाडी", "बोरमाळवाडी", "पिंपळतळे", "वडगव्हाण खुर्द",
    "निंबतळेवाडी", "धानोरमाळ", "जांभूळवस्ती", "करंजतळे", "शिरसमाळवाडी",
]

# Real district -> real talukas of that district.
DISTRICT_TALUKAS = {
    "पुणे": ["हवेली", "बारामती", "इंदापूर", "जुन्नर", "शिरूर"],
    "सातारा": ["कराड", "पाटण", "फलटण", "कोरेगाव"],
    "सोलापूर": ["माढा", "पंढरपूर", "बार्शी", "माळशिरस"],
    "नाशिक": ["निफाड", "दिंडोरी", "सिन्नर", "येवला"],
    "कोल्हापूर": ["हातकणंगले", "शिरोळ", "कागल", "पन्हाळा"],
    "अहिल्यानगर": ["श्रीगोंदा", "राहुरी", "पारनेर", "संगमनेर"],
}

# --- record vocabulary ----------------------------------------------------
CROPS = ["ज्वारी", "बाजरी", "गहू", "ऊस", "हरभरा", "सोयाबीन", "कापूस", "भात", "तूर", "भुईमूग"]
SEASONS = ["खरीप", "रब्बी"]
IRRIGATION = ["जिरायत", "बागायत"]          # rain-fed / irrigated
BANKS = ["जिल्हा मध्यवर्ती सहकारी बँक", "ग्रामीण बँक", "विविध कार्यकारी सोसायटी"]
MUTATION_TYPES = {                          # internal name -> Marathi label
    "sale": "खरेदी-विक्री",
    "inheritance": "वारस नोंद",
    "partition": "वाटप",
    "gift": "बक्षीसपत्र",
}


def person(rng: random.Random) -> str:
    """A full Marathi name: own name + father's name + surname."""
    first = rng.choice(MALE_FIRST_NAMES + FEMALE_FIRST_NAMES)
    # A father with the same first name looks like a bug in a screenshot.
    father = rng.choice([name for name in MALE_FIRST_NAMES if name != first])
    return f"{first} {father} {rng.choice(SURNAMES)}"


def place(rng: random.Random) -> dict:
    """One invented village inside a real taluka and district."""
    district = rng.choice(list(DISTRICT_TALUKAS))
    return {
        "district": district,
        "taluka": rng.choice(DISTRICT_TALUKAS[district]),
        "village": rng.choice(VILLAGES),
    }
