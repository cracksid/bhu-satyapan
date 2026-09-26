"""Cached OCR results, so a demo never depends on the room's wi-fi or luck.

Reading a page takes about 15 seconds and needs Tesseract installed. That is
fine at a desk and wrong in front of judges, so the results for the demo
records are computed once and stored in data/demo_cache.json.

Build the cache (needs Tesseract, takes a few seconds per record):

    python -m src.demo build                 # the records named in DEMO_RECORDS
    python -m src.demo build R0013 R0044     # or whichever you name
    python -m src.demo list                  # what is cached now

Then, during the demo:

    $env:BHU_DEMO_MODE = "1"
    streamlit run src/app.py

With BHU_DEMO_MODE set, the app serves cached results only and never calls
Tesseract - so it cannot stall, and it works with the network switched off.
Without it, the cache is still used when a record is in it, and anything else
is read live.
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CACHE_FILE = PROJECT_ROOT / "data" / "demo_cache.json"

# The two records the demo walks through: one that passes everything, one that
# fails loudly. Filled in by "python -m src.demo pick".
DEMO_RECORDS_FILE = PROJECT_ROOT / "data" / "demo_records.json"


def tesseract_available() -> bool:
    """Is the OCR engine installed on this machine?"""
    import shutil
    if shutil.which("tesseract"):
        return True
    return Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()


def demo_mode() -> bool:
    """Should OCR come only from the cache?

    True when BHU_DEMO_MODE is set, and also whenever Tesseract is missing -
    which is the case on a hosted server. There, cached readings are the only
    thing that can work, and falling back to them beats an error page.
    """
    if os.environ.get("BHU_DEMO_MODE", "").strip() in {"1", "true", "yes", "on"}:
        return True
    return not tesseract_available()


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def demo_records() -> dict:
    """The showcase records: {"clean": "R0007", "flagged": "R0013"}."""
    if DEMO_RECORDS_FILE.exists():
        return json.loads(DEMO_RECORDS_FILE.read_text(encoding="utf-8"))
    return {}


def cached_reading(record_id: str):
    """What OCR read for this record last time, or None."""
    return load_cache().get(record_id)


def read_record(record_id: str, image_path) -> dict:
    """The OCR reading for a record: from the cache if possible.

    In demo mode a missing record is an error rather than a 15-second pause,
    because that pause in front of an audience is the thing we are avoiding.
    """
    cached = cached_reading(record_id)
    if cached is not None:
        cached["_ocr"] = {**cached.get("_ocr", {}), "from_cache": True}
        return cached
    if demo_mode():
        raise KeyError(
            f"{record_id} is not in the demo cache and demo mode is on. "
            f"Run:  python -m src.demo build {record_id}")

    from src.ocr.extract import extract_from_file
    return extract_from_file(image_path)


# --------------------------------------------------------------------------
def build(record_ids: list) -> int:
    from src.ocr.extract import extract_from_file

    images = PROJECT_ROOT / "data" / "synthetic" / "images"
    cache = load_cache()
    for record_id in record_ids:
        image = images / f"{record_id}.jpg"
        if not image.exists():
            print(f"  {record_id}: no image at {image}")
            return 1
        print(f"  reading {record_id} ...", flush=True)
        cache[record_id] = extract_from_file(image)
    save_cache(cache)
    print(f"Cached {len(record_ids)} record(s) in {CACHE_FILE}")
    return 0


def pick(limit: int = 4) -> int:
    """Choose the two showcase records, and check OCR handles them too.

    A demo record has to work in both modes: the clean one must come out clean
    even when read from the scan, and the flagged one must still be flagged
    for the same reason. Candidates that only look right on paper are no use
    in front of an audience, so each one is actually read before it is chosen.
    """
    from src.ocr.extract import extract_from_file
    from src.validation.config import DEFECT_TO_RULE, RED_FROM
    from src.validation.engine import evaluate, evaluate_batch, load_records

    data = PROJECT_ROOT / "data" / "synthetic"
    records = load_records(data)
    reports = evaluate_batch(records)

    clean = [rid for rid, record in records.items()
             if not record["defects"] and record["hissa_record_ids"]
             and len(record["owners"]) >= 2][:limit]
    # Defects a viewer can see on the page for themselves.
    visible = {"owner_share_mismatch", "broken_mutation_chain", "duplicate_record"}
    flagged = [rid for rid, record in records.items()
               if reports[rid].score >= RED_FROM
               and {d["type"] for d in record["defects"]} & visible][:limit]

    chosen, cache = {}, load_cache()
    for label, candidates in (("clean", clean), ("flagged", flagged)):
        print(f"\ntrying {label} candidates: {', '.join(candidates) or 'none'}")
        for record_id in candidates:
            reading = extract_from_file(data / "images" / f"{record_id}.jpg")
            report = evaluate(reading, {})
            failed = {result.rule_id for result in report.failed}
            if label == "clean":
                good = not failed
                why = "no rule fired on the OCR reading" if good else f"OCR flagged {failed}"
            else:
                wanted = {DEFECT_TO_RULE[d["type"]] for d in records[record_id]["defects"]}
                good = bool(failed & wanted)
                why = (f"OCR still flags {sorted(failed & wanted)}" if good
                       else "OCR did not reproduce the flag")
            print(f"  {record_id}: {why}")
            if good:
                chosen[label] = record_id
                cache[record_id] = reading
                break

    if len(chosen) < 2:
        print("\nCould not find a working record for both roles. "
              "Try again after regenerating, or pick by hand.")
        return 1

    DEMO_RECORDS_FILE.write_text(json.dumps(chosen, indent=1), encoding="utf-8")
    save_cache(cache)
    print(f"\nShowcase records: {chosen}")
    print(f"Written to {DEMO_RECORDS_FILE}, readings cached in {CACHE_FILE}")
    return 0


def dataset(size: int = 30) -> int:
    """Copy a small, self-contained batch into data/demo_dataset.

    The hosted app has no generator and no OCR engine, so it needs records in
    the repository. Families are kept whole: rule 1 compares a survey number
    against its hissa records and rule 6 compares parcels across the batch, so
    half a family would make the app show flags that are not really there.
    """
    import shutil

    source = PROJECT_ROOT / "data" / "synthetic"
    target = PROJECT_ROOT / "data" / "demo_dataset"
    truth_files = sorted((source / "ground_truth").glob("*.json"))
    if not truth_files:
        print(f"No records in {source}. Run:  python -m src.generator.generate")
        return 1

    records = {}
    for path in truth_files:
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["record_id"]] = record

    families = {}
    for record in records.values():
        families.setdefault(record["family_id"], []).append(record)

    # Start with the showcase records' families, then add variety: one family
    # per defect type, then clean ones to fill the rest.
    chosen_families, wanted = [], set(demo_records().values())
    for family_id, members in families.items():
        if any(member["record_id"] in wanted for member in members):
            chosen_families.append(family_id)

    seen_defects = set()
    for family_id, members in families.items():
        if family_id in chosen_families:
            continue
        kinds = {d["type"] for member in members for d in member["defects"]}
        if kinds - seen_defects:
            seen_defects |= kinds
            chosen_families.append(family_id)

    for family_id, members in families.items():
        if sum(len(families[f]) for f in chosen_families) >= size:
            break
        if family_id not in chosen_families and not any(m["defects"] for m in members):
            chosen_families.append(family_id)

    # Clean families first, above, so a small dataset stays calm to look at.
    # Anything still missing is defective; take it only if there is room, which
    # is how asking for the whole batch copies every record.
    for family_id in families:
        if sum(len(families[f]) for f in chosen_families) >= size:
            break
        if family_id not in chosen_families:
            chosen_families.append(family_id)

    shutil.rmtree(target, ignore_errors=True)
    (target / "images").mkdir(parents=True)
    (target / "ground_truth").mkdir(parents=True)

    copied = 0
    for family_id in chosen_families:
        for member in families[family_id]:
            record_id = member["record_id"]
            shutil.copy2(source / "ground_truth" / f"{record_id}.json",
                         target / "ground_truth" / f"{record_id}.json")
            shutil.copy2(source / "images" / f"{record_id}.jpg",
                         target / "images" / f"{record_id}.jpg")
            copied += 1

    megabytes = sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) / 1_048_576
    print(f"Copied {copied} records ({len(chosen_families)} whole families, "
          f"{megabytes:.1f} MB) into {target}")
    return 0


def show() -> int:
    cache = load_cache()
    if not cache:
        print(f"Nothing cached yet. Run:  python -m src.demo build")
        return 0
    print(f"{len(cache)} record(s) cached in {CACHE_FILE}:")
    for record_id, reading in sorted(cache.items()):
        meta = reading.get("_ocr", {})
        print(f"  {record_id}  read in {meta.get('seconds', '?')} s, "
              f"mean confidence {meta.get('mean_confidence', '?')}")
    chosen = demo_records()
    if chosen:
        print(f"\nShowcase records: {chosen}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cache OCR results for the demo.")
    parser.add_argument("command", choices=["build", "list", "pick", "dataset"],
                        help="build the cache, list it, pick showcase records, "
                             "or copy a small dataset for the hosted app")
    parser.add_argument("records", nargs="*", help="record ids, e.g. R0013")
    args = parser.parse_args(argv)

    if args.command == "list":
        return show()
    if args.command == "pick":
        return pick()
    if args.command == "dataset":
        # "dataset 210" copies the whole batch; "dataset" keeps it small.
        if not args.records:
            return dataset()
        if not args.records[0].isdigit():
            print(f"How many records? e.g.  python -m src.demo dataset 210")
            return 1
        return dataset(int(args.records[0]))

    record_ids = args.records or list(demo_records().values())
    if not record_ids:
        print("No records given and no showcase records chosen yet.\n"
              "Run:  python -m src.demo build R0001 R0013")
        return 1
    return build(record_ids)


if __name__ == "__main__":
    sys.exit(main())
