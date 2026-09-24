"""The five consistency checks, run on a record as structured data.

Nothing here touches an image. A rule takes the record - and, for rule 1, the
other records of the same survey number - and returns a RuleResult saying
what it found, in plain English, naming the fields it looked at.

That separation is the point: the rules can be trusted and tested on their
own, long before OCR is anywhere near them. In Phase 4 the same rules will
run on whatever the OCR managed to read, which is why every rule skips
politely when a field it needs is missing, instead of crashing or guessing.
"""

from dataclasses import dataclass

from . import config
from .config import AREA_TOLERANCE_HA, RULES

PASS, FAIL, SKIPPED = "pass", "fail", "skipped"


@dataclass
class RuleResult:
    """What one rule found on one record."""
    rule_id: str
    status: str            # PASS, FAIL or SKIPPED
    explanation: str       # plain English, with the actual numbers in it
    fields: list           # the record fields this rule looked at

    @property
    def title(self) -> str:
        return RULES[self.rule_id]["title"]

    @property
    def severity(self) -> str:
        return RULES[self.rule_id]["severity"]

    @property
    def weight(self) -> int:
        return RULES[self.rule_id]["weight"]

    @property
    def why_it_matters(self) -> str:
        return RULES[self.rule_id]["why"]

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    @property
    def needs_human(self) -> bool:
        """Skipped because OCR was unsure, rather than because it did not apply."""
        return self.status == SKIPPED and self.explanation.startswith("Not checked:")


# --- small helpers --------------------------------------------------------
def _missing(record: dict, keys) -> list:
    """Which of these fields are absent or empty? (Phase 4 hands us gaps.)"""
    return [key for key in keys if record.get(key) is None]


def _more_or_less(difference: float) -> str:
    return "more" if difference > 0 else "less"


def _lowest_confidence(record: dict, *fields) -> float:
    """The least confident of these fields, as OCR scored them.

    A record that came from the register rather than from a scan carries no
    confidences at all, and is treated as certain - which is why the same
    rules can run on both without knowing where the data came from.
    """
    marks = record.get("_confidence") or {}
    if not marks:
        return 100.0
    return min((marks.get(field, 100.0) for field in fields), default=100.0)


def _floor() -> float:
    """Read the confidence floor at call time, so it can be tuned in one place."""
    return config.OCR_CONFIDENCE_FLOOR


def _unsure(rule_id: str, confidence: float, what: str, fields: list) -> RuleResult:
    """Say why a rule declined to judge, in the reviewer's language."""
    if confidence == 0:
        why = (f"two independent OCR readings of {what} disagreed, so the figure "
               f"is not trustworthy enough to judge")
    elif confidence < 0:
        why = f"{what} could not be read at all"
    else:
        why = (f"OCR was only {confidence:.0f}% sure of {what}, below the "
               f"{_floor():.0f}% a rule needs")
    return RuleResult(rule_id, SKIPPED,
                      f"Not checked: {why}. This record needs a human to confirm "
                      f"the figures.", fields)


def _date(iso_date: str) -> str:
    """2005-08-06 -> 06/08/2005, the way a 7/12 prints it.

    OCR sometimes cannot read a date at all, so anything unexpected is passed
    through rather than crashing the whole report.
    """
    parts = (iso_date or "").split("-")
    if len(parts) != 3:
        return iso_date or "(unreadable)"
    year, month, day = parts
    return f"{day}/{month}/{year}"


# --- rule 1 ---------------------------------------------------------------
def hissa_area(record: dict, family: dict) -> RuleResult:
    """Sub-division areas must add up to the area of the parent survey number."""
    rule_id, fields = "R1_hissa_area", ["total_area", "hissa_record_ids"]
    child_ids = record.get("hissa_record_ids") or []

    if not child_ids:
        return RuleResult(rule_id, SKIPPED,
                          "This survey number has no hissa sub-divisions, so there is "
                          "nothing to reconcile.", fields)
    if record.get("total_area") is None:
        return RuleResult(rule_id, SKIPPED,
                          "Cannot check: the total area could not be read.", fields)

    known = [family[cid] for cid in child_ids if cid in family]
    if len(known) != len(child_ids):
        missing = [cid for cid in child_ids if cid not in family]
        return RuleResult(rule_id, SKIPPED,
                          f"Cannot check: {len(missing)} of the {len(child_ids)} hissa "
                          f"records were not supplied ({', '.join(missing)}).", fields)

    confidence = min([_lowest_confidence(record, "total_area")]
                     + [_lowest_confidence(child, "total_area") for child in known])
    if confidence < _floor():
        return _unsure(rule_id, confidence, "an area on this record or a hissa record",
                       fields)

    children_total = sum(child["total_area"] for child in known)
    difference = children_total - record["total_area"]
    if abs(difference) <= AREA_TOLERANCE_HA:
        return RuleResult(rule_id, PASS,
                          f"The {len(known)} hissa records add up to {children_total:.2f} ha, "
                          f"matching the {record['total_area']:.2f} ha recorded for this "
                          f"survey number.", fields)
    return RuleResult(rule_id, FAIL,
                      f"The {len(known)} hissa records ({', '.join(child_ids)}) add up to "
                      f"{children_total:.2f} ha, which is {abs(difference):.2f} ha "
                      f"{_more_or_less(difference)} than the {record['total_area']:.2f} ha "
                      f"recorded for survey number {record.get('survey_number', '?')}.",
                      fields)


