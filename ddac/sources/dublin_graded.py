"""Dublin Athletics graded track meets.

One results site per meet, at a predictable address:
  http://pastresults.dublinathletics.com/graded26-7/menu.html
The pages are built by Timetronics meet software: the menu lists every race
with an onclick of createTable('<id>'), and createTable() loads <id>_list.xml
and draws the result tables. Headless Chromium opens the menu, calls
createTable() for each race and reads the rendered tables.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

from ..browser import browser_page
from ..models import Result
from ..tables import parse_html_tables, rows_to_results

NAME = "dublin_graded"
UA = {"User-Agent": "DDAC-results-bot/1.0 (+https://ddac.ie)"}


def _get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code == 200 and r.text.strip():
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
    except requests.RequestException:
        pass
    return None


def meet_info(menu_xml: str) -> tuple[str, str]:
    """Meet name and ISO date from menu.xml (<name>, <startdate>dd-mm-yyyy)."""
    soup = BeautifulSoup(menu_xml, "xml")
    comp = soup.find("competition")
    name = comp.find("name").get_text(strip=True) if comp and comp.find("name") else ""
    d = comp.find("startdate").get_text(strip=True) if comp and comp.find("startdate") else ""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", d)
    iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
    # the meet software sometimes keeps last year's date; prefer a scheduled race date
    sess = soup.find("datescheduled") or soup.find("date")
    if sess and re.match(r"\d{4}-\d{2}-\d{2}", sess.get_text(strip=True)):
        iso = sess.get_text(strip=True)
    return name, iso


def parse_rendered(html: str, base: dict) -> list[Result]:
    out: list[Result] = []
    for heading, headers, rows, links in parse_html_tables(html):
        if len(rows) < 1 or len(headers) < 3:
            continue
        out += rows_to_results(headers, rows, {**base, "race": base.get("race") or heading})
    return out


def scrape_meet(meet: str, menu_url: str, menu_xml: str) -> list[Result]:
    name, mdate = meet_info(menu_xml)
    base = {"source": NAME, "event_id": meet, "event_name": name or f"Dublin Graded {meet}",
            "event_date": mdate, "url": menu_url}
    debug = os.environ.get("DEBUG") == "1"
    results: list[Result] = []
    with browser_page() as page:
        page.goto(menu_url, wait_until="networkidle")
        page.wait_for_timeout(1500)
        races = page.evaluate("""() => Array.from(document.querySelectorAll('a[onclick*="createTable("]'))
            .map(a => [a.innerText.trim(), (a.getAttribute('onclick').match(/createTable\\('([^']+)'/) || [])[1]])
            .filter(x => x[1])""")
        races = list(dict.fromkeys(tuple(r) for r in races))
        if debug:
            print(f"    {meet}: {name!r} {mdate} — {len(races)} races")
        for i, (race_name, rid) in enumerate(races):
            try:
                page.evaluate(f"createTable('{rid}')")
                page.wait_for_timeout(700)
                html = page.content()
            except Exception as e:
                print(f"    ! {race_name}: {e}")
                continue
            res = parse_rendered(html, {**base, "race": race_name})
            if debug and i == 0:
                for h, hdr, rows, _ in parse_html_tables(html)[:4]:
                    print(f"    sample table {h!r}: headers={hdr} rows={rows[:2]}")
            results += res
    return list({r.key: r for r in results}.values())


def run(store, cfg: dict, since: str | None = None) -> list[Result]:
    st = store.source_state(NAME)
    meets = st.setdefault("meets", {})
    yy = date.today().strftime("%y")
    debug = os.environ.get("DEBUG") == "1"
    found: list[Result] = []
    for n in range(1, cfg.get("max_meets", 12) + 1):
        meet = f"graded{yy}-{n}"
        prev = meets.get(meet, {})
        if prev.get("done") and not debug and not since:
            continue
        folder = f"{cfg['base_url']}/{meet}"
        menu_xml = _get(f"{folder}/menu.xml")
        if not menu_xml:
            continue
        # menu.xml changes whenever results are added or corrected
        h = hashlib.sha1(menu_xml.encode()).hexdigest()
        first = prev.get("first_seen", date.today().isoformat())
        if prev.get("hash") == h and not debug and not since:
            if (date.today() - date.fromisoformat(first)).days > cfg.get("recheck_days", 3):
                meets[meet]["done"] = True
            continue
        print(f"  checking {meet}")
        res = scrape_meet(meet, f"{folder}/menu.html", menu_xml)
        meets[meet] = {"hash": h, "first_seen": first, "ddac": len(res)}
        found += res
    return found
