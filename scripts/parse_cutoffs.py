#!/usr/bin/env python3
"""Parse MHT-CET CAP engineering cutoff PDFs into a structured CSV database."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from pypdf import PdfReader

# Known category code stems (before H/O/S/AI suffix)
CATEGORY_STEMS = {
    "OPEN",
    "SC",
    "ST",
    "VJ",
    "NT1",
    "NT2",
    "NT3",
    "OBC",
    "SEBC",
    "PWDOPEN",
    "PWDSC",
    "PWDST",
    "PWDVJ",
    "PWDNT1",
    "PWDNT2",
    "PWDNT3",
    "PWDOBC",
    "PWDSEBC",
    "PWDROPEN",
    "PWDRSC",
    "PWDRST",
    "PWDRVJ",
    "PWDRNT1",
    "PWDRNT2",
    "PWDRNT3",
    "PWDROBC",
    "PWDRSEBC",
    "DEFOPEN",
    "DEFSC",
    "DEFST",
    "DEFVJ",
    "DEFNT1",
    "DEFNT2",
    "DEFNT3",
    "DEFOBC",
    "DEFSEBC",
    "DEFROPEN",
    "DEFRSC",
    "DEFRST",
    "DEFRVJ",
    "DEFRNT1",
    "DEFRNT2",
    "DEFRNT3",
    "DEFROBC",
    "DEFRSEBC",
    "TFWS",
    "ORPHAN",
    "EWS",
    "MI",
    "AI",
}

PREFIXES = ("G", "L", "")
SUFFIXES = ("H", "O", "S", "AI", "")

KNOWN_CODES: set[str] = set()
for stem in CATEGORY_STEMS:
    for pref in PREFIXES:
        for suf in SUFFIXES:
            if stem in {"TFWS", "ORPHAN", "EWS", "MI"} and pref:
                # these usually have no G/L prefix
                continue
            code = f"{pref}{stem}{suf}"
            if code:
                KNOWN_CODES.add(code)

# Also allow bare stems used occasionally
KNOWN_CODES.update(CATEGORY_STEMS)

# 2022-23 / 2023-24 PDFs use 4-digit college + 9-digit choice codes.
# 2024-25 PDFs use zero-padded 5-digit college + 10-digit choice codes.
# Some choice codes have seat-type suffixes: F (female), K (Konkan), U, L, LK.
COLLEGE_RE = re.compile(r"^(\d{4,5})\s*-\s*(.+?)\s*$")
COURSE_RE = re.compile(r"^(\d{9,10}[A-Za-z]*)\s*-\s*(.+?)\s*$")
STAGE_RE = re.compile(r"^(I{1,3}|VII|I-Non\s*PWD|II|III)\s*$", re.I)
STAGE_INLINE_RE = re.compile(
    r"^\s*(I{1,3}|VII|I-Non\s*PWD)\s+(\d+)\s*$", re.I
)
RANK_RE = re.compile(r"^(\d{1,7})$")
PCT_RE = re.compile(r"^\((\d+\.\d+)\)$")
SECTION_HINTS = (
    "state level",
    "home university",
    "other than home",
    "all india",
    "minority",
)


def normalize_college_code(code: str) -> str:
    return code.strip().zfill(5)


def normalize_choice_code(code: str) -> str:
    """Zero-pad numeric stem to 10 digits; preserve trailing letter suffixes."""
    raw = code.strip()
    m = re.match(r"^(\d+)([A-Za-z]*)$", raw)
    if not m:
        return raw
    digits, suffix = m.group(1), m.group(2).upper()
    return digits.zfill(10) + suffix


def college_code_from_choice(choice_code: str) -> str:
    m = re.match(r"^(\d{5})", normalize_choice_code(choice_code))
    return m.group(1) if m else ""


def normalize_category_tokens(raw_tokens: list[str]) -> list[str]:
    """Join line-broken category codes like PWDROBC + S -> PWDROBCS."""
    tokens = [t.strip() for t in raw_tokens if t.strip()]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i].upper().replace(" ", "")
        # Merge with next fragment if that forms a known code
        if i + 1 < len(tokens):
            nxt = tokens[i + 1].upper().replace(" ", "")
            merged = t + nxt
            if merged in KNOWN_CODES and t not in KNOWN_CODES:
                out.append(merged)
                i += 2
                continue
            # Header line sometimes ends mid-code: "... PWDROBC" then "S DEFRSEBC S EWS"
            if t in KNOWN_CODES or any(
                merged.startswith(c) and len(merged) <= len(c) + 2 for c in KNOWN_CODES
            ):
                pass
        if t in KNOWN_CODES or re.match(
            r"^[GL]?(OPEN|SC|ST|VJ|NT[123]|OBC|SEBC|PWD|DEF|TFWS|ORPHAN|EWS|MI)", t
        ):
            out.append(t)
        i += 1
    return out


def is_category_header_line(line: str) -> bool:
    """True for one or more seat-category codes (e.g. 'GOPENH' or 'GOPENH LOPENH')."""
    parts = line.split()
    if not parts:
        return False
    if line.lower().startswith("status"):
        return False
    upper_parts = [p.upper() for p in parts]
    cat_re = re.compile(
        r"^[GL]?(OPEN|SC|ST|VJ|NT[123]|OBC|SEBC|PWD|DEF|TFWS|ORPHAN|EWS|MI)"
    )
    hits = sum(1 for p in upper_parts if p in KNOWN_CODES or cat_re.match(p))
    # Accept a single category code line (common for low-demand branches)
    # or multi-code headers. Reject mixed prose lines.
    if hits == 0:
        return False
    return hits == len(upper_parts)


def parse_page_text(
    text: str,
    year: str,
    round_name: str,
    state: dict,
) -> list[dict]:
    """Parse one page; mutate shared state for college continuity across pages."""
    rows: list[dict] = []
    lines = [ln.rstrip() for ln in text.splitlines()]

    # Skip legend / footer noise (do NOT skip real section headers like
    # "Maharashtra State Seats Allotted to All India Candidature Candidates")
    skip_prefixes = (
        "legends:",
        "maharashtra state seats - cut",
        "maharashtra state seats - cut off",
        "* maharashtra state seats",
        "state common entrance",
        "cut off list",
        "government of maharashtra",
        "degree courses",
        "published",
        "page ",
        "d",
        "i",
        "r",
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        low = line.lower()
        if low in {"d", "i", "r"} or low.startswith("legends:"):
            i += 1
            continue
        if any(low.startswith(p) for p in skip_prefixes if len(p) > 2):
            i += 1
            continue

        m_course = COURSE_RE.match(line)
        if m_course:
            state["choice_code"] = normalize_choice_code(m_course.group(1))
            state["branch"] = m_course.group(2).strip()
            # Keep college_code aligned with the choice code stem. This prevents
            # stale college context when a prior page's course lacked a recognized
            # header (e.g. suffixed codes) and categories were mis-attributed.
            derived = college_code_from_choice(state["choice_code"])
            if derived:
                state["college_code"] = derived
                names = state.setdefault("college_names", {})
                if derived in names:
                    state["college_name"] = names[derived]
            state["status"] = ""
            i += 1
            continue

        m_col = COLLEGE_RE.match(line)
        if m_col:
            state["college_code"] = normalize_college_code(m_col.group(1))
            state["college_name"] = m_col.group(2).strip()
            state.setdefault("college_names", {})[state["college_code"]] = state["college_name"]
            i += 1
            continue

        if line.lower().startswith("status:"):
            state["status"] = line.split(":", 1)[1].strip()
            i += 1
            continue

        if any(h in low for h in SECTION_HINTS) and not is_category_header_line(line):
            state["section"] = line.strip()
            i += 1
            continue

        if is_category_header_line(line):
            # Collect possibly wrapped header lines until a stage marker
            header_tokens: list[str] = line.split()
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if STAGE_INLINE_RE.match(nxt) or STAGE_RE.match(nxt) or nxt.startswith("I ") or nxt.startswith("II ") or nxt.startswith("VII"):
                    break
                if re.match(r"^MH\b", nxt, re.I) or re.match(r"^I-Non", nxt, re.I):
                    break
                if COURSE_RE.match(nxt) or COLLEGE_RE.match(nxt):
                    break
                if nxt.lower().startswith("stage"):
                    j += 1
                    break
                # continuation of wrapped category codes
                if is_category_header_line(nxt) or all(
                    re.match(r"^[A-Za-z0-9]+$", p) for p in nxt.split()
                ):
                    # avoid absorbing rank lines
                    if RANK_RE.match(nxt) or PCT_RE.match(nxt):
                        break
                    if STAGE_INLINE_RE.match(nxt):
                        break
                    header_tokens.extend(nxt.split())
                    j += 1
                    continue
                break

            categories = normalize_category_tokens(header_tokens)
            i = j

            # Parse stage blocks until next course/college/section/header
            while i < len(lines):
                cur = lines[i].strip()
                if not cur:
                    i += 1
                    continue
                if cur.lower() == "stage":
                    i += 1
                    break
                if COURSE_RE.match(cur) or COLLEGE_RE.match(cur):
                    break
                if cur.lower().startswith("status:"):
                    break
                if any(h in cur.lower() for h in SECTION_HINTS) and not is_category_header_line(cur):
                    break
                if is_category_header_line(cur):
                    break

                stage = None
                stage_categories = None  # optional override for special allotment lines
                m_inline = STAGE_INLINE_RE.match(cur)
                m_mh = re.match(r"^MH\s+(\d{1,7})$", cur, re.I)
                if m_inline:
                    stage = re.sub(r"\s+", " ", m_inline.group(1).upper())
                    values_start = [m_inline.group(2)]
                    i += 1
                elif m_mh:
                    # Minority Maharashtra allotment: "MH <rank>" binds ONLY to MI,
                    # never re-aligns to GOPENS/LOPENS/etc from the parent header.
                    stage = "I"
                    values_start = [m_mh.group(1)]
                    stage_categories = ["MI"] if "MI" in categories else ["MI"]
                    i += 1
                elif re.match(r"^I-Non", cur, re.I):
                    # Multiline forms: "I-Non" then "PWD" / "Defence"
                    stage = "I-Non"
                    i += 1
                    while i < len(lines):
                        lab = lines[i].strip().upper()
                        if lab in {"PWD", "DEFENCE", "DEFENSE", "NON"}:
                            stage = f"I-Non {lab.title().replace('Defense', 'Defence')}"
                            i += 1
                            continue
                        break
                    values_start = []
                elif STAGE_RE.match(cur) or re.match(r"^(I{1,3}|VII)\b", cur, re.I):
                    # "I" alone or "I 12345"
                    parts = cur.split(None, 1)
                    stage = parts[0].upper()
                    values_start = []
                    if len(parts) > 1 and RANK_RE.match(parts[1].strip()):
                        values_start = [parts[1].strip()]
                    i += 1
                else:
                    # leftover noise
                    i += 1
                    continue

                # Gather rank/(pct) pairs
                nums: list[tuple[int, float | None]] = []
                # seed from inline
                pending_rank: int | None = None
                for seed in values_start:
                    pending_rank = int(seed)

                while i < len(lines):
                    cur = lines[i].strip()
                    if not cur:
                        i += 1
                        continue
                    if cur.lower() == "stage":
                        break
                    if COURSE_RE.match(cur) or COLLEGE_RE.match(cur):
                        break
                    if cur.lower().startswith("status:"):
                        break
                    if is_category_header_line(cur):
                        break
                    if any(h in cur.lower() for h in SECTION_HINTS) and not RANK_RE.match(cur):
                        break
                    if STAGE_RE.match(cur) or STAGE_INLINE_RE.match(cur) or re.match(
                        r"^(I{1,3}|VII|II|III|MH|I-Non)\b", cur, re.I
                    ):
                        break

                    if PCT_RE.match(cur) and pending_rank is not None:
                        pct = float(PCT_RE.match(cur).group(1))
                        nums.append((pending_rank, pct))
                        pending_rank = None
                        i += 1
                        continue

                    # "12345 (88.5)" rare same-line form
                    m_both = re.match(r"^(\d{1,7})\s*\((\d+\.\d+)\)$", cur)
                    if m_both:
                        if pending_rank is not None:
                            nums.append((pending_rank, None))
                            pending_rank = None
                        nums.append((int(m_both.group(1)), float(m_both.group(2))))
                        i += 1
                        continue

                    if RANK_RE.match(cur):
                        if pending_rank is not None:
                            nums.append((pending_rank, None))
                        pending_rank = int(cur)
                        i += 1
                        continue

                    # wrapped stage label fragments like "I-Non" / "PWD" / "Defence"
                    if re.match(r"^I-Non", cur, re.I) or cur.upper() in {
                        "PWD",
                        "NON",
                        "DEFENCE",
                        "DEFENSE",
                        "MH",
                    }:
                        i += 1
                        continue

                    # unknown token — stop stage value gathering
                    break

                if pending_rank is not None:
                    nums.append((pending_rank, None))

                align_categories = stage_categories if stage_categories is not None else categories

                # Align values to categories (truncate/pad carefully)
                if not align_categories:
                    continue
                # If more numbers than categories, still map 1:1 up to categories
                for idx in range(min(len(align_categories), len(nums))):
                    rank, pct = nums[idx]
                    cat = align_categories[idx]
                    choice = state.get("choice_code", "")
                    college = college_code_from_choice(choice) or state.get("college_code", "")
                    names = state.get("college_names", {})
                    college_name = names.get(college) or state.get("college_name", "")
                    rows.append(
                        {
                            "year": year,
                            "round": round_name,
                            "college_code": college,
                            "college_name": college_name,
                            "choice_code": choice,
                            "branch": state.get("branch", ""),
                            "status": state.get("status", ""),
                            "section": state.get("section", ""),
                            "stage": stage or "I",
                            "category": cat,
                            "merit_rank": rank,
                            "percentile": pct if pct is not None else "",
                        }
                    )
            continue

        i += 1

    return rows


def parse_pdf(pdf_path: Path, year: str, round_name: str) -> list[dict]:
    reader = PdfReader(str(pdf_path))
    state: dict = {
        "college_code": "",
        "college_name": "",
        "choice_code": "",
        "branch": "",
        "status": "",
        "section": "",
        "college_names": {},
    }
    all_rows: list[dict] = []
    total = len(reader.pages)
    for idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        all_rows.extend(parse_page_text(text, year, round_name, state))
        if (idx + 1) % 200 == 0 or idx + 1 == total:
            print(f"  {pdf_path.name}: {idx + 1}/{total} pages, {len(all_rows)} rows", flush=True)
    return all_rows


def discover_pdfs(root: Path) -> list[tuple[Path, str, str]]:
    found = []
    for year_dir in sorted(root.glob("20*")):
        year = year_dir.name  # e.g. 2024-25
        cutoff_dir = year_dir / "Cutoffs"
        if not cutoff_dir.exists():
            continue
        for pdf in sorted(cutoff_dir.glob("*.pdf")):
            name = pdf.name.upper()
            if "CAP1" in name:
                rnd = "CAP1"
            elif "CAP2" in name:
                rnd = "CAP2"
            elif "CAP3" in name:
                rnd = "CAP3"
            else:
                rnd = "UNKNOWN"
            found.append((pdf, year, rnd))
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data_root = root / "raw"
    out_csv = root / "data" / "cutoffs_db.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    pdfs = discover_pdfs(data_root)
    if not pdfs:
        print("No cutoff PDFs found", file=sys.stderr)
        return 1

    all_rows: list[dict] = []
    for pdf, year, rnd in pdfs:
        print(f"Parsing {pdf} ({year} {rnd})...", flush=True)
        rows = parse_pdf(pdf, year, rnd)
        print(f"  -> {len(rows)} rows", flush=True)
        all_rows.extend(rows)

    fields = [
        "year",
        "round",
        "college_code",
        "college_name",
        "choice_code",
        "branch",
        "status",
        "section",
        "stage",
        "category",
        "merit_rank",
        "percentile",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
