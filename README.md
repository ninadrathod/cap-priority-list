# CAP Priority List

Build a Maharashtra CAP engineering preference list from your MHT-CET results and historical CAP cutoffs.

You give the tool your Final Merit Status (or scorecard). It returns a CSV of college–branch options in three buckets: **aspirational**, **moderate**, and **safe** (~100 choices by default).

**Repository:** [github.com/ninadrathod/cap-priority-list](https://github.com/ninadrathod/cap-priority-list)

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
