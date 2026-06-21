#!/usr/bin/env python3
"""Bundle the submission cards into zip archives.

Creates, under --out:
  - all_cards.zip                  every card
  - <theme>.zip  (one per theme)   cards of submissions in that theme

A submission that belongs to multiple themes appears in each of those theme zips.

Example:
    ./make_zips.py --input ~/Downloads/export.xlsx
"""
import argparse
import sys
import zipfile
from pathlib import Path

import ddw_common as c


def slug(theme: str) -> str:
    return theme.lower().replace(" ", "_")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--cards-dir", type=Path, default=Path("build/cards"),
                   help="Folder with the card files (default: build/cards)")
    p.add_argument("--out", type=Path, default=Path("build/zips"),
                   help="Output folder for the zips (default: build/zips)")
    p.add_argument("--ext", default="png", help="Card file extension (default: png)")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)
    args.out.mkdir(parents=True, exist_ok=True)

    # submission id -> card path, and theme -> [ids]
    cards: dict[int, Path] = {}
    by_theme: dict[str, list[int]] = {t: [] for t in c.THEME_NAMES}
    missing = []
    for _, row in df.iterrows():
        sid = int(row["submission id"])
        card = args.cards_dir / f"{sid}.{args.ext}"
        if not card.exists():
            missing.append(sid)
            continue
        cards[sid] = card
        for t in c.themes_of(row):
            if t in by_theme:
                by_theme[t].append(sid)

    if missing:
        print(f"  note: no card for {len(missing)} submission(s): "
              f"{' '.join(map(str, missing))}", file=sys.stderr)

    # all_cards.zip
    all_zip = args.out / "all_cards.zip"
    with zipfile.ZipFile(all_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for sid in sorted(cards):
            z.write(cards[sid], f"{sid}.{args.ext}")
    print(f"{all_zip.name}: {len(cards)} cards")

    # per-theme zips
    for theme in c.THEME_NAMES:
        ids = sorted(by_theme[theme])
        theme_zip = args.out / f"{slug(theme)}.zip"
        with zipfile.ZipFile(theme_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for sid in ids:
                z.write(cards[sid], f"{sid}.{args.ext}")
        print(f"{theme_zip.name}: {len(ids)} cards")

    print(f"\nWrote zips to {args.out}")


if __name__ == "__main__":
    main()
