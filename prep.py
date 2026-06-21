#!/usr/bin/env python3
"""Prepare DDW submission data from the Excel export.

Replaces copy_files.ipynb. Reads the submissions .xlsx export and produces:
  - a CSV summary (id, title, affiliation, name, email, theme columns, format)
  - one markdown file per submission in the --md-dir
  - a per-submission folder under --output containing the copied documentation
    file and audience-experience image

Submission numbers are stable: they come from a persistent registry keyed by the
submission timestamp (see ddw_common.assign_numbers). Re-running on a newer
export keeps existing numbers and only assigns new ones to late submissions.

Example:
    ./prep.py --input ~/Downloads/export.xlsx
    ./prep.py --input export.xlsx --since 167 --md-dir md --output build
"""
import argparse
import shutil
import sys
from pathlib import Path

import ddw_common as c


def write_csv(df, out: Path) -> None:
    rows = []
    for _, row in df.iterrows():
        themes = c.themes_of(row)
        rec = {
            "submission id": row["submission id"],
            "title": row[c.COL_TITLE],
            "affiliation": row[c.COL_AFFIL],
            "name": row[c.COL_NAME],
            "email": row[c.COL_EMAIL],
        }
        for t in c.THEME_NAMES:
            rec[t] = t if t in themes else ""
        rec["format"] = row[c.COL_FORMAT]
        rows.append(rec)
    import pandas as pd
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote CSV: {out} ({len(rows)} rows)")


def build_markdown(row) -> str:
    sid = row["submission id"]
    md = (
        f"submission **{sid}** from **{row[c.COL_NAME]}** "
        f"at {row[c.COL_AFFIL]}\n\n"
    )
    md += f"# {row[c.COL_TITLE]}\n\n"
    md += f"{row[c.COL_ABSTRACT]}\n\n"
    md += f"## audience experience\n\n{row[c.COL_AUDIENCE]}\n\n"

    authors = row[c.COL_AUTHORS]
    if isinstance(authors, str) and authors.strip():
        md += f"## authors and affiliations\n\n{authors}\n\n"

    additional = row[c.COL_ADDITIONAL]
    if isinstance(additional, str) and additional.strip():
        md += f"## additional info\n\n{additional}\n\n"

    doc_link = row[c.COL_DOC_LINK]
    if isinstance(doc_link, str):
        md += f"## online documentation\n\n[online documentation]({doc_link})\n\n"
    video_link = row[c.COL_VIDEO_LINK]
    if isinstance(video_link, str):
        md += f"## link to video\n\n[link to video]({video_link})\n\n"
    return md


def write_markdown(df, md_dir: Path, since: int) -> None:
    md_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for _, row in df.iterrows():
        sid = row["submission id"]
        if sid < since:
            continue
        (md_dir / f"{sid}.md").write_text(build_markdown(row), encoding="utf-8")
        n += 1
    print(f"Wrote {n} markdown files to {md_dir}")


def copy_files(df, src_root: Path, out: Path, since: int) -> None:
    copied = 0
    for _, row in df.iterrows():
        sid = row["submission id"]
        if sid < since:
            continue
        dest = out / str(sid)
        dest.mkdir(parents=True, exist_ok=True)
        for col in (c.COL_DOC_PATH, c.COL_PIC_PATH):
            rel = row[col]
            if not isinstance(rel, str):
                continue
            src = src_root / rel
            if not src.exists():
                print(f"  [{sid}] missing file: {src}", file=sys.stderr)
                continue
            shutil.copy(src, dest)
            copied += 1
    print(f"Copied {copied} files into {out}/<id>/")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--output", type=Path, default=Path("build"),
                   help="Folder for per-submission copied files (default: build)")
    p.add_argument("--md-dir", type=Path, default=Path("md"),
                   help="Folder for generated markdown (default: md)")
    p.add_argument("--csv", type=Path, default=Path("submissions.csv"),
                   help="Output CSV path (default: submissions.csv)")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--since", type=int, default=0,
                   help="Only process submissions with id >= this value")
    p.add_argument("--skip-copy", action="store_true",
                   help="Do not copy documentation/image files")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)
    # The source files are referenced relative to the Excel's own folder.
    src_root = args.input.resolve().parent

    write_csv(df, args.csv)
    write_markdown(df, args.md_dir, args.since)
    if not args.skip_copy:
        copy_files(df, src_root, args.output, args.since)


if __name__ == "__main__":
    main()
