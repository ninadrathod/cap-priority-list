"""Map CAP engineering branches into high-level stream categories."""

from __future__ import annotations

import re

# Public stream IDs used by the CLI and CSV output.
STREAMS: dict[str, str] = {
    "cs_it": "Computer Science & IT",
    "electronics": "Electronics & Communication",
    "electrical": "Electrical Engineering",
    "mechanical": "Mechanical Engineering",
    "civil": "Civil Engineering",
}

STREAM_ORDER = ("cs_it", "electronics", "electrical", "mechanical", "civil")

# Context labels shown to users for readability.
STREAM_CONTEXT: dict[str, str] = {
    "cs_it": "Software, Data, AI, Computing",
    "electronics": "Signals, Communication, Embedded, Instrumentation",
    "electrical": "Power Systems, Circuits, Energy",
    "mechanical": "Machines, Manufacturing, Industrial & Process",
    "civil": "Infrastructure, Structures, Built Environment",
}

# Aliases accepted on the CLI / interactive prompt.
STREAM_ALIASES: dict[str, str] = {
    "1": "cs_it",
    "2": "electronics",
    "3": "electrical",
    "4": "mechanical",
    "5": "civil",
    "cs": "cs_it",
    "cs_it": "cs_it",
    "it": "cs_it",
    "computer": "cs_it",
    "electronics": "electronics",
    "ece": "electronics",
    "extc": "electronics",
    "electrical": "electrical",
    "ee": "electrical",
    "mechanical": "mechanical",
    "mech": "mechanical",
    "civil": "civil",
    "ce": "civil",
}

# Explicit mapping for branches that are domain-specific but should still be
# grouped into one of the five user-facing categories.
EXPLICIT_BRANCH_STREAM: dict[str, str] = {
    "Agricultural Engineering": "mechanical",
    "Architectural Assistantship": "civil",
    "Bio Medical Engineering": "electronics",
    "Bio Technology": "mechanical",
    "Chemical Engineering": "mechanical",
    "Dyestuff Technology": "mechanical",
    "Fashion Technology": "mechanical",
    "Fibres and Textile Processing Technology": "mechanical",
    "Fire Engineering": "civil",
    "Food Engineering": "mechanical",
    "Food Engineering and Technology": "mechanical",
    "Food Technology": "mechanical",
    "Food Technology And Management": "mechanical",
    "Man Made Textile Technology": "mechanical",
    "Metallurgy and Material Technology": "mechanical",
    "Mining Engineering": "mechanical",
    "Oil and Paints Technology": "mechanical",
    "Oil Fats and Waxes Technology": "mechanical",
    "Oil Technology": "mechanical",
    "Oil,Oleochemicals and Surfactants Technology": "mechanical",
    "Paints Technology": "mechanical",
    "Paper and Pulp Technology": "mechanical",
    "Petro Chemical Engineering": "mechanical",
    "Pharmaceutical and Fine Chemical Technology": "mechanical",
    "Pharmaceuticals Chemistry and Technology": "mechanical",
    "Plastic and Polymer Engineering": "mechanical",
    "Plastic Technology": "mechanical",
    "Polymer Engineering and Technology": "mechanical",
    "Printing and Packing Technology": "mechanical",
    "Safety and Fire Engineering": "civil",
    "Surface Coating Technology": "mechanical",
    "Technical Textiles": "mechanical",
    "Textile Chemistry": "mechanical",
    "Textile Engineering / Technology": "mechanical",
    "Textile Technology": "mechanical",
}


def _norm(branch: str) -> str:
    b = branch.lower().strip()
    b = b.replace("[", " ").replace("]", " ")
    b = b.replace("(", " ").replace(")", " ")
    b = b.replace("/", " ").replace("-", " ").replace("&", " ")
    b = re.sub(r"\s+", " ", b)
    return b


