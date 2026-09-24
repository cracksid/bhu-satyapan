"""Phase 2 tests: catch every injected defect, and leave clean records alone.

There are two kinds of test here:

  * small hand-written records, so you can read one test and see exactly what
    a rule reacts to;
  * a whole generated batch, built in memory (no images, no browser), which is
    the real measurement: every defect the generator injected must be caught,
    and no clean record may be flagged.

Run them from the project folder:

    pytest -v
"""

import random
from collections import Counter

import pytest

from src.generator.generate import build_batch
from src.validation.config import DEFECT_TO_RULE, RULES, band
from src.validation.engine import evaluate, evaluate_batch


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def make_record(**overrides) -> dict:
    """A tiny record that is consistent in every way, to build test cases from."""
    record = {
        "record_id": "T0001",
        "village": "तुळजामाळ",
        "survey_number": "101",
        "hissa_number": None,
        "total_area": 1.00,
        "cultivable_area": 0.90,
        "pot_kharaba": 0.10,
        "owners": [
            {"name": "A. Patil", "share_area": 0.60},
            {"name": "B. Jadhav", "share_area": 0.40},
        ],
        "mutations": [
            {"mutation_number": "101", "date": "2001-01-01", "type": "sale",
             "from_owner": "A. Patil", "to_owner": "B. Jadhav", "area": 0.40},
            {"mutation_number": "102", "date": "2005-01-01", "type": "sale",
             "from_owner": "B. Jadhav", "to_owner": "C. More", "area": 0.10},
        ],
        "hissa_record_ids": [],
        "defects": [],
    }
    record.update(overrides)
    return record


def result_for(report, rule_id):
    """The one RuleResult with this rule id."""
    return next(result for result in report.results if result.rule_id == rule_id)


# --------------------------------------------------------------------------
# the config itself
# --------------------------------------------------------------------------
def test_weights_add_up_to_100():
    assert sum(rule["weight"] for rule in RULES.values()) == 100


def test_bands_go_green_amber_red():
    assert band(0) == ("Low", "green")
    assert band(1)[1] == "amber"
    assert band(19)[1] == "amber"
    assert band(20)[1] == "red"        # the lightest high-severity weight
    assert band(100)[1] == "red"


def test_every_high_severity_rule_alone_turns_a_record_red():
    """The colours have to line up with the severities, or nobody trusts them."""
    from src.validation.config import RED_FROM
    for rule_id, rule in RULES.items():
        if rule["severity"] == "high":
            assert rule["weight"] >= RED_FROM, f"{rule_id} is high but would show amber"


# --------------------------------------------------------------------------
# one rule at a time, on hand-written records
# --------------------------------------------------------------------------
def test_a_consistent_record_scores_zero():
    report = evaluate(make_record())
    assert report.score == 0
    assert report.failed == []
    assert report.band_colour == "green"


def test_area_balance_catches_a_mismatch():
    record = make_record(pot_kharaba=0.30)          # 0.90 + 0.30 != 1.00
    result = result_for(evaluate(record), "R2_area_balance")
    assert result.failed
    assert "0.20 ha more" in result.explanation      # the number is in the text


def test_a_rounding_difference_is_forgiven():
    record = make_record(pot_kharaba=0.11)          # one are over: inside tolerance
    assert not result_for(evaluate(record), "R2_area_balance").failed


def test_owner_shares_must_add_up():
    record = make_record(owners=[{"name": "A. Patil", "share_area": 0.60},
                                 {"name": "B. Jadhav", "share_area": 0.60}])
    result = result_for(evaluate(record), "R3_owner_shares")
    assert result.failed
    assert "1.20 ha" in result.explanation


def test_a_mutation_by_a_stranger_is_caught():
    record = make_record()
    record["mutations"][1]["from_owner"] = "Somebody Else"
    result = result_for(evaluate(record), "R4_mutation_chain")
    assert result.failed
    assert "Somebody Else" in result.explanation


def test_out_of_order_mutation_dates_are_caught():
    record = make_record()
    record["mutations"][1]["date"] = "1999-01-01"    # before the one above it
    result = result_for(evaluate(record), "R5_mutation_dates")
    assert result.failed
    assert "01/01/1999" in result.explanation


def test_hissa_rule_is_skipped_when_there_are_no_subdivisions():
    assert result_for(evaluate(make_record()), "R1_hissa_area").status == "skipped"


