"""Weekly members-list sync from Box.

Downloads the members spreadsheet (xlsx or csv) from Box, keeps ONLY the
names, and writes data/members.json. Everything else in the sheet is
discarded immediately and never saved.

Auth: Box OAuth 2.0 with a refresh token. Box rotates the refresh token on
every use (valid 60 days), so the new one is written to .box_refresh_token
and the workflow saves it back to the BOX_REFRESH_TOKEN secret.

Env: BOX_CLIENT_ID, BOX_CLIENT_SECRET, BOX_REFRESH_TOKEN,
     BOX_FILE_ID (a fixed file) or BOX_FOLDER_ID (newest spreadsheet in folder).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import requests
from openpyxl import load_workbook

from . import ROOT, load_config
from .notify import send_alert

API = "https://api.box.com/2.0"


def get_access_token() -> str:
    r = requests.post("https://api.box.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": os.environ["BOX_REFRESH_TOKEN"],
        "client_id": os.environ["BOX_CLIENT_ID"],
        "client_secret": os.environ["BOX_CLIENT_SECRET"],
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    # save rotated refresh token for the workflow to store back as a secret
    (ROOT / ".box_refresh_token").write_text(tok["refresh_token"])
    return tok["access_token"]


def newest_in_folder(token: str, folder_id: str) -> tuple[str, str]:
    r = requests.get(f"{API}/folders/{folder_id}/items",
                     params={"fields": "id,name,modified_at,type", "limit": 1000},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    files = [e for e in r.json()["entries"]
             if e["type"] == "file" and e["name"].lower().endswith((".xlsx", ".csv"))]
    if not files:
        raise RuntimeError("No .xlsx/.csv files in the Box folder")
    f = max(files, key=lambda e: e["modified_at"])
    return f["id"], f["name"]


def download(token: str, file_id: str) -> tuple[bytes, str]:
    h = {"Authorization": f"Bearer {token}"}
    meta = requests.get(f"{API}/files/{file_id}", params={"fields": "name"}, headers=h, timeout=30)
    meta.raise_for_status()
    r = requests.get(f"{API}/files/{file_id}/content", headers=h, timeout=60)
    r.raise_for_status()
    return r.content, meta.json()["name"]


def extract_names(content: bytes, filename: str, name_cols: list[str]) -> list[str]:
    if filename.lower().endswith(".csv"):
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig", errors="ignore"))))
    else:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [[("" if c is None else str(c)).strip() for c in row] for row in ws.iter_rows(values_only=True)]
    wanted = [c.lower() for c in name_cols]
    # find header row in first 10 rows
    for hi, row in enumerate(rows[:10]):
        low = [c.lower().strip() for c in row]
        if any(w in low for w in wanted):
            break
    else:
        raise RuntimeError(f"No name column found (looked for {name_cols})")
    low = [c.lower().strip() for c in rows[hi]]
    idx = lambda *names: next((low.index(n) for n in names if n in low), None)
    full = idx("name", "full name", "member name")
    first = idx("first name", "firstname", "forename")
    last = idx("surname", "last name", "lastname")
    names = []
    for row in rows[hi + 1:]:
        if full is not None and full < len(row) and row[full]:
            names.append(row[full])
        elif first is not None and last is not None and max(first, last) < len(row):
            n = f"{row[first]} {row[last]}".strip()
            if n:
                names.append(n)
    return sorted({n.strip() for n in names if n.strip()})


def main() -> int:
    cfg = load_config()["members"]
    try:
        token = get_access_token()
        file_id = os.environ.get("BOX_FILE_ID") or cfg.get("box_file_id")
        folder_id = os.environ.get("BOX_FOLDER_ID") or cfg.get("box_folder_id")
        if not file_id and folder_id:
            file_id, _ = newest_in_folder(token, folder_id)
        if not file_id:
            raise RuntimeError("Set BOX_FILE_ID or BOX_FOLDER_ID")
        content, fname = download(token, file_id)
        names = extract_names(content, fname, cfg["name_columns"])
    except Exception as e:
        send_alert("Members sync failed", f"{type(e).__name__}: {e}\n\nThe previous members list is still in use.")
        print(f"FAILED: {e}")
        return 1

    path = ROOT / cfg["file"]
    prev_raw = os.environ.get("MEMBERS_JSON") or (path.read_text() if path.exists() else "")
    prev = json.loads(prev_raw)["names"] if prev_raw else []
    if len(names) < cfg.get("min_expected", 50) or (prev and len(names) < 0.7 * len(prev)):
        send_alert("Members list looks wrong",
                   f"Downloaded {fname} has {len(names)} names (previous list: {len(prev)}). "
                   "Kept the previous list. Check the spreadsheet layout.")
        return 1
    payload = json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "count": len(names), "names": names}, separators=(",", ":"), ensure_ascii=False)
    if len(payload.encode()) > 47_000:   # GitHub secrets are capped at 48 KB
        send_alert("Members list too large", f"{len(names)} names is over the 48 KB secret limit.")
        return 1
    path.write_text(payload)   # the workflow copies this into the MEMBERS_JSON secret, then deletes it
    print(f"Members updated: {len(names)} names from {fname} "
          f"(+{len(set(names) - set(prev))} / -{len(set(prev) - set(names))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
