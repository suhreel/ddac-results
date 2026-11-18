"""Turn results tables (HTML tables or fixed-width <pre> text) into DDAC Results."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .club_match import match_club, match_line
from .members import is_member
from .models import Result

HEADER_KEYS = {
    "place": ["place", "pos", "position", "overall", "rank", "pl"],
    "athlete": ["name", "athlete", "runner", "competitor"],
    "club": ["club", "team", "affiliation", "organisation", "organization"],
    "time": ["chip", "net", "time", "gross", "gun", "result", "mark", "perf", "performance"],
    "category": ["cat", "category", "age", "sub cat", "subcat", "age cat", "agegroup"],
    "cat_place": ["cat pos", "cat place", "catpos", "cat pl"],
    "bib": ["bib", "no", "number", "race no"],
}

TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\b|\b\d{1,3}\.\d{2}m?\b")


def _norm_header(h: str) -> str:
    """'chipTime' / 'chip_time' / 'Chip Time' -> 'chip time'."""
    h = re.sub(r"([a-z])([A-Z])", r"\1 \2", h or "")
    return re.sub(r"[_\-.]+", " ", h).strip().lower()


def map_headers(headers: list[str]) -> dict[str, int]:
    """Map logical field -> column index. Prefers chip/net time over gun time."""
    out: dict[str, int] = {}
    hs = [_norm_header(h) for h in headers]
    # split first/last name columns (JSON APIs)
    first = next((i for i, h in enumerate(hs) if h in ("first name", "firstname", "forename", "fname", "given name")), None)
    last = next((i for i, h in enumerate(hs) if h in ("last name", "lastname", "surname", "sname", "family name")), None)
    if first is not None and last is not None:
        out["first"], out["last"] = first, last
    race = next((i for i, h in enumerate(hs) if h in ("distance", "race", "race name", "race distance", "event")), None)
    if race is not None:
        out["race"] = race
    for field in ("cat_place", "place", "athlete", "club", "category", "bib"):
        for i, h in enumerate(hs):
            if i in out.values():
                continue
            if field == "athlete" and "first" in out:
                break
            if field == "club" and "id" in h.split():
                continue
            if field in ("place", "category") and h.split()[-1] == "id":
                continue
            if any(h == k or h.startswith(k + " ") or h.endswith(" " + k) for k in HEADER_KEYS[field]):
                out[field] = i
                break
    # prefer age-group column ("Sub Cat", "Age Cat") over plain M/F "Cat"
    for i, h in enumerate(hs):
        if ("sub" in h or "age" in h) and "cat" in h and i not in out.values():
            out["category"] = i
            break
    time_cols = [i for i, h in enumerate(hs) if any(k in h for k in HEADER_KEYS["time"])
                 and i not in out.values()]
    if time_cols:
        pref = [i for i in time_cols if "chip" in hs[i] or "net" in hs[i]]
        out["time"] = pref[0] if pref else time_cols[0]
    return out


def classify(club: str, athlete: str, raw_line: str = "") -> str | None:
    """Combine club match + members list."""
    m = match_club(club) if club is not None else match_line(raw_line)
    member = is_member(athlete) if athlete else False
    if m == "ambiguous" and member:
        return "confident"
    if m:
        return m
    if member and not (club or "").strip():
        return "member-only"   # member, club left blank -> flag for review
    return None


def rows_to_results(headers: list[str], rows: list[list[str]], base: dict,
                    links: list[str] | None = None) -> list[Result]:
    cols = map_headers(headers)
    out = []
    for idx, cells in enumerate(rows):
        if not any(c.strip() for c in cells):
            continue
        get = lambda f: cells[cols[f]].strip() if f in cols and cols[f] < len(cells) else ""
        if "first" in cols:
            athlete = f"{get('first')} {get('last')}".strip()
        else:
            athlete = re.sub(r"\s*#\d+\s*$", "", get("athlete"))
        if get("race"):
            base = {**base, "race": base.get("race") or get("race")}
        club = get("club") if "club" in cols else None
        raw = " | ".join(c.strip() for c in cells)
        m = classify(club, athlete, raw)
        if not m:
            continue
        time = get("time")
        if not time:
            t = TIME_RE.search(raw)
            time = t.group(0) if t else ""
        out.append(Result(
            athlete=athlete or raw[:60], club_raw=club or "", time=time,
            place=get("place"), category=get("category"), cat_place=get("cat_place"),
            raw=raw, match=m,
            url=(links[idx] if links and idx < len(links) and links[idx] else base.get("url", "")),
            **{k: v for k, v in base.items() if k != "url"},
        ))
    return out


def parse_html_tables(html: str) -> list[tuple[str, list[str], list[list[str]], list[str]]]:
    """Return (caption/heading, headers, rows, row_links) for every table."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t in soup.find_all("table"):
        heading = ""
        prev = t.find_previous(["h1", "h2", "h3", "h4", "caption", "b", "strong"])
        if t.caption:
            heading = t.caption.get_text(" ", strip=True)
        elif prev:
            heading = prev.get_text(" ", strip=True)
        trs = t.find_all("tr")
        if not trs:
            continue
        head_cells = trs[0].find_all(["th", "td"])
        headers = [c.get_text(" ", strip=True) for c in head_cells]
        rows, links = [], []
        for tr in trs[1:]:
            cells = tr.find_all(["td", "th"])
            rows.append([c.get_text(" ", strip=True) for c in cells])
            a = tr.find("a", href=True)
            links.append(a["href"] if a else "")
        out.append((heading, headers, rows, links))
    return out


def parse_pre_text(text: str, base: dict) -> list[Result]:
    """Fixed-width results (HyTek/Lynx style). Tracks event headings; matches lines."""
    out = []
    race = base.get("race", "")
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # event headings look like "Event 12  Women 800 Meter Run" or "Men 1500m B Race"
        if re.match(r"^(event\s+\d+|#?\d+\s+)?(men|women|boys|girls|mixed|u\d{2}|senior|master)", s, re.I) \
                and not TIME_RE.search(s):
            race = s
            continue
        m = classify(None, "", s)
        if not m:
            continue
        t = TIME_RE.findall(s)
        place = re.match(r"^(\d+)\b", s)
        name = re.sub(r"^\d+\s+(\d+\s+)?", "", s)
        name = re.split(r"\s{2,}", name)[0]
        out.append(Result(athlete=name, club_raw="", time=t[-1] if t else "",
                          place=place.group(1) if place else "", raw=s, match=m,
                          **{**base, "race": race}))
    return out
