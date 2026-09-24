"""Run every rule over a record and turn the failures into a dispute-risk score.

The score is a weighted sum: each failed rule adds its weight from
config.RULES, and the weights add up to 100. Nothing is invented here - if a
record scores 45, it is because exactly these rules failed and their weights
add to 45, which is what makes the number defensible to a revenue officer.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import band
from .rules import ALL_RULES, FAIL, PASS, SKIPPED


@dataclass
class Report:
    """The verdict on one record."""
    record_id: str
    score: int                 # 0-100
    band_label: str            # "Low", "Medium" or "High"
    band_colour: str           # "green", "amber" or "red"
    results: list              # every RuleResult, in rule order

    @property
    def failed(self) -> list:
        return [result for result in self.results if result.status == FAIL]

    @property
    def passed(self) -> list:
        return [result for result in self.results if result.status == PASS]

    @property
    def skipped(self) -> list:
        return [result for result in self.results if result.status == SKIPPED]

    def headline(self) -> str:
        if not self.failed:
            return (f"{self.record_id}: no inconsistencies found "
                    f"({len(self.passed)} checks passed, {len(self.skipped)} not applicable).")
        return (f"{self.record_id}: dispute risk {self.score}/100 ({self.band_label}) - "
                f"{len(self.failed)} of {len(self.results)} checks failed.")


def evaluate(record: dict, family: dict | None = None) -> Report:
    """Score one record. `family` maps record_id -> record for rule 1's siblings."""
    results = [rule(record, family or {}) for rule in ALL_RULES]
    score = min(100, sum(result.weight for result in results if result.failed))
    label, colour = band(score)
    return Report(record.get("record_id", "?"), score, label, colour, results)


def evaluate_batch(records: dict) -> dict:
    """Score every record. Pass them all in, so rule 1 can find the hissa records."""
    return {record_id: evaluate(record, records) for record_id, record in records.items()}


def load_records(folder) -> dict:
    """Read a folder of ground-truth JSON files into {record_id: record}.

    Accepts either data/synthetic or data/synthetic/ground_truth.
    """
    folder = Path(folder)
    if folder.name != "ground_truth" and (folder / "ground_truth").is_dir():
        folder = folder / "ground_truth"
    if not folder.is_dir():
        raise FileNotFoundError(
            f"No records folder at '{folder}'. Generate a batch first:\n"
            f"    python -m src.generator.generate")

    records = {}
    for path in sorted(folder.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["record_id"]] = record
    if not records:
        raise FileNotFoundError(f"'{folder}' holds no .json records.")
    return records
