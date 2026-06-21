#!/usr/bin/env python3
"""Upload submissions to Google Drive as native Google Docs, with images + files.

Replaces md_to_gdoc_converter.py. For each submission it:
  1. ensures the per-submission folder exists in the target Shared Drive
  2. (replace mode) trashes any existing files already in that folder
  3. creates a native Google Doc and fills it via the Docs API with proper
     headings, bold and hyperlinks, then embeds up to two images UNDER the text:
       - the audience-experience picture (if any)
       - the documentation image: the file itself if it is an image, otherwise
         the photo extracted from the PDF (see extract_pdf_images.py)
  4. uploads the submission materials (documentation file + audience image) into
     the same folder. The video is a link, kept inside the doc.

Building docs with the Docs API (not HTML auto-convert) avoids the old "blank
until opened manually" problem. Images can't be embedded from local bytes, so
each is uploaded to the folder, link-shared, inserted by URL, then removed (the
doc keeps its own copy). Large images are downscaled first.

Requires credentials.json (OAuth client) and poppler-extracted candidates.
On first run a browser opens for consent; token.json is written. Because this
needs the Docs scope too, delete token.json once if you authorised the old
Drive-only script.

Example:
    ./upload.py --input ~/Downloads/export.xlsx --dry-run
    ./upload.py --input ~/Downloads/export.xlsx
"""
import argparse
import re
import socket
import ssl
import sys
import tempfile
import time
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from PIL import Image

import ddw_common as c

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}
PAGE_WIDTH_PT = 450  # printable width to size embedded images to

# ---------------------------------------------------------------------------
# Markdown -> Google Docs requests (small subset emitted by prep.py)
# ---------------------------------------------------------------------------
_INLINE = re.compile(r"\*\*(.+?)\*\*|\[(.+?)\]\((.+?)\)")


def _parse_inline(text: str) -> list[dict]:
    runs, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append({"text": text[pos:m.start()], "bold": False, "link": None})
        if m.group(1) is not None:
            runs.append({"text": m.group(1), "bold": True, "link": None})
        else:
            runs.append({"text": m.group(2), "bold": False, "link": m.group(3)})
        pos = m.end()
    if pos < len(text):
        runs.append({"text": text[pos:], "bold": False, "link": None})
    return runs


def _parse_markdown(md: str) -> list[dict]:
    blocks, para = [], []

    def flush():
        if para:
            blocks.append({"style": "NORMAL_TEXT",
                           "runs": _parse_inline(" ".join(para))})
            para.clear()

    for line in md.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("## "):
            flush()
            blocks.append({"style": "HEADING_2", "runs": _parse_inline(s[3:])})
        elif s.startswith("# "):
            flush()
            blocks.append({"style": "HEADING_1", "runs": _parse_inline(s[2:])})
        else:
            para.append(s)
    flush()
    return blocks


def build_text_requests(md: str) -> list[dict]:
    blocks = _parse_markdown(md)
    full_text = ""
    para_styles, text_styles = [], []
    index = 1
    for block in blocks:
        block_start = index
        for run in block["runs"]:
            t = run["text"]
            if not t:
                continue
            start = index
            full_text += t
            index += len(t)
            if run["bold"] or run["link"]:
                text_styles.append((start, index, run["bold"], run["link"]))
        full_text += "\n"
        index += 1
        if block["style"] != "NORMAL_TEXT":
            para_styles.append((block_start, index, block["style"]))

    requests = [{"insertText": {"location": {"index": 1}, "text": full_text}}]
    for start, end, style in para_styles:
        requests.append({"updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": style},
            "fields": "namedStyleType"}})
    for start, end, bold, link in text_styles:
        style, fields = {}, []
        if bold:
            style["bold"] = True
            fields.append("bold")
        if link:
            style["link"] = {"url": link}
            fields.append("link")
        requests.append({"updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": style, "fields": ",".join(fields)}})
    return requests


