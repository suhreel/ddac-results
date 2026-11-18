"""Dublin Athletics graded track meets.

Results are published as static pages at a predictable address per meet:
  http://pastresults.dublinathletics.com/graded26-7/menu.html
The menu links to one page per event. Pages may be HTML tables or fixed-width
<pre> text (meet-management software output), so both are handled.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..browser import DEBUG_DIR
from ..models import Result
from ..tables import parse_html_tables, parse_pre_text, rows_to_results

NAME = "dublin_graded"
UA = {"User-Agent": "DDAC-results-bot/1.0 (+https://ddac.ie)"}
DATE_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[ /.-]([A-Za-z]{3,9}|\d{1,2})[ /.-](\d{2,4})\b")


def _get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code == 200 and r.text.strip():
            r.encoding = r.apparent_encoding or r.encoding
            if os.environ.get("DEBUG") == "1":
                DEBUG_DIR.mkdir(exist_ok=True)
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("://", 1)[-1])[-100:]
                (DEBUG_DIR / f"dg_{name}.html").write_text(r.text, encoding="utf-8")
            return r.text
    except requests.RequestException:
        pass
    return None


def _find_date(text: str) -> str:
    m = DATE_RE.search(text)
    if not m:
        return ""
    d, mo, y = m.groups()
    y = int(y) + 2000 if len(y) == 2 else int(y)
    for fmt in ("%d %b %Y", "%d %B %Y", "%d %m %Y"):
        try:
            return datetime.strptime(f"{d} {mo} {y}", fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _probe(menu_url: str) -> None:
    """Debug: render a Timetronics menu in the browser and print its structure."""
    from ..browser import browser_page
    folder = menu_url.rsplit("/", 1)[0]
    for js in ("inc/settings.js", "inc/createMenu.js"):
        txt = _get(f"{folder}/{js}") or ""
        print(f"    {js} ({len(txt)} chars): {txt[:1200]!r}")
    with browser_page() as page:
        reqs = []
        page.on("request", lambda r: reqs.append(r.url))
        page.goto(menu_url, wait_until="networkidle")
        page.wait_for_timeout(2000)
        info = page.evaluate("""() => ({
            anchors: Array.from(document.querySelectorAll('a')).slice(0, 40).map(a =>
                [a.innerText.trim().slice(0, 40), a.getAttribute('href'), a.getAttribute('onclick')]),
            tables: document.querySelectorAll('table').length,
            text: document.body.innerText.slice(0, 800)
        })""")
        print(f"    rendered anchors: {info['anchors']}")
        print(f"    tables={info['tables']} text={info['text']!r}")
        print(f"    requests: {[u for u in reqs if not u.endswith(('.css', '.png', '.gif', '.jpg'))][:40]}")


def parse_page(html: str, base: dict) -> list[Result]:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "") or base.get("race", "")
    out: list[Result] = []
    tables = parse_html_tables(html)
    for heading, headers, rows, links in tables:
        out += rows_to_results(headers, rows, {**base, "race": heading or title})
    for pre in soup.find_all("pre"):
        out += parse_pre_text(pre.get_text("\n"), {**base, "race": title})
    if not tables and not soup.find("pre"):
        # plain text page
        out += parse_pre_text(soup.get_text("\n"), {**base, "race": title})
    return out


def scrape_meet(meet: str, menu_url: str, menu_html: str) -> tuple[list[Result], str, str]:
    soup = BeautifulSoup(menu_html, "lxml")
    meet_name = soup.title.get_text(strip=True) if soup.title else f"Dublin Graded {meet}"
    meet_date = _find_date(soup.get_text(" "))
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(menu_url, a["href"])
        if href.startswith(menu_url.rsplit("/", 1)[0]) and href != menu_url and not href.endswith((".pdf", ".zip")):
            links.append((a.get_text(" ", strip=True), href))
    links = list(dict.fromkeys(links))
    if os.environ.get("DEBUG") == "1" and meet.endswith("-1"):
        _probe(menu_url)
    base = {"source": NAME, "event_id": meet, "event_name": meet_name, "event_date": meet_date}
    results: list[Result] = []
    # results might also be on the menu page itself
    results += parse_page(menu_html, {**base, "race": meet_name, "url": menu_url})
    for i, (text, href) in enumerate(links):
        html = _get(href)
        if html:
            results += parse_page(html, {**base, "race": text, "url": href})
    return list({r.key: r for r in results}.values()), meet_name, meet_date


def run(store, cfg: dict, since: str | None = None) -> list[Result]:
    st = store.source_state(NAME)
    meets = st.setdefault("meets", {})
    yy = date.today().strftime("%y")
    found: list[Result] = []
    for n in range(1, cfg.get("max_meets", 12) + 1):
        meet = f"graded{yy}-{n}"
        prev = meets.get(meet, {})
        if prev.get("done") and os.environ.get("DEBUG") != "1":
            continue
        url = f"{cfg['base_url']}/{meet}/menu.html"
        html = _get(url)
        if not html:
            continue
        # follow page hashes so unchanged meets aren't re-parsed
        h = hashlib.sha1(html.encode()).hexdigest()
        first = prev.get("first_seen", date.today().isoformat())
        if prev.get("hash") == h and prev.get("parsed") and os.environ.get("DEBUG") != "1":
            age = (date.today() - date.fromisoformat(first)).days
            if age > cfg.get("recheck_days", 3):
                meets[meet]["done"] = True
            continue
        print(f"  checking {meet}")
        res, name, mdate = scrape_meet(meet, url, html)
        for r in res:
            if not r.event_date:
                r.event_date = mdate or first
        meets[meet] = {"hash": h, "parsed": True, "first_seen": first, "name": name,
                       "date": mdate, "ddac": len(res)}
        found += res
    return found
