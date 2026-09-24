"""Score a whole batch and show how well the rules did against the ground truth.

    python -m src.validation.report                      # data/synthetic
    python -m src.validation.report --data data/demo --show 3

Because the generator wrote down every defect it injected, this can report a
real detection rate per rule, and show whether clean records are being flagged
by mistake. Those two numbers are what makes the engine believable.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from .config import DEFECT_TO_RULE, RULES
from .engine import evaluate_batch, load_records


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Score a batch of records and measure the rules against ground truth.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"),
                        help="folder holding the records (default: data/synthetic)")
    parser.add_argument("--show", type=int, default=2,
                        help="how many flagged records to print in full (default: 2)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        records = load_records(args.data)
    except FileNotFoundError as error:
        print(error)
        return 1

    reports = evaluate_batch(records)
    print(f"Scored {len(records)} records from {args.data}\n")

    # --- how the scores came out ---------------------------------------- #
    bands = Counter(report.band_colour for report in reports.values())
    print("Risk bands")
    for colour, label in (("green", "clean (0)"), ("amber", "Medium (1-24)"),
                          ("red", "High (25-100)")):
        print(f"  {colour:<6} {label:<16} {bands[colour]:>4}")

    # --- did the rules catch what was injected? -------------------------- #
    injected = Counter()
    caught = Counter()
    false_alarms = Counter()
    for record_id, record in records.items():
        report = reports[record_id]
        declared = {defect["type"] for defect in record.get("defects", [])}
        expected_rules = {DEFECT_TO_RULE[kind] for kind in declared}
        for rule_id in expected_rules:
            injected[rule_id] += 1
        for result in report.failed:
            if result.rule_id in expected_rules:
                caught[result.rule_id] += 1
            else:
                false_alarms[result.rule_id] += 1

    print("\nDetection against the generator's ground truth")
    print(f"  {'rule':<20} {'injected':>9} {'caught':>7} {'missed':>7} "
          f"{'rate':>8} {'false alarms':>13}")
    for rule_id in RULES:
        total, hit = injected[rule_id], caught[rule_id]
        rate = f"{hit / total * 100:.1f}%" if total else "-"
        print(f"  {rule_id:<20} {total:>9} {hit:>7} {total - hit:>7} {rate:>8} "
              f"{false_alarms[rule_id]:>13}")
    total_injected, total_caught = sum(injected.values()), sum(caught.values())
    overall = f"{total_caught / total_injected * 100:.1f}%" if total_injected else "-"
    print(f"  {'TOTAL':<20} {total_injected:>9} {total_caught:>7} "
          f"{total_injected - total_caught:>7} {overall:>8} "
          f"{sum(false_alarms.values()):>13}")

    clean_ids = [rid for rid, rec in records.items() if not rec.get("defects")]
    wrongly_flagged = [rid for rid in clean_ids if reports[rid].failed]
    print(f"\nClean records wrongly flagged: {len(wrongly_flagged)} of {len(clean_ids)}")
    for record_id in wrongly_flagged[:5]:
        print(f"  {reports[record_id].headline()}")

    # --- a couple of flagged records in full ----------------------------- #
    flagged = [report for report in reports.values() if report.failed]
    for report in flagged[: args.show]:
        print(f"\n{report.headline()}")
        for result in report.failed:
            print(f"  [FAIL {result.weight:>2} pts, {result.severity}] {result.title}")
            print(f"         {result.explanation}")
            print(f"         fields: {', '.join(result.fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
