#!/usr/bin/env python3
"""
Generate a CAP college-branch priority shortlist from a candidate profile.

Accepts either:
  - MHT-CET scorecard PDF (percentile-based matching), or
  - CET Final Merit Status page saved as .mht / .mhtml / .html
    (State General Merit No used for matching — preferred when available)

Example:
  python generate_recommendations.py "Nikhil Dnyaneshwar Jadhav.mht" -o output/recommendations.csv
  python generate_recommendations.py scorecards/scorecard.pdf --streams all

Requires:
  - pypdf (for PDF scorecards only)
  - data/cutoffs_db.csv (build once with: python scripts/parse_cutoffs.py)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from branch_categories import (  # noqa: E402
    STREAM_ORDER,
    STREAMS,
    classify_branch,
    prompt_streams,
    resolve_stream_tokens,
    summarize_classification,
)

DEFAULT_DB = ROOT / "data" / "cutoffs_db.csv"

YEAR_WEIGHT = {"2024-25": 0.50, "2023-24": 0.30, "2022-23": 0.20}
ROUND_WEIGHT = {"CAP1": 1.0, "CAP2": 0.75, "CAP3": 0.55}

CATEGORY_MAP = {
    "DT/VJ": ["VJ"],
    "DT": ["VJ"],
    "VJ": ["VJ"],
    "VJ/DT": ["VJ"],
    "SC": ["SC"],
    "ST": ["ST"],
    "NT1": ["NT1"],
    "NT-B": ["NT1"],
    "NTB": ["NT1"],
    "NT2": ["NT2"],
    "NT-C": ["NT2"],
    "NTC": ["NT2"],
    "NT3": ["NT3"],
    "NT-D": ["NT3"],
    "NTD": ["NT3"],
    "OBC": ["OBC"],
    "SEBC": ["SEBC"],
    "OPEN": [],
    "GENERAL": [],
}

BUCKET_ORDER = ("aspirational", "moderate", "safe")
DEFAULT_LIMITS = {"aspirational": 30, "moderate": 40, "safe": 30}

# Lower rank = preferred in shortlist (govt / aided first).
OWNERSHIP_GOVERNMENT = 0
OWNERSHIP_GOVT_AIDED = 1
OWNERSHIP_UNIVERSITY = 2
OWNERSHIP_OTHER = 3

CSV_FIELDS = [
    "priority",
    "bucket",
    "stream",
    "college",
    "branch",
    "choice_code",
    "college_type",
    "median_closing_percentile",
    "min_closing_percentile",
    "median_closing_merit",
    "min_closing_merit",
    "difficulty_score",
    "clear_rate",
    "candidate_name",
    "candidate_category",
    "candidate_percentile",
    "candidate_merit_rank",
    "candidate_gender",
]

MERIT_SUFFIXES = {".mht", ".mhtml", ".html", ".htm"}


def ownership_rank(status: str) -> int:
    """Rank college ownership for shortlist preference (lower = better)."""
    s = (status or "").strip().lower()
    # Check Un-Aided before "aided" so private colleges are not misclassified.
    if "un-aided" in s or "unaided" in s:
        return OWNERSHIP_OTHER
    if "government-aided" in s or "govt-aided" in s:
        return OWNERSHIP_GOVT_AIDED
    if "government" in s:
        return OWNERSHIP_GOVERNMENT
    if "university" in s:
        return OWNERSHIP_UNIVERSITY
    return OWNERSHIP_OTHER


def college_type_label(rank: int) -> str:
    return {
        OWNERSHIP_GOVERNMENT: "Government",
        OWNERSHIP_GOVT_AIDED: "Government-Aided",
        OWNERSHIP_UNIVERSITY: "University",
        OWNERSHIP_OTHER: "Private / Un-Aided",
    }.get(rank, "Private / Un-Aided")


@dataclass
class Student:
    name: str
    category: str
    percentile: float
    is_female: bool
    roll_no: str = ""
    application_no: str = ""
    merit_rank: int | None = None  # PCM State General Merit No
    category_merit_rank: int | None = None
    home_university: str = ""
    source: str = "scorecard"  # scorecard | merit_status


def _normalize_category(raw: str) -> str:
    category = raw.upper().strip()
    category = category.replace("NT-B", "NT1").replace("NTB", "NT1")
    category = category.replace("NT-C", "NT2").replace("NTC", "NT2")
    category = category.replace("NT-D", "NT3").replace("NTD", "NT3")
    return category


def _mhtml_plain_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if "MIME-Version:" in text[:500] or "multipart/related" in text[:800].lower():
        html = ""
        for part in re.split(r"------+[^\n]*", text):
            idx = part.find("<!DOCTYPE")
            if idx < 0:
                idx = part.lower().find("<html")
            if idx >= 0:
                html = part[idx:]
                break
        if not html:
            html = text
    else:
        html = text

    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    plain = re.sub(r"(?s)<[^>]+>", "\n", html)
    plain = (
        plain.replace("\xa0", " ")
        .replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
    )
    plain = re.sub(r"[ \t]+", " ", plain)
    return [ln.strip() for ln in plain.splitlines() if ln.strip()]


def _mhtml_plain_text(path: Path) -> str:
    return "\n".join(_mhtml_plain_lines(path))


def _pdf_plain_text(path: Path) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def _looks_like_merit_status(text: str) -> bool:
    t = text.lower()
    return (
        "merit status" in t
        or "pcm state general merit no" in t
        or "provisional merit" in t
        or "final merit" in t
    )


_CATEGORY_TOKEN = (
    r"(DT/VJ|VJ/DT|OPEN|SC|ST|OBC|SEBC|NT-?B|NT-?C|NT-?D|NT[123]|VJ|DT)"
)


def parse_merit_status_text(text: str, force_female: bool | None = None) -> Student:
    """Parse CET Provisional/Final Merit Status text (from .mht or PDF extract)."""
    if not text.strip():
        raise ValueError("Empty merit status text")

    # Prefer "Category for Admission" so nav items like "SC Login" are ignored.
    m_cat = re.search(
        rf"Category\s*for\s*Admission\s*:?\s*{_CATEGORY_TOKEN}",
        text,
        flags=re.I,
    )
    if not m_cat:
        m_cat = re.search(
            rf"(?<![A-Za-z])Category\s*:?\s*{_CATEGORY_TOKEN}(?!\s*Login)",
            text,
            flags=re.I,
        )
    if not m_cat:
        raise ValueError("Could not find category in merit status")
    category = _normalize_category(m_cat.group(1))

    m_name = re.search(
        r"Candidate's\s+Full\s+Name\s*:?\s*([A-Z][A-Z\s'.]{3,80}?)"
        r"(?=Gender|DOB|Candidature|Category|Application|\n)",
        text,
        flags=re.I,
    )
    if not m_name:
        m_name = re.search(
            r"Candidate\s+Name\s*\(as\s*per\s*CET\)\s*:?\s*([A-Z][A-Z\s'.]{3,80}?)"
            r"(?=Physics|Chemistry|Mathematics|Total|Gender|\n)",
            text,
            flags=re.I,
        )
    if not m_name:
        raise ValueError("Could not find candidate name in merit status")
    name = " ".join(m_name.group(1).split()).title()

    m_gender = re.search(r"Gender\s*:?\s*(Female|Male)\b", text, flags=re.I)
    if force_female is not None:
        is_female = force_female
    elif m_gender:
        is_female = m_gender.group(1).lower().startswith("f")
    else:
        is_female = False

    m_app = re.search(r"Application\s*ID\s*:?\s*(EN\d+)", text, flags=re.I)
    application_no = m_app.group(1) if m_app else ""

    m_hu = re.search(
        r"Home\s+University\s*:?\s*(.+?)"
        r"(?=Category|Applied\s+for|Candidature|Gender|Orphan)",
        text,
        flags=re.I | re.S,
    )
    home_university = " ".join(m_hu.group(1).split()) if m_hu else ""

    # Prefer PCM State General Merit (engineering). Works for Final + Provisional,
    # and for both newline-separated (.mht) and jammed PDF extracts.
    m_state = re.search(
        r"PCM\s+State\s+General\s+Merit\s+No\s*:?\s*(\d+)\s*[-–]\s*"
        r"MHT-CET-PCM[^\n(]*\((\d+\.\d+)\)",
        text,
        flags=re.I,
    )
    if not m_state:
        m_block = re.search(
            r"Your\s+PCM\s+(?:Final|Provisional)\s+Merit\s+Status\s+is\.\.\.(.*)"
            r"(?:Your\s+PCM\s+or\s+PCB|Important\s+Instructions|Note\s*:-|Login\s+Links)",
            text,
            flags=re.I | re.S,
        )
        block = m_block.group(1) if m_block else text
        m_state = re.search(
            r"(?<!Ladies\s)(?<!All\sIndia\s)State\s+General\s+Merit\s+No\s*:?\s*(\d+)\s*[-–]\s*"
            r"MHT-CET-PCM[^\n(]*\((\d+\.\d+)\)",
            block,
            flags=re.I,
        )
    if not m_state:
        raise ValueError("Could not find PCM State General Merit No in merit status")

    merit_rank = int(m_state.group(1))
    percentile = float(m_state.group(2))

    m_cat_merit = re.search(
        rf"PCM\s+State\s+Category\s+Merit\s+No\s*:?\s*{_CATEGORY_TOKEN}\s*[-–]\s*(\d+)",
        text,
        flags=re.I,
    )
    category_merit_rank = int(m_cat_merit.group(2)) if m_cat_merit else None

    m_roll = re.search(
        r"MHT-CET\s+20\d{2}\s+PCM\s*\[Roll\s*No\s*-\s*(\d{8,12})",
        text,
        flags=re.I,
    )
    if not m_roll:
        m_roll = re.search(r"Roll\s*No\s*-\s*(\d{8,12})", text, flags=re.I)
    roll_no = m_roll.group(1) if m_roll else ""

    return Student(
        name=name,
        category=category,
        percentile=percentile,
        is_female=is_female,
        roll_no=roll_no,
        application_no=application_no,
        merit_rank=merit_rank,
        category_merit_rank=category_merit_rank,
        home_university=home_university,
        source="merit_status",
    )


def parse_merit_status(path: Path, force_female: bool | None = None) -> Student:
    """Parse a CET Merit Status page (.mht / .mhtml / .html / merit PDF)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_plain_text(path)
    else:
        text = _mhtml_plain_text(path)
    try:
        return parse_merit_status_text(text, force_female=force_female)
    except ValueError as e:
        raise ValueError(f"{e}: {path}") from e


