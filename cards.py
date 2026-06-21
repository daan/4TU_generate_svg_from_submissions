#!/usr/bin/env python3
"""Generate SVG (and optionally PNG) cards for DDW submissions.

Replaces create_miro_cards.ipynb. Reads the submissions .xlsx export and draws
one 800x600 card per submission: background image, theme colour bars, zero-padded
number, title and institute. Cards are written to <output>/cards/<id>.svg.

Submission numbers come from the same persistent registry as prep.py, so card
numbers always match the markdown/Docs numbers. Use --since to resume.

Example:
    ./cards.py --input ~/Downloads/export.xlsx
    ./cards.py --input export.xlsx --since 194 --png
"""
import argparse
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import drawsvg as draw
from PIL import ImageFont

import ddw_common as c

DEFAULT_INKSCAPE = "/Applications/Inkscape.app/Contents/MacOS/inkscape"
WIDTH, HEIGHT = 800, 600
FONT_FAMILY = "Inter"
FONT_WEIGHT = 500  # Medium
FONT_PATH = os.path.expanduser("~/Library/Fonts/InterVariable.ttf")

TITLE_X = 110
TITLE_MARGIN = 10
TITLE_MAX_W = WIDTH - TITLE_X - TITLE_MARGIN  # available px for the title
TITLE_SIZE_1 = 40  # one-line titles
TITLE_SIZE_2 = 34  # two-line titles


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _width(text: str, size: int) -> float:
    return _font(size).getlength(text)


def wrap_title(title: str, size: int, max_w: float) -> list[str]:
    """Wrap a title into at most two lines that fit max_w; the second line is
    truncated with an ellipsis if even two lines are not enough."""
    if _width(title, size) <= max_w:
        return [title]
    words = title.split()
    line1 = []
    i = 0
    while i < len(words):
        trial = " ".join(line1 + [words[i]])
        if line1 and _width(trial, size) > max_w:
            break
        line1.append(words[i])
        i += 1
    rest = words[i:]
    line2 = " ".join(rest)
    while rest and _width(line2, size) > max_w:
        rest = rest[:-1]
        line2 = " ".join(rest) + "…"
    return [" ".join(line1), line2] if line2 else [" ".join(line1)]


def make_card(index: int, title: str, institute: str,
              themes: list[str], picture: Path | None) -> draw.Drawing:
    d = draw.Drawing(WIDTH, HEIGHT)

    if picture is not None:
        d.append(draw.Image(0, 50, WIDTH, HEIGHT, str(picture), embed=True))

    h = 30
    w = WIDTH / 5
    for i in range(5):
        if c.THEME_NAMES[i] in themes:
            d.append(draw.Rectangle(i * w, 0, w, h, fill=c.THEME_COLORS[i]))
            tcolor = "black" if i == 1 else "white"
            d.append(draw.Text(c.THEME_NAMES[i], 16, i * w + w / 2, h / 2,
                               fill=tcolor, font_family=FONT_FAMILY,
                               font_weight=FONT_WEIGHT, text_anchor="middle",
                               dominant_baseline="middle"))

    lines = wrap_title(title, TITLE_SIZE_1, TITLE_MAX_W)
    if len(lines) == 1:
        title_size, box_h = TITLE_SIZE_1, 70
    else:
        title_size, box_h = TITLE_SIZE_2, 100
        lines = wrap_title(title, TITLE_SIZE_2, TITLE_MAX_W)

    d.append(draw.Rectangle(0, h, 100, 70, fill="#000000"))
    d.append(draw.Text(str(index).zfill(3), 40, 50, h + 30, fill="white",
                       font_family=FONT_FAMILY, font_weight=FONT_WEIGHT,
                       text_anchor="middle", dominant_baseline="middle"))
    d.append(draw.Rectangle(100, h, WIDTH, box_h, fill="#ffffff"))

    if len(lines) == 1:
        d.append(draw.Text(lines[0], title_size, TITLE_X, h + 30, fill="black",
                           font_family=FONT_FAMILY, font_weight=FONT_WEIGHT,
                           dominant_baseline="middle"))
        institute_y = h + 60
    else:
        d.append(draw.Text(lines[0], title_size, TITLE_X, h + 28, fill="black",
                           font_family=FONT_FAMILY, font_weight=FONT_WEIGHT,
                           dominant_baseline="middle"))
        d.append(draw.Text(lines[1], title_size, TITLE_X, h + 62, fill="black",
                           font_family=FONT_FAMILY, font_weight=FONT_WEIGHT,
                           dominant_baseline="middle"))
        institute_y = h + 88

    d.append(draw.Text(institute, 15, TITLE_X, institute_y, fill="#aaaaaa",
                       font_family=FONT_FAMILY, font_weight=FONT_WEIGHT,
                       dominant_baseline="middle"))
    return d


def export_png(svg_path: Path, inkscape: str) -> bool:
    png_path = svg_path.with_suffix(".png")
    try:
        subprocess.run(
            [inkscape, str(svg_path), f"--export-filename={png_path}",
             "--export-width=800", "--export-height=600"],
            check=True, capture_output=True,
        )
        return True
    except FileNotFoundError:
        sys.exit(f"Inkscape not found at: {inkscape} (use --inkscape to set path)")
    except subprocess.CalledProcessError as e:
        print(f"  PNG export failed for {svg_path}: {e.stderr.decode().strip()}",
              file=sys.stderr)
        return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--output", type=Path, default=Path("build"),
                   help="Base output folder; cards go to <output>/cards "
                        "(default: build)")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--since", type=int, default=0,
                   help="Only render submissions with id >= this value")
    p.add_argument("--missing-picture-only", action="store_true",
                   help="Only render submissions that have no audience picture")
    p.add_argument("--pdf-fallback", action="store_true",
                   help="When a submission has no picture, use the reviewed "
                        "candidate at <output>/<id>/<id>-frompdf.png if present "
                        "(see extract_pdf_images.py)")
    p.add_argument("--png", action="store_true",
                   help="Also export PNGs via Inkscape")
    p.add_argument("--inkscape", default=DEFAULT_INKSCAPE,
                   help="Path to the Inkscape executable")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)
    src_root = args.input.resolve().parent

    cards_dir = args.output / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    for _, row in df.iterrows():
        sid = int(row["submission id"])
        if sid < args.since:
            continue

        rel = row[c.COL_PIC_PATH]
        has_real_pic = isinstance(rel, str) and rel.strip() != ""
        if args.missing_picture_only and has_real_pic:
            continue
        picture = src_root / rel if isinstance(rel, str) else None
        if picture is not None and not picture.exists():
            print(f"  [{sid}] missing image: {picture}", file=sys.stderr)
            picture = None
        if picture is None and args.pdf_fallback:
            candidate = args.output / str(sid) / f"{sid}-frompdf.png"
            if candidate.exists():
                picture = candidate

        d = make_card(sid, row[c.COL_TITLE], row[c.COL_AFFIL],
                      c.themes_of(row), picture)
        svg_path = cards_dir / f"{sid}.svg"
        d.save_svg(str(svg_path))
        n += 1
        if args.png:
            export_png(svg_path, args.inkscape)

    print(f"Wrote {n} cards to {cards_dir}" + (" (+PNG)" if args.png else ""))


if __name__ == "__main__":
    main()
