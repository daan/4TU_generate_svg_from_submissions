#!/usr/bin/env python3
"""Extract a candidate background image from the PDF of picture-less submissions.

For every submission that has no audience-experience picture but does have a PDF
documentation file, this drops one candidate image into build/<id>/ named
"<id>-frompdf.png" so you can review them (e.g. `open build`).

Strategy per PDF:
  1. Extract embedded images from the first --pages pages and pick the largest
     one above --min-size pixels (a real photo, when present).
  2. If none qualifies, render page 1 with pdftoppm as a fallback.

Then run `cards.py --pdf-fallback` to use the surviving candidates. Delete any
bad candidate before that and its card stays blank-background.

Requires poppler (pdfimages, pdftoppm, pdfinfo) on PATH.

Example:
    ./extract_pdf_images.py --input ~/Downloads/export.xlsx
"""
import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import ddw_common as c

CANDIDATE_SUFFIX = "-frompdf.png"


def png_size(path: Path):
    """Return (width, height) of a PNG, or None."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def largest_embedded(pdf: Path, pages: int, min_size: int) -> Path | None:
    """Extract embedded images from the first `pages` pages; return the path to
    the largest one (by pixel area) meeting the min-size threshold, copied to a
    stable temp file. Returns None if nothing qualifies."""
    tmp = Path(tempfile.mkdtemp(prefix="pdfimg_"))
    try:
        subprocess.run(
            ["pdfimages", "-png", "-f", "1", "-l", str(pages),
             str(pdf), str(tmp / "img")],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        return None
    best, best_area = None, 0
    for p in tmp.glob("*.png"):
        size = png_size(p)
        if not size:
            continue
        w, h = size
        if min(w, h) < min_size:
            continue
        if w * h > best_area:
            best, best_area = p, w * h
    return best


def render_page1(pdf: Path, dpi: int) -> Path | None:
    tmp = Path(tempfile.mkdtemp(prefix="pdfpage_"))
    out = tmp / "page"
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-singlefile", "-f", "1", "-l", "1",
             "-r", str(dpi), str(pdf), str(out)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        return None
    result = out.with_suffix(".png")
    return result if result.exists() else None


def has(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--output", type=Path, default=Path("build"),
                   help="Base output folder with per-submission dirs (default: build)")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--pages", type=int, default=5,
                   help="How many leading pages to scan for images (default: 5)")
    p.add_argument("--min-size", type=int, default=400,
                   help="Minimum width/height in px for an embedded image (default: 400)")
    p.add_argument("--dpi", type=int, default=150,
                   help="Render DPI for the page-1 fallback (default: 150)")
    p.add_argument("--force", action="store_true",
                   help="Re-extract even if a candidate already exists")
    p.add_argument("--all", action="store_true",
                   help="Process every submission with a PDF, not only those "
                        "lacking an audience picture")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)
    src_root = args.input.resolve().parent

    embedded = rendered = skipped = failed = 0
    for _, row in df.iterrows():
        if has(row[c.COL_PIC_PATH]) and not args.all:
            continue  # already has a real picture
        rel = row[c.COL_DOC_PATH]
        if not has(rel) or Path(rel).suffix.lower() != ".pdf":
            continue
        sid = int(row["submission id"])
        pdf = src_root / rel
        if not pdf.exists():
            print(f"  [{sid}] PDF missing: {pdf}", file=sys.stderr)
            failed += 1
            continue

        dest_dir = args.output / str(sid)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{sid}{CANDIDATE_SUFFIX}"
        if dest.exists() and not args.force:
            skipped += 1
            continue

        img = largest_embedded(pdf, args.pages, args.min_size)
        if img is not None:
            dest.write_bytes(img.read_bytes())
            w, h = png_size(dest)
            print(f"  [{sid}] embedded image {w}x{h}  <- {Path(rel).name}")
            embedded += 1
            continue

        page = render_page1(pdf, args.dpi)
        if page is not None:
            dest.write_bytes(page.read_bytes())
            print(f"  [{sid}] rendered page 1       <- {Path(rel).name}")
            rendered += 1
        else:
            print(f"  [{sid}] no image extractable  <- {Path(rel).name}",
                  file=sys.stderr)
            failed += 1

    print(f"\nDone: {embedded} embedded, {rendered} page-renders, "
          f"{skipped} skipped (exists), {failed} failed.")
    print(f"Review with:  open {args.output}")


if __name__ == "__main__":
    main()