def parse_student_card(pdf_path: Path, force_female: bool | None = None) -> Student:
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages)

    cats = re.findall(
        r"\b(DT/VJ|VJ/DT|OPEN|SC|ST|OBC|SEBC|NT-?B|NT-?C|NT-?D|NT[123]|VJ|DT)\b",
        text,
        flags=re.I,
    )
    if not cats:
        raise ValueError(f"Could not find category in scorecard: {pdf_path}")

    category = _normalize_category(cats[0])

    pcts = [float(x) for x in re.findall(r"\b(\d{1,2}\.\d{5,})\b", text)]
    if not pcts:
        raise ValueError(f"Could not find percentile in scorecard: {pdf_path}")

    cat_pos = text.upper().find(cats[0].upper())
    tail = text[cat_pos:] if cat_pos >= 0 else text
    tail_pcts = [float(x) for x in re.findall(r"\b(\d{1,2}\.\d{5,})\b", tail)]
    percentile = tail_pcts[0] if tail_pcts else pcts[0]

    name = "Unknown"
    m_name = re.search(
        rf"{re.escape(cats[0])}\s*\n([A-Z][A-Z\s'.]{{5,80}})\n",
        text,
    )
    if m_name:
        name = " ".join(m_name.group(1).split()).title()

    if force_female is not None:
        is_female = force_female
    else:
        is_female = bool(re.search(r"\b(Female|Gender\s*:\s*F)\b", text, re.I))
        if re.search(r"\b(Male|Gender\s*:\s*M)\b", text, re.I):
            is_female = False
        elif not re.search(r"\b(Female|Male|Gender)\b", text, re.I):
            first = name.split()[0].lower() if name else ""
            female_names = {
                "priya", "puja", "pooja", "sneha", "ananya", "aarti", "arti", "neha",
                "rita", "gita", "seema", "kavita", "swati", "asha", "isha", "shruti",
                "shreya", "anushka", "vaishnavi", "sakshi", "pratiksha", "nikita",
                "payal", "komal", "rani", "sita", "gargi", "aishwarya", "divya",
            }
            is_female = first in female_names

    rolls = re.findall(r"\b(\d{10,12})\b", text)
    return Student(
        name=name,
        category=category,
        percentile=percentile,
        is_female=is_female,
        roll_no=rolls[-1] if rolls else "",
        application_no=rolls[0] if rolls else "",
        source="scorecard",
    )


