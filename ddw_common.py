"""Shared helpers for the DDW submission scripts.

Holds the column names, theme definitions, and the persistent submission-number
registry so that prep.py, cards.py and upload.py all agree on which submission
gets which number.

Numbering is anchored to the immutable `When` (submission timestamp) column,
which is unique per submission. A small CSV registry maps that timestamp to a
permanent number, so re-running on a newer export (with late submissions added)
keeps every existing number stable and only assigns new numbers to new rows.
"""
from pathlib import Path

import pandas as pd

THEME_NAMES = [
    "Thriving Planet",
    "Living Environments",
    "Digital Future",
    "Health and Wellbeing",
    "Equal Society",
]
THEME_COLORS = ["#ff595e", "#ffca3a", "#8ac926", "#1982c4", "#6a4c93"]

# Exact Excel column names from the 2026 DDW export.
COL_WHEN = "When"
COL_TITLE = "Project Title"
COL_ABSTRACT = "Abstract"
COL_AUTHORS = "Authors and Affiliations"
COL_NAME = "Submitter Name"
COL_EMAIL = "Submitter Email"
COL_AFFIL = "Submitter Affiliation"
COL_THEME = "DU Theme"
COL_FORMAT = "Presentation Format"
COL_AUDIENCE = "what does the audience experience?"
COL_ADDITIONAL = "additional info"
COL_DOC_LINK = "Link to Online Documentation"
COL_VIDEO_LINK = "Link to Video"
COL_DOC_PATH = "Documentation - path"
COL_PIC_PATH = "Visualisation of the audience experience (optional) - path"

REGISTRY_COLUMNS = ["when", "number", "title", "email"]


def load_submissions(input_path: Path) -> pd.DataFrame:
    """Read the Excel export."""
    return pd.read_excel(input_path)


def _when_key(value) -> str:
    """Canonical, stable string key for a submission timestamp."""
    return pd.Timestamp(value).isoformat()


def themes_of(row) -> list[str]:
    raw = row[COL_THEME]
    return raw.split("; ") if isinstance(raw, str) else []


def assign_numbers(df: pd.DataFrame, registry_path: Path,
                   start: int = 100) -> pd.DataFrame:
    """Attach a stable `submission id` column, updating the registry on disk.

    Existing timestamps reuse their stored number; new ones get the next free
    number. The registry CSV is rewritten only when new submissions appear.
    """
    registry: dict[str, int] = {}
    existing_rows: list[dict] = []
    if registry_path.exists():
        reg = pd.read_csv(registry_path)
        for _, r in reg.iterrows():
            registry[str(r["when"])] = int(r["number"])
            existing_rows.append({c: r.get(c) for c in REGISTRY_COLUMNS})

    next_num = max(registry.values(), default=start - 1) + 1
    assigned: list[int] = []
    new_rows: list[dict] = []
    for idx, row in df.iterrows():
        key = _when_key(row[COL_WHEN])
        if key in registry:
            assigned.append(registry[key])
        else:
            registry[key] = next_num
            assigned.append(next_num)
            new_rows.append({
                "when": key,
                "number": next_num,
                "title": row[COL_TITLE],
                "email": row[COL_EMAIL],
            })
            next_num += 1

    out = df.copy()
    out["submission id"] = assigned

    if new_rows:
        pd.DataFrame(existing_rows + new_rows, columns=REGISTRY_COLUMNS).to_csv(
            registry_path, index=False)
        print(f"Registry {registry_path}: "
              f"{len(existing_rows)} kept, {len(new_rows)} new "
              f"(total {len(existing_rows) + len(new_rows)})")
    else:
        print(f"Registry {registry_path}: {len(existing_rows)} entries, "
              "no new submissions")

    return out
