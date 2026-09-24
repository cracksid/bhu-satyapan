"""Measure the OCR against the generator's ground truth, and say so plainly.

    python -m src.ocr.evaluate --count 15

Three numbers, reported separately because they answer different questions:

  * character error rate - how well Tesseract reads Marathi text on these
    scans. One wrong letter in a name still shows up here.
  * field-level accuracy - how often a whole field arrives exactly right,
    which is what actually matters for a record.
  * score agreement - how often the dispute-risk score computed from what OCR
    read matches the score computed from the true record. This is the one to
    care about: it is the end-to-end question.

Nothing here rounds a result in the pipeline's favour.
"""

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from ..validation.engine import evaluate as score_record
from .extract import extract_from_file

TEXT_FIELDS = ["village", "taluka", "district"]
VALUE_FIELDS = ["record_id", "survey_number", "hissa_number", "khata_number",
                "tenure_class", "total_area", "cultivable_area", "pot_kharaba",
                "assessment"]


def levenshtein(first: str, second: str) -> int:
    """How many single-character edits turn one string into the other."""
    if first == second:
        return 0
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, start=1):
        current = [i]
        for j, b in enumerate(second, start=1):
            current.append(min(previous[j] + 1,          # delete
                               current[j - 1] + 1,       # insert
                               previous[j - 1] + (a != b)))  # substitute
        previous = current
    return previous[-1]


def same_value(expected, found) -> bool:
    """Exact match, with numbers compared at the precision the form prints."""
    if expected is None or found is None:
        return expected is None and found is None
    if isinstance(expected, float) or isinstance(found, float):
        try:
            return abs(float(expected) - float(found)) < 0.005
        except (TypeError, ValueError):
            return False
    return str(expected).strip() == str(found).strip()


def bucket_of(confidence: float) -> str:
    """Group a confidence score, to see whether it predicts correctness."""
    if confidence < 0:
        return "not read"
    if confidence < 70:
        return "under 70"
    if confidence < 80:
        return "70 to 79"
    if confidence < 90:
        return "80 to 89"
    return "90 and up"


