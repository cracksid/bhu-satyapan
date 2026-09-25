"""Streamlit UI: the screen a revenue official would actually use.

Run it from the project folder, with the virtual environment active:

    streamlit run src/app.py

Three pages:

  * Review queue - every record, worst first, so an official knows what to open
  * Record       - the scan beside the fields, the risk score, and every check
  * Dashboard    - how much has been processed, what is flagged, and where

For now the fields come from the ground-truth JSON. In Phase 4 the same
screens will show what the OCR actually read, with low-confidence fields
shaded - nothing else about these pages has to change.

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

import pandas as pd                                          # noqa: E402
import streamlit as st                                       # noqa: E402

from src import demo                                          # noqa: E402
from src.validation.config import RULES                      # noqa: E402
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
def page_queue(records, reports, reviews):
    st.subheader("Review queue")
    st.caption("Every record, highest dispute risk first. Select a row to open it.")

    table = queue_table(records, reports, reviews)

    left, middle, right = st.columns(3)
    bands = left.multiselect("Risk band", ["High", "Medium", "Low"],
                             default=["High", "Medium", "Low"])
    districts = middle.multiselect("District", sorted(table["District"].unique()))
    only_pending = right.checkbox("Only records still pending", value=False)

    shown = table[table["Band"].isin(bands)]
    if districts:
        shown = shown[shown["District"].isin(districts)]
    if only_pending:
        shown = shown[shown["Status"] == "Pending"]

    st.write(f"**{len(shown)}** of {len(table)} records")
    event = st.dataframe(
        shown, hide_index=True, use_container_width=True, height=430,
        on_select="rerun", selection_mode="single-row",
        column_config={"Risk": st.column_config.ProgressColumn(
            "Risk", min_value=0, max_value=100, format="%d")},
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
        show_checks(report)
        field_tables(record, confidences)

        st.divider()
        decided = reviews.get(chosen)
        if decided:
            st.info(f"Marked **{decided['decision']}** on {decided['at']}"
                    + (f" — {decided['note']}" if decided["note"] else ""))
        note = st.text_input("Reviewer note (optional)", key=f"note_{chosen}")
        accept, correct = st.columns(2)
        if accept.button("Mark as reviewed", use_container_width=True):
            save_review(chosen, "Reviewed", note)
            st.rerun()
        if correct.button("Needs correction", type="primary", use_container_width=True):
            save_review(chosen, "Needs correction", note)
            st.rerun()
        st.caption("Recording a decision never changes the land record itself.")


def page_upload(records, reports, reviews):
    st.subheader("Check a scan")
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
        show_checks(report)
        field_tables(record, record.get("_confidence", {}))

    st.caption("This page was not saved and no land record was changed. Checks "
               "that compare one record against others cannot run on a single "
               "upload, and say so above.")


def page_dashboard(records, reports, reviews):
    st.subheader("Dashboard")
    table = queue_table(records, reports, reviews)

    flagged = table[table["Failed checks"] > 0]
    pending = flagged[flagged["Status"] == "Pending"]
    columns = st.columns(5)
    columns[0].metric("Records processed", len(table))
    columns[1].metric("Clean", len(table) - len(flagged))
    columns[2].metric("Flagged", len(flagged))
    columns[3].metric("High risk", int((table["Band"] == "High").sum()))
    columns[4].metric("Pending verification", len(pending))

    left, right = st.columns(2)
    with left:
        st.markdown("**Error statistics — how often each check fails**")
        counts = []
        for rule_id, rule in RULES.items():
            failures = sum(1 for report in reports.values()
                           if any(r.rule_id == rule_id for r in report.failed))
            # Short labels: the full titles do not fit on a chart axis.
            short = rule_id.split("_", 1)[0] + " " + rule_id.split("_", 1)[1].replace("_", " ")
            counts.append({"Check": short, "Records failing": failures})
        st.bar_chart(pd.DataFrame(counts).set_index("Check"), horizontal=True, height=260)

    with right:
        st.markdown("**District-wise progress**")
        by_district = table.groupby("District").agg(
            Records=("Record", "count"),
            Flagged=("Failed checks", lambda values: int((values > 0).sum())),
        )
        by_district["Flagged %"] = (by_district["Flagged"] / by_district["Records"] * 100).round(1)
        st.dataframe(by_district.sort_values("Records", ascending=False),
                     use_container_width=True)

    # Three coloured counts rather than a chart: same colours as the record
    # screen, and a bar chart puts the bands in alphabetical order.
    st.markdown("**Risk bands**")
    counts = table["Band"].value_counts()
    for column, (label, colour_key) in zip(st.columns(3),
                                           [("Low", "green"), ("Medium", "amber"),
                                            ("High", "red")]):
        count = int(counts.get(label, 0))
        share = count / len(table) * 100 if len(table) else 0
        column.markdown(
            f"""
            <div style="background:{COLOURS[colour_key]};color:white;border-radius:10px;
                        padding:12px 16px;">
              <div style="font-size:13px;opacity:.9;">{label.upper()}</div>
              <div style="font-size:34px;font-weight:700;line-height:1.15;">{count}</div>
              <div style="font-size:13px;">{share:.0f}% of records</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Bhu-Satyapan — 7/12 validation",
                       page_icon="📄", layout="wide")
    st.title("Bhu-Satyapan")
    st.caption("Reads a 7/12 extract, checks it for inconsistencies, and flags "
               "the risky ones for a human. It never edits a land record.")

    try:
        records, reports = load_everything(str(DATA_FOLDER))
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()

    reviews = load_reviews()
    pages = {"Review queue": page_queue, "Record": page_record,
             "Check a scan": page_upload, "Dashboard": page_dashboard}
    with st.sidebar:
        st.header("Bhu-Satyapan")
        choice = st.radio("Page", list(pages),
                          index=list(pages).index(st.session_state.get("page", "Review queue")))
        st.session_state["page"] = choice
        st.divider()
        st.caption(f"{len(records)} records loaded from `data/synthetic`.\n\n"
                   "On the Record page you can switch between the record as "
                   "filed and what OCR reads from the scan.")
        if demo.demo_mode():
            cached = len(demo.load_cache())
            st.success(f"Demo mode: OCR is served from the cache "
                       f"({cached} records). Works offline.")

    pages[choice](records, reports, reviews)


if __name__ == "__main__":
    main()