# --- rule 2 ---------------------------------------------------------------
def area_balance(record: dict, family: dict) -> RuleResult:
    """Total area must equal cultivable area plus pot kharaba."""
    rule_id = "R2_area_balance"
    fields = ["total_area", "cultivable_area", "pot_kharaba"]

    gaps = _missing(record, fields)
    if gaps:
        return RuleResult(rule_id, SKIPPED,
                          f"Cannot check: {', '.join(gaps)} could not be read.", fields)

    confidence = _lowest_confidence(record, *fields)
    if confidence < _floor():
        return _unsure(rule_id, confidence, "the area figures", fields)

    parts = record["cultivable_area"] + record["pot_kharaba"]
    difference = parts - record["total_area"]
    if abs(difference) <= AREA_TOLERANCE_HA:
        return RuleResult(rule_id, PASS,
                          f"Cultivable {record['cultivable_area']:.2f} ha plus pot kharaba "
                          f"{record['pot_kharaba']:.2f} ha comes to {parts:.2f} ha, matching "
                          f"the total area on the record.", fields)
    return RuleResult(rule_id, FAIL,
                      f"Cultivable {record['cultivable_area']:.2f} ha plus pot kharaba "
                      f"{record['pot_kharaba']:.2f} ha comes to {parts:.2f} ha, which is "
                      f"{abs(difference):.2f} ha {_more_or_less(difference)} than the total "
                      f"area of {record['total_area']:.2f} ha printed on the record.", fields)


# --- rule 3 ---------------------------------------------------------------
def owner_shares(record: dict, family: dict) -> RuleResult:
    """Every owner's share, added up, must equal the total area."""
    rule_id, fields = "R3_owner_shares", ["owners", "total_area"]

    owners = record.get("owners")
    if not owners or record.get("total_area") is None:
        return RuleResult(rule_id, SKIPPED,
                          "Cannot check: the owner list or the total area could not be read.",
                          fields)

    # A share OCR could not read is not a share of zero: adding it up as zero
    # would invent a shortfall and flag an innocent record.
    unreadable = [owner for owner in owners if owner.get("share_area") is None]
    if unreadable:
        return RuleResult(rule_id, SKIPPED,
                          f"Cannot check: the share could not be read for "
                          f"{len(unreadable)} of the {len(owners)} owners.", fields)

    confidence = min(
        [_lowest_confidence(record, "total_area")]
        + [(owner.get("_confidence") or {}).get("share_area", 100.0) for owner in owners])
    if confidence < _floor():
        return _unsure(rule_id, confidence, "the total area or an owner's share", fields)

    shares = sum(owner["share_area"] for owner in owners)
    difference = shares - record["total_area"]
    if abs(difference) <= AREA_TOLERANCE_HA:
        return RuleResult(rule_id, PASS,
                          f"The {len(owners)} owner share(s) add up to {shares:.2f} ha, "
                          f"matching the total area.", fields)
    return RuleResult(rule_id, FAIL,
                      f"The {len(owners)} owner share(s) add up to {shares:.2f} ha, which is "
                      f"{abs(difference):.2f} ha {_more_or_less(difference)} than the total "
                      f"area of {record['total_area']:.2f} ha.", fields)


