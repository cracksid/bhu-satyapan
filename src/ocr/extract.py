"""Turn the cells of a page into a record the validation engine can read.

The mapping is a template for this 7/12 layout: which column holds the owner
name, which line of the left block holds the total area, and so on. That is
deliberate - real land records come in a handful of fixed formats, and a
template per format is both more accurate and easier to explain than a model
that guesses. Another state's format means another template here, not new
machine learning.

Everything is read by POSITION rather than by matching the printed labels:
OCR mangles a heading as easily as a value ("जिल्हा" came back as "णजल्हा"),
but the geometry of a ruled form is stable.

Nothing in here ever "corrects" a value to make a record consistent. If the
page says the areas do not add up, that is what comes out - finding those is
the entire point of the system.
"""

import re
import time

from . import read as reader
from .preprocess import PreparedPage, load, prepare
from .tables import find_cells, group_rows

DEVANAGARI_TO_ASCII = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
DATE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})")

# Which column of the main table holds what, left to right.
AREA_BLOCK, KHATA, OWNER_NAME, OWNER_AREA, OWNER_AKAR, POT_KHARABA, FERFAR, RIGHTS = range(8)


def to_ascii_digits(text: str) -> str:
    """१.२४ -> 1.24, and a comma read for a decimal point -> a decimal point."""
    return text.translate(DEVANAGARI_TO_ASCII).replace(",", ".")


def first_number(text: str):
    """The first number in the text, or None. Never guesses a missing digit."""
    match = NUMBER.search(to_ascii_digits(text))
    return float(match.group()) if match else None


def last_number(text: str):
    matches = NUMBER.findall(to_ascii_digits(text))
    return float(matches[-1]) if matches else None


def after_label(text: str) -> str:
    """The value part of "गाव : रानतळेवाडी".

    OCR often reads the colon as ';' or '.', and sometimes drops it, so fall
    back to dropping the first word - every label on this form is one word.
    """
    for separator in (":", ";"):
        if separator in text:
            return text.split(separator)[-1].strip(" .|_-")
    parts = text.split()
    return " ".join(parts[1:]).strip(" .|_-") if len(parts) > 1 else text.strip()


JUNK_EDGES = " .|_,;:-'\"`~*"


def clean(text: str) -> str:
    """Drop the stray punctuation that leftover rule fragments leave behind.

    A printed rule clipped at the edge of a crop comes back as |, _, ' or a
    stray comma, and those would otherwise end up inside a name.
    """
    return re.sub(r"\s+", " ", text.strip(JUNK_EDGES)).strip(JUNK_EDGES).strip()


def _tidy_id(text: str):
    """PU-ID "ROO11" or "१0116" -> "R0011" / "R0116".

    Two things go wrong with this one field. The Latin R is often read as a
    Devanagari letter, because the page is mostly Marathi and that model
    dominates; and a 0 in a Latin id comes back as the letter O about as often
    as not. The PU-ID's shape is fixed for this format - R followed by four
    digits - so both can be undone without inventing anything: take the digits
    and keep the last four.
    """
    squashed = re.sub(r"[^A-Za-z0-9]", "", to_ascii_digits(text)).upper()
    squashed = squashed.translate(str.maketrans("OILSB", "01158"))
    digits = re.sub(r"[^0-9]", "", squashed)
    if len(digits) < 4:
        return f"R{digits}" if digits else None
    return f"R{digits[-4:]}"


def to_iso_date(text: str):
    """२६/०९/२००६ -> 2006-09-26, or None if no date could be read."""
    match = DATE.search(to_ascii_digits(text))
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _agreed_number(page, cell, fast_text: str):
    """Take a number only when both OCR models read it the same way.

    Measured on 60 numeric cells across 8 pages: where the model the installer
    ships and the accurate one agree, the value is right 100% of the time;
    where they disagree, 45%. That is a far better signal than Tesseract's own
    confidence (90% against 60%), and it is free - the fast reading already
    happened when every cell was read.

    Returns (value, confidence), where a confidence of 0 means the two models
    disagreed, so no rule should judge this field.
    """
    best = reader.read_number(page, cell)
    best_value = first_number(best.text)
    if best_value is None:
        return None, -1.0

    if not reader.best_model_available():
        # Only one model is installed, so there is no second opinion to compare
        # against. Fall back to Tesseract's own confidence and the floor in
        # config.py - weaker, and the rules will skip more often.
        return best_value, best.confidence

    fast_value = first_number(fast_text)
    if fast_value is not None and abs(fast_value - best_value) < 0.005:
        return best_value, best.confidence
    return best_value, 0.0