def parse_candidate(path: Path, force_female: bool | None = None) -> Student:
    suffix = path.suffix.lower()
    if suffix in MERIT_SUFFIXES:
        return parse_merit_status(path, force_female=force_female)
    if suffix == ".pdf":
        text = _pdf_plain_text(path)
        if _looks_like_merit_status(text):
            return parse_merit_status_text(text, force_female=force_female)
        return parse_student_card(path, force_female=force_female)
    # Content sniff for extension-less / odd saves
    head = path.read_bytes()[:2000].decode("utf-8", errors="replace")
    head_l = head.lower()
    if (
        "merit status" in head_l
        or "multipart/related" in head_l
        or "<html" in head_l
    ):
        return parse_merit_status(path, force_female=force_female)
    raise ValueError(
        f"Unsupported candidate file type: {path.suffix or '(none)'} "
        f"(expected merit-status .mht/.pdf or CET scorecard .pdf)"
    )


def eligible_category_codes(category: str, is_female: bool) -> set[str]:
    stems = ["OPEN"] + CATEGORY_MAP.get(category.upper(), [])
    if category.upper() not in CATEGORY_MAP and category.upper() not in {"OPEN", "GENERAL"}:
        stems.append(category.upper())

    codes: set[str] = set()
    genders = ["G", "L"] if is_female else ["G"]
    for stem in stems:
        for g in genders:
            for suf in ("H", "O", "S"):
                codes.add(f"{g}{stem}{suf}")
    return codes


