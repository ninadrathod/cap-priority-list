# CAP Priority List

Build a **Maharashtra CAP engineering preference list** from your MHT-CET results and historical CAP cutoffs.

You give the tool your Final Merit Status (or scorecard). It returns a CSV of college–branch options in three buckets: **aspirational**, **moderate**, and **safe** (~100 choices by default).

**Repository:** [github.com/ninadrathod/cap-priority-list](https://github.com/ninadrathod/cap-priority-list)

**How it works (GitHub Pages):** open [`index.html`](./index.html) in this repo, or enable Pages on the `main` branch (root) so the same page is served publicly.

---

## Quick start

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/ninadrathod/cap-priority-list.git
cd cap-priority-list

python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

Later sessions: `cd` into the project and run `source .venv/bin/activate` again before using the scripts.

### 2. Build the cutoff database (once)

Historical CAP PDFs already live under `raw/`. Parse them into a CSV database:

```bash
python scripts/parse_cutoffs.py
```

This creates `data/cutoffs_db.csv`. Re-run only when you add new cutoff years.

### 3. Add your candidate file

**Best option — Final Merit Status**

1. Open your merit status on the CET site
2. Save the page as `.mht` / `.mhtml` (Chrome: “Webpage, Complete”)
3. Put it in this folder (or anywhere you like)

**Or — CET scorecard PDF**

Place it under `scorecards/` (that folder is gitignored so personal files stay local).

### 4. Generate recommendations

```bash
# Merit status (preferred — uses State General Merit No)
python generate_recommendations.py "Your Name.mht" --streams all

# Scorecard PDF (percentile matching)
python generate_recommendations.py scorecards/your_scorecard.pdf --streams all
```

Open `output/recommendations.csv` in Excel / Google Sheets.

---

## Choosing branches (streams)

| # | Stream | Typical courses |
|---|--------|-----------------|
| 1 | Computer Science & IT | CSE, IT, AI/ML, Data Science, IoT |
| 2 | Electronics & Communication | EXTC, ECE, Instrumentation |
| 3 | Electrical Engineering | Electrical, Electrical & Power |
| 4 | Mechanical Engineering | Mechanical, Auto, Mechatronics, Robotics |
| 5 | Civil Engineering | Civil, Structural |

```bash
# All five streams
python generate_recommendations.py candidate.mht --streams all

# Only CS + Electronics
python generate_recommendations.py candidate.mht --streams 1,2
python generate_recommendations.py candidate.mht --streams cs,electronics

# Interactive prompt (no --streams)
python generate_recommendations.py candidate.mht
```

---

## Useful options

```bash
python generate_recommendations.py candidate.mht \
  --streams all \
  -o output/recommendations.csv \
  --aspirational 30 \
  --moderate 40 \
  --safe 30
```

| Flag | What it does |
|------|----------------|
| `-o` | Output CSV path |
| `--streams` | `all`, `1,2`, or names like `cs,mechanical` |
| `--aspirational` / `--moderate` / `--safe` | How many rows per bucket (default 30 / 40 / 30) |
| `--female` / `--male` | Force gender if auto-detect is wrong |
| `--db` | Alternate cutoff database path |

---

## What the CSV means

| Column | Meaning |
|--------|---------|
| `priority` | Suggested order (1 = try first) |
| `bucket` | `aspirational` / `moderate` / `safe` |
| `college` / `branch` / `choice_code` | CAP option |
| `college_type` | Government, Government-Aided, University, or Private |
| `median_closing_merit` | Typical historical closing State Merit (when available) |
| `clear_rate` | Share of past rounds you would likely have cleared |
| `candidate_*` | Your parsed details (for reference) |

Government / aided / university colleges are preferred in the shortlist when they qualify.

---

## How matching works (short version)

1. **Category + gender** decide which seats you can take  
   - Your category seats + OPEN  
   - Female candidates also get Ladies (`L*`) seats  
2. **Merit file** → match on **State General Merit No** vs CAP closing ranks (lower rank = better)  
3. **Scorecard only** → match on **percentile**  
4. Options are scored across 3 years × CAP1–3, then bucketed and shortlisted  

Home University is stored from the merit page but **not applied yet** (H/O/S seats are pooled).

For a visual walkthrough of the logic, open [`index.html`](./index.html).

---

## Project layout

```text
cap-priority-list/
├── index.html                    # Project page (GitHub Pages)
├── generate_recommendations.py   # Main command
├── requirements.txt
├── raw/                          # Historical CAP cutoff PDFs
├── input/                        # Your merit/scorecard files (gitignored)
├── data/cutoffs_db.csv           # Parsed cutoff DB (after step 2)
├── scorecards/                   # Optional alternate for PDFs (gitignored)
├── output/                       # Generated CSV (gitignored)
└── scripts/
    ├── parse_cutoffs.py
    └── branch_categories.py
```

Personal files (`input/*`, `scorecards/*`, `*.mht`, `output/*`) are gitignored — do not commit them.

---

## Adding a new cutoff year

1. Create `raw/2025-26/Cutoffs/`
2. Add CAP1 / CAP2 / CAP3 PDFs (filenames should contain `CAP1`, `CAP2`, `CAP3`)
3. Run `python scripts/parse_cutoffs.py` again

---

## Publish the project page (GitHub Pages)

1. Push this repo to GitHub  
2. **Settings → Pages → Build and deployment**  
3. Source: **Deploy from a branch**  
4. Branch: `main` (or `master`), folder: `/ (root)`  
5. Save — the site will serve `index.html` at  
   `https://ninadrathod.github.io/cap-priority-list/`
