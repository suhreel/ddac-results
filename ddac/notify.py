"""Email a digest of new/updated DDAC results (Gmail App Password via SMTP)."""
from __future__ import annotations

import os
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from .models import Result


def send_digest(new: list[Result], updated: list[Result], subject_prefix="DDAC results") -> bool:
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("NOTIFY_TO") or user
    if not (user and pw) or not (new or updated):
        return False
    events = defaultdict(list)
    for r in new + updated:
        events[(r.event_date, r.event_name)].append(r)
    names = ", ".join(sorted({n for _, n in events}))[:120]
    subject = f"{subject_prefix}: {len(new)} new" + (f", {len(updated)} updated" if updated else "") + f" — {names}"

    html = ["<h2>New DDAC results</h2>"]
    text = []
    for (d, name), rs in sorted(events.items(), reverse=True):
        html.append(f"<h3>{escape(name)} <small>({escape(d)})</small></h3><table border=1 cellpadding=4 "
                    "style='border-collapse:collapse'><tr><th>Pos</th><th>Athlete</th><th>Race</th>"
                    "<th>Time</th><th>Note</th></tr>")
        text.append(f"\n{name} ({d})")
        for r in rs:
            note = {"ambiguous": "check club", "member-only": "no club listed"}.get(r.match, "")
            if r in updated:
                note = (note + " updated").strip()
            html.append(f"<tr><td>{escape(r.place)}</td><td>{escape(r.athlete)}</td><td>{escape(r.race)}</td>"
                        f"<td>{escape(r.time)}</td><td>{note}</td></tr>")
            text.append(f"  {r.place:>4} {r.athlete:<28} {r.race:<12} {r.time} {note}")
        html.append(f"</table><p><a href='{escape(rs[0].url)}'>Full results</a></p>")

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText("\n".join(text), "plain"))
    msg.attach(MIMEText("".join(html), "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return True


def send_alert(subject: str, body: str) -> None:
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        print(f"ALERT (email not configured): {subject}\n{body}")
        return
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = f"[DDAC scraper] {subject}", user, user
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [user], msg.as_string())
