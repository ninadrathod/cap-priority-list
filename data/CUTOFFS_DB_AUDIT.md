# Cutoffs DB Audit Report

**Database:** `data/cutoffs_db.csv`  
**Source:** all CAP cutoff PDFs under `raw/*/Cutoffs/`  
**Latest audit:** 2026-07-27 (thorough re-check)

## Verdict

**PASS.** No missing choice codes or colleges vs source PDFs. Required fields complete. Spot-checks and random re-extracts match PDF text.

## Metrics

| Metric | Value |
|--------|------:|
| Rows | 187,149 |
| Unique choice codes | 2,187 |
| Unique college codes | 361 |
| Missing required fields | **0** |
| Choice↔college prefix mismatches | **0** |
| PDF choice codes missing from DB (9 files) | **0** |
| PDF college headers missing (CAP1) | **0** |
| Exact duplicate rows | **0** |
| Non-MI ambiguous slots | **0** |
| Dual MI slots (Stage I + MH line in source) | 367 |

## Coverage

All 9 cutoff PDFs: **0 missing / 0 extra** choice codes.

| Year | CAP1 | CAP2 | CAP3 |
|------|-----:|-----:|-----:|
| 2022–23 | 1752 | 1669 | 1664 |
| 2023–24 | 1882 | 1819 | 1773 |
| 2024–25 | 2051 | 2017 | 2004 |

## Accuracy checks

| Check | Result |
|-------|--------|
| 13 known PDF value spot-checks | **13/13 OK** |
| 50 random 2024 CAP1 re-extracts | **50/50 OK** |
| Minority GOPENS double-mapped via MH | **0** |
| OPEN rank↔percentile sanity | top 5% avg rank ≪ bottom 5% |

## Fixes applied during this re-audit

- **Section labeling:** “Maharashtra State Seats Allotted to All India…” was previously skipped as a footer. Fixed so TFWS/EWS under that section keep the correct section name. Non-MI ambiguous slots → **0**.

## Residual (not errors)

1. **367 dual MI values** — real PDF pattern: Stage-I `MI` plus following `MH <rank>` minority allotment. Both stored.
2. **21 college codes with name variants** across years (renames), e.g. Aurangabad → Chhatrapati Sambhajinagar.
3. **2 choice codes with branch-name spelling variants** (`Electrical and Computer` vs `Engineering`).
4. Rare OPEN vs SC percentile inversions in late CAP rounds for low-demand branches — present in source allotments, not parser swaps.

## Rebuild

```bash
python scripts/parse_cutoffs.py
```
