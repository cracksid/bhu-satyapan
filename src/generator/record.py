"""Build 7/12 records as plain Python dictionaries.

A "family" is one survey number (गट क्रमांक):
  * a parent record covering the whole survey number, and
  * sometimes its hissa records - the sub-divisions 1, 2, 3 ... of that number

Records built here are always internally consistent: areas add up, owner
shares add up, and the mutation chain is unbroken and in date order. Faults
are added on purpose afterwards, by defects.py.

Areas are floats in hectares, where 1.25 means 1 hectare 25 are (हे.आर.).
"""

import random
from datetime import date, timedelta

from . import names

MAX_MUTATION_DATE = date(2025, 12, 31)


def round2(value: float) -> float:
    """Round to 2 decimals (1 are), avoiding float noise like 0.30000000000004."""
    return round(value + 1e-9, 2)


def _split_areas(rng: random.Random, total: float):
    """Split a total area into cultivable land and pot kharaba (uncultivable)."""
    if rng.random() < 0.7:
        pot_kharaba = round2(total * rng.uniform(0.02, 0.12))
    else:
        pot_kharaba = 0.0
    return round2(total - pot_kharaba), pot_kharaba


def _build_mutation_chain(rng: random.Random, total_area: float):
    """Create a legal ownership history and the owners it leaves behind.

    The chain is correct by construction, which is what makes it useful as
    ground truth: every seller really did own the land at that moment, dates
    only move forward, and the shares left over add up to the total area.

    Returns (mutations, owners).
    """
    ledger = {names.person(rng): total_area}          # owner name -> area held
    mutations = []
    when = date(1996 + rng.randint(0, 8), rng.randint(1, 12), rng.randint(1, 28))
    number = rng.randint(800, 2400)

    for _ in range(rng.randint(2, 4)):
        when = when + timedelta(days=rng.randint(200, 1500))
        if when > MAX_MUTATION_DATE:
            break
        number += rng.randint(20, 300)

        seller = rng.choice([n for n, a in ledger.items() if a > 0.05])
        kind = rng.choice(list(names.MUTATION_TYPES))
        held = ledger[seller]
        # An inheritance passes the whole holding; a sale often passes part of it.
        if kind == "inheritance" or rng.random() < 0.35:
            area = held
        else:
            area = max(0.01, min(round2(held * rng.uniform(0.3, 0.7)), held))
        buyer = names.person(rng)

        ledger[seller] = round2(held - area)
        if ledger[seller] <= 0.005:
            del ledger[seller]
        ledger[buyer] = round2(ledger.get(buyer, 0.0) + area)

        mutations.append({
            "mutation_number": str(number),
            "date": when.isoformat(),
            "type": kind,
            "from_owner": seller,
            "to_owner": buyer,
            "area": area,
        })

    # Rounding can drift by an are or two; give the difference to the largest holder.
    drift = round2(total_area - sum(ledger.values()))
    if drift:
        biggest = max(ledger, key=ledger.get)
        ledger[biggest] = round2(ledger[biggest] + drift)

    owners = [{"name": name, "share_area": area}
              for name, area in sorted(ledger.items(), key=lambda kv: -kv[1])]
    return mutations, owners


def _other_rights(rng: random.Random) -> list:
    """The इतर हक्क column: loans, tenancy and similar encumbrances."""
    if rng.random() < 0.35:
        return []
    rights = []
    if rng.random() < 0.6:
        amount = rng.randrange(20000, 300000, 5000)
        rights.append(f"{rng.choice(names.BANKS)} कर्ज रु. {amount}")
    if rng.random() < 0.3:
        rights.append(f"कूळ: {names.person(rng)}")
    if rng.random() < 0.25:
        rights.append(rng.choice(["विहीर", "रस्ता हक्क", "पाणी वापर हक्क"]))
    return rights or ["विहीर"]