def compare(truth: dict, read: dict, character_errors: dict, fields: dict,
            buckets: dict | None = None):
    """Add one record's results into the running totals."""
    for field in TEXT_FIELDS:
        expected, found = str(truth.get(field) or ""), str(read.get(field) or "")
        character_errors[field][0] += levenshtein(expected, found)
        character_errors[field][1] += len(expected)
        fields[field][0] += int(expected == found)
        fields[field][1] += 1

    confidences = read.get("_confidence", {})
    for field in VALUE_FIELDS:
        correct = same_value(truth.get(field), read.get(field))
        fields[field][0] += int(correct)
        fields[field][1] += 1
        if buckets is not None and field in ("total_area", "cultivable_area",
                                             "pot_kharaba", "assessment"):
            bucket = buckets[bucket_of(confidences.get(field, -1.0))]
            bucket[0] += int(correct)
            bucket[1] += 1

    # Owners: the count first, then name and share for the ones we can pair up.
    true_owners, read_owners = truth["owners"], read["owners"]
    fields["owner count"][0] += int(len(true_owners) == len(read_owners))
    fields["owner count"][1] += 1
    for expected_owner, found_owner in zip(true_owners, read_owners):
        expected_name, found_name = expected_owner["name"], found_owner["name"] or ""
        character_errors["owner name"][0] += levenshtein(expected_name, found_name)
        character_errors["owner name"][1] += len(expected_name)
        fields["owner name"][0] += int(expected_name == found_name)
        fields["owner name"][1] += 1
        share_correct = same_value(expected_owner["share_area"], found_owner["share_area"])
        fields["owner share"][0] += int(share_correct)
        fields["owner share"][1] += 1
        if buckets is not None:
            bucket = buckets[bucket_of(
                found_owner.get("_confidence", {}).get("share_area", -1.0))]
            bucket[0] += int(share_correct)
            bucket[1] += 1

    true_mutations, read_mutations = truth["mutations"], read["mutations"]
    fields["mutation count"][0] += int(len(true_mutations) == len(read_mutations))
    fields["mutation count"][1] += 1
    for expected_mutation, found_mutation in zip(true_mutations, read_mutations):
        for key, label in (("mutation_number", "mutation number"), ("date", "mutation date"),
                           ("area", "mutation area")):
            correct = same_value(expected_mutation[key], found_mutation.get(key))
            fields[label][0] += int(correct)
            fields[label][1] += 1
            if buckets is not None and key in ("mutation_number", "area"):
                bucket = buckets[bucket_of(
                    found_mutation.get("_confidence", {}).get(key, -1.0))]
                bucket[0] += int(correct)
                bucket[1] += 1
        for key, label in (("from_owner", "mutation from"), ("to_owner", "mutation to")):
            expected_name = expected_mutation[key]
            found_name = found_mutation.get(key) or ""
            character_errors[label][0] += levenshtein(expected_name, found_name)
            character_errors[label][1] += len(expected_name)
            fields[label][0] += int(expected_name == found_name)
            fields[label][1] += 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Measure OCR against the ground truth.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--count", type=int, default=15,
                        help="how many records to read (default: 15)")
    parser.add_argument("--seed", type=int, default=3, help="which records to sample")
    args = parser.parse_args(argv)

    truth_files = sorted((args.data / "ground_truth").glob("*.json"))
    if not truth_files:
        print(f"No records in {args.data}. Generate a batch first.")
        return 1
    chosen = random.Random(args.seed).sample(truth_files, min(args.count, len(truth_files)))

    character_errors = defaultdict(lambda: [0, 0])     # field -> [edits, characters]
    fields = defaultdict(lambda: [0, 0])               # field -> [correct, total]
    buckets = defaultdict(lambda: [0, 0])              # confidence band -> [correct, total]
    score_matches = 0
    band_matches = 0
    fully_checked = 0
    routed_to_human = 0
    seconds = 0.0

    print(f"Reading {len(chosen)} records from {args.data} ...\n")
    for index, path in enumerate(chosen, start=1):
        truth = json.loads(path.read_text(encoding="utf-8"))
        image = args.data / "images" / f"{truth['record_id']}.jpg"

        started = time.time()
        read = extract_from_file(image)
        seconds += time.time() - started

        compare(truth, read, character_errors, fields, buckets)

        truth_report = score_record(truth, {})
        read_report = score_record(read, {})
        unsure = [result for result in read_report.results if result.needs_human]
        if unsure:
            routed_to_human += 1
        else:
            fully_checked += 1
            score_matches += int(truth_report.score == read_report.score)
            band_matches += int(truth_report.band_label == read_report.band_label)

        print(f"  {index:>3}/{len(chosen)}  {truth['record_id']}  "
              f"true score {truth_report.score:>3}  |  from OCR {read_report.score:>3}"
              f"   ({read['_ocr']['seconds']} s, mean confidence "
              f"{read['_ocr']['mean_confidence']})")

    total_edits = sum(edits for edits, _ in character_errors.values())
    total_characters = sum(count for _, count in character_errors.values())
    print(f"\nCHARACTER ERROR RATE (Marathi text fields)")
    print(f"  {'field':<18} {'edits':>7} {'chars':>7} {'CER':>8}")
    for field, (edits, count) in sorted(character_errors.items()):
        rate = edits / count * 100 if count else 0.0
        print(f"  {field:<18} {edits:>7} {count:>7} {rate:>7.1f}%")
    overall = total_edits / total_characters * 100 if total_characters else 0.0
    print(f"  {'OVERALL':<18} {total_edits:>7} {total_characters:>7} {overall:>7.1f}%")

    print(f"\nFIELD-LEVEL ACCURACY (exact match)")
    print(f"  {'field':<18} {'correct':>8} {'of':>6} {'accuracy':>10}")
    for field, (correct, total) in fields.items():
        rate = correct / total * 100 if total else 0.0
        print(f"  {field:<18} {correct:>8} {total:>6} {rate:>9.1f}%")
    correct_total = sum(correct for correct, _ in fields.values())
    checked_total = sum(total for _, total in fields.values())
    print(f"  {'OVERALL':<18} {correct_total:>8} {checked_total:>6} "
          f"{correct_total / checked_total * 100:>9.1f}%")

    print(f"\nDOES CONFIDENCE PREDICT CORRECTNESS? (numeric fields)")
    print(f"  {'confidence':<12} {'correct':>8} {'of':>6} {'accuracy':>10}")
    for band in ("not read", "under 70", "70 to 79", "80 to 89", "90 and up"):
        correct, total = buckets.get(band, [0, 0])
        rate = f"{correct / total * 100:.1f}%" if total else "-"
        print(f"  {band:<12} {correct:>8} {total:>6} {rate:>10}")

    print(f"\nEND TO END")
    print(f"  checked automatically : {fully_checked}/{len(chosen)} "
          f"({fully_checked / len(chosen) * 100:.0f}%) - every field a rule needed "
          f"was read confidently")
    print(f"  sent to a human       : {routed_to_human}/{len(chosen)} "
          f"({routed_to_human / len(chosen) * 100:.0f}%) - at least one figure was "
          f"too doubtful to judge")
    if fully_checked:
        print(f"  of those checked, identical risk score : {score_matches}/{fully_checked} "
              f"({score_matches / fully_checked * 100:.0f}%)")
        print(f"  of those checked, identical risk band  : {band_matches}/{fully_checked} "
              f"({band_matches / fully_checked * 100:.0f}%)")
    print(f"  average time          : {seconds / len(chosen):.1f} s per page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
