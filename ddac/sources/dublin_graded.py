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
from ..tables import parse_html_tables, rows_to_results, tidy_name

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


def _flip(name: str) -> str:
    """'DEL BELLO, Caoimhe' -> 'Caoimhe DEL BELLO'."""
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name


def parse_rendered(html: str, base: dict) -> list[Result]:
    out: list[Result] = []
    for heading, headers, rows, links in parse_html_tables(html):
        low = [h.strip().lower() for h in headers]
        # results tables have Place + Result; start lists don't
        if "result" not in low or not any(h in ("place", "rank") for h in low):
            continue
        if "team" in low:  # Timetronics fills Team with 'undefined'/blank; Club is the real one
            i = low.index("team")
            headers = headers[:i] + headers[i + 1:]
            rows = [r[:i] + r[i + 1:] for r in rows]
        ni = next((i for i, h in enumerate(headers) if h.strip().lower() == "name"), None)
        if ni is not None:
            rows = [r[:ni] + [_flip(r[ni])] + r[ni + 1:] if len(r) > ni else r for r in rows]
        race = base.get("race") or heading
        out += rows_to_results(headers, rows, {**base, "race": race})
    for r in out:
        r.athlete = tidy_name(r.athlete)
        r.race = re.sub(r"\s+", " ", r.race).strip()
    return [r for r in out if r.time.upper() not in ("DNS", "DQ*")]


def race_date(folder: str, rid: str) -> str:
    """Real race date from <id>_version.xml timestamp (the meet header date is often stale)."""
    xml = _get(f"{folder}/{rid}_version.xml") or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", xml)
    if m:
        return m.group(0)
    m = re.search(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", xml)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def fix_date(d: str, season: str, newly_seen: bool) -> str:
    """The meet software often carries an old year. A meet appearing now, in season,
    is dated today; otherwise keep month/day and use the season's year."""
    today = date.today()
    if d[:4] == season:
        return d
    if newly_seen and 4 <= today.month <= 9:
        return today.isoformat()
    return f"{season}{d[4:]}" if re.match(r"\d{4}-\d{2}-\d{2}", d) else today.isoformat()


def scrape_meet(meet: str, menu_url: str, menu_xml: str, newly_seen: bool = False) -> list[Result]:
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
        folder = menu_url.rsplit("/", 1)[0]
        for _, rid in races[:3]:
            d = race_date(folder, rid)
            if d:
                base["event_date"] = mdate = d
                break
        mdate = base["event_date"] = fix_date(mdate, "20" + meet[6:8], newly_seen)
        if debug:
            print(f"    {meet}: {name!r} {mdate} — {len(races)} races")
        for i, (race_name, rid) in enumerate(races):
            try:
                page.evaluate(f"createTable('{rid}')")
                page.wait_for_timeout(700)
                html = page.content()
            except Exception:
                continue  # race with no data yet
            res = parse_rendered(html, {**base, "race": race_name})
            if debug and res:
                print(f"    {race_name}: " + "; ".join(f"{r.athlete} {r.time} ({r.club_raw})" for r in res))
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
        if any(v.get("hash") == h for k, v in meets.items() if k != meet):
            meets[meet] = {"hash": h, "first_seen": first, "duplicate": True}
            continue  # folder holds a copy of another meet
        print(f"  checking {meet}")
        res = scrape_meet(meet, f"{folder}/menu.html", menu_xml, newly_seen=not prev)
        meets[meet] = {"hash": h, "first_seen": first, "ddac": len(res)}
        found += res
    return found
