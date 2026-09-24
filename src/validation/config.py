"""The one place where the scoring is decided.

Change a number here and it changes everywhere: the rule engine, the tests,
the reports and (from Phase 3) the UI all read these values. Nothing else in
the project hard-codes them. That is deliberate - in a demo you have to be
able to say exactly why a record scored what it scored, and be able to tune
it in one place when a revenue officer disagrees.
"""

# How much difference to forgive when comparing areas, in hectares.
# 0.02 ha = 2 are: larger than rounding noise, far smaller than a real error.
AREA_TOLERANCE_HA = 0.02

# What each failed rule adds to the dispute-risk score, how serious it is, and
# why it carries that weight. The weights add up to exactly 100, so a record
# that fails every check scores 100.
RULES = {
    "R1_hissa_area": {
        "title": "Hissa areas reconcile with the parent survey number",
        "weight": 20,
        "severity": "high",
        "why": "Sub-division areas that do not add up are a classic cause of "
               "boundary disputes between neighbours.",
    },
    "R2_area_balance": {
        "title": "Total area equals cultivable area plus pot kharaba",
        "weight": 10,
        "severity": "medium",
        "why": "Usually a copying mistake, but it makes every area figure on "
               "the page doubtful.",
    },
    "R3_owner_shares": {
        "title": "Owner shares add up to the total area",
        "weight": 20,
        "severity": "high",
        "why": "If the shares do not add up, it is unclear how much land each "
               "co-owner actually holds.",
    },
    "R4_mutation_chain": {
        "title": "Every mutation is made by a recorded owner",
        "weight": 25,
        "severity": "high",
        "why": "A transfer by somebody who never held the land is the single "
               "strongest sign of a fraudulent or mis-recorded entry.",
    },
    "R5_mutation_dates": {
        "title": "Mutations are in date order",
        "weight": 5,
        "severity": "medium",
        "why": "Dates out of order suggest a back-dated entry or a data-entry "
               "mistake in the mutation register.",
    },
    "R6_duplicate_parcel": {
        "title": "The same parcel is not recorded twice",
        "weight": 20,
        "severity": "high",
        "why": "Two records for one parcel means two owners can each hold a "
               "valid-looking extract for the same land - and it is how a "
               "parcel gets sold twice.",
    },
}

# How sure OCR has to be before a rule will judge a field, 0-100.
#
# This floor applies to TEXT (names, dates). Numbers are gated by something
# stronger: they are read by two independent models and only accepted when
# both agree, which src/ocr/extract.py records as a confidence of 0 when they
# do not. Measured on 60 numeric cells, agreement meant 100% correct against
# 45% for disagreement, while Tesseract's own confidence only separated 94%
# from 75% - not enough to judge a record on.
#
# Swept over 16 pages, this is what the floor buys:
#
#   floor   records checked automatically   false alarms on clean records
#     off               16/16                         11/14
#     70                 3/16                          0/2
#     80                 0/16                            -
#
# 70 is the setting that never cried wolf. One record in five gets checked
# automatically; the rest go to a human with the doubtful fields highlighted,
# which is the human-assisted verification the problem statement asks for.
# Raising this coverage means better OCR, not a looser rule.
#
# Records that did not come from OCR carry no confidences and are always judged.
OCR_CONFIDENCE_FLOOR = 70

# Colour bands for the score. 0 means nothing failed. 20 is the weight of the
# lightest "high" severity rule, so the colours line up with the severities:
# any single high-severity failure turns the record red, while the medium
# ones (10 and 5) leave it amber even when both fail.
AMBER_FROM = 1
RED_FROM = 20

# Which rule is supposed to catch which injected defect. Used only to measure
# the engine against the generator's ground truth (see report.py and the
# tests); the engine itself never looks at this.
DEFECT_TO_RULE = {
    "hissa_area_mismatch": "R1_hissa_area",
    "area_balance_mismatch": "R2_area_balance",
    "owner_share_mismatch": "R3_owner_shares",
    "broken_mutation_chain": "R4_mutation_chain",
    "mutation_date_out_of_order": "R5_mutation_dates",
    "duplicate_record": "R6_duplicate_parcel",
}


def band(score: int) -> tuple[str, str]:
    """(label, colour) for a score - used by the reports and the UI."""
    if score >= RED_FROM:
        return "High", "red"
    if score >= AMBER_FROM:
        return "Medium", "amber"
    return "Low", "green"
