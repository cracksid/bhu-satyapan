"""Break records on purpose, and write down exactly how they were broken.

Each injector damages ONE thing and records what it did on the affected
record:

    {"type": ..., "record_id": ..., "detail": "...", "fields": [...]}

That entry is the ground truth. In Phase 2 the rule engine is graded against
it: every injected defect must be caught, and clean records must pass.

Each injector is careful to leave everything else consistent, so a record
never accidentally carries a defect we did not record.
"""

import copy
import random
from collections import Counter

from .record import round2
from . import names

# The six faults, matching the six validation rules.
DEFECT_TYPES = [
    "hissa_area_mismatch",          # sub-division areas do not add up to the parent
    "area_balance_mismatch",        # total != cultivable + pot kharaba
    "owner_share_mismatch",         # owner shares do not add up to the total
    "broken_mutation_chain",        # a seller who did not own the land
    "mutation_date_out_of_order",   # a mutation dated before the one before it
    "duplicate_record",             # the same parcel recorded on two pages
]


def _note(record, kind, detail, fields):
    record["defects"].append({
        "type": kind,
        "record_id": record["record_id"],
        "detail": detail,
        "fields": fields,
    })


def _shift(rng: random.Random, low=0.06, high=0.40) -> float:
    """A change big enough to be a real error, not a rounding difference."""
    return round2(rng.uniform(low, high)) * rng.choice([-1, 1])


def hissa_area_mismatch(rng, family, next_record_id=None) -> bool:
    """Make the parent's area stop matching the sum of its hissa records."""
    parent = family[0]
    if not parent["hissa_record_ids"]:
        return False

    children_total = round2(sum(r["total_area"] for r in family[1:]))
    delta = _shift(rng)
    if parent["total_area"] + delta <= 0.1:
        delta = abs(delta)

    parent["total_area"] = round2(parent["total_area"] + delta)
    # Keep the parent internally consistent, so only THIS defect is present.
    parent["cultivable_area"] = round2(parent["total_area"] - parent["pot_kharaba"])
    parent["owners"][0]["share_area"] = round2(parent["owners"][0]["share_area"] + delta)

    _note(parent, "hissa_area_mismatch",
          f"parent area is {parent['total_area']:.2f} ha but its "
          f"{len(family) - 1} hissa records add up to {children_total:.2f} ha",
          ["total_area", "hissa_record_ids"])
    return True


def area_balance_mismatch(rng, family, next_record_id=None) -> bool:
    """Make total_area stop equalling cultivable_area + pot_kharaba."""
    record = rng.choice(family)
    delta = abs(_shift(rng, 0.06, 0.25))
    record["pot_kharaba"] = round2(record["pot_kharaba"] + delta)

    _note(record, "area_balance_mismatch",
          f"cultivable {record['cultivable_area']:.2f} + pot kharaba "
          f"{record['pot_kharaba']:.2f} != total {record['total_area']:.2f} ha",
          ["total_area", "cultivable_area", "pot_kharaba"])
    return True


def owner_share_mismatch(rng, family, next_record_id=None) -> bool:
    """Make the owners' shares stop adding up to the total area."""
    record = rng.choice(family)
    owner = rng.choice(record["owners"])
    delta = _shift(rng, 0.06, 0.30)
    if owner["share_area"] + delta <= 0.05:
        delta = abs(delta)
    owner["share_area"] = round2(owner["share_area"] + delta)

    shares = round2(sum(o["share_area"] for o in record["owners"]))
    _note(record, "owner_share_mismatch",
          f"owner shares add up to {shares:.2f} ha but the total area is "
          f"{record['total_area']:.2f} ha",
          ["owners", "total_area"])
    return True


def broken_mutation_chain(rng, family, next_record_id=None) -> bool:
    """Make a mutation be sold by somebody who never owned the land."""
    candidates = [r for r in family if len(r["mutations"]) >= 2]
    if not candidates:
        return False
    record = rng.choice(candidates)
    mutation = rng.choice(record["mutations"][1:])

    stranger = names.person(rng)
    real_seller = mutation["from_owner"]
    mutation["from_owner"] = stranger

    _note(record, "broken_mutation_chain",
          f"mutation {mutation['mutation_number']} is transferred by {stranger}, "
          f"who was not an owner at that time (the holder was {real_seller})",
          ["mutations"])
    return True


def mutation_date_out_of_order(rng, family, next_record_id=None) -> bool:
    """Date a mutation before the one that came before it."""
    candidates = [r for r in family if len(r["mutations"]) >= 2]
    if not candidates:
        return False
    record = rng.choice(candidates)
    index = rng.randrange(1, len(record["mutations"]))
    mutation = record["mutations"][index]
    previous = record["mutations"][index - 1]

    year, month, day = (int(part) for part in previous["date"].split("-"))
    moved = f"{year - rng.randint(1, 3):04d}-{month:02d}-{day:02d}"
    original = mutation["date"]
    mutation["date"] = moved

    _note(record, "mutation_date_out_of_order",
          f"mutation {mutation['mutation_number']} is dated {moved}, before "
          f"mutation {previous['mutation_number']} on {previous['date']} "
          f"(it was {original})",
          ["mutations"])
    return True


def duplicate_record(rng, family, next_record_id=None) -> bool:
    """Record the same parcel a second time, as a careless re-entry would.

    The copy is a separate page for the same village, survey number and hissa.
    Both pages are marked, because both are part of the problem: whichever one
    a clerk opens, the other exists.
    """
    if next_record_id is None:
        return False

    original = rng.choice(family)
    twin = copy.deepcopy(original)
    twin["record_id"] = next_record_id()
    twin["defects"] = []
    # A duplicate page is not the parent of the original's hissa records.
    twin["hissa_record_ids"] = []
    family.append(twin)

    parcel = f"survey number {original['survey_number']}"
    if original["hissa_number"]:
        parcel += f" hissa {original['hissa_number']}"
    for record, other in ((original, twin), (twin, original)):
        _note(record, "duplicate_record",
              f"{parcel} in {record['village']} is recorded twice: on "
              f"{record['record_id']} and on {other['record_id']}",
              ["village", "survey_number", "hissa_number"])
    return True


INJECTORS = {
    "hissa_area_mismatch": hissa_area_mismatch,
    "area_balance_mismatch": area_balance_mismatch,
    "owner_share_mismatch": owner_share_mismatch,
    "broken_mutation_chain": broken_mutation_chain,
    "mutation_date_out_of_order": mutation_date_out_of_order,
    "duplicate_record": duplicate_record,
}


def inject_balanced(rng: random.Random, families: list, target: int,
                    next_record_id=None) -> Counter:
    """Damage `target` families, one defect each, spreading the types evenly.

    Taking a random defect type each time would under-use the ones that are
    fussy about where they fit: hissa_area_mismatch needs a sub-divided survey
    number, and the mutation defects need at least two mutations. Phase 2 has
    to measure detection for every rule, so instead we take the types in turn
    and, for each, find a family that can carry it. A type is dropped once no
    remaining family can take it.
    """
    injected = Counter()
    remaining = rng.sample(families, len(families))   # untouched families
    available = list(DEFECT_TYPES)
    turn = 0

    while injected.total() < target and remaining and available:
        kind = available[turn % len(available)]
        for position, family in enumerate(remaining):
            if INJECTORS[kind](rng, family, next_record_id):
                injected[kind] += 1
                remaining.pop(position)
                turn += 1
                break
        else:
            available.remove(kind)        # nothing left this defect can break
    return injected
