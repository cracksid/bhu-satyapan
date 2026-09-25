# Land Record Validation System (SIH26018)

A prototype for **Smart India Hackathon 2026**, problem statement **SIH26018 –
Intelligent Land Record Digitization and Validation System**.

It reads a scanned Maharashtra **7/12 extract (सातबारा उतारा)**, extracts the
fields, checks them for internal inconsistencies, and outputs a
**dispute-risk score (0–100)** together with the specific checks that failed.

> **The system never edits a land record.** It only flags records for human review.

## Status

| Phase | What | Status |
|-------|------|--------|
| 0 | Setup: folders, virtual environment, Tesseract | ✅ Done |
| 1 | Synthetic 7/12 generator | ✅ Done |
| 2 | Validation engine | ✅ Done |
| 3 | Streamlit UI | ✅ Done |
| 4 | OCR pipeline | ✅ Done |
| 5 | Demo reliability | ✅ Done |

---

## Setup (Windows, PowerShell)

Tested on Windows 11 with Python 3.14.7. Any Python 3.11 or newer should work.

### 1. Open PowerShell in the project folder

```powershell
cd "C:\Users\Admin\projects\land validator"
```

Keep the quotes, because the folder name contains a space. Change the path if
your copy of the project is somewhere else.

### 2. Create the virtual environment and install the packages

A **virtual environment** (the `.venv` folder) is a private copy of Python for
this project only, so its packages never clash with other projects.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

- Line 1 creates `.venv`. Do it once.
- Line 2 activates it. Do it **every time you open a new terminal**. Your
  prompt then starts with `(.venv)`.
- Line 3 installs the packages listed in `requirements.txt`. Do it once, and
  again whenever that file changes.