# ---------------------------------------------------------------------------
# Per-submission image / material selection
# ---------------------------------------------------------------------------
def has(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def audience_image(row, src_root: Path) -> Path | None:
    rel = row[c.COL_PIC_PATH]
    if not has(rel):
        return None
    p = src_root / rel
    return p if p.exists() else None


def doc_image(row, src_root: Path, output: Path, sid: int) -> Path | None:
    rel = row[c.COL_DOC_PATH]
    if not has(rel):
        return None
    ext = Path(rel).suffix.lower()
    if ext in IMAGE_EXTS:
        p = src_root / rel
        return p if p.exists() else None
    if ext == ".pdf":
        cand = output / str(sid) / f"{sid}-frompdf.png"
        return cand if cand.exists() else None
    return None


def materials(row, src_root: Path) -> list[Path]:
    out = []
    for col in (c.COL_DOC_PATH, c.COL_PIC_PATH):
        rel = row[col]
        if has(rel):
            p = src_root / rel
            if p.exists():
                out.append(p)
    return out


def downscale(src: Path, max_px: int) -> tuple[Path, int, int]:
    """Write a downscaled RGB PNG to a temp file; return (path, w, h)."""
    img = Image.open(src)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((max_px, max_px))
    fd, name = tempfile.mkstemp(suffix=".png")
    import os
    os.close(fd)
    out = Path(name)
    img.save(out, "PNG")
    return out, img.width, img.height


# ---------------------------------------------------------------------------
# Retry transient network / server errors
# ---------------------------------------------------------------------------
_RETRYABLE = (ssl.SSLError, socket.timeout, ConnectionError, IncompleteRead,
              RemoteDisconnected, BrokenPipeError, TimeoutError, OSError)


def with_retry(fn, attempts: int = 5, base: float = 2.0, label: str = ""):
    for i in range(attempts):
        try:
            return fn()
        except HttpError as e:
            status = e.resp.status if getattr(e, "resp", None) else None
            if status and int(status) in (429, 500, 502, 503, 504) and i < attempts - 1:
                wait = base * (2 ** i)
                print(f"    retry {label}: HTTP {status} (wait {wait:.0f}s)",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except _RETRYABLE as e:
            if i < attempts - 1:
                wait = base * (2 ** i)
                print(f"    retry {label}: {type(e).__name__} (wait {wait:.0f}s)",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Google API plumbing
# ---------------------------------------------------------------------------
def authenticate():
    creds = None
    if Path("token.json").exists():
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if creds and creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        Path("token.json").write_text(creds.to_json())
    return (build("drive", "v3", credentials=creds),
            build("docs", "v1", credentials=creds))


def get_shared_drive_id(drive, name: str) -> str | None:
    resp = drive.drives().list(q=f"name='{name}'", pageSize=1).execute()
    drives = resp.get("drives", [])
    if not drives:
        print(f"Error: Shared Drive '{name}' not found.", file=sys.stderr)
        return None
    print(f"Found Shared Drive '{name}' -> {drives[0]['id']}")
    return drives[0]["id"]


def get_or_create_folder(drive, name: str, parent_id: str, drive_id: str) -> str:
    query = (f"'{parent_id}' in parents and name='{name}' "
             "and mimeType='application/vnd.google-apps.folder' and trashed=false")
    resp = drive.files().list(
        q=query, spaces="drive", corpora="drive", driveId=drive_id,
        includeItemsFromAllDrives=True, supportsAllDrives=True,
        fields="files(id, name)").execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    folder = drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        supportsAllDrives=True, fields="id").execute()
    return folder["id"]


def ensure_base_path(drive, drive_id: str, path: str) -> str:
    parent = drive_id
    for part in path.split("/"):
        parent = get_or_create_folder(drive, part, parent, drive_id)
    return parent


def empty_folder(drive, folder_id: str) -> int:
    """Permanently delete all non-folder files directly inside a folder."""
    resp = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false "
          "and mimeType!='application/vnd.google-apps.folder'",
        spaces="drive", includeItemsFromAllDrives=True, supportsAllDrives=True,
        fields="files(id)").execute()
    n = 0
    for f in resp.get("files", []):
        drive.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
        n += 1
    return n


def upload_to_folder(drive, folder_id: str, path: Path, mimetype=None) -> str:
    media = MediaFileUpload(str(path), mimetype=mimetype, resumable=True)
    f = drive.files().create(
        body={"name": path.name, "parents": [folder_id]},
        media_body=media, supportsAllDrives=True, fields="id").execute()
    return f["id"]


def make_public(drive, file_id: str) -> bool:
    try:
        drive.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True).execute()
        return True
    except HttpError as e:
        print(f"    (could not link-share image: {e})", file=sys.stderr)
        return False


def doc_end_index(docs, doc_id: int) -> int:
    doc = docs.documents().get(documentId=doc_id,
                               fields="body(content(endIndex))").execute()
    return doc["body"]["content"][-1]["endIndex"]


def append_image(docs, doc_id, uri, w, h):
    """Append an image on its own line at the end of the document."""
    end = doc_end_index(docs, doc_id)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"location": {"index": end - 1}, "text": "\n"}}]}).execute()
    end = doc_end_index(docs, doc_id)
    height = PAGE_WIDTH_PT * (h / w) if w else PAGE_WIDTH_PT
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertInlineImage": {
            "location": {"index": end - 1},
            "uri": uri,
            "objectSize": {
                "width": {"magnitude": PAGE_WIDTH_PT, "unit": "PT"},
                "height": {"magnitude": height, "unit": "PT"}}}}]}).execute()


