"""Email a digest of new/updated DDAC results (Gmail App Password via SMTP)."""
from __future__ import annotations

import os
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from .models import Result


def _creds():
    """Tolerate pasted secrets: trailing newlines, and spaces in the 16-char app password."""
    user = (os.environ.get("GMAIL_USER") or "").strip()
    pw = "".join((os.environ.get("GMAIL_APP_PASSWORD") or "").split())
    to = (os.environ.get("NOTIFY_TO") or "").strip() or user
    return user, pw, to


def _send(user: str, pw: str, to: str, msg) -> bool:
    recipients = [a.strip() for a in to.replace(";", ",").split(",") if a.strip()]
    for attempt in ("ssl", "starttls"):
        try:
            if attempt == "ssl":
                s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
            else:
                s = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
                s.starttls()
            with s:
                s.login(user, pw)
                s.sendmail(user, recipients, msg.as_string())
            print(f"Email sent to {', '.join(recipients)}")
            return True
        except smtplib.SMTPAuthenticationError as e:
            print(f"! Gmail rejected the login ({e.smtp_code}). Check GMAIL_USER and GMAIL_APP_PASSWORD.")
            return False
        except Exception as e:
            print(f"! Email via {attempt} failed: {type(e).__name__}: {e}")
    return False


def send_digest(new: list[Result], updated: list[Result], subject_prefix="DDAC results") -> bool:
    user, pw, to = _creds()
    if not (user and pw) or not (new or updated):
        return False
    print(f"Sending digest from {user[:3]}…@{user.split('@')[-1]} (password length {len(pw)})")
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
    return _send(user, pw, to, msg)


def send_alert(subject: str, body: str) -> None:
    user, pw, _ = _creds()
    if not (user and pw):
        print(f"ALERT (email not configured): {subject}\n{body}")
        return
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = f"[DDAC scraper] {subject}", user, user
    _send(user, pw, user, msg)