def _column_of(cell, header_cells) -> int:
    """Which header column does this cell sit under?"""
    best, best_overlap = -1, 0.0
    for index, header in enumerate(header_cells):
        overlap = min(cell.right, header.right) - max(cell.x, header.x)
        if overlap > best_overlap:
            best, best_overlap = index, overlap
    return best


def _parse_area_block(lines: list) -> dict:
    """Read the left-hand block: जिरायत / बागायत / एकूण / पो.ख. / एकूण क्षेत्र / आकारणी.

    Labels are matched where they survived OCR, and the fixed line order is
    the fallback. Both are needed: "एकूण" and "एकूण क्षेत्र" differ by one word.
    """
    values = {}
    numbered = [(index, line, last_number(line)) for index, line in enumerate(lines)]
    with_numbers = [(index, line, value) for index, line, value in numbered if value is not None]

    for index, line, value in with_numbers:
        squashed = line.replace(" ", "")
        if "आकारणी" in squashed and "विशेष" not in squashed and "जुडी" not in squashed:
            values.setdefault("assessment", value)
        elif "पो" in squashed and "ख" in squashed:
            values.setdefault("pot_kharaba", value)
        elif "एकूणक्षेत्र" in squashed:
            values.setdefault("total_area", value)
        elif "जिरायत" in squashed:
            values.setdefault("jirayat", value)
        elif "बागायत" in squashed:
            values.setdefault("bagayat", value)
        elif "एकूण" in squashed:
            values.setdefault("cultivable_area", value)

    # Fall back to the fixed order of the block for anything the labels missed:
    # jirayat, bagayat, cultivable total, pot kharaba, total area, assessment.
    order = ["jirayat", "bagayat", "cultivable_area", "pot_kharaba",
             "total_area", "assessment"]
    for position, key in enumerate(order):
        if key not in values and position < len(with_numbers):
            values[key] = with_numbers[position][2]

    if "cultivable_area" not in values and "jirayat" in values:
        values["cultivable_area"] = values["jirayat"]
    return values