def test_hissa_areas_must_add_up_to_the_parent():
    parent = make_record(record_id="P1", total_area=1.00, hissa_record_ids=["C1", "C2"])
    family = {
        "P1": parent,
        "C1": make_record(record_id="C1", total_area=0.40),
        "C2": make_record(record_id="C2", total_area=0.45),     # 0.85, not 1.00
    }
    result = result_for(evaluate(parent, family), "R1_hissa_area")
    assert result.failed
    assert "0.15 ha less" in result.explanation


def test_the_same_parcel_on_two_records_is_flagged():
    first = make_record(record_id="A1", survey_number="101")
    second = make_record(record_id="A2", survey_number="101")     # same village too
    batch = {"A1": first, "A2": second}
    result = result_for(evaluate(first, batch), "R6_duplicate_parcel")
    assert result.failed
    assert "A2" in result.explanation


def test_two_different_parcels_are_not_duplicates():
    first = make_record(record_id="A1", survey_number="101")
    second = make_record(record_id="A2", survey_number="102")
    batch = {"A1": first, "A2": second}
    assert not result_for(evaluate(first, batch), "R6_duplicate_parcel").failed


def test_hissas_of_one_survey_number_are_not_duplicates():
    # 101/1 and 101/2 share a survey number but are different parcels.
    first = make_record(record_id="A1", survey_number="101", hissa_number="1")
    second = make_record(record_id="A2", survey_number="101", hissa_number="2")
    batch = {"A1": first, "A2": second}
    assert not result_for(evaluate(first, batch), "R6_duplicate_parcel").failed


def test_a_rule_skips_instead_of_crashing_when_a_field_is_missing():
    # Phase 4 will hand us records where OCR could not read something.
    record = make_record(total_area=None)
    report = evaluate(record)
    assert result_for(report, "R2_area_balance").status == "skipped"
    assert report.score == 0        # unreadable is not the same as wrong


# --------------------------------------------------------------------------
# the whole generated batch
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def batch():
    """A generated batch, built in memory: the records only, no rendering."""
    rng = random.Random(7)
    records, _families, _injected = build_batch(rng, count=300, defect_rate=0.30)
    return {record["record_id"]: record for record in records}


def test_every_injected_defect_is_caught(batch):
    reports = evaluate_batch(batch)
    missed = []
    for record_id, record in batch.items():
        failed_rules = {result.rule_id for result in reports[record_id].failed}
        for defect in record["defects"]:
            if DEFECT_TO_RULE[defect["type"]] not in failed_rules:
                missed.append((record_id, defect["type"]))
    assert missed == [], f"defects the rules did not catch: {missed}"


def test_clean_records_are_never_flagged(batch):
    reports = evaluate_batch(batch)
    flagged = [(record_id, [r.rule_id for r in reports[record_id].failed])
               for record_id, record in batch.items()
               if not record["defects"] and reports[record_id].failed]
    assert flagged == [], f"clean records wrongly flagged: {flagged}"


def test_score_is_exactly_the_sum_of_failed_weights(batch):
    for report in evaluate_batch(batch).values():
        expected = min(100, sum(result.weight for result in report.failed))
        assert report.score == expected


def test_detection_rate_per_rule(batch, capsys):
    """Measure, and print, how many of each defect type the rules caught."""
    reports = evaluate_batch(batch)
    injected, caught, false_alarms = Counter(), Counter(), Counter()

    for record_id, record in batch.items():
        expected = {DEFECT_TO_RULE[d["type"]] for d in record["defects"]}
        for rule_id in expected:
            injected[rule_id] += 1
        for result in reports[record_id].failed:
            if result.rule_id in expected:
                caught[result.rule_id] += 1
            else:
                false_alarms[result.rule_id] += 1

    with capsys.disabled():
        print(f"\n\n  detection over {len(batch)} generated records")
        print(f"  {'rule':<20} {'injected':>9} {'caught':>7} {'rate':>8} {'false':>7}")
        for rule_id in RULES:
            total = injected[rule_id]
            rate = f"{caught[rule_id] / total * 100:.1f}%" if total else "-"
            print(f"  {rule_id:<20} {total:>9} {caught[rule_id]:>7} {rate:>8} "
                  f"{false_alarms[rule_id]:>7}")
        print()

    for rule_id in RULES:
        assert injected[rule_id] > 0, f"{rule_id} was never exercised by the batch"
        assert caught[rule_id] == injected[rule_id], f"{rule_id} missed a defect"
        assert false_alarms[rule_id] == 0, f"{rule_id} fired on a record with no such defect"
