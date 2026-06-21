# 4TU DDW submission tooling

Three command-line scripts that turn the DDW submissions Excel export into a CSV,
per-submission markdown + copied files, SVG/PNG cards, and Google Docs.

These replace the old Jupyter notebooks (`copy_files.ipynb`,
`create_miro_cards.ipynb`) and `md_to_gdoc_converter.py`.

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Submission numbering (important)

Numbers are **not** positional. They live in a persistent registry,
`numbering.csv`, keyed by each submission's `When` timestamp (unique and
immutable). The first submission is 100.

- `prep.py` and `cards.py` both read/update this registry, so card numbers always
  match the markdown/Docs numbers.
- **Re-running on a newer export is safe**: existing submissions keep their
  numbers; only late (new-timestamp) submissions get new numbers, appended at the
  end. Removing or reordering rows in a later export does *not* renumber anything.
- **Keep `numbering.csv` — commit it.** It is the source of truth. Deleting it
  restarts numbering from 100.

Each script also takes `--since <id>` to limit work to ids >= a value, and
`--registry <path>` to point at a different registry file.

## 1. prep.py — data, markdown, file copy

```sh
./prep.py --input ~/Downloads/export.xlsx
```

Produces:
- `submissions.csv` — id, title, affiliation, name, email, theme columns, format
- `md/<id>.md` — one markdown file per submission
- `build/<id>/` — copied documentation file + audience-experience image

Source files are resolved relative to the Excel file's own folder. Options:
`--output`, `--md-dir`, `--csv`, `--since`, `--skip-copy`.

## 2. cards.py — SVG / PNG cards

```sh
./cards.py --input ~/Downloads/export.xlsx          # SVGs only
./cards.py --input ~/Downloads/export.xlsx --png    # also PNG via Inkscape
```

Writes `build/cards/<id>.svg`. Cards use the **Inter Medium** font; long titles
wrap to two lines automatically. `--png` shells out to Inkscape (`--inkscape` to
override the path). Options: `--output`, `--since`, `--missing-picture-only`
(only render submissions that have no audience picture), `--pdf-fallback` (use
reviewed `build/<id>/<id>-frompdf.png` candidates as backgrounds).

## stats.py — coverage report

```sh
./stats.py --input ~/Downloads/export.xlsx
```

Reports how many submissions have a picture, and for those without one what else
they have (documentation file, video link, online-doc link) — useful for
deciding card backgrounds. Read-only, no output files.

## extract_pdf_images.py — PDF background candidates (optional)

For submissions with no picture but a PDF, extracts a candidate background into
`build/<id>/<id>-frompdf.png`:

```sh
./extract_pdf_images.py --input ~/Downloads/export.xlsx
open build            # review the candidates, delete any bad ones
./cards.py --input ~/Downloads/export.xlsx --pdf-fallback --png
```

It picks the largest embedded image from the first `--pages` pages (real photos),
and falls back to rendering page 1 when a PDF has none (often a title page — worth
deleting). `cards.py --pdf-fallback` uses whatever candidates survive your review.
Requires poppler (`pdfimages`, `pdftoppm`). Options: `--pages`, `--min-size`,
`--dpi`, `--force`.

## make_zips.py — card bundles

```sh
./make_zips.py --input ~/Downloads/export.xlsx
```

Writes to `build/zips/`: `all_cards.zip` (every card) plus one zip per theme
(e.g. `equal_society.zip`). Submissions in multiple themes appear in each theme's
zip. Uses the PNG cards in `build/cards` by default (`--ext`, `--cards-dir`,
`--out` to override).

## make_sheet.py — Google Sheet overview

```sh
./make_sheet.py --input ~/Downloads/export.xlsx --dry-run   # preview CSV
./make_sheet.py --input ~/Downloads/export.xlsx             # create the sheet
```

Creates a native Google Sheet in the Shared Drive with columns: submission id,
title, one column per theme (for sorting), institute, submitter name, submitter
email, and a **document** column hyperlinking to each submission's Google Doc
(`--no-link-docs` to omit). If a sheet of the same name already exists anywhere
in the drive it is **updated in place** (so it stays wherever you moved it);
otherwise it is created in `--folder-path` (default `submissions/submissions`).
Drive scope only.

## 3. upload.py — Google Docs

```sh
./upload.py --dry-run        # parse markdown, report, no API calls
./upload.py                  # create the docs
```

For each `md/<id>.md` it creates a **native Google Doc** in the Shared Drive and
fills it via the Docs API with real headings, bold and hyperlinks. This replaces
the old "upload HTML and let Drive convert it" path, which produced docs that
appeared blank until opened manually.

Needs `credentials.json` (OAuth client). First run opens a browser and writes
`token.json`. **If you previously ran the old Drive-only script, delete
`token.json` once** — this script also needs the Docs scope.

Options: `--md-dir`, `--drive-name` (default `4TU.DU DDW26`),
`--folder-path` (default `submissions/submissions`), `--since`, `--dry-run`.