- Line 4 downloads the headless browser that draws the synthetic 7/12 pages
  (about 300 MB, once). A browser is used because it shapes Devanagari
  correctly; see [Generating synthetic records](#generating-synthetic-records-phase-1).

### 3. Install Tesseract OCR with the Marathi language pack

Tesseract is the OCR engine. It is a separate Windows program, not a Python
package; Python talks to it through `pytesseract`. We use the Windows installer
built by UB Mannheim. Their wiki, <https://github.com/UB-Mannheim/tesseract/wiki>,
always links to the newest version.

1. **Download** `tesseract-ocr-w64-setup-5.5.3.20260724.exe` (26.6 MB) from the
   official release page: <https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3>
2. **Check the download is genuine** (optional, but a good habit). This prints
   `True` if the file matches the official SHA-256 checksum:

   ```powershell
   (Get-FileHash "$HOME\Downloads\tesseract-ocr-w64-setup-5.5.3.20260724.exe").Hash -eq "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
   ```

3. **Run the installer** and choose:
   - **Choose Users** → *Install for anyone using this computer*
   - **Choose Components** → expand **Additional language data (download)**
     and tick **Marathi**. Leave everything else as it is (English is already
     included).
   - **Choose Install Location** → keep `C:\Program Files\Tesseract-OCR`

   The installer downloads the Marathi data (about 2 MB) while it installs,
   so stay online.

### 3b. Download the accurate Marathi model (recommended)

Tesseract's installer ships the *fast* Marathi model. The *best* model reads
the small Devanagari numbers on a 7/12 far better - measured on this project's
pages, 63% of them exactly against 86%. Download it once into the project:

```powershell
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata_best/raw/main/mar.traineddata" -OutFile "data\tessdata_best\mar.traineddata"
```

Create the folder first if it does not exist (`mkdir data\tessdata_best`). The
file is about 13 MB and is not committed to git. Without it the pipeline still
runs - it just reads numbers less well, and says so.

### 4. Add Tesseract to PATH

`PATH` is the list of folders Windows searches when you type a program name.
The installer does not add Tesseract to it, so add it once by hand:

1. Press the **Windows key**, type `environment variables`, and open
   **Edit environment variables for your account**.
2. Under **User variables**, select **Path** and click **Edit…**
3. Click **New**, paste `C:\Program Files\Tesseract-OCR`, then click **OK**
   and **OK** again.
4. **Close every terminal and VS Code window, then open a new one.**
   Programs only read PATH when they start.
5. Test it:

   ```powershell
   tesseract --version
   tesseract --list-langs
   ```

   The first command should print `tesseract v5.5.3...`. The language list
   must include `mar`.

### 5. Run the setup check

```powershell
.\.venv\Scripts\Activate.ps1
python check_setup.py
```

The script checks Python, the packages, Tesseract and the Marathi pack. Then it
draws a line of Marathi text and asks Tesseract to read it back. If everything
works it ends with **All checks passed**. Otherwise it stops at the first
`[FAIL]` and tells you how to fix it.

---

## Generating synthetic records (Phase 1)

Real 7/12 extracts contain real people's names, so the system is built and
measured on invented ones instead. The generator writes an image *and* a
ground-truth file for every record: because we know exactly what each page
says, and exactly how it was broken, the rules and the OCR can be scored
honestly later.

```powershell
python -m src.generator.generate
```

That makes 200 records, 30% of them carrying a deliberate defect, in
`data/synthetic/`. Useful variations:

```powershell
python -m src.generator.generate --count 20 --seed 1 --overwrite
```

| Option | Meaning |
|--------|---------|
| `--count 200` | how many records (families are kept whole, so you may get a few extra) |
| `--defect-rate 0.30` | share of records carrying a defect |
| `--seed 42` | the same seed always produces exactly the same batch |
| `--no-degrade` | keep the pages crisp, without the scanner wear |
| `--overwrite` | replace a batch already in the output folder |
| `--out data/synthetic` | where to write |

**What it produces**

```
data/synthetic/
├── images/R0001.jpg          the page, as if it had been scanned
├── ground_truth/R0001.json   what the page really says, plus any defect in it
└── manifest.json             one entry per record
```

**The five defects it injects**, matching the five rules of Phase 2:

| Defect | What is wrong |
|--------|---------------|
| `hissa_area_mismatch` | the hissa areas do not add up to the parent survey number |
| `area_balance_mismatch` | total area != cultivable + pot kharaba |
| `owner_share_mismatch` | the owners' shares do not add up to the total |
| `broken_mutation_chain` | a mutation is sold by somebody who did not own the land |
| `mutation_date_out_of_order` | a mutation is dated before the one before it |

**Why a browser draws the pages.** Devanagari needs shaping: क्षेत्र and
वर्ग-२ are wrong unless conjuncts and matras are placed properly. Pillow can
only do that when an extra library happens to be present, and it fails
silently when it is not. Chromium always gets it right, and an HTML table is
easier to keep looking like a printed form. `src/generator/layout.py` holds
the form, so changing how the page looks means changing HTML and CSS.

**How close the layout is to a real 7/12.** It follows a digitally-signed
extract from the state land-records portal: A4 portrait, the 1971 rule
citation under the title, and one main table whose left block carries
जिरायत / बागायत / एकूण / पो.ख. / आकारणी while each owner has a row with
खाते क्र., क्षेत्र, आकार, पो.ख. and the फेरफार numbers.

Two things are deliberately **not** copied: the State Emblem of India, and
the portal's watermark, QR code and verification number. Fabricated records
carrying those would look like genuine government documents. Every generated
page instead carries a faint "नमुना · SAMPLE" watermark and a footer reading
*SYNTHETIC SAMPLE, NOT A REAL LAND RECORD*.

A real 7/12 lists only mutation *numbers*; the dates and the names of buyer
and seller live in the separate फेरफार register. Rules 4 and 5 need that
detail, so each page carries it in a clearly labelled mutation-register
summary below the form rather than pretending it belongs to Form VII.

---

## Validating records (Phase 2)

The rule engine reads a record as **structured data, never as an image**. It
knows nothing about OCR, which is why it can be trusted and tested on its
own. In Phase 4 the same rules will run over whatever the OCR managed to
read, and any field OCR could not read makes a rule *skip* rather than fail -
unreadable is not the same as wrong.

```powershell
pytest -v                          # the tests, with a detection rate per rule
python -m src.validation.report    # score data/synthetic and measure the rules
```

### The six rules

| Rule | Checks | Weight | Severity |
|------|--------|--------|----------|
| R1 | hissa areas reconcile with the parent survey number | 20 | high |
| R2 | total area = cultivable + pot kharaba | 10 | medium |
| R3 | owner shares add up to the total area | 20 | high |
| R4 | every mutation is made by a recorded owner | 25 | high |
| R5 | mutations are in date order | 5 | medium |
| R6 | the same parcel is not recorded twice | 20 | high |

R6 is the only rule that looks beyond one record and its hissas: it compares
the parcel (village, survey number, hissa) against the whole batch, because
two records for one piece of land is how a parcel gets sold twice.

Each rule returns pass, fail or skipped, with a plain-English explanation
that names the actual numbers, and the fields it looked at:

> The 3 hissa records (R0025, R0026, R0027) add up to 1.47 ha, which is
> 0.12 ha less than the 1.59 ha recorded for survey number 391.

### The dispute-risk score

The score is the **sum of the weights of the failed rules**, so it is always
explainable: a record scoring 37 failed exactly R4 (30) and R5 (8)… nothing
is hidden in a model. Weights add up to 100, so failing everything scores 100.

| Score | Band | Meaning |
|-------|------|---------|
| 0 | green | nothing failed |
| 1–19 | amber | only medium-severity problems |
| 20–100 | red | at least one high-severity problem |

The threshold is 20 because that is the lightest high-severity weight: any
single serious inconsistency turns a record red, while the two medium rules
together (10 + 5) stay amber. A test enforces that rule, so the colours can
never drift away from the severities.

**All of this lives in one file, [`src/validation/config.py`](src/validation/config.py)** -
weights, severities, the area tolerance (0.02 ha = 2 are) and the colour
thresholds. Change a number there and the engine, the tests, the report and
the UI all follow.

### Measured, not asserted

Because the generator recorded every defect it injected, the engine can be
scored honestly. On the 200-record batch:

| | Result |
|---|---|
| defects injected | 70 |
| defects caught | 70 (**100%**) |
| clean records wrongly flagged | **0** of 140 |

---

## The reviewer's screen (Phase 3)

```powershell
streamlit run src/app.py
```

It opens at <http://localhost:8501>. Press Ctrl+C in the terminal to stop it.

| Page | What it is for |
|------|----------------|
| **Review queue** | every record, highest risk first, with filters for band, district and "still pending". Selecting a row opens it. |
| **Record** | the scan on the left; on the right the dispute-risk score, each failed check in plain English, and the fields in tabs (fields, owners, mutations, crops) |
| **Check a scan** | upload your own 7/12 as JPG, PNG or PDF; it is read, checked and scored by the same pipeline, and nothing is saved |
| **Dashboard** | records processed, clean, flagged, high risk, pending verification; how often each check fails; district-wise progress; the three risk bands |

Marking a record **Reviewed** or **Needs correction** writes a line to
`data/synthetic/review_state.json` with the time and any note. That file is
the beginning of an audit trail, and it is what makes "pending verification"
on the dashboard a real number. **Recording a decision never changes the land
record itself** - the system only ever flags.

Each record can be shown two ways, with the **Fields from** switch: the record
as filed (instant), or read from the scan by OCR (about 20 seconds, then
cached). In OCR mode the doubtful fields are shaded and the same five rules
run on whatever was read - see [Reading the scan](#reading-the-scan-phase-4).

`.streamlit/config.toml` fixes a light theme, so the app looks the same on
any machine and screenshots read well on a slide.

---

## Reading the scan (Phase 4)

```powershell
python -m src.ocr.evaluate --count 12       # measure OCR against the ground truth
```

In the UI, open a record and switch **Fields from** to *OCR — read the scan
now*. The same screen then shows what Tesseract actually read, with the
doubtful fields shaded, and the same five rules run on it.

### The pipeline

| Step | What happens | Where |
|------|--------------|-------|
| 0 | scale the page to 1650 px wide, whatever came in | `preprocess.py` |
| 1 | grayscale, deskew, denoise, Sauvola binarise, lift off the ruling lines | `preprocess.py` |
| 2 | find the cells the printed rules box in, group them into rows and tables | `tables.py` |
| 3 | OCR each cell separately (Tesseract mar+eng), keeping a confidence | `read.py` |
| 4 | map cells to fields by position, normalise Devanagari digits ०-९ to 0-9 | `extract.py` |
| 5 | measure against the ground truth | `evaluate.py` |

Reading cell by cell rather than throwing the whole page at Tesseract is what
makes every value arrive with a position - that is how the extractor can say
"this number is the total area" instead of "this is a number somewhere".

**Step 0 matters more than it looks.** Several numbers downstream are in
pixels: the Sauvola window, the smallest thing that counts as a cell, how far
inside a border to crop, how much to enlarge a cell for Tesseract. A PDF
rendered at 200 dpi arrives about 3,500 px wide, and at that size those
numbers no longer describe the page - the mutation table stopped being found
at all. Scans arrive at any resolution, so every page is scaled to one width
first and the pixel numbers are tuned once. The same page now reads the same
at 200 dpi, 400 dpi and from the original image.

### Four things that were measured, not guessed

Each of these came from scoring cells whose correct text the ground truth
already holds:

| Change | Character error rate |
|--------|----------------------|
| crop including the cell borders (first attempt) | 41% |
| crop **inside** the borders — stray `|` and `___` gone | 9% |
| feed Tesseract the **grayscale** crop, not our binarised one | 3% |
| enlarge **3×** — matras and the decimal point are a few pixels tall | 2% |

A digit whitelist for numeric cells sounded obvious and made things far worse
(29%): the LSTM engine reads better with its language model intact. `--psm 8`
and `--psm 13` collapse completely on these cells.

### How a figure earns the right to be judged

Tesseract's own confidence turned out to be a weak guide: figures it scored
90+ were right 94% of the time, below that about 75%. Not good enough to judge
a record on, because a rule comparing three numbers is only as good as its
worst one.

What works is **agreement between two independent models**. Every number the
rules depend on is read twice, with the fast model and the accurate one:

| | Correct |
|---|---|
| both models read the same number | **38/38 (100%)** |
| they disagreed | 45% |

So a figure is only judged when both models agree. When they differ, the rule
reports *"two independent OCR readings disagreed"* and the record goes to a
human — which is exactly the human-assisted verification the problem statement
asks for. **Nothing is ever auto-corrected to make a record look consistent.**

### What it actually reads — measured on 16 pages

```powershell
python -m src.ocr.evaluate --count 16 --seed 11
```

| | Result |
|---|---|
| character error rate, Marathi text | **1.6%** |
| field-level accuracy, all fields | **90.0%** |
| village, taluka, district, PU-ID, mutation numbers | 100% |
| mutation dates | 97.6% |
| owner names | 94.7% |
| survey / hissa / khata numbers | 93.8% |
| areas (total, cultivable, pot kharaba, assessment) | 75–81% |
| owner shares | 63.2% |
| time | ~14 s per page |

Names and places read almost perfectly; **small two-decimal numbers are the
weak point**, and those are exactly what the rules compare. Degradation is not
the cause — crisp renders score no better (81.7% against 83.7%). It is the
Marathi model on small digits.

### What that means end to end

Because the agreement gate only lets through figures both models confirm,
every reading it accepted in this run was correct — 131 of 131.

| | Result |
|---|---|
| records checked automatically | **3 of 16 (19%)** |
| of those, identical risk score to the true record | 2 of 3 |
| clean records wrongly flagged | **0** |
| real defects missed | **0** |
| records routed to a human | 13 of 16 (81%) |

Turn the gate off and it will check all 16 — and wrongly flag 11 of the 14
clean ones. That is the honest trade, and it is why the gate exists: a land
record system that cries wolf four times out of five is worse than useless.

**Raising that 19% means better OCR, not a looser rule** — fine-tuning the
Marathi model on fields reviewers have corrected is the roadmap item that
moves it.

---

## Demo day (Phase 5)

Reading a page takes about 15 seconds and needs Tesseract. That is fine at a
desk and wrong in front of judges, so the OCR results for the showcase records
are computed once and stored in `data/demo_cache.json`.

```powershell
$env:BHU_DEMO_MODE = "1"
streamlit run src/app.py
```

In demo mode the app serves OCR **only** from the cache and never calls
Tesseract, so it cannot stall and it works with the network switched off. The
sidebar says so, and the Record page shows *"OCR from the demo cache"*.

| Command | What it does |
|---------|--------------|
| `python -m src.demo pick` | choose the two showcase records and cache their readings |
| `python -m src.demo build R0013` | cache another record |
| `python -m src.demo list` | show what is cached |

`pick` does not just take the first clean and first flagged record: it reads
each candidate with OCR and keeps only ones that behave in **both** modes -
the clean record must still come out clean when read from the scan, and the
flagged one must still be flagged for the same reason. A demo record that only
works on paper is no use in front of an audience.

The two chosen records are stored in `data/demo_records.json`:

| Record | Shows |
|--------|-------|
| **R0001** | a clean record: every check passes, score 0, green |
| **R0003** | a mutation sold by somebody who never held the land - red, and the OCR reading finds it too |

### The whole thing from scratch

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python check_setup.py                      # Tesseract + Marathi must pass first
python -m src.generator.generate           # 200+ records with ground truth
pytest -v                                  # the rules, measured against it
python -m src.validation.report            # scores and detection rates
python -m src.demo pick                    # showcase records + OCR cache
streamlit run src/app.py                   # the reviewer's screen
```

---

## Project structure

```
land validator/
├── check_setup.py       Phase 0: checks Python, packages, Tesseract and Marathi
├── requirements.txt     Python packages, with exact versions
├── .gitignore           keeps .venv/ and data/real/ out of git
├── .venv/               virtual environment (made on each machine, never committed)
├── data/
│   ├── synthetic/       generated images + ground truth (not committed; rebuild it)
│   └── real/            real extracts you download by hand (NEVER committed)
├── src/
│   ├── generator/       Phase 1: synthetic 7/12 generator
│   │   ├── names.py       invented people and villages
│   │   ├── record.py      builds one consistent survey number + its hissas
│   │   ├── defects.py     breaks records on purpose, and records how
│   │   ├── layout.py      the 7/12 form itself, as HTML + CSS
│   │   ├── render.py      HTML -> image, via headless Chromium
│   │   ├── degrade.py     tilt, blur, noise, uneven light, JPEG artefacts
│   │   └── generate.py    the command you run
│   ├── validation/      Phase 2: rule engine
│   │   ├── config.py      weights, severities, tolerance, colour bands
│   │   ├── rules.py       the six checks
│   │   ├── engine.py      runs the rules, adds up the score
│   │   └── report.py      scores a batch, measures it against ground truth
│   ├── demo.py          Phase 5: cached OCR results, so a demo never stalls
│   ├── ocr/             Phase 4: preprocessing, OCR, field extraction
│   │   ├── preprocess.py  deskew, denoise, binarise, lift off the ruling lines
│   │   ├── tables.py      find the cells the rules box in
│   │   ├── read.py        OCR a cell, with confidence and two-model agreement
│   │   ├── extract.py     cells -> record fields
│   │   └── evaluate.py    measure it all against the ground truth
│   └── app.py           Phase 3: the Streamlit UI (queue, record, upload, dashboard)
├── .streamlit/
│   └── config.toml      fixes the light theme for the UI
├── packages.txt         Linux programs the hosted copy needs (Tesseract)
├── pytest.ini           lets the tests import src/ from the project folder
└── tests/
    ├── test_validation.py     Phase 2: the rules, and detection per rule
    └── test_ocr_parsing.py    Phase 4: digits, dates, labels, the area block
```

## Data rules

- `data/real/` is listed in `.gitignore`. Real extracts contain real people's
  names, so never commit them and never use them in screenshots or demo records.
- Synthetic records use invented names and invented village names only.
- No scrapers for any government portal. Real extracts are downloaded by hand.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. Or skip activation and run `.\.venv\Scripts\python.exe check_setup.py` instead. |
| `tesseract : The term 'tesseract' is not recognized` | Tesseract is not on PATH, or the terminal was opened before PATH changed. Redo step 4 and open a **new** terminal. |
| `mar` is missing from `tesseract --list-langs` | The installer could not download it. Download `mar.traineddata` from <https://github.com/tesseract-ocr/tessdata_fast/raw/main/mar.traineddata> (the same file the installer uses). Copy it into `C:\Program Files\Tesseract-OCR\tessdata\`. Windows will ask for admin permission. |
| The hosted app says "cached mode ... Tesseract is not installed here" | The Streamlit Cloud container builds from `packages.txt`. Check that file is in the repository, then open the app's menu on share.streamlit.io and choose **Reboot app** so it rebuilds. Note the hosted copy has no `tessdata_best`, so it has no second opinion on numbers and will skip more checks than your laptop. |
| Marathi text shows as boxes in the terminal | That is only the terminal's font. The check compares the actual text, so a `[PASS]` is still a pass. |
| Things break after you move or rename the project folder | A virtual environment remembers its full path. Delete `.venv` and redo step 2. |
