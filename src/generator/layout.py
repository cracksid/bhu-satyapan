"""Turn one record into the HTML of a 7/12 extract page.

The layout follows a real digitally-signed 7/12 from the Maharashtra land
records portal: A4 portrait, the rule citation under the title, and one main
table whose left block carries the area and assessment figures while each
owner gets a row with खाते क्र., क्षेत्र, आकार, पो.ख. and the फेरफार numbers.

Two things from the real form are deliberately NOT copied: the State Emblem
of India, and the portal's watermark, QR code and verification number.
Putting those on fabricated records would make them look like genuine
government documents. These pages carry a "नमुना · SAMPLE" watermark and a
synthetic footer instead.

A real 7/12 lists only mutation NUMBERS; the dates and the names of buyer and
seller live in the separate फेरफार register. Rules 4 and 5 need that detail,
so the page carries it in a clearly labelled mutation-register summary below
the form, rather than pretending it is part of Form VII.

Why HTML: a browser shapes Devanagari correctly (क्षेत्र, वर्ग-२, हिस्सा all
come out right), and a CSS table is far easier to keep looking like a printed
form than drawing every line by hand.

Numbers print in Devanagari digits (०-९), as the real form does. The
ground-truth JSON keeps ordinary 0-9, so Phase 4 has to convert between them.
"""

import html

from . import names

DEVANAGARI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def dev(value) -> str:
    """Write a number the way the form does: १२३ instead of 123."""
    return str(value).translate(DEVANAGARI_DIGITS)


def area(value: float) -> str:
    """Area as hectare.are, e.g. 1.25 -> १.२५"""
    return dev(f"{value:.2f}")


def date_dmy(iso_date: str) -> str:
    """2018-06-15 -> १५/०६/२०१८"""
    year, month, day = iso_date.split("-")
    return dev(f"{day}/{month}/{year}")


CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; background: #ffffff; }
  #sheet {
    width: 820px; padding: 20px 24px 14px 24px; background: #ffffff;
    font-family: "Nirmala UI", "Noto Sans Devanagari", sans-serif;
    color: #111111; position: relative;
  }
  .watermark {
    position: absolute; top: 38%; left: 0; width: 100%; text-align: center;
    font-size: 62px; font-weight: 700; letter-spacing: 10px;
    color: rgba(190, 140, 70, 0.08); transform: rotate(-16deg);
  }
  .gov { text-align: center; font-size: 12px; }
  .title { text-align: center; font-size: 16px; font-weight: 700; margin-top: 1px; }
  .rule { text-align: center; font-size: 9px; margin: 2px 0 7px 0; }
  table.t { width: 100%; border-collapse: collapse; margin-bottom: 7px; }
  table.t th, table.t td { border: 1px solid #000000; padding: 3px 5px; vertical-align: top; }
  table.t th { font-weight: 700; text-align: center; font-size: 10.5px; }
  .c { text-align: center; }
  .sec { font-size: 12px; font-weight: 700; margin: 4px 0 4px 1px; }
  .qr { width: 58px; text-align: center; color: #888888; font-size: 9px; padding-top: 16px; }
  table.sub { width: 100%; border-collapse: collapse; }
  table.sub td { border: none; border-bottom: 1px dotted #999999; padding: 2px 2px; font-size: 10px; }
  table.sub td.v { text-align: right; font-weight: 600; }
  .rights div { margin-bottom: 2px; }
  .dash { text-align: center; color: #444444; }
  .foot { margin-top: 5px; font-size: 9px; text-align: center; color: #555555;
          border-top: 1px dashed #999999; padding-top: 4px; }
"""


def _area_block(record) -> str:
    """The tall left-hand block: cultivable split, pot kharaba, assessment."""
    rows = [
        ("लागवडी योग्य क्षेत्र", ""),
        ("जिरायत", area(record["cultivable_area"])),
        ("बागायत", area(0.0)),
        ("एकूण", area(record["cultivable_area"])),
        ("पो.ख. क्षेत्र", area(record["pot_kharaba"])),
        ("एकूण क्षेत्र", area(record["total_area"])),
        ("आकारणी (रु.)", dev(f'{record["assessment"]:.2f}')),
        ("जुडी किंवा विशेष आकारणी", "—"),
    ]
    cells = "".join(
        f'<tr><td>{label}</td><td class="v">{value}</td></tr>' for label, value in rows)
    return f'<table class="sub">{cells}</table>'


def _mutation_numbers_for(record, owner_name) -> str:
    """The फेरफार numbers that brought land to this owner, as (१२३४)."""
    numbers = [m["mutation_number"] for m in record["mutations"]
               if m["to_owner"] == owner_name]
    return " ".join(f"({dev(number)})" for number in numbers)


def _rights_cell(record) -> str:
    if not record["other_rights"]:
        return '<div class="dash">—</div>'
    # dev() here too, so a loan amount is not the one ASCII number on the page.
    return "".join(f"<div>{html.escape(dev(right))}</div>" for right in record["other_rights"])


def _owner_rows(record) -> str:
    """One row per owner, with the area block and rights column spanning them all."""
    owners = record["owners"]
    rows = []
    for index, owner in enumerate(owners):
        cells = []
        if index == 0:
            cells.append(f'<td rowspan="{len(owners)}">{_area_block(record)}</td>')
        cells.append(f'<td class="c">{dev(record["khata_number"])}</td>')
        cells.append(f'<td>{html.escape(owner["name"])}</td>')
        assessment_share = dev(f'{owner["assessment_share"]:.2f}')
        cells.append(f'<td class="c">{area(owner["share_area"])}</td>')
        cells.append(f'<td class="c">{assessment_share}</td>')
        # Pot kharaba belongs to the survey number, so it is shown once.
        cells.append(f'<td class="c">{area(record["pot_kharaba"]) if index == 0 else ""}</td>')
        cells.append(f'<td class="c">{_mutation_numbers_for(record, owner["name"])}</td>')
        if index == 0:
            cells.append(f'<td class="rights" rowspan="{len(owners)}">{_rights_cell(record)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(rows)


def _mutation_rows(record) -> str:
    rows = []
    for mutation in record["mutations"]:
        rows.append(
            "<tr>"
            f'<td class="c">{dev(mutation["mutation_number"])}</td>'
            f'<td class="c">{date_dmy(mutation["date"])}</td>'
            f'<td class="c">{names.MUTATION_TYPES[mutation["type"]]}</td>'
            f'<td>{html.escape(mutation["from_owner"])}</td>'
            f'<td>{html.escape(mutation["to_owner"])}</td>'
            f'<td class="c">{area(mutation["area"])}</td>'
            "</tr>"
        )
    return "".join(rows)


def _crop_rows(record) -> str:
    rows = []
    for crop in record["crops"]:
        rows.append(
            "<tr>"
            f'<td class="c">{dev(crop["year"])}</td>'
            f'<td class="c">{crop["season"]}</td>'
            f'<td class="c">{crop["crop"]}</td>'
            f'<td class="c">{area(crop["area"])}</td>'
            f'<td class="c">{crop["irrigation"]}</td>'
            "</tr>"
        )
    return "".join(rows)


def record_to_html(record: dict, font_px: int = 12) -> str:
    """The whole 7/12 page as one HTML document."""
    survey = dev(record["survey_number"])
    if record["hissa_number"]:
        survey = f'{survey}/{dev(record["hissa_number"])}'
    old_mutations = " ".join(f'({dev(m["mutation_number"])})' for m in record["mutations"])

    return f"""<!DOCTYPE html>
<html lang="mr"><head><meta charset="utf-8"><style>{CSS}
  #sheet {{ font-size: {font_px}px; }}
</style></head>
<body><div id="sheet">
  <div class="watermark">नमुना · SAMPLE</div>

  <div class="gov">महाराष्ट्र शासन</div>
  <div class="title">गाव नमुना सात ( अधिकार अभिलेख पत्रक )</div>
  <div class="rule">[ महाराष्ट्र जमीन महसूल अधिकार अभिलेख आणि नोंदवह्या (तयार करणे व सुस्थितीत
    ठेवणे) नियम १९७१ यातील नियम ३, ५, ६ आणि ७ ]</div>

  <table class="t">
    <tr>
      <td>गाव : <b>{html.escape(record["village"])}</b></td>
      <td>तालुका : <b>{html.escape(record["taluka"])}</b></td>
      <td>जिल्हा : <b>{html.escape(record["district"])}</b></td>
      <td class="qr" rowspan="2">नमुना<br>QR</td>
    </tr>
    <tr>
      <td>PU-ID : <b>{html.escape(record["record_id"])}</b></td>
      <td>गट क्रमांक व उपविभाग : <b>{survey}</b></td>
      <td>खाते क्रमांक : <b>{dev(record["khata_number"])}</b></td>
    </tr>
  </table>

  <table class="t">
    <tr>
      <td style="width:50%">भूधारणा पद्धती : <b>भोगवटादार वर्ग-{dev(record["tenure_class"])}</b></td>
      <td>शेताचे स्थानिक नाव :</td>
    </tr>
  </table>

  <table class="t">
    <tr>
      <th style="width:18%">क्षेत्र, एकक व आकारणी</th>
      <th style="width:7%">खाते क्र.</th>
      <th style="width:23%">भोगवटादाराचे नाव</th>
      <th style="width:8%">क्षेत्र</th>
      <th style="width:7%">आकार</th>
      <th style="width:6%">पो.ख.</th>
      <th style="width:8%">फेरफार क्र.</th>
      <th style="width:23%">कुळ, खंड व इतर अधिकार</th>
    </tr>
    {_owner_rows(record)}
  </table>

  <table class="t">
    <tr>
      <td>जुने फेरफार क्र. : {old_mutations}</td>
      <td style="width:22%">शेरा : —</td>
    </tr>
  </table>

  <div class="sec">फेरफार नोंदवहीतील नोंदी (सारांश)</div>
  <table class="t">
    <tr>
      <th style="width:11%">फेरफार क्र.</th>
      <th style="width:12%">दिनांक</th>
      <th style="width:14%">प्रकार</th>
      <th style="width:27%">कोणाकडून</th>
      <th style="width:27%">कोणाकडे</th>
      <th style="width:9%">क्षेत्र</th>
    </tr>
    {_mutation_rows(record)}
  </table>

  <div class="sec">गाव नमुना बारा — पीक पाहणी</div>
  <table class="t">
    <tr>
      <th style="width:14%">वर्ष</th>
      <th style="width:14%">हंगाम</th>
      <th style="width:30%">पिकाचे नाव</th>
      <th style="width:16%">क्षेत्र (हे.आर.)</th>
      <th style="width:26%">जलसिंचनाचे साधन</th>
    </tr>
    {_crop_rows(record)}
  </table>

  <div class="foot">संगणकनिर्मित नमुना — SYNTHETIC SAMPLE, NOT A REAL LAND RECORD
    &nbsp;·&nbsp; {html.escape(record["record_id"])} &nbsp;·&nbsp; पृष्ठ क्र. १/१</div>

</div></body></html>"""
