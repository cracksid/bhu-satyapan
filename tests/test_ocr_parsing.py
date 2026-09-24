"""Tests for the OCR text handling: the parts that turn what Tesseract saw
into record fields.

These need no images and no Tesseract, so they run in milliseconds. They cover
the mistakes OCR actually made on our pages - a comma read for a decimal
point, "R0011" read as "ROO11" - so a future change cannot quietly undo those
fixes.
"""

from src.ocr.extract import (_parse_area_block, _tidy_id, after_label, clean,
                             first_number, to_ascii_digits, to_iso_date)


def test_devanagari_digits_become_ordinary_ones():
    assert to_ascii_digits("१.२४") == "1.24"
    assert to_ascii_digits("२०२३-२४") == "2023-24"


def test_a_comma_read_for_a_decimal_point_is_accepted():
    # Tesseract returned "0,08" for ०.०८ on several pages.
    assert first_number("0,08") == 0.08


def test_first_number_ignores_the_rubbish_around_it():
    assert first_number("| ०.५६ |") == 0.56
    assert first_number("क्षेत्र १.४०") == 1.40


def test_first_number_is_none_when_there_is_no_number():
    assert first_number("विहीर") is None
    assert first_number("") is None


def test_dates_become_iso():
    assert to_iso_date("२६/०९/२००६") == "2006-09-26"
    assert to_iso_date("6 / 4 / 1998") == "1998-04-06"
    assert to_iso_date("no date here") is None


def test_the_value_after_a_label_is_taken():
    assert after_label("गाव : रानतळेवाडी") == "रानतळेवाडी"
    assert after_label("तालुका ; निफाड") == "निफाड"      # colon read as semicolon
    assert after_label("जिल्हा नाशिक") == "नाशिक"         # colon lost entirely


def test_stray_rule_fragments_are_stripped():
    assert clean("| वत्सला कृष्णा भोसले |") == "वत्सला कृष्णा भोसले"
    assert clean("__ २०२२-२३ '") == "२०२२-२३"


def test_letters_read_for_digits_in_the_id_are_undone():
    assert _tidy_id("ROO11") == "R0011"          # O read for zero
    assert _tidy_id(" R0035 _") == "R0035"
    assert _tidy_id("RO1I7") == "R0117"          # O and I read for 0 and 1
    assert _tidy_id("१0116") == "R0116"          # the R read as a Devanagari letter
    assert _tidy_id("२९0144") == "R0144"


def test_the_area_block_is_read_by_its_labels():
    lines = [
        "लागवडी योग्य क्षेत्र",
        "जिरायत २.८७",
        "बागायत ०.००",
        "एकूण २.८७",
        "पो.ख. क्षेत्र ०.१२",
        "एकूण क्षेत्र २.९९",
        "आकारणी (रु.) ६.३६",
        "जुडी किंवा विशेष आकारणी —",
    ]
    areas = _parse_area_block(lines)
    assert areas["cultivable_area"] == 2.87
    assert areas["pot_kharaba"] == 0.12
    assert areas["total_area"] == 2.99           # एकूण क्षेत्र, not एकूण
    assert areas["assessment"] == 6.36


def test_the_area_block_falls_back_to_line_order_when_labels_are_mangled():
    # Same block, but OCR wrecked every label.
    lines = ["ला गव डी", "जि रायत २.८७", "बा गा यत ०.००", "एक ण २.८७",
             "पो ख ०.१२", "एक ण क्ष त्र २.९९", "आ का र णी ६.३६", "जु डी —"]
    areas = _parse_area_block(lines)
    assert areas["total_area"] == 2.99
    assert areas["assessment"] == 6.36