# --- rule 4 ---------------------------------------------------------------
def mutation_chain(record: dict, family: dict) -> RuleResult:
    """Each mutation must be made by somebody the record already knows as a holder.

    This checks identity, not amounts: the seller has to be a person who
    appears earlier in the chain. Whether the AREAS add up is rule 3's job,
    and keeping the two apart stops one fault being reported twice.
    """
    rule_id, fields = "R4_mutation_chain", ["mutations", "owners"]

    mutations = record.get("mutations") or []
    # An entry whose names OCR could not read cannot be checked against the
    # chain - and must not be reported as a stranger selling the land.
    usable = [m for m in mutations if m.get("from_owner") and m.get("to_owner")]
    if len(usable) < 2:
        return RuleResult(rule_id, SKIPPED,
                          f"Cannot check: only {len(usable)} of "
                          f"{len(mutations)} mutations have both names readable.",
                          fields)

    names_confidence = min(
        [min((m.get("_confidence") or {}).get("from_owner", 100.0),
             (m.get("_confidence") or {}).get("to_owner", 100.0)) for m in usable])
    if names_confidence < _floor():
        return _unsure(rule_id, names_confidence, "a name in the mutation register", fields)

    # The earliest entry's seller is taken as the original holder: there is
    # nothing before it on this record to check them against.
    holders = {usable[0]["from_owner"]}
    for mutation in usable:
        seller = mutation["from_owner"]
        if seller not in holders:
            return RuleResult(rule_id, FAIL,
                              f"Mutation {mutation['mutation_number']} dated "
                              f"{_date(mutation['date'])} transfers land from {seller}, who "
                              f"does not appear as a holder earlier in this record. The "
                              f"holders on record before it were: "
                              f"{', '.join(sorted(holders))}.", fields)
        holders.add(mutation["to_owner"])

    return RuleResult(rule_id, PASS,
                      f"All {len(usable)} mutations are made by holders the record "
                      f"already knows.", fields)


# --- rule 5 ---------------------------------------------------------------
def mutation_dates(record: dict, family: dict) -> RuleResult:
    """Mutations must be dated in the order they are recorded."""
    rule_id, fields = "R5_mutation_dates", ["mutations"]

    mutations = record.get("mutations") or []
    dated = [m for m in mutations if m.get("date")]
    if len(dated) < 2:
        return RuleResult(rule_id, SKIPPED,
                          f"Cannot check: only {len(dated)} of {len(mutations)} "
                          f"mutations have a readable date.", fields)

    dates_confidence = min([(m.get("_confidence") or {}).get("date", 100.0) for m in dated])
    if dates_confidence < _floor():
        return _unsure(rule_id, dates_confidence, "a mutation date", fields)

    for earlier, later in zip(dated, dated[1:]):
        if later["date"] < earlier["date"]:
            return RuleResult(rule_id, FAIL,
                              f"Mutation {later['mutation_number']} is dated "
                              f"{_date(later['date'])}, which is earlier than mutation "
                              f"{earlier['mutation_number']} dated {_date(earlier['date'])} "
                              f"recorded before it.", fields)

    return RuleResult(rule_id, PASS,
                      f"All {len(dated)} dated mutations run in order, from "
                      f"{_date(dated[0]['date'])} to {_date(dated[-1]['date'])}.",
                      fields)


# --- rule 6 ---------------------------------------------------------------
def _parcel_key(record: dict):
    """What identifies a parcel: its village, survey number and hissa."""
    village = (record.get("village") or "").strip()
    survey = (record.get("survey_number") or "").strip()
    if not village or not survey:
        return None
    return village, survey, (record.get("hissa_number") or "").strip()


def duplicate_parcel(record: dict, family: dict) -> RuleResult:
    """One parcel must appear on one record, not two.

    This is the only rule that needs the rest of the batch rather than just
    this record and its hissas, which is why the engine hands every rule the
    whole set.
    """
    rule_id = "R6_duplicate_parcel"
    fields = ["village", "survey_number", "hissa_number"]

    key = _parcel_key(record)
    if key is None:
        return RuleResult(rule_id, SKIPPED,
                          "Cannot check: the village or survey number could not be read.",
                          fields)
    if len(family) < 2:
        return RuleResult(rule_id, SKIPPED,
                          "Not checked: only this record was supplied, so there is "
                          "nothing to compare it against.", fields)

    confidence = _lowest_confidence(record, "village", "survey_number")
    if confidence < _floor():
        return _unsure(rule_id, confidence, "the village or survey number", fields)

    twins = sorted(other_id for other_id, other in family.items()
                   if other_id != record.get("record_id") and _parcel_key(other) == key)
    if not twins:
        return RuleResult(rule_id, PASS,
                          f"Survey number {key[1]} in {key[0]} appears on this record "
                          f"only.", fields)

    parcel = f"survey number {key[1]}" + (f" hissa {key[2]}" if key[2] else "")
    return RuleResult(rule_id, FAIL,
                      f"The same parcel ({parcel} in {key[0]}) is also recorded on "
                      f"{', '.join(twins)}. Two records for one piece of land let two "
                      f"people each hold a valid-looking extract for it.", fields)


# Every rule, in the order they are shown. Same signature for all of them, so
# the engine can simply loop.
ALL_RULES = [hissa_area, area_balance, owner_shares, mutation_chain, mutation_dates,
             duplicate_parcel]
