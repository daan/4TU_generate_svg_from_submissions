#!/usr/bin/env python3
"""Report coverage statistics for a DDW submissions export.

Shows how many submissions have a picture, and for those without one, what other
material exists (documentation file, video link, online-doc link) so you can
decide where card backgrounds could come from.

Example:
    ./stats.py --input ~/Downloads/export.xlsx
"""
import argparse
import collections
import sys
from pathlib import Path

import ddw_common as c


def has(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    args = p.parse_args()
    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    n = len(df)
    pic = df[c.COL_PIC_PATH].apply(has)
    doc = df[c.COL_DOC_PATH].apply(has)
    vid = df[c.COL_VIDEO_LINK].apply(has)
    onl = df[c.COL_DOC_LINK].apply(has)

    print(f"Total submissions: {n}\n")
    print(f"  with picture:        {pic.sum():3d}")
    print(f"  WITHOUT picture:     {(~pic).sum():3d}")
    print(f"  with documentation:  {doc.sum():3d}")
    print(f"  with video link:     {vid.sum():3d}")
    print(f"  with online-doc link:{onl.sum():3d}\n")

    no = df[~pic]
    no_doc = no[c.COL_DOC_PATH].apply(has)
    no_vid = no[c.COL_VIDEO_LINK].apply(has)
    no_onl = no[c.COL_DOC_LINK].apply(has)
    nothing = (~no_doc) & (~no_vid) & (~no_onl)
    print(f"Of the {len(no)} WITHOUT a picture:")
    print(f"  have a documentation file: {no_doc.sum()}")
    print(f"  have a video link:         {no_vid.sum()}")
    print(f"  have an online-doc link:   {no_onl.sum()}")
    print(f"  have NOTHING at all:       {nothing.sum()}\n")

    pdf_no_pic = sum(1 for v in no[c.COL_DOC_PATH]
                     if has(v) and Path(v).suffix.lower() == ".pdf")
    print(f"  -> {pdf_no_pic} of them have a PDF (candidate for image extraction)\n")

    print("Documentation file types (all submissions):")
    ext = collections.Counter(Path(v).suffix.lower()
                              for v in df[c.COL_DOC_PATH] if has(v))
    for k, count in ext.most_common():
        print(f"  {k or '(none)':6s}: {count}")


if __name__ == "__main__":
    main()
