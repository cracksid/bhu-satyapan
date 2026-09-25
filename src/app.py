"""Streamlit UI: the screen a revenue official would actually use.

Run it from the project folder, with the virtual environment active:

    streamlit run src/app.py

Four pages:

  * Review queue - every record, worst first, so an official knows what to open
  * Record       - the scan beside the fields, the risk score, and every check
  * Check a scan - the same pipeline run on a page the user uploads
  * Dashboard    - how much has been processed, what is flagged, and where

On the Record page the fields come either from the record as filed or from
what OCR actually read, and the rows OCR was least sure of are shaded.

The tool never edits a land record. It only flags records for a human.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Streamlit runs this file directly, so the project folder is not on Python's
# import path yet. Add it, so "from src.validation ..." works below.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import altair as alt                                        # noqa: E402
import pandas as pd                                          # noqa: E402
import streamlit as st                                       # noqa: E402

from src import demo                                          # noqa: E402
from src.validation.config import RULES                      # noqa: E402
from src.validation.rules import FAIL, PASS                  # noqa: E402
from src.validation.engine import (evaluate, evaluate_batch,  # noqa: E402
                                   load_records)

def _data_folder() -> Path:
    """Where the records live.

    On your machine that is the full generated batch. On the hosted app there
    is no generator, so it falls back to the small dataset committed to the
    repository (see `python -m src.demo dataset`).
    """
    generated = PROJECT_ROOT / "data" / "synthetic" / "ground_truth"
    if generated.is_dir() and any(generated.glob("*.json")):
        return PROJECT_ROOT / "data" / "synthetic"
    return PROJECT_ROOT / "data" / "demo_dataset"


DATA_FOLDER = _data_folder()
REVIEW_FILE = DATA_FOLDER / "review_state.json"

COLOURS = {"green": "#2E7D32", "amber": "#C98A00", "red": "#C0392B"}
INK, MUTED, NAVY = "#12263F", "#5A6472", "#1F4E79"
TINTS = {"green": "#E7F3E9", "amber": "#FDF3DE", "red": "#FBE3E0", "grey": "#EFF2F6"}

# One place for the look of the app. Streamlit's defaults are serviceable but
# plain; this adds cards, pills and a little breathing room, and nothing here
# changes what the app does.
STYLE = """
<style>
  .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px; }
  header[data-testid="stHeader"] { background: transparent; }

  .bs-title { font-size: 30px; font-weight: 700; color: #12263F;
              letter-spacing: -0.4px; line-height: 1.2; margin-bottom: 2px; }
  .bs-sub { color: #5A6472; font-size: 14px; margin-bottom: 4px; }

  .bs-kpi { background: #FFFFFF; border: 1px solid #E3E9F2; border-radius: 12px;
            padding: 14px 16px 12px 16px; height: 100%; }
  .bs-kpi .kpi-label { font-size: 11.5px; color: #5A6472; font-weight: 500;
                       letter-spacing: 0.6px; text-transform: uppercase; }
  .bs-kpi .kpi-value { font-size: 30px; font-weight: 700; line-height: 1.2;
                       margin-top: 2px; }
  .bs-kpi .kpi-note { font-size: 12px; color: #5A6472; }

  .bs-chip { display: inline-block; padding: 4px 11px; border-radius: 999px;
             font-size: 12px; font-weight: 500; margin: 0 6px 7px 0; }

  .bs-card { background: #FFFFFF; border: 1px solid #E3E9F2; border-radius: 12px;
             padding: 16px 18px; margin-bottom: 10px; }
  .bs-section { font-size: 13px; font-weight: 600; color: #12263F;
                text-transform: uppercase; letter-spacing: 0.7px;
                margin: 6px 0 8px 0; }
</style>
"""


def kpi(container, label: str, value, colour: str = INK, note: str = ""):
    """One number in a card. Used across the queue and the dashboard."""
    container.markdown(
        f'<div class="bs-kpi"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value" style="color:{colour}">{value}</div>'
        f'<div class="kpi-note">{note}</div></div>',
        unsafe_allow_html=True)


def check_chips(report):
    """All six checks at a glance: green passed, red failed, grey not checked."""
    pieces = []
    for result in report.results:
        if result.status == FAIL:
            tint, colour, mark = TINTS["red"], COLOURS["red"], "✕"
        elif result.status == PASS:
            tint, colour, mark = TINTS["green"], COLOURS["green"], "✓"
        else:
            tint, colour, mark = TINTS["grey"], MUTED, "–"
        short = result.rule_id.split("_", 1)[0]
        pieces.append(f'<span class="bs-chip" style="background:{tint};color:{colour}" '
                      f'title="{result.title}">{mark} {short}</span>')
    st.markdown("".join(pieces), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading records...")
def load_everything(folder: str):
    """Read the records once and score them all. Cached, so pages are instant."""
    records = load_records(folder)
    reports = evaluate_batch(records)
    return records, reports


@st.cache_data(show_spinner="Reading the page with OCR (about 15 seconds)...")
def read_with_ocr(record_id: str, image_path: str) -> dict:
    """What OCR reads from the scan.

    Served from the demo cache when the record is in it, so a demo never waits
    on Tesseract; read live otherwise. See src/demo.py.
    """
    return demo.read_record(record_id, image_path)


def uploaded_to_image(upload) -> bytes:
    """Turn an uploaded file into image bytes the pipeline can read.

    A PDF is rendered at 200 dpi, which is about what a scanner produces and
    what the OCR step was tuned on. Only the first page: a 7/12 is one page.
    """
    data = upload.getvalue()
    if not upload.name.lower().endswith(".pdf"):
        return data

    import pymupdf
    document = pymupdf.open(stream=data, filetype="pdf")
    if document.page_count == 0:
        raise ValueError("that PDF has no pages")
    page = document.load_page(0)
    return page.get_pixmap(dpi=200).tobytes("png")


@st.cache_data(show_spinner="Reading your page (about 15 seconds)...")
def read_upload(image_bytes: bytes, name: str) -> dict:
    """Run the real pipeline on a file the user just gave us."""
    import tempfile
    from pathlib import Path as _Path

    from src.ocr.extract import extract_from_file

    suffix = ".png" if name.lower().endswith(".pdf") else _Path(name).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(image_bytes)
        temporary = handle.name
    try:
        return extract_from_file(temporary)
    finally:
        _Path(temporary).unlink(missing_ok=True)


def show_value(value, decimals: int = 2) -> str:
    """Format a field for display, saying plainly when OCR could not read it."""
    if value is None or value == "":
        return "— not read —"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def load_reviews() -> dict:
    """What a reviewer has already decided, kept in a small JSON file."""
    if REVIEW_FILE.exists():
        return json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    return {}


def save_review(record_id: str, decision: str, note: str):
    """Append one decision. This is the start of the audit trail."""
    reviews = load_reviews()
    reviews[record_id] = {
        "decision": decision,
        "note": note,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    REVIEW_FILE.write_text(json.dumps(reviews, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def queue_table(records: dict, reports: dict, reviews: dict) -> pd.DataFrame:
    """One row per record, worst risk first."""
    rows = []
    for record_id, record in records.items():
        report = reports[record_id]
        survey = record["survey_number"]
        if record["hissa_number"]:
            survey = f"{survey}/{record['hissa_number']}"
        rows.append({
            "Record": record_id,
            "Risk": report.score,
            "Band": report.band_label,
            "Failed checks": len(report.failed),
            "Village": record["village"],
            "Taluka": record["taluka"],
            "District": record["district"],
            "Survey no.": survey,
            "Status": reviews.get(record_id, {}).get("decision", "Pending"),
        })
    frame = pd.DataFrame(rows)
    return frame.sort_values(["Risk", "Record"], ascending=[False, True]).reset_index(drop=True)


# --------------------------------------------------------------------------
# small pieces of screen
# --------------------------------------------------------------------------
def risk_banner(report):
    """The score, big and colour-coded, with what it is made of."""
    colour = COLOURS[report.band_colour]
    failed = len(report.failed)
    caption = ("No inconsistency found" if not failed
               else f"{failed} of {len(report.results)} checks failed")
    st.markdown(
        f"""
        <div style="background:{colour};color:white;border-radius:10px;
                    padding:14px 18px;margin-bottom:10px;">
          <div style="font-size:13px;opacity:.9;">DISPUTE RISK</div>
          <div style="font-size:44px;font-weight:700;line-height:1.1;">
            {report.score}<span style="font-size:20px;opacity:.85;">/100</span>
          </div>
          <div style="font-size:14px;">{report.band_label} &middot; {caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_checks(report):
    """Every rule: the failures first, in plain English, then the rest."""
    for result in report.failed:
        st.error(
            f"**{result.title}**  \n{result.explanation}  \n"
            f"*Adds {result.weight} points &middot; severity {result.severity} "
            f"&middot; fields: {', '.join(result.fields)}*"
        )
    if not report.failed:
        st.success("Every applicable check passed.")

    with st.expander(f"Checks that passed ({len(report.passed)}) and "
                     f"were not applicable ({len(report.skipped)})"):
        for result in report.passed:
            st.markdown(f"✅ **{result.title}** — {result.explanation}")
        for result in report.skipped:
            st.markdown(f"➖ **{result.title}** — {result.explanation}")


def shade_by_confidence(frame: pd.DataFrame):
    """Tint rows OCR was unsure about: red below 70, amber below 85."""
    def colour(row):
        confidence = row.get("Confidence", None)
        if confidence is None or confidence < 0:
            return [""] * len(row)
        if confidence < 70:
            return ["background-color: #FBE3E0"] * len(row)
        if confidence < 85:
            return ["background-color: #FFF3DB"] * len(row)
        return [""] * len(row)
    return frame.style.apply(colour, axis=1).format({"Confidence": "{:.0f}"})


def field_tables(record: dict, confidences: dict | None = None):
    """The record's own contents, as the form states them.

    When the fields came from OCR, each row also carries how sure Tesseract
    was, and the doubtful ones are shaded for a human to confirm.
    """
    summary = [
        ("District", record["district"], "district"),
        ("Taluka", record["taluka"], "taluka"),
        ("Village", record["village"], "village"),
        ("Survey number", record["survey_number"], "survey_number"),
        ("Hissa number", record["hissa_number"] or "—", "survey_number"),
        ("Khata number", record["khata_number"], "khata_number"),
        ("Tenure", f"भोगवटादार वर्ग-{show_value(record['tenure_class'], 0)}", "tenure_class"),
        ("Total area (ha)", show_value(record["total_area"]), "total_area"),
        ("Cultivable area (ha)", show_value(record["cultivable_area"]), "cultivable_area"),
        ("Pot kharaba (ha)", show_value(record["pot_kharaba"]), "pot_kharaba"),
        ("Assessment (Rs.)", show_value(record["assessment"]), "assessment"),
    ]
    rows = [{"Field": label, "Value": show_value(value)} for label, value, _key in summary]
    if confidences is not None:
        for row, (_label, _value, key) in zip(rows, summary):
            row["Confidence"] = confidences.get(key, -1.0)

    fields_tab, owners_tab, mutations_tab, crops_tab = st.tabs(
        ["Fields", f"Owners ({len(record['owners'])})",
         f"Mutations ({len(record['mutations'])})", "Crops"])

    with fields_tab:
        frame = pd.DataFrame(rows)
        st.dataframe(shade_by_confidence(frame) if confidences is not None else frame,
                     hide_index=True, use_container_width=True)
        st.markdown("**Other rights (इतर हक्क)**")
        for right in record["other_rights"] or ["—"]:
            st.markdown(f"- {right}")

    with owners_tab:
        owner_rows = []
        for owner in record["owners"]:
            row = {"Owner": show_value(owner["name"]),
                   "Share (ha)": show_value(owner["share_area"]),
                   "Assessment (Rs.)": show_value(owner.get("assessment_share"))}
            if confidences is not None:
                row["Confidence"] = min(owner.get("_confidence", {}).get("name", -1.0),
                                        owner.get("_confidence", {}).get("share_area", -1.0))
            owner_rows.append(row)
        frame = pd.DataFrame(owner_rows)
        st.dataframe(shade_by_confidence(frame) if confidences is not None and owner_rows
                     else frame, hide_index=True, use_container_width=True)

    with mutations_tab:
        mutation_rows = []
        for mutation in record["mutations"]:
            row = {"Mutation": show_value(mutation["mutation_number"]),
                   "Date": show_value(mutation["date"]),
                   "Type": show_value(mutation["type"]),
                   "From": show_value(mutation["from_owner"]),
                   "To": show_value(mutation["to_owner"]),
                   "Area (ha)": show_value(mutation["area"])}
            if confidences is not None:
                marks = mutation.get("_confidence", {}).values()
                row["Confidence"] = min(marks) if marks else -1.0
            mutation_rows.append(row)
        frame = pd.DataFrame(mutation_rows)
        st.dataframe(shade_by_confidence(frame) if confidences is not None and mutation_rows
                     else frame, hide_index=True, use_container_width=True)

    with crops_tab:
        st.dataframe(pd.DataFrame([
            {"Year": show_value(c["year"]), "Season": show_value(c["season"]),
             "Crop": show_value(c["crop"]), "Area (ha)": show_value(c["area"]),
             "Irrigation": show_value(c["irrigation"])}
            for c in record["crops"]]), hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
# A coloured dot in front of the band, so the queue can be read at a glance.
BAND_DOTS = {"High": "🔴 High", "Medium": "🟠 Medium",
             "Low": "🟢 Low"}


def page_queue(records, reports, reviews):
    st.markdown('<div class="bs-section">Review queue</div>', unsafe_allow_html=True)
    st.caption("Every record, highest dispute risk first. Click a row to open it.")

    table = queue_table(records, reports, reviews)
    total = len(table)
    flagged = int((table["Failed checks"] > 0).sum())
    high = int((table["Band"] == "High").sum())
    pending = int((table["Status"] == "Pending").sum())

    tiles = st.columns(4)
    kpi(tiles[0], "Records", total, NAVY, "in this batch")
    kpi(tiles[1], "Flagged", flagged, COLOURS["amber"],
        f"{flagged / total * 100:.0f}% of the batch" if total else "")
    kpi(tiles[2], "High risk", high, COLOURS["red"], "open these first")
    kpi(tiles[3], "Reviewed", total - pending, COLOURS["green"],
        f"{pending} still pending")
    st.write("")

    search = st.text_input(
        "Search", placeholder="Search a record id, village, taluka or survey number",
        label_visibility="collapsed")

    left, middle, right = st.columns([1.2, 1.2, 1])
    bands = left.multiselect("Risk band", ["High", "Medium", "Low"],
                             default=["High", "Medium", "Low"])
    districts = middle.multiselect("District", sorted(table["District"].unique()))
    only_pending = right.checkbox("Only records still pending", value=False)

    shown = table[table["Band"].isin(bands)]
    if districts:
        shown = shown[shown["District"].isin(districts)]
    if only_pending:
        shown = shown[shown["Status"] == "Pending"]
    if search.strip():
        # Match the typed text anywhere in the row: id, village, survey number.
        needle = search.strip().lower()
        keep = shown.apply(
            lambda row: needle in " ".join(str(cell).lower() for cell in row), axis=1)
        shown = shown[keep]

    if shown.empty:
        st.info("No record matches those filters. Widen them to see more.")
        return

    st.caption(f"Showing **{len(shown)}** of {total} records")
    display = shown.copy()
    display["Band"] = display["Band"].map(BAND_DOTS)
    event = st.dataframe(
        display, hide_index=True, use_container_width=True, height=430,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Risk": st.column_config.ProgressColumn(
                "Risk", help="Dispute-risk score out of 100",
                min_value=0, max_value=100, format="%d"),
            "Failed checks": st.column_config.NumberColumn("Failed", width="small"),
        },
    )
    if event.selection.rows:
        st.session_state["record_id"] = shown.iloc[event.selection.rows[0]]["Record"]
        st.session_state["page"] = "Record"
        st.rerun()


def page_record(records, reports, reviews):
    record_ids = list(records)
    current = st.session_state.get("record_id", record_ids[0])
    chosen = st.selectbox("Record", record_ids, index=record_ids.index(current),
                          key="record_picker")
    st.session_state["record_id"] = chosen

    is_cached = demo.cached_reading(chosen) is not None
    ocr_label = ("OCR — read from the scan (cached)" if is_cached
                 else "OCR — read the scan now (~15 s)")
    source = st.radio("Fields from", ["The record as filed (instant)", ocr_label],
                      horizontal=True, key=f"source_{chosen}")
    from_ocr = source.startswith("OCR")

    image_path = DATA_FOLDER / "images" / f"{chosen}.jpg"
    if from_ocr and image_path.exists():
        try:
            record = read_with_ocr(chosen, str(image_path))
        except Exception as error:                 # most often: Tesseract missing
            st.error(
                f"The page could not be read: {error}\n\n"
                "If this says Tesseract is not installed, check README steps 3 "
                "and 4, then **restart this app from a new terminal** - a "
                "program keeps the PATH it started with.")
            st.stop()
        report = evaluate(record, {})
        confidences = record.get("_confidence", {})
    else:
        record, report = records[chosen], reports[chosen]
        confidences = None

    survey = show_value(record["survey_number"], 0)
    if record["hissa_number"]:
        survey = f"{survey}/{record['hissa_number']}"
    st.subheader(f"{chosen} — survey {survey}, {show_value(record['village'])}, "
                 f"{show_value(record['taluka'])}, {show_value(record['district'])}")

    image_column, detail_column = st.columns([1.05, 1])
    with image_column:
        if image_path.exists():
            st.image(str(image_path), use_container_width=True)
        else:
            st.warning(f"No image at {image_path}")

    with detail_column:
        if from_ocr:
            meta = record.get("_ocr", {})
            source = "from the demo cache" if meta.get("from_cache") else "read just now"
            st.caption(
                f"OCR {source}: {meta.get('seconds', '?')} s, "
                f"{meta.get('cells', '?')} cells, page straightened by "
                f"{meta.get('deskew_angle', 0)}°, mean confidence "
                f"{meta.get('mean_confidence', '?')}. Shaded rows are the ones "
                f"OCR was least sure of; nothing here is corrected automatically.")
        risk_banner(report)
        check_chips(report)
        show_checks(report)
        field_tables(record, confidences)

        st.divider()
        decided = reviews.get(chosen)
        if decided:
            st.info(f"Marked **{decided['decision']}** on {decided['at']}"
                    + (f" — {decided['note']}" if decided["note"] else ""))
        note = st.text_input("Reviewer note (optional)", key=f"note_{chosen}")
        accept, correct = st.columns(2)
        # The message is kept in session state and shown after the rerun,
        # otherwise the page redraws before the toast has been seen.
        if accept.button("Mark as reviewed", use_container_width=True):
            save_review(chosen, "Reviewed", note)
            st.session_state["flash"] = f"{chosen} marked as reviewed"
            st.rerun()
        if correct.button("Needs correction", type="primary", use_container_width=True):
            save_review(chosen, "Needs correction", note)
            st.session_state["flash"] = f"{chosen} sent for correction"
            st.rerun()
        st.caption("Recording a decision never changes the land record itself.")


def page_upload(records, reports, reviews):
    st.markdown('<div class="bs-section">Check a scan</div>', unsafe_allow_html=True)
    st.caption("Upload a 7/12 extract and the system reads it, checks it, and "
               "scores it — the same pipeline the sample records go through.")

    if demo.demo_mode():
        st.warning(
            "This copy is running in cached mode, so it cannot read a new page: "
            "Tesseract is not installed here. Run the app on a machine with "
            "Tesseract (README steps 3 and 4) to check your own scans.")
        st.stop()

    upload = st.file_uploader("A scanned 7/12 extract",
                              type=["jpg", "jpeg", "png", "pdf"])
    if upload is None:
        st.info("JPG, PNG or PDF. A PDF is read at 200 dpi, first page only.")
        return

    try:
        image_bytes = uploaded_to_image(upload)
        record = read_upload(image_bytes, upload.name)
    except Exception as error:
        st.error(f"That page could not be read: {error}")
        return

    # Nothing to compare against: rules needing the rest of the batch will say so.
    report = evaluate(record, {})

    image_column, detail_column = st.columns([1.05, 1])
    with image_column:
        st.image(image_bytes, use_container_width=True)
    with detail_column:
        meta = record.get("_ocr", {})
        st.caption(f"Read in {meta.get('seconds', '?')} s — {meta.get('cells', '?')} "
                   f"cells, straightened by {meta.get('deskew_angle', 0)}°, mean "
                   f"confidence {meta.get('mean_confidence', '?')}.")
        risk_banner(report)
        check_chips(report)
        show_checks(report)
        field_tables(record, record.get("_confidence", {}))

    st.caption("This page was not saved and no land record was changed. Checks "
               "that compare one record against others cannot run on a single "
               "upload, and say so above.")


def page_dashboard(records, reports, reviews):
    st.markdown('<div class="bs-section">Dashboard</div>', unsafe_allow_html=True)
    st.caption("How much of the batch has been processed, what is flagged, "
               "and which check is failing most often.")

    table = queue_table(records, reports, reviews)
    total = len(table)
    flagged = table[table["Failed checks"] > 0]
    pending = flagged[flagged["Status"] == "Pending"]

    tiles = st.columns(5)
    kpi(tiles[0], "Processed", total, NAVY, "records scored")
    kpi(tiles[1], "Clean", total - len(flagged), COLOURS["green"], "no check failed")
    kpi(tiles[2], "Flagged", len(flagged), COLOURS["amber"], "at least one failure")
    kpi(tiles[3], "High risk", int((table["Band"] == "High").sum()), COLOURS["red"],
        "score 20 or more")
    kpi(tiles[4], "Pending", len(pending), INK, "awaiting a reviewer")
    st.write("")

    left, right = st.columns([1.35, 1])

    with left:
        st.markdown('<div class="bs-section">Which check fails most often</div>',
                    unsafe_allow_html=True)
        counts = []
        for rule_id in RULES:
            failures = sum(1 for report in reports.values()
                           if any(r.rule_id == rule_id for r in report.failed))
            # Short labels: the full titles do not fit on a chart axis.
            number, name = rule_id.split("_", 1)
            counts.append({"Check": f"{number} {name.replace('_', ' ')}",
                           "Failures": failures})
        frame = pd.DataFrame(counts)
        bars = alt.Chart(frame).mark_bar(
            cornerRadiusEnd=4, color=NAVY, size=22).encode(
            x=alt.X("Failures:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("Check:N", title=None, sort="-x"),
            tooltip=["Check", "Failures"])
        labels = bars.mark_text(align="left", dx=5, color=MUTED,
                                fontSize=12).encode(text="Failures:Q")
        st.altair_chart((bars + labels).properties(height=250),
                        use_container_width=True)

    with right:
        st.markdown('<div class="bs-section">Risk bands</div>', unsafe_allow_html=True)
        band_counts = table["Band"].value_counts()
        band_frame = pd.DataFrame({
            "Band": ["Low", "Medium", "High"],
            "Records": [int(band_counts.get(name, 0))
                        for name in ["Low", "Medium", "High"]]})
        donut = alt.Chart(band_frame).mark_arc(
            innerRadius=58, stroke="#FFFFFF", strokeWidth=2).encode(
            theta=alt.Theta("Records:Q", stack=True),
            color=alt.Color("Band:N",
                            scale=alt.Scale(
                                domain=["Low", "Medium", "High"],
                                range=[COLOURS["green"], COLOURS["amber"],
                                       COLOURS["red"]]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Band", "Records"])
        # The total sits in the hole of the ring.
        centre = alt.Chart(pd.DataFrame({"label": [f"{total} records"]})).mark_text(
            fontSize=15, color=MUTED).encode(text="label:N")
        st.altair_chart((donut + centre).properties(height=250),
                        use_container_width=True)

    st.markdown('<div class="bs-section">District-wise progress</div>',
                unsafe_allow_html=True)
    by_district = table.groupby("District").agg(
        Records=("Record", "count"),
        Flagged=("Failed checks", lambda values: int((values > 0).sum())),
    )
    by_district["Flagged %"] = (by_district["Flagged"] / by_district["Records"]
                                * 100).round(1)
    st.dataframe(
        by_district.sort_values("Records", ascending=False),
        use_container_width=True,
        column_config={"Flagged %": st.column_config.ProgressColumn(
            "Flagged %", min_value=0, max_value=100, format="%.0f%%")})


# --------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Bhu-Satyapan — 7/12 validation",
                       page_icon="📄", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)

    # A message left by the previous run (see the review buttons).
    flash = st.session_state.pop("flash", None)
    if flash:
        st.toast(flash, icon="✅")

    st.markdown(
        '<div class="bs-title">Bhu-Satyapan '
        '<span style="font-size:15px;font-weight:500;color:#5A6472;">'
        '· 7/12 record validation</span></div>'
        '<div class="bs-sub">Reads a 7/12 extract, checks it for '
        'inconsistencies, and flags the risky ones for a human. '
        'It never edits a land record.</div>',
        unsafe_allow_html=True)

    try:
        records, reports = load_everything(str(DATA_FOLDER))
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    reviews = load_reviews()
    pages = {"Review queue": page_queue, "Record": page_record,
             "Check a scan": page_upload, "Dashboard": page_dashboard}
    with st.sidebar:
        st.markdown('<div class="bs-title" style="font-size:21px;">Bhu-Satyapan</div>'
                    '<div class="bs-sub">भू-सत्या'
                    'पन · 7/12 validation</div>',
                    unsafe_allow_html=True)
        choice = st.radio("Page", list(pages), label_visibility="collapsed",
                          index=list(pages).index(st.session_state.get("page", "Review queue")))
        st.session_state["page"] = choice
        st.divider()

        # A live summary, so the size of the batch is visible from any page.
        flagged = sum(1 for report in reports.values() if report.failed)
        high = sum(1 for report in reports.values() if report.band_label == "High")
        st.markdown(f"**{len(records)}** records loaded  \n"
                    f"**{flagged}** flagged · **{high}** high risk")
        st.progress(flagged / len(records) if records else 0.0,
                    text="share of the batch flagged")
        st.caption("On the Record page you can switch between the record as "
                   "filed and what OCR reads from the scan.")
        if demo.demo_mode():
            cached = len(demo.load_cache())
            st.success(f"Demo mode: OCR is served from the cache "
                       f"({cached} records). Works offline.")

    pages[choice](records, reports, reviews)


if __name__ == "__main__":
    main()
