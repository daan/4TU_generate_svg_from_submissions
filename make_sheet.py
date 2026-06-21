#!/usr/bin/env python3
"""Create a Google Sheet overview of the submissions in the Shared Drive.

Columns: submission id, title, one column per theme (value = theme name when the
submission is in it, else empty, for easy sorting/filtering), institute,
submitter name, submitter email.

The sheet is created by uploading a CSV with conversion to a native Google Sheet
(Drive scope only). Re-running trashes a previous sheet of the same name first.

Example:
    ./make_sheet.py --input ~/Downloads/export.xlsx --dry-run
    ./make_sheet.py --input ~/Downloads/export.xlsx
"""
import argparse
import csv
import io
import sys
from pathlib import Path

from googleapiclient.http import MediaIoBaseUpload

import ddw_common as c
import upload as u  # reuse auth + Drive folder helpers

SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def build_csv(df, links: dict | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    header = (["submission id", "title"] + c.THEME_NAMES
              + ["institute", "submitter name", "submitter email"])
    if links is not None:
        header.append("document")
    w.writerow(header)
    for _, row in df.iterrows():
        sid = int(row["submission id"])
        themes = c.themes_of(row)
        rec = [row["submission id"], row[c.COL_TITLE]]
        rec += [t if t in themes else "" for t in c.THEME_NAMES]
        rec += [row[c.COL_AFFIL], row[c.COL_NAME], row[c.COL_EMAIL]]
        if links is not None:
            url = links.get(sid)
            rec.append(f'=HYPERLINK("{url}","open doc")' if url else "")
        w.writerow(rec)
    return buf.getvalue()


def doc_links(drive, drive_id: str) -> dict:
    """Map submission number -> Google Doc webViewLink (docs named with digits)."""
    links, page = {}, None
    while True:
        resp = drive.files().list(
            q="mimeType='application/vnd.google-apps.document' and trashed=false",
            corpora="drive", driveId=drive_id, includeItemsFromAllDrives=True,
            supportsAllDrives=True, spaces="drive", pageToken=page, pageSize=1000,
            fields="nextPageToken, files(name, webViewLink)").execute()
        for f in resp.get("files", []):
            if f["name"].isdigit():
                links[int(f["name"])] = f.get("webViewLink")
        page = resp.get("nextPageToken")
        if not page:
            break
    return links


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--drive-name", default="4TU.DU DDW26",
                   help="Target Shared Drive name")
    p.add_argument("--folder-path", default="submissions/submissions",
                   help="Folder within the Shared Drive to create the sheet in")
    p.add_argument("--name", default="DDW2026 submissions overview",
                   help="Name of the Google Sheet")
    p.add_argument("--no-link-docs", action="store_true",
                   help="Do not add a column linking to each submission's Doc")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the CSV that would be uploaded; no API calls")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)

    if args.dry_run:
        # links need the Drive; show structure with placeholders instead
        print(build_csv(df, links={} if not args.no_link_docs else None))
        print(f"[dry-run] would create/update sheet '{args.name}' "
              f"in {args.drive_name} (links: {not args.no_link_docs})")
        return

    drive, _ = u.authenticate()
    drive_id = u.get_shared_drive_id(drive, args.drive_name)
    if not drive_id:
        return

    links = None if args.no_link_docs else doc_links(drive, drive_id)
    if links is not None:
        print(f"Found {len(links)} document links")
    csv_text = build_csv(df, links)
    media = MediaIoBaseUpload(io.BytesIO(csv_text.encode("utf-8")),
                              mimetype="text/csv", resumable=True)

    # Update the existing sheet in place (wherever it was moved to), else create.
    found = drive.files().list(
        q=f"name='{args.name}' and mimeType='{SHEET_MIME}' and trashed=false",
        corpora="drive", driveId=drive_id, includeItemsFromAllDrives=True,
        supportsAllDrives=True, spaces="drive",
        fields="files(id, webViewLink)").execute().get("files", [])
    if found:
        fid = found[0]["id"]
        drive.files().update(fileId=fid, media_body=media,
                             supportsAllDrives=True).execute()
        print(f"Updated sheet in place: {found[0].get('webViewLink')}")
    else:
        folder_id = u.ensure_base_path(drive, drive_id, args.folder_path)
        created = drive.files().create(
            body={"name": args.name, "mimeType": SHEET_MIME,
                  "parents": [folder_id]},
            media_body=media, supportsAllDrives=True,
            fields="id, webViewLink").execute()
        print(f"Created sheet: {created.get('webViewLink')}")


if __name__ == "__main__":
    main()
