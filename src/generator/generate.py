"""Generate synthetic 7/12 extracts: one image plus one ground-truth file each.

Run from the project folder, with the virtual environment active:

    python -m src.generator.generate                       # 200 records, 30% defective
    python -m src.generator.generate --count 20 --seed 1   # a quick small batch
    python -m src.generator.generate --no-degrade          # crisp pages, no scanner wear

It writes into data/synthetic/ :

    images/R0001.jpg          the picture of the extract
    ground_truth/R0001.json   what that extract really says, and any defect in it
    manifest.json             one entry per record, for the UI and the tests

The ground truth is the point of the whole phase: because we know what each
image says and exactly how it was broken, Phase 2 can measure whether the
rules catch the faults, and Phase 4 can measure how well the OCR reads.
"""

import argparse
import itertools
import json
import random
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import defects, layout
from .degrade import clean_jpeg, degrade
from .record import make_family
from .render import SheetRenderer

FONT_SIZES = [14, 15, 16]        # small variation, so OCR is not tuned to one size


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate synthetic Maharashtra 7/12 extracts with ground truth.")
    parser.add_argument("--count", type=int, default=200,
                        help="how many records to generate (default: 200)")
    parser.add_argument("--defect-rate", type=float, default=0.30,
                        help="share of records carrying a defect, 0 to 1 (default: 0.30)")
    parser.add_argument("--seed", type=int, default=42,
                        help="same seed gives exactly the same batch (default: 42)")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"),
                        help="output folder (default: data/synthetic)")
    parser.add_argument("--no-degrade", action="store_true",
                        help="keep the pages crisp instead of adding scanner wear")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace a batch that is already in the output folder")
    return parser.parse_args(argv)


def build_batch(rng: random.Random, count: int, defect_rate: float):
    """Create the records, then damage some of them on purpose.

    Records are built in families (a survey number and its hissa records), so
    we keep generating whole families until we have at least `count` records.
    """
    records, families = [], []
    used_keys = set()                       # village/survey pairs already used
    numbers = itertools.count(1)
    next_record_id = lambda: f"R{next(numbers):04d}"        # noqa: E731

    while len(records) < count:
        family = make_family(rng, f"F{len(families) + 1:04d}", next_record_id, used_keys)
        families.append(family)
        records.extend(family)

    # Damage at most one thing per family, until enough records are defective.
    target = round(defect_rate * len(records))
    injected = defects.inject_balanced(rng, families, target, next_record_id)

    # The duplicate defect adds a record, so rebuild the list from the families.
    records = [record for family in families for record in family]
    return records, families, injected


def prepare_output(out: Path, overwrite: bool):
    """Make the output folders, refusing to silently replace an existing batch."""
    images_dir, truth_dir = out / "images", out / "ground_truth"
    existing = list(images_dir.glob("*.jpg")) if images_dir.exists() else []
    if existing and not overwrite:
        print(f"'{out}' already holds {len(existing)} images from an earlier run.")
        print("Re-run with --overwrite to replace them, or use --out to write elsewhere.")
        return None
    if existing:
        print(f"Removing the previous batch of {len(existing)} records from '{out}'.")
        shutil.rmtree(images_dir, ignore_errors=True)
        shutil.rmtree(truth_dir, ignore_errors=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    return images_dir, truth_dir


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.count < 1:
        print("--count must be at least 1")
        return 1
    if not 0.0 <= args.defect_rate <= 1.0:
        print("--defect-rate must be between 0 and 1")
        return 1

    folders = prepare_output(args.out, args.overwrite)
    if folders is None:
        return 1
    images_dir, truth_dir = folders

    rng = random.Random(args.seed)
    records, families, injected = build_batch(rng, args.count, args.defect_rate)
    print(f"Rendering {len(records)} records "
          f"({len(families)} survey numbers) with a headless browser...")

    started = time.time()
    with SheetRenderer() as renderer:
        for index, record in enumerate(records, start=1):
            page_html = layout.record_to_html(record, font_px=rng.choice(FONT_SIZES))
            png_bytes = renderer.render(page_html)
            image_bytes = clean_jpeg(png_bytes) if args.no_degrade else degrade(png_bytes, rng)

            record["image_file"] = f"images/{record['record_id']}.jpg"
            (images_dir / f"{record['record_id']}.jpg").write_bytes(image_bytes)
            (truth_dir / f"{record['record_id']}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            if index % 20 == 0 or index == len(records):
                print(f"  {index}/{len(records)} records", flush=True)
    elapsed = time.time() - started

    defective = [r for r in records if r["defects"]]
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "requested_count": args.count,
        "record_count": len(records),
        "family_count": len(families),
        "defect_rate_requested": args.defect_rate,
        "defective_records": len(defective),
        "defect_counts": dict(injected),
        "degraded": not args.no_degrade,
        "records": [
            {
                "record_id": r["record_id"],
                "family_id": r["family_id"],
                "role": r["role"],
                "village": r["village"],
                "survey_number": r["survey_number"],
                "hissa_number": r["hissa_number"],
                "image": r["image_file"],
                "ground_truth": f"ground_truth/{r['record_id']}.json",
                "defects": [d["type"] for d in r["defects"]],
            }
            for r in records
        ],
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    share = len(defective) / len(records) * 100
    print(f"\nDone in {elapsed:.0f} s  ({elapsed / len(records):.2f} s per record)")
    print(f"  folder            : {args.out}")
    print(f"  records           : {len(records)} in {len(families)} survey numbers")
    print(f"  clean records     : {len(records) - len(defective)}")
    print(f"  defective records : {len(defective)} ({share:.1f}%)")
    for kind, number in sorted(injected.items(), key=lambda kv: -kv[1]):
        print(f"      {kind:<28} {number}")
    print(f"  scanner wear      : {'no (--no-degrade)' if args.no_degrade else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