def load_relevant_rows(db_path: Path, codes: set[str]) -> list[dict]:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Cutoff database not found: {db_path}\n"
            f"Build it once with: python scripts/parse_cutoffs.py"
        )

    rows = []
    with db_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["category"] not in codes:
                continue
            if row["stage"] not in {"I", "1"}:
                continue
            if not row["percentile"]:
                continue
            try:
                row["percentile_f"] = float(row["percentile"])
            except ValueError:
                continue
            rank_raw = (row.get("merit_rank") or "").strip()
            if rank_raw.isdigit():
                row["merit_rank_i"] = int(rank_raw)
            else:
                row["merit_rank_i"] = None
            if not row["choice_code"] or not row["college_name"]:
                continue
            rows.append(row)
    return rows


def aggregate(rows: list[dict], student: Student) -> list[dict]:
    """Score college–branch options for a candidate.

    When ``student.merit_rank`` is set (Final Merit Status), matching uses CAP
    State General Merit numbers (lower rank is better). Otherwise matching uses
    percentile (higher is better). Difficulty / display closings stay percentile-
    based so shortlist ordering stays comparable.
    """
    by_choice: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    use_merit = student.merit_rank is not None
    student_pct = student.percentile
    student_rank = student.merit_rank

    for r in rows:
        key = r["choice_code"]
        by_choice[key].append(r)
        status = r.get("status", "")
        meta[key] = {
            "college_code": r["college_code"],
            "college_name": r["college_name"],
            "branch": r["branch"],
            "choice_code": r["choice_code"],
            "status": status,
            "ownership": ownership_rank(status),
        }

    results = []
    for choice, items in by_choice.items():
        by_yr: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in items:
            by_yr[(r["year"], r["round"])].append(r)

        observations = []
        for (year, rnd), group in by_yr.items():
            pcts = [r["percentile_f"] for r in group]
            ranks = [r["merit_rank_i"] for r in group if r.get("merit_rank_i") is not None]
            best_pct = min(pcts)  # easiest closing by percentile
            # Easiest closing by rank = highest merit number among eligible seats
            best_rank = max(ranks) if ranks else None

            if use_merit and best_rank is not None and student_rank is not None:
                cleared = student_rank <= best_rank
                # ~3 percentile-points of slack ≈ a few thousand merit places
                rank_slack = max(2500, int(best_rank * 0.04))
                reachable = student_rank <= best_rank + rank_slack
                signal = best_rank
            else:
                cleared = student_pct >= best_pct
                reachable = best_pct <= student_pct + 3.0
                signal = best_pct

            observations.append(
                {
                    "year": year,
                    "round": rnd,
                    "best_closing": best_pct,
                    "best_rank": best_rank,
                    "cleared": cleared,
                    "reachable": reachable,
                    "signal": signal,
                    "w": YEAR_WEIGHT.get(year, 0.2) * ROUND_WEIGHT.get(rnd, 0.5),
                }
            )
        if not observations:
            continue

        wsum = sum(o["w"] for o in observations)
        difficulty = sum(o["best_closing"] * o["w"] for o in observations) / wsum

        cleared = [o for o in observations if o["cleared"]]
        cleared_cap1 = [o for o in cleared if o["round"] == "CAP1"]
        years_cleared_cap1 = {o["year"] for o in cleared_cap1}
        years_cleared_any = {o["year"] for o in cleared}

        min_closing = min(o["best_closing"] for o in observations)
        max_closing = max(o["best_closing"] for o in observations)
        cap1 = [o for o in observations if o["round"] == "CAP1"]
        closings_sorted = sorted(o["best_closing"] for o in observations)
        median_like = closings_sorted[len(closings_sorted) // 2]

        rank_vals = [o["best_rank"] for o in observations if o["best_rank"] is not None]
        min_closing_rank = max(rank_vals) if rank_vals else None  # easiest
        max_closing_rank = min(rank_vals) if rank_vals else None  # hardest
        median_rank = (
            sorted(rank_vals)[len(rank_vals) // 2] if rank_vals else None
        )

        reachable = [o for o in observations if o["reachable"]]
        reachable_rate = len(reachable) / len(observations)

        if use_merit and student_rank is not None and median_rank is not None:
            # Positive gap => candidate is better than the closing merit.
            gap_median = median_rank - student_rank
            gap_best = (min_closing_rank - student_rank) if min_closing_rank else 0

            if not cleared and reachable_rate < 0.25:
                continue
            if min_closing_rank is not None and student_rank > min_closing_rank + max(
                2500, int(min_closing_rank * 0.04)
            ):
                continue
            if len(observations) < 2 and gap_best < 0:
                continue

            clear_rate = len(cleared) / len(observations)
            cap1_clear_rate = len(cleared_cap1) / len(cap1) if cap1 else 0.0

            if cap1_clear_rate >= 0.67 and gap_median >= 3000:
                bucket = "safe"
            elif clear_rate >= 0.35 or (cap1_clear_rate >= 0.33 and gap_median >= -2000):
                bucket = "moderate"
            elif reachable_rate >= 0.25 and gap_median >= -8000:
                bucket = "aspirational"
            else:
                continue

            if not cleared and bucket != "aspirational":
                bucket = "aspirational"
            elif clear_rate < 0.2 and gap_median < 0:
                bucket = "aspirational"

            # Drop ultra-easy filler safes far below the candidate's merit.
            if bucket == "safe" and gap_median > max(25000, int(student_rank * 0.45)):
                continue
        else:
            if not cleared and reachable_rate < 0.25:
                continue
            if min_closing > student_pct + 3.0:
                continue
            if len(observations) < 2 and min_closing > student_pct:
                continue

            clear_rate = len(cleared) / len(observations)
            cap1_clear_rate = len(cleared_cap1) / len(cap1) if cap1 else 0.0

            if cap1_clear_rate >= 0.67 and median_like <= student_pct - 3:
                bucket = "safe"
            elif clear_rate >= 0.35 or (
                cap1_clear_rate >= 0.33 and median_like <= student_pct + 2
            ):
                bucket = "moderate"
            elif reachable_rate >= 0.25 and median_like <= student_pct + 8:
                bucket = "aspirational"
            else:
                continue

            if not cleared and bucket != "aspirational":
                bucket = "aspirational"
            elif clear_rate < 0.2 and median_like > student_pct:
                bucket = "aspirational"

            if bucket == "safe" and median_like < max(30.0, student_pct - 25.0):
                continue

        results.append(
            {
                **meta[choice],
                "bucket": bucket,
                "difficulty": difficulty,
                "min_closing": min_closing,
                "max_closing": max_closing,
                "median_closing": median_like,
                "min_closing_rank": min_closing_rank,
                "max_closing_rank": max_closing_rank,
                "median_closing_rank": median_rank,
                "clear_rate": clear_rate,
                "cap1_clear_rate": cap1_clear_rate,
                "years_cleared_any": len(years_cleared_any),
                "years_cleared_cap1": len(years_cleared_cap1),
                "n_obs": len(observations),
                "best_gap": student_pct - min_closing,
            }
        )
    return results


def filter_by_streams(results: list[dict], selected_streams: set[str]) -> list[dict]:
    filtered = []
    for r in results:
        sid = classify_branch(r["branch"])
        if sid in selected_streams:
            filtered.append({**r, "stream": STREAMS[sid], "stream_id": sid})
    return filtered


def shortlist(
    results: list[dict],
    student_pct: float,
    limits: dict[str, int],
) -> list[dict]:
    """Curate a CAP list, preferring government / government-aided colleges.

    Multiple streams from the same college are allowed. Within each bucket,
    preferred ownership (Government → Government-Aided → University → other)
    is filled first; remaining slots use the usual difficulty ranking.
    """

    def quality_key(r: dict, safe_mode: bool) -> tuple:
        if safe_mode:
            return (
                -(min(r["median_closing"], student_pct - 2)),
                -r["difficulty"],
                r["college_name"],
                r["branch"],
            )
        return (-r["difficulty"], r["college_name"], r["branch"])

    def pick(items: list[dict], n: int, safe_mode: bool = False) -> list[dict]:
        if n <= 0 or not items:
            return []

        preferred = [
            r
            for r in items
            if r.get("ownership", OWNERSHIP_OTHER) <= OWNERSHIP_UNIVERSITY
        ]
        preferred_sorted = sorted(
            preferred,
            key=lambda r: (r.get("ownership", OWNERSHIP_OTHER),) + quality_key(r, safe_mode),
        )

        # Take all preferred that fit, then fill remaining with best overall
        # (still ranking preferred ownership ahead of private).
        selected = preferred_sorted[:n]
        if len(selected) < n:
            selected_keys = {r["choice_code"] for r in selected}
            rest = [r for r in items if r["choice_code"] not in selected_keys]
            rest_sorted = sorted(
                rest,
                key=lambda r: (
                    r.get("ownership", OWNERSHIP_OTHER),
                )
                + quality_key(r, safe_mode),
            )
            selected.extend(rest_sorted[: n - len(selected)])

        # Keep display order: preferred first, then by quality within group
        return sorted(
            selected,
            key=lambda r: (
                r.get("ownership", OWNERSHIP_OTHER),
            )
            + quality_key(r, safe_mode),
        )

    curated: list[dict] = []
    for bucket in BUCKET_ORDER:
        n = limits.get(bucket, 0)
        if n <= 0:
            continue
        bucket_items = [r for r in results if r["bucket"] == bucket]
        curated.extend(pick(bucket_items, n, safe_mode=(bucket == "safe")))
    return curated


def write_csv(path: Path, curated: list[dict], student: Student) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gender = "female" if student.is_female else "male"

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        priority = 1
        for bucket in BUCKET_ORDER:
            items = [r for r in curated if r["bucket"] == bucket]
            for r in items:
                writer.writerow(
                    {
                        "priority": priority,
                        "bucket": bucket,
                        "stream": r.get("stream", ""),
                        "college": r["college_name"],
                        "branch": r["branch"],
                        "choice_code": r["choice_code"],
                        "college_type": college_type_label(
                            r.get("ownership", OWNERSHIP_OTHER)
                        ),
                        "median_closing_percentile": round(r["median_closing"], 4),
                        "min_closing_percentile": round(r["min_closing"], 4),
                        "median_closing_merit": r.get("median_closing_rank") or "",
                        "min_closing_merit": r.get("min_closing_rank") or "",
                        "difficulty_score": round(r["difficulty"], 4),
                        "clear_rate": round(r["clear_rate"], 4),
                        "candidate_name": student.name,
                        "candidate_category": student.category,
                        "candidate_percentile": student.percentile,
                        "candidate_merit_rank": student.merit_rank or "",
                        "candidate_gender": gender,
                    }
                )
                priority += 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate CAP college-branch recommendations CSV from an MHT-CET scorecard."
    )
    p.add_argument(
        "scorecard",
        type=Path,
        help=(
            "Candidate file: MHT-CET scorecard PDF, or CET Final Merit Status "
            "(.mht / .mhtml / .html)"
        ),
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "output" / "recommendations.csv",
        help="Output CSV path (default: output/recommendations.csv)",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Cutoff database CSV (default: {DEFAULT_DB})",
    )
    p.add_argument(
        "--streams",
        type=str,
        default=None,
        help=(
            "Branch streams to include, comma-separated. "
            "Use 1-5, all, or names: cs, electronics, electrical, mechanical, civil. "
            "If omitted, you will be prompted interactively."
        ),
    )
    p.add_argument(
        "--aspirational",
        type=int,
        default=DEFAULT_LIMITS["aspirational"],
        help="Max aspirational options (default: 30)",
    )
    p.add_argument(
        "--moderate",
        type=int,
        default=DEFAULT_LIMITS["moderate"],
        help="Max moderate options (default: 40)",
    )
    p.add_argument(
        "--safe",
        type=int,
        default=DEFAULT_LIMITS["safe"],
        help="Max safe options (default: 30)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--female",
        action="store_true",
        help="Force female seat eligibility (include L* seats)",
    )
    g.add_argument(
        "--male",
        action="store_true",
        help="Force male seat eligibility (G* seats only)",
    )
    return p.parse_args(argv)


def select_streams(args: argparse.Namespace) -> set[str]:
    if args.streams:
        parts = [p.strip() for p in args.streams.replace(";", ",").split(",")]
        selected = resolve_stream_tokens(parts)
        if not selected:
            raise ValueError("No valid streams provided via --streams")
        return selected

    if sys.stdin.isatty():
        return prompt_streams(stdin_interactive=True)

    # Non-interactive fallback (piped/CI): include all core streams
    print(
        "No --streams provided and stdin is not interactive; "
        "defaulting to all branch streams.",
        file=sys.stderr,
    )
    return set(STREAM_ORDER)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.scorecard.exists():
        print(f"Error: scorecard not found: {args.scorecard}", file=sys.stderr)
        return 1

    force_female = True if args.female else False if args.male else None
    try:
        student = parse_candidate(args.scorecard, force_female=force_female)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    merit_bit = (
        f" | state_merit={student.merit_rank}"
        if student.merit_rank is not None
        else ""
    )
    hu_bit = f" | HU={student.home_university}" if student.home_university else ""
    print(
        f"Candidate: {student.name} | category={student.category} | "
        f"percentile={student.percentile:.7f}{merit_bit} | "
        f"gender={'female' if student.is_female else 'male'} | "
        f"source={student.source}{hu_bit}"
    )
    if student.merit_rank is not None:
        print("Matching mode: State General Merit rank (CAP closing ranks)")
    else:
        print("Matching mode: percentile (no merit rank in input)")

    try:
        selected_streams = select_streams(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        "Selected streams: "
        + ", ".join(STREAMS[s] for s in STREAM_ORDER if s in selected_streams)
    )

    codes = eligible_category_codes(student.category, student.is_female)
    try:
        rows = load_relevant_rows(args.db, codes)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Loaded {len(rows)} relevant cutoff rows from {args.db}")

    # Show how many unique branches fall in each selected stream
    unique_branches = sorted({r["branch"] for r in rows})
    grouped = summarize_classification(unique_branches)
    for sid in STREAM_ORDER:
        mark = "✓" if sid in selected_streams else " "
        print(f"  [{mark}] {STREAMS[sid]}: {len(grouped[sid])} branch types")
    print(f"  [ ] Other / specialized (excluded): {len(grouped['other'])} branch types")

    results = aggregate(rows, student)
    results = filter_by_streams(results, selected_streams)
    print(f"Options with a chance in selected streams: {len(results)}")

    limits = {
        "aspirational": args.aspirational,
        "moderate": args.moderate,
        "safe": args.safe,
    }
    curated = shortlist(results, student.percentile, limits)
    write_csv(args.output, curated, student)

    counts = {b: sum(1 for r in curated if r["bucket"] == b) for b in BUCKET_ORDER}
    print(
        f"Wrote {len(curated)} recommendations to {args.output} "
        f"(aspirational={counts['aspirational']}, "
        f"moderate={counts['moderate']}, safe={counts['safe']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