def embed_images(drive, docs, doc_id, folder_id, images: list[Path], max_px: int):
    """Upload (downscaled), link-share, insert into doc, then delete the temp
    upload — the doc retains its own copy."""
    for img in images:
        tmp, w, h = downscale(img, max_px)
        try:
            fid = upload_to_folder(drive, folder_id, tmp, mimetype="image/png")
            if not make_public(drive, fid):
                drive.files().delete(fileId=fid, supportsAllDrives=True).execute()
                continue
            uri = f"https://drive.google.com/uc?export=view&id={fid}"
            try:
                append_image(docs, doc_id, uri, w, h)
            finally:
                drive.files().delete(fileId=fid, supportsAllDrives=True).execute()
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to the submissions .xlsx export")
    p.add_argument("--md-dir", type=Path, default=Path("md"),
                   help="Folder with <id>.md text (default: md)")
    p.add_argument("--output", type=Path, default=Path("build"),
                   help="Base folder holding extracted PDF images (default: build)")
    p.add_argument("--registry", type=Path, default=Path("numbering.csv"),
                   help="Submission-number registry (default: numbering.csv)")
    p.add_argument("--drive-name", default="4TU.DU DDW26",
                   help="Target Shared Drive name")
    p.add_argument("--folder-path", default="submissions/submissions",
                   help="Base folder path within the Shared Drive")
    p.add_argument("--since", type=int, default=0,
                   help="Only upload submissions with id >= this value")
    p.add_argument("--max-image-px", type=int, default=1600,
                   help="Max width/height for embedded images (default: 1600)")
    p.add_argument("--no-images", action="store_true",
                   help="Do not embed images under the text")
    p.add_argument("--no-materials", action="store_true",
                   help="Do not upload the documentation/image files")
    p.add_argument("--keep-existing", action="store_true",
                   help="Do not trash existing files in each folder first")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would happen; no API calls")
    args = p.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    df = c.load_submissions(args.input)
    df = c.assign_numbers(df, args.registry)
    src_root = args.input.resolve().parent

    rows = []
    for _, row in df.iterrows():
        sid = int(row["submission id"])
        if sid < args.since:
            continue
        md_path = args.md_dir / f"{sid}.md"
        if not md_path.exists():
            print(f"  [{sid}] no markdown, skipping", file=sys.stderr)
            continue
        imgs = [] if args.no_images else [
            x for x in (audience_image(row, src_root),
                        doc_image(row, src_root, args.output, sid)) if x]
        mats = [] if args.no_materials else materials(row, src_root)
        rows.append((sid, md_path, imgs, mats))

    if not rows:
        sys.exit("Nothing to upload.")

    if args.dry_run:
        for sid, md_path, imgs, mats in rows:
            print(f"[dry-run] {sid}: text + {len(imgs)} image(s) + "
                  f"{len(mats)} material file(s)")
        print(f"[dry-run] {len(rows)} documents.")
        return

    drive, docs = authenticate()
    drive_id = get_shared_drive_id(drive, args.drive_name)
    if not drive_id:
        return
    base_id = ensure_base_path(drive, drive_id, args.folder_path)

    def process(sid, md_path, imgs, mats):
        folder_id = get_or_create_folder(drive, str(sid), base_id, drive_id)
        if not args.keep_existing:
            removed = empty_folder(drive, folder_id)
            if removed:
                print(f"  trashed {removed} existing file(s)")
        doc = drive.files().create(
            body={"name": str(sid),
                  "mimeType": "application/vnd.google-apps.document",
                  "parents": [folder_id]},
            supportsAllDrives=True, fields="id, webViewLink").execute()
        docs.documents().batchUpdate(
            documentId=doc["id"],
            body={"requests": build_text_requests(
                md_path.read_text(encoding="utf-8"))}).execute()
        print(f"  doc: {doc.get('webViewLink')}")
        if imgs:
            embed_images(drive, docs, doc["id"], folder_id, imgs, args.max_image_px)
            print(f"  embedded {len(imgs)} image(s)")
        for m in mats:
            with_retry(lambda m=m: upload_to_folder(drive, folder_id, m),
                       label=f"{sid} material {m.name}")
        if mats:
            print(f"  uploaded {len(mats)} material file(s)")

    failures = []
    for sid, md_path, imgs, mats in rows:
        print(f"\n--- {sid} ---")
        try:
            with_retry(lambda: process(sid, md_path, imgs, mats),
                       label=f"submission {sid}")
        except Exception as e:  # noqa: BLE001 - keep going on any single failure
            print(f"  FAILED {sid}: {type(e).__name__}: {e}", file=sys.stderr)
            failures.append(sid)

    print(f"\nDone: {len(rows) - len(failures)}/{len(rows)} uploaded.")
    if failures:
        print("Failed: " + " ".join(map(str, failures)))
        print("Re-run the same command to retry (it trashes + recreates).")


if __name__ == "__main__":
    main()