def _crops(rng: random.Random, cultivable: float) -> list:
    """A few rows of the Form XII crop register."""
    rows = []
    for year in range(2022, 2022 + rng.randint(2, 3)):
        for season in names.SEASONS[: rng.randint(1, 2)]:
            rows.append({
                "year": f"{year}-{str(year + 1)[-2:]}",
                "season": season,
                "crop": rng.choice(names.CROPS),
                "area": round2(cultivable * rng.uniform(0.4, 1.0)),
                "irrigation": rng.choice(names.IRRIGATION),
            })
    return rows


def _make_record(rng, record_id, family_id, role, place, survey_number,
                 hissa_number, total_area):
    """One 7/12 page: a survey number (or one hissa of it) with everything on it."""
    cultivable, pot_kharaba = _split_areas(rng, total_area)
    mutations, owners = _build_mutation_chain(rng, total_area)

    # आकार: the assessment is shown per holding on the form, so split it the
    # same way the area is split, and give any rounding drift to the largest.
    assessment = round2(cultivable * rng.uniform(1.5, 4.5))
    for owner in owners:
        owner["assessment_share"] = round2(assessment * owner["share_area"] / total_area)
    drift = round2(assessment - sum(o["assessment_share"] for o in owners))
    owners[0]["assessment_share"] = round2(owners[0]["assessment_share"] + drift)

    return {
        "record_id": record_id,
        "family_id": family_id,
        "role": role,                                  # "parent" or "hissa"
        "district": place["district"],
        "taluka": place["taluka"],
        "village": place["village"],
        "survey_number": survey_number,
        "hissa_number": hissa_number,                  # None when not sub-divided
        "khata_number": str(rng.randint(101, 989)),
        "total_area": total_area,
        "cultivable_area": cultivable,
        "pot_kharaba": pot_kharaba,
        "assessment": assessment,
        "tenure_class": 1 if rng.random() < 0.8 else 2,
        "owners": owners,
        "other_rights": _other_rights(rng),
        "mutations": mutations,
        "crops": _crops(rng, cultivable),
        "parent_record_id": None,                      # filled in for hissa records
        "hissa_record_ids": [],                        # filled in for parent records
        "defects": [],                                 # empty means a clean record
    }


def make_family(rng: random.Random, family_id: str, next_record_id,
                used_keys: set | None = None) -> list:
    """Build one survey number and, sometimes, its hissa sub-divisions.

    `next_record_id` is a function returning the next record id, e.g. "R0007".
    `used_keys` collects the village/survey pairs already handed out, so two
    families never land on the same parcel by accident - that would be a
    duplicate nobody recorded, and rule 6 would rightly flag it while the
    tests called it a false alarm.

    Returns the list of records, parent first.
    """
    used_keys = used_keys if used_keys is not None else set()
    for _attempt in range(200):
        place = names.place(rng)
        survey_number = str(rng.randint(12, 480))
        key = (place["village"], survey_number)
        if key not in used_keys:
            break
    used_keys.add(key)
    parent_id = next_record_id()

    # About 45% of survey numbers are sub-divided into hissas.
    subdivided = rng.random() < 0.45
    if not subdivided:
        total = round2(rng.uniform(0.4, 3.5))
        parent = _make_record(rng, parent_id, family_id, "parent", place,
                              survey_number, None, total)
        return [parent]

    # Sub-divided: children first, so the parent's area is exactly their sum.
    children = []
    for index in range(rng.randint(2, 4)):
        child_area = round2(rng.uniform(0.25, 1.6))
        child = _make_record(rng, next_record_id(), family_id, "hissa", place,
                             survey_number, str(index + 1), child_area)
        child["parent_record_id"] = parent_id
        children.append(child)

    total = round2(sum(child["total_area"] for child in children))
    parent = _make_record(rng, parent_id, family_id, "parent", place,
                          survey_number, None, total)
    parent["hissa_record_ids"] = [child["record_id"] for child in children]
    return [parent] + children
