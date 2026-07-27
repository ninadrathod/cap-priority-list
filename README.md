# CAP Priority List

Generate a Maharashtra CAP engineering admission preference shortlist from an MHT-CET scorecard, using historical category-wise cutoffs.

Given a candidate's scorecard PDF, the tool:

1. Reads **category**, **percentile**, and **gender** (for female `L*` seats)
2. Matches against 3 years of CAP Round 1–3 cutoffs
3. Writes a curated CSV of **aspirational / moderate / safe** college–branch options

---

## Directory layout

```text
cap-priority-list/
├── generate_recommendations.py   # Main CLI
├── requirements.txt
├── README.md
├── raw/                          # Historical cutoff + seat-matrix PDFs
│   ├── 2022-23/
│   ├── 2023-24/
│   └── 2024-25/
├── scorecards/                   # Put candidate scorecard PDFs here
├── data/
│   └── cutoffs_db.csv            # Parsed cutoff database (generated)
├── output/
│   └── recommendations.csv       # Recommendation CSV (generated)
└── scripts/
    ├── parse_cutoffs.py          # One-time PDF → database builder
    └── branch_categories.py      # Branch → stream mapping
```

---

## Setup

```bash
pip install -r requirements.txt
```

Build the cutoff database once (or again after adding new year PDFs under `raw/`):

```bash
python scripts/parse_cutoffs.py
```

This writes `data/cutoffs_db.csv`.

---

## Branch streams

Branches are grouped into five streams:

| # | Stream | Examples |
|---|--------|----------|
| 1 | Computer Science & IT | CSE, IT, AI/ML, Data Science, Cyber Security, IoT |
| 2 | Electronics & Communication | EXTC, ECE, VLSI, Instrumentation, 5G |
| 3 | Electrical Engineering | Electrical, Electrical & Power |
| 4 | Mechanical Engineering | Mechanical, Automobile, Mechatronics, Production, Robotics & Automation |
| 5 | Civil Engineering | Civil, Structural, Environmental Civil |

Specialized branches (Chemical, Textile, Food, etc.) are excluded unless you add them later.

When you run the tool **without** `--streams`, it asks interactively which streams to use.

```bash
# Interactive prompt for streams
python generate_recommendations.py scorecards/your_scorecard.pdf

# Or pass streams non-interactively
python generate_recommendations.py scorecards/your_scorecard.pdf --streams 1,2
python generate_recommendations.py scorecards/your_scorecard.pdf --streams cs,electronics
python generate_recommendations.py scorecards/your_scorecard.pdf --streams all
```

## Usage

Place the candidate MHT-CET scorecard PDF in `scorecards/`, then run:

```bash
python generate_recommendations.py scorecards/your_scorecard.pdf
```

Default output: `output/recommendations.csv`

### Options

```bash
python generate_recommendations.py scorecards/your_scorecard.pdf \
  -o output/recommendations.csv \
  --streams 1,2 \
  --aspirational 30 \
  --moderate 40 \
  --safe 30 \
  --female
```

| Flag | Meaning |
|------|---------|
| `-o` / `--output` | Output CSV path |
| `--db` | Path to cutoff database (default `data/cutoffs_db.csv`) |
| `--streams` | Branch streams to include (`1,2`, `cs,mechanical`, or `all`). If omitted, prompts interactively |
| `--aspirational` | Max aspirational rows (default 30) |
| `--moderate` | Max moderate rows (default 40) |
| `--safe` | Max safe rows (default 30) |
| `--female` / `--male` | Override gender detection from the scorecard |

### Output CSV columns

| Column | Description |
|--------|-------------|
| `priority` | Preference order (1 = highest) |
| `bucket` | `aspirational`, `moderate`, or `safe` |
| `stream` | Selected branch stream label |
| `college` | Institute name |
| `branch` | Course name |
| `choice_code` | CAP choice code |
| `college_type` | Government / Government-Aided / University / Private |
| `median_closing_percentile` | Typical historical closing percentile |
| `min_closing_percentile` | Easiest historical closing percentile |
| `difficulty_score` | Weighted competitiveness score |
| `clear_rate` | Share of past rounds the candidate would have cleared |
| `candidate_*` | Parsed scorecard fields |

Multiple streams from the same college can appear in the list.

---

## How recommendations work

- Eligible seats: candidate **category** (e.g. DT/VJ → `GVJ*`) plus **OPEN** (`GOPEN*`)
- Female candidates also get **Ladies** seats (`L*`); male candidates do not
- Only branches in the **selected streams** are considered
- Home University is **not** applied yet (H/O/S seats are pooled)
- Only Stage-I cutoffs with a realistic chance are kept
- A shortlist of ~100 options is curated across the three buckets (30 / 40 / 30)
- Government, government-aided, and university colleges are preferred when they qualify

---

## Adding new cutoff years

1. Add a folder under `raw/`, e.g. `raw/2025-26/Cutoffs/`
2. Put CAP1/CAP2/CAP3 cutoff PDFs there (names containing `CAP1`, `CAP2`, `CAP3`)
3. Re-run `python scripts/parse_cutoffs.py`