def classify_branch(branch: str) -> str | None:
    """
    Return a stream id for a branch name, or None if it does not fit
    the five core categories (e.g. Chemical, Textile, Food).
    """
    branch_clean = branch.strip()
    if branch_clean in EXPLICIT_BRANCH_STREAM:
        return EXPLICIT_BRANCH_STREAM[branch_clean]

    b = _norm(branch_clean)
    if not b:
        return None

    # --- Civil ---
    if "civil" in b or "structural engineering" == b or b.startswith("structural"):
        return "civil"

    # --- Explicit hybrids (order matters) ---
    if "electrical and computer" in b:
        return "electrical"
    if "electrical and electronics" in b or "electrical, electronics" in b:
        return "electrical"
    if "electronics and computer" in b:
        return "electronics"
    if "electronics and power" in b or "electrical engg electronics and power" in b:
        return "electrical"

    # --- Computer Science & IT ---
    cs_tokens = (
        "computer science",
        "computer engineering",
        "computer technology",
        "information technology",
        "artificial intelligence",
        "data science",
        "data engineering",
        "cyber security",
        "software engineering",
        "computer science and business",
        "computer science and design",
        "computer science and information",
    )
    if any(t in b for t in cs_tokens):
        return "cs_it"
    if b in {"computer science", "cyber security", "data science", "data engineering"}:
        return "cs_it"
    if re.search(r"\biot\b", b) or "internet of things" in b or "industrial iot" in b:
        return "cs_it"
    if "robotics and artificial intelligence" in b:
        return "cs_it"

    # --- Electronics & Communication ---
    if (
        "electronics" in b
        or "telecommunication" in b
        or "communication engineering" in b
        or "communication advanced" in b
        or "vlsi" in b
        or b == "5g"
        or "instrumentation" in b
    ):
        return "electronics"

    # --- Electrical ---
    if "electrical" in b:
        return "electrical"

    # --- Mechanical ---
    mech_tokens = (
        "mechanical",
        "mechatronics",
        "automobile",
        "automotive",
        "production engineering",
        "manufacturing",
        "automation and robotics",
        "robotics and automation",
        "aeronautical",
        "aerospace",
    )
    if any(t in b for t in mech_tokens):
        return "mechanical"

    return None


def branches_for_streams(branches: list[str], selected: set[str]) -> set[str]:
    """Filter branch names whose classified stream is in `selected`."""
    out: set[str] = set()
    for branch in branches:
        stream = classify_branch(branch)
        if stream in selected:
            out.add(branch)
    return out


def resolve_stream_tokens(tokens: list[str]) -> set[str]:
    """Map user tokens (numbers/aliases) to stream ids. Raises ValueError on unknown."""
    selected: set[str] = set()
    for raw in tokens:
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        if not key:
            continue
        if key in {"a", "all"}:
            return set(STREAM_ORDER)
        if key not in STREAM_ALIASES:
            raise ValueError(
                f"Unknown stream '{raw}'. Use 1-5, all, or names like cs, electronics, "
                f"electrical, mechanical, civil."
            )
        selected.add(STREAM_ALIASES[key])
    return selected


def prompt_streams(stdin_interactive: bool = True) -> set[str]:
    """Ask the user which streams to include. Returns selected stream ids."""
    print()
    print("Which branch streams should be considered for recommendations?")
    for i, sid in enumerate(STREAM_ORDER, start=1):
        print(f"  {i}) {STREAMS[sid]}")
    print("  A) All of the above")
    print()
    print("Enter choices separated by commas (e.g. 1,2 or cs,mechanical or A):")

    if not stdin_interactive:
        raise RuntimeError("Interactive stream selection requires a TTY")

    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            raw = "A"
        if not raw:
            print("Please enter at least one choice.")
            continue
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        try:
            selected = resolve_stream_tokens(parts)
        except ValueError as e:
            print(f"  {e}")
            continue
        if not selected:
            print("Please enter at least one choice.")
            continue
        return selected


def summarize_classification(all_branches: list[str]) -> dict[str, list[str]]:
    """Group unique branch names by stream (plus 'other')."""
    grouped: dict[str, list[str]] = {sid: [] for sid in STREAM_ORDER}
    grouped["other"] = []
    for branch in sorted(set(all_branches), key=str.lower):
        sid = classify_branch(branch)
        grouped[sid or "other"].append(branch)
    return grouped
