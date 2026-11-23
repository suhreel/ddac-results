"""Turn new DDAC Facebook page posts into DRAFT notices on the Members page.

No AI: the card summary is taken straight from the post's own text.
- Reads the club page's recent posts (Meta Graph API, page token).
- For each post not seen before, creates a *draft* item in the Webflow CMS
  collection "Member Notices", with a "See full post" button linking to the
  original Facebook post.
- Emails NOTIFY_TO so the draft can be checked and published (approved) in
  Webflow. Nothing goes live until someone publishes it.

Secrets (GitHub Actions): FB_PAGE_ID, FB_PAGE_TOKEN, WEBFLOW_TOKEN,
GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_TO.

First run: only the newest post is drafted (so you can see it working);
older posts are marked as seen and skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "fb_notices_state.json"

GRAPH = "https://graph.facebook.com/v21.0"
WEBFLOW = "https://api.webflow.com/v2"
COLLECTION_ID = "6b04353bbb1d61c981d5f50a"  # Member Notices
WEBFLOW_DESIGNER = "https://webflow.com/design/ddac2026"

TITLE_MAX = 90
MESSAGE_MAX = 280
RESULT_WORDS = re.compile(
    r"\b(results?|pbs?|personal best|finish(?:ed|ers)?|podium|placed|1st|2nd|3rd|"
    r"\d+\s?k\b|marathon|parkrun|cross[- ]country|xc|race|relay|medal)\b",
    re.I,
)


def env(name: str) -> str:
    return "".join((os.environ.get(name) or "").split())


# ---------------------------------------------------------------- text helpers
def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    return re.sub(r"\n{2,}", "\n", text).strip()


def cut(text: str, limit: int) -> str:
    """Trim at a word boundary and add an ellipsis if needed."""
    text = text.strip()
    if len(text) <= limit:
        return text
    short = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return short + "…"


def first_sentences(text: str, limit: int) -> str:
    """Whole sentences up to `limit` characters; falls back to a word cut."""
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
    out = ""
    for p in parts:
        if len(out) + len(p) + 1 > limit:
            break
        out = f"{out} {p}".strip()
    return out or cut(text, limit)


def build_notice(post: dict) -> dict | None:
    msg = clean(post.get("message", ""))
    if not msg:
        return None  # photo-only post with no text: nothing to summarise
    lines = [l.strip() for l in msg.split("\n") if l.strip()]
    # Title = first sentence of the first line; everything after it is the summary.
    head = re.split(r"(?<=[.!?])\s+", lines[0], maxsplit=1)[0]
    first_rest = lines[0][len(head):].strip()
    title = cut(head, TITLE_MAX)
    rest = " ".join([first_rest] + lines[1:]).strip()
    if not rest and len(head) > TITLE_MAX:
        rest = head
    summary = first_sentences(rest, MESSAGE_MAX) if rest else "See the full post on Facebook."
    label = "Results" if RESULT_WORDS.search(msg) else "Club news"
    created = post.get("created_time", "")
    try:
        when = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except ValueError:
        when = datetime.now(timezone.utc)
    post_id = post["id"].split("_")[-1]
    field_data = {
        "name": title,
        "slug": f"fb-{post_id}"[:250],
        "notice-date": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "label": label,
        "message": summary,
        "button-text": "See full post",
        "button-link": post.get("permalink_url") or f"https://www.facebook.com/{post['id']}",
    }
    if post.get("full_picture"):
        field_data["image"] = {"url": post["full_picture"]}
    return field_data


# ---------------------------------------------------------------- APIs
def fetch_posts(page_id: str, token: str, limit: int = 15) -> list[dict]:
    r = requests.get(
        f"{GRAPH}/{page_id}/posts",
        params={
            "fields": "id,message,created_time,permalink_url,full_picture",
            "limit": limit,
            "access_token": token,
        },
        timeout=30,
    )
    if r.status_code != 200:
        err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
        raise RuntimeError(f"Facebook API error {r.status_code}: {err.get('message', r.text[:200])}")
    return r.json().get("data", [])


def create_draft(token: str, field_data: dict) -> dict:
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json", "content-type": "application/json"}
    body = {"isDraft": True, "isArchived": False, "fieldData": field_data}
    r = requests.post(f"{WEBFLOW}/collections/{COLLECTION_ID}/items", headers=headers, json=body, timeout=60)
    if r.status_code == 400 and "image" in field_data:
        # Facebook image links can expire or be refused; try again without the picture.
        body["fieldData"] = {k: v for k, v in field_data.items() if k != "image"}
        r = requests.post(f"{WEBFLOW}/collections/{COLLECTION_ID}/items", headers=headers, json=body, timeout=60)
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"Webflow API error {r.status_code}: {r.text[:300]}")
    return r.json()


# ---------------------------------------------------------------- email
def email_drafts(drafts: list[dict]) -> None:
    from ddac.notify import _creds, _send

    user, pw, to = _creds()
    if not (user and pw):
        print("Email not configured; skipping notification.")
        return
    n = len(drafts)
    subject = f"DDAC Members page: {n} new draft notice{'s' if n != 1 else ''} to check"
    html = [
        f"<p>{n} new Facebook post{'s have' if n != 1 else ' has'} been turned into a <b>draft</b> notice "
        "for the Members page. Nothing is live yet.</p>",
        "<p><b>To approve:</b> open Webflow → CMS → <b>Member Notices</b>, check the draft (edit the "
        "wording if you like) and click <b>Publish</b>. <b>To reject:</b> delete the draft.</p>",
        f"<p><a href='{WEBFLOW_DESIGNER}'>Open Webflow</a></p><hr>",
    ]
    text = [subject, "", "To approve: Webflow → CMS → Member Notices → check the draft → Publish.",
            "To reject: delete the draft.", f"Webflow: {WEBFLOW_DESIGNER}", ""]
    for d in drafts:
        f = d["fieldData"]
        html.append(
            f"<p style='margin:0;color:#C41230;font-weight:600'>{escape(f['label'])}</p>"
            f"<h3 style='margin:.2em 0'>{escape(f['name'])}</h3>"
            f"<p>{escape(f['message'])}</p>"
            f"<p><a href='{escape(f['button-link'])}'>See the original Facebook post</a>"
            f"{' · has an image' if f.get('image') else ''}</p><hr>"
        )
        text += [f"[{f['label']}] {f['name']}", f["message"], f"Original post: {f['button-link']}", ""]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText("\n".join(text), "plain"))
    msg.attach(MIMEText("".join(html), "html"))
    _send(user, pw, to, msg)


def alert(subject: str, body: str) -> None:
    try:
        from ddac.notify import send_alert
        send_alert(subject, body)
    except Exception as e:  # never let the alert itself crash the run
        print(f"! Could not send alert: {e}")


# ---------------------------------------------------------------- main
def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Show what would be drafted; change nothing")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args()

    page_id, fb_token, wf_token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN"), env("WEBFLOW_TOKEN")
    missing = [n for n, v in (("FB_PAGE_ID", page_id), ("FB_PAGE_TOKEN", fb_token), ("WEBFLOW_TOKEN", wf_token)) if not v]
    if missing:
        print(f"! Missing secrets: {', '.join(missing)}")
        return 1

    state = load_state()
    seen: dict = state.setdefault("seen", {})
    first_run = not seen

    try:
        posts = fetch_posts(page_id, fb_token)
    except Exception as e:
        print(f"! {e}")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state.get("last_alert") != today and not args.dry_run:
            alert("Facebook → Members notices failed",
                  f"{e}\n\nIf this says the token expired or was invalid, a new page token is needed "
                  "(FB_PAGE_TOKEN secret).")
            state["last_alert"] = today
            save_state(state)
        return 1

    posts.sort(key=lambda p: p.get("created_time", ""))  # oldest first
    new = [p for p in posts if p["id"] not in seen]
    if first_run and new:
        for p in new[:-1]:
            seen[p["id"]] = "skipped-first-run"
        new = new[-1:]
        print(f"First run: marked {len(posts) - 1} older post(s) as seen; drafting only the newest.")

    print(f"Fetched {len(posts)} post(s); {len(new)} new.")
    drafts = []
    for p in new:
        fd = build_notice(p)
        if fd is None:
            print(f"- {p['id']}: no text, skipped")
            seen[p["id"]] = "no-text"
            continue
        if args.dry_run:
            print(json.dumps(fd, indent=1, ensure_ascii=False))
            continue
        try:
            item = create_draft(wf_token, fd)
        except Exception as e:
            print(f"! {p['id']}: {e}")
            continue  # not marked seen, so it is retried next run
        seen[p["id"]] = item.get("id", "drafted")
        drafts.append(item if "fieldData" in item else {"fieldData": fd})
        print(f"+ Drafted: {fd['name']}")

    if args.dry_run:
        return 0
    state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_state(state)
    if drafts and not args.no_email:
        email_drafts(drafts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