def extract(page: PreparedPage) -> dict:
    """Read one prepared page into a record dict, plus per-field confidence."""
    started = time.time()
    cells = find_cells(page)
    rows = group_rows(cells)

    texts = {}
    for cell in cells:
        texts[id(cell)] = reader.read_cell(page, cell)

    def text_of(cell) -> str:
        return texts[id(cell)].text

    def confidence_of(cell) -> float:
        return texts[id(cell)].confidence

    record = {
        "record_id": None, "district": None, "taluka": None, "village": None,
        "survey_number": None, "hissa_number": None, "khata_number": None,
        "total_area": None, "cultivable_area": None, "pot_kharaba": None,
        "assessment": None, "tenure_class": None,
        "owners": [], "other_rights": [], "mutations": [], "crops": [],
        "parent_record_id": None, "hissa_record_ids": [], "defects": [],
    }
    confidence = {}

    # --- the header rows, above the main table --------------------------- #
    header_index = next((index for index, row in enumerate(rows) if len(row) >= 7), None)
    info_rows = rows[:header_index] if header_index is not None else rows[:3]

    if len(info_rows) >= 1 and len(info_rows[0]) >= 3:
        for key, cell in zip(("village", "taluka", "district"), info_rows[0][:3]):
            record[key] = clean(after_label(text_of(cell)))
            confidence[key] = confidence_of(cell)
    if len(info_rows) >= 2 and len(info_rows[1]) >= 3:
        pu_id, survey_cell, khata_cell = info_rows[1][:3]
        record["record_id"] = _tidy_id(after_label(text_of(pu_id)))
        confidence["record_id"] = confidence_of(pu_id)

        survey_text = to_ascii_digits(after_label(text_of(survey_cell)))
        numbers = NUMBER.findall(survey_text)
        if numbers:
            record["survey_number"] = str(int(float(numbers[0])))
            if "/" in survey_text and len(numbers) > 1:
                record["hissa_number"] = str(int(float(numbers[1])))
        confidence["survey_number"] = confidence_of(survey_cell)

        khata = NUMBER.search(to_ascii_digits(text_of(khata_cell)))
        record["khata_number"] = str(int(float(khata.group()))) if khata else None
        confidence["khata_number"] = confidence_of(khata_cell)
    if len(info_rows) >= 3 and info_rows[2]:
        tenure_text = to_ascii_digits(text_of(info_rows[2][0]))
        match = re.search(r"वर्ग\s*-?\s*(\d)", tenure_text) or re.search(r"(\d)\s*$", tenure_text)
        record["tenure_class"] = int(match.group(1)) if match else None
        confidence["tenure_class"] = confidence_of(info_rows[2][0])

    # --- the main table: area block, owners, other rights ----------------- #
    main_end = len(rows)
    if header_index is not None:
        header_cells = rows[header_index]
        for offset, row in enumerate(rows[header_index + 1:], start=header_index + 1):
            if len(row) <= 3:               # the "जुने फेरफार" strip ends the table
                main_end = offset
                break
            columns = {_column_of(cell, header_cells): cell for cell in row}

            if AREA_BLOCK in columns and record["total_area"] is None:
                block_cell = columns[AREA_BLOCK]
                best_lines, block_confidence = reader.read_lines(page, block_cell, best=True)
                fast_lines, _ = reader.read_lines(page, block_cell)
                areas = _parse_area_block(best_lines)
                fast_areas = _parse_area_block(fast_lines)
                for key in ("total_area", "cultivable_area", "pot_kharaba", "assessment"):
                    value = areas.get(key)
                    record[key] = value
                    # Same rule as everywhere else: a figure only counts as read
                    # when both models read it the same.
                    other = fast_areas.get(key)
                    agreed = (value is not None and other is not None
                              and abs(value - other) < 0.005)
                    confidence[key] = block_confidence if agreed else 0.0

            if RIGHTS in columns:
                rights_text = clean(text_of(columns[RIGHTS]))
                if rights_text and rights_text not in {"—", "-", "_"}:
                    record["other_rights"] = [rights_text]
                    confidence["other_rights"] = confidence_of(columns[RIGHTS])

            if OWNER_NAME in columns:
                name = clean(text_of(columns[OWNER_NAME]))
                if name:
                    # The share has to be right for the rules, so it is only
                    # accepted when both models agree. आकार is shown but never
                    # checked, so the fast reading is good enough for it.
                    share, share_confidence = (
                        _agreed_number(page, columns[OWNER_AREA],
                                       text_of(columns[OWNER_AREA]))
                        if OWNER_AREA in columns else (None, -1.0))
                    akar_read = (texts[id(columns[OWNER_AKAR])]
                                 if OWNER_AKAR in columns else None)
                    record["owners"].append({
                        "name": name,
                        "share_area": share,
                        "assessment_share": first_number(akar_read.text) if akar_read else None,
                        "_confidence": {
                            "name": confidence_of(columns[OWNER_NAME]),
                            "share_area": share_confidence,
                        },
                    })

    # --- the mutation register and the crop table ------------------------- #
    # Only rows BELOW the main table: an owner row for the second owner also
    # has six cells (the area block and the rights column belong to the first
    # row only), and those were being read as mutations.
    tail = rows[main_end:]

    six_column_rows = [row for row in tail if len(row) == 6]
    for row in six_column_rows[1:]:                     # row 0 is the heading
        # The number and area columns are only taken when both models agree.
        number_value, number_confidence = _agreed_number(page, row[0], text_of(row[0]))
        area_value, area_confidence = _agreed_number(page, row[5], text_of(row[5]))
        date = to_iso_date(text_of(row[1]))
        if number_value is None and date is None:
            continue
        record["mutations"].append({
            "mutation_number": str(int(number_value)) if number_value is not None else "",
            "date": date or "",
            "type": clean(text_of(row[2])),
            "from_owner": clean(text_of(row[3])),
            "to_owner": clean(text_of(row[4])),
            "area": area_value,
            "_confidence": {
                "mutation_number": number_confidence,
                "date": confidence_of(row[1]),
                "from_owner": confidence_of(row[3]),
                "to_owner": confidence_of(row[4]),
                "area": area_confidence,
            },
        })

    five_column_rows = [row for row in tail if len(row) == 5]
    for row in five_column_rows[1:]:
        year = clean(text_of(row[0]))
        if not year:
            continue
        record["crops"].append({
            "year": year,
            "season": clean(text_of(row[1])),
            "crop": clean(text_of(row[2])),
            "area": first_number(text_of(row[3])),
            "irrigation": clean(text_of(row[4])),
        })

    record["_confidence"] = confidence
    record["_ocr"] = {
        "deskew_angle": round(page.angle, 2),
        "cells": len(cells),
        "seconds": round(time.time() - started, 1),
        "mean_confidence": round(
            sum(c for c in confidence.values() if c >= 0) / max(
                sum(1 for c in confidence.values() if c >= 0), 1), 1),
    }
    return record


def extract_from_file(path) -> dict:
    """Read an image file straight through to a record."""
    return extract(prepare(load(path)))
