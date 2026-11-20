"""RaceResult (my.raceresult.com) — also covers Pop Up Races, JustRuns Events
and Race Timing Ireland, which all publish through RaceResult.

Each event has a JSON API (no browser needed):
  GET https://my.raceresult.com/<id>/results/config?lang=en
      -> key, server, contests, TabConfig.Lists (the result lists)
  GET https://<server>/<id>/results/list?key=..&listname=..&contest=..&page=results&r=all&l=0
      -> DataFields (one expression per column) + data (rows, grouped by race,
         sometimes nested e.g. race -> gender)

Events are found three ways:
  1. RaceResult's own event list filtered to Ireland (country=372). This covers
     JustRuns and most Irish timers that list their events publicly.
  2. Pop Up Races' "finished" pages: each race page embeds RRPublish(<id>).
     Pop Up events are often unlisted, so they don't appear in (1).
  3. Race Timing Ireland's results page: links to race pages that embed RRPublish(<id>).
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urljoin

import requests

from ..models import Result
from ..tables import classify, tidy_name

NAME = "raceresult"
UA = ("Mozilla/5.0 (compatible; DDAC-results-bot/1.0; "
      "+https://ddac.ie; club results collection)")
RR = "https://my.raceresult.com"
RRPUBLISH_RE = re.compile(r"RRPublish\s*\([^,]+,\s*(\d{5,7})")
RRLINK_RE = re.compile(r"my\d*\.raceresult\.com/(\d{5,7})")

# event types to skip (RaceResult times lots of non-athletics sport)
SKIP_TYPES = re.compile(r"cycl|bike|cross\s*country\s*ski|ski|swim|motor|equestr|golf|rowing|"
                        r"kayak|canoe|e-?sport|sailing|horse|fitness|hyrox|deka", re.I)
# result lists we don't want when a better one exists for the same race
WEAK_LIST = re.compile(r"master|age ?group|team|top ?\d|club|split|award|prize|live", re.I)

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en"})


def _debug(msg: str):
    if os.environ.get("DEBUG") == "1":
        print("    " + msg)


def get(url: str, as_json: bool = False, tries: int = 2):
    last = None
    for i in range(tries):
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 200:
                return r.json() if as_json else r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # network blip
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def get_html(url: str) -> str:
    """Plain request first; fall back to the headless browser if the site blocks bots."""
    try:
        return get(url)
    except RuntimeError as e:
        if "HTTP 403" not in str(e) and "HTTP 503" not in str(e):
            raise
    from ..browser import browser_page
    with browser_page() as page:
        page.goto(url, wait_until="domcontentloaded")
        return page.content()


# ---------------------------------------------------------------- discovery

def ireland_events(date_from: date, date_to: date, countries=(372,)) -> list[dict]:
    """Events RaceResult lists publicly for Ireland in a date range."""
    out = []
    start = date_from
    while start <= date_to:  # month chunks so 'limit' never truncates
        end = min(start + timedelta(days=30), date_to)
        for c in countries:
            url = (f"{RR}/RREvents/list?country={c}&dateFrom={start}&dateTo={end}"
                   f"&modes=last,next&group=0&user=0&lang=en&limit=500")
            for grp in get(url, as_json=True) or []:
                for e in grp.get("Events", []):
                    if SKIP_TYPES.search(e.get("eventTypeName", "")) or SKIP_TYPES.search(e.get("name") or ""):
                        continue
                    out.append({"id": str(e["id"]), "name": (e.get("name") or "").strip(),
                                "date": e.get("dateFrom", ""), "via": "raceresult",
                                "location": e.get("location", "")})
        start = end + timedelta(days=1)
    return out


def event_info(ids: list[str]) -> dict[str, dict]:
    """Name/date for listed events by id (unlisted ones come back missing)."""
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ",".join(ids[i:i + 50])
        for grp in get(f"{RR}/RREvents/list?ids={chunk}&modes=&lang=en", as_json=True) or []:
            for e in grp.get("Events", []):
                out[str(e["id"])] = {"name": (e.get("name") or "").strip(), "date": e.get("dateFrom", "")}
    return out


def popupraces_events(pages: int, st: dict) -> list[dict]:
    """Pop Up Races finished list -> race page -> RaceResult id."""
    out = []
    for n in range(1, pages + 1):
        url = "https://www.popupraces.ie/race-status/finished/" + ("" if n == 1 else f"page/{n}/")
        out += parse_popupraces_list(get_html(url))
    uniq = {e["page"]: e for e in out}
    return list(uniq.values())


def parse_popupraces_list(html: str) -> list[dict]:
    """Each race is an <article>: <h1 class="entry-title"><a href=race page>Name</a></h1>
    and a date "DD-MM-YYYY" in the excerpt."""
    from bs4 import BeautifulSoup
    out = []
    for art in BeautifulSoup(html, "lxml").find_all("article"):
        a = art.select_one(".entry-title a[href]") or art.find("a", href=re.compile(r"/race/"))
        m = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", art.get_text(" "))
        if not a or not m or "/race/" not in a["href"]:
            continue
        dd, mm, yyyy = m.groups()
        out.append({"page": a["href"].split("#")[0], "name": a.get_text(" ", strip=True),
                    "date": f"{yyyy}-{mm}-{dd}", "via": "popupraces"})
    return out


def resolve_page_ids(events: list[dict], st: dict) -> None:
    """Find the RaceResult id embedded in each race page (cached in state)."""
    cache = st.setdefault("page_ids", {})
    for ev in events:
        if "id" in ev:
            continue
        if ev["page"] in cache:
            if cache[ev["page"]]:
                ev["id"] = cache[ev["page"]]
            continue
        try:
            html = get_html(ev["page"])
        except Exception as e:
            print(f"  ! couldn't open {ev['page']}: {e}")
            continue
        m = RRPUBLISH_RE.search(html) or RRLINK_RE.search(html)
        cache[ev["page"]] = m.group(1) if m else ""
        if m:
            ev["id"] = m.group(1)
        time.sleep(0.5)


def rti_events(urls: list[str], st: dict) -> list[dict]:
    """Race Timing Ireland results page(s): links to race pages on their own site."""
    from bs4 import BeautifulSoup
    out = []
    for url in urls:
        soup = BeautifulSoup(get_html(url), "lxml")
        for a in soup.find_all("a", href=True):
            name = a.get_text(" ", strip=True)
            if len(name) < 3:
                continue
            link = urljoin(url, a["href"]).split("#")[0]
            direct = RRLINK_RE.search(link)
            if direct:
                out.append({"id": direct.group(1), "name": name, "via": "racetimingireland"})
            elif re.match(r"https://(www\.)?racetimingireland\.com/[a-z0-9\-]+/?$", link, re.I) \
                    and not re.search(r"\.com/(results|events|about|cart|our-|chip-timing|timing-|new-|quote|home|"
                                      r"hyoxtimingireland)", link):
                out.append({"page": link, "name": name, "via": "racetimingireland"})
    uniq = {e.get("page") or e["id"]: e for e in out}
    return list(uniq.values())


# ---------------------------------------------------------------- results

def _col(fields: list[str], *patterns, exclude: str | None = None) -> int | None:
    for pat in patterns:
        for i, f in enumerate(fields):
            if re.search(pat, f, re.I) and not (exclude and re.search(exclude, f, re.I)):
                return i
    return None


def map_fields(fields: list[str]) -> dict[str, int]:
    """RaceResult column expressions -> our fields."""
    cols = {
        "athlete": _col(fields, r"^displayname$", r"^(fl|lf)?name$", r"displayname", r"fullname"),
        "first": _col(fields, r"^first ?name$", r"^firstname"),
        "last": _col(fields, r"^last ?name$", r"^lastname", r"^surname"),
        "club": _col(fields, r"^club$", r"^\[?club\]?$", r"\bclub\b", r"^team$", exclude=r"rank"),
        "place": _col(fields, r"^(auto|total|overall)?rank\d?(\.p)?$", r"withstatus\(\[?(total|overall)?rank",
                      r"rank", exclude=r"gender|agegroup|division|sex|ag\b|age"),
        "category": _col(fields, r"agegroup\d?\.name(short)?$", r"agegroup", r"^category", r"^ag$",
                         exclude=r"rank"),
        "cat_place": _col(fields, r"agegroup\w*rank", r"ag\w*rank"),
        "time": _col(fields, r"\.chip$", r"chiptime", r"\bchip\b", r"net", r"^finish$", r"\.gun$",
                     r"guntime", r"time", exclude=r"link|icon|img|video|picture"),
    }
    return {k: v for k, v in cols.items() if v is not None}


def _flatten(data, label: str = "") -> list[tuple[str, list]]:
    """data is {group: rows} or nested {group: {sub: rows}}; returns (race label, row)."""
    out = []
    if isinstance(data, list):
        return [(label, row) for row in data]
    for k, v in (data or {}).items():
        name = re.sub(r"^#\d+_", "", k).strip()
        out += _flatten(v, label or name)
    return out


def _clean_name(n: str) -> str:
    n = re.sub(r"\[.*?\]", "", n or "").strip()
    if "," in n:  # "Kelly, Natasha" -> "Natasha Kelly"
        last, first = [p.strip() for p in n.split(",", 1)]
        n = f"{first} {last}"
    return tidy_name(n)


def choose_lists(cfg: dict) -> list[dict]:
    lists = [l for l in cfg.get("TabConfig", {}).get("Lists", []) if l.get("Mode") != "hidden"]
    by_contest: dict[str, list[dict]] = {}
    for l in lists:
        by_contest.setdefault(str(l.get("Contest", "0")), []).append(l)
    chosen = []
    for contest, ls in by_contest.items():
        good = [l for l in ls if not WEAK_LIST.search(l["Name"])] or ls
        chosen.append(good[0])
    # a contest-0 list already covers every race
    if any(str(l.get("Contest")) == "0" for l in chosen) and len(chosen) > 1:
        chosen = [l for l in chosen if str(l.get("Contest")) != "0"]
    return chosen


def scrape_event(ev: dict) -> list[Result]:
    eid = ev["id"]
    try:
        cfg = get(f"{RR}/{eid}/results/config?lang=en", as_json=True, tries=1)
    except RuntimeError as e:
        if "HTTP 404" in str(e):   # event has no public results page (yet)
            return []
        raise
    if not isinstance(cfg, dict) or "key" not in cfg:
        return []
    server = cfg.get("server") or "my.raceresult.com"
    contests = cfg.get("contests", {})
    name = ev.get("name") or cfg.get("eventname", "")
    base = {"source": NAME, "event_id": eid, "event_name": name.strip(),
            "event_date": ev.get("date", ""), "url": f"{RR}/{eid}/results",
            "extra": {"via": ev.get("via", "raceresult")}}
    results: list[Result] = []
    for l in choose_lists(cfg):
        contest = str(l.get("Contest", "0"))
        url = (f"https://{server}/{eid}/results/list?key={cfg['key']}&listname={quote(l['Name'])}"
               f"&page=results&contest={contest}&r=all&l=0")
        try:
            j = get(url, as_json=True)
        except Exception as e:
            print(f"    ! list failed ({l['Name']}): {e}")
            continue
        fields = j.get("DataFields") or []
        cols = map_fields(fields)
        if "athlete" not in cols and "first" in cols and "last" in cols:
            cols["athlete"] = -1  # built from first + last below
        if "athlete" not in cols:
            _debug(f"no name column in {l['Name']}: {fields}")
            continue
        _debug(f"{l['Name']} contest {contest}: {cols}")
        for race, row in _flatten(j.get("data")):
            val = lambda f: str(row[cols[f]]).strip() if f in cols and cols[f] < len(row) else ""
            athlete = _clean_name(f"{val('first')} {val('last')}" if cols["athlete"] == -1 else val("athlete"))
            club = val("club") if "club" in cols else None
            raw = " | ".join(str(c) for c in row if not str(c).startswith("http"))
            m = classify(club, athlete, raw)
            if not m:
                continue
            race_label = contests.get(contest, "") if contest != "0" else ""
            results.append(Result(
                athlete=athlete, club_raw=club or "", time=val("time"),
                place=val("place").rstrip("."), category=val("category"),
                cat_place=val("cat_place").rstrip("."), raw=raw[:300], match=m,
                race=race_label or race, **base))
    return list({r.key: r for r in results}.values())


# ---------------------------------------------------------------- run

def run(store, cfg: dict, since: str | None = None) -> list[Result]:
    st = store.source_state(NAME)
    events_state = st.setdefault("events", {})
    today = date.today()
    window = timedelta(days=cfg.get("recheck_days", 4))
    start = date.fromisoformat(since) if since else today - window
    if cfg.get("until"):
        today = min(today, date.fromisoformat(cfg["until"]))

    events: list[dict] = []
    try:
        events += ireland_events(start, today, tuple(cfg.get("countries", [372])))
    except Exception as e:
        print(f"  ! RaceResult event list failed: {e}")
    if cfg.get("popupraces_pages"):
        pages = cfg["popupraces_pages"] if not since else max(cfg["popupraces_pages"], cfg.get("backfill_pages", 10))
        try:
            pur = popupraces_events(pages, st)
            pur = [e for e in pur if start.isoformat() <= e["date"] <= today.isoformat()]
            resolve_page_ids(pur, st)
            events += [e for e in pur if "id" in e]
        except Exception as e:
            print(f"  ! Pop Up Races list failed: {e}")
    if cfg.get("rti_pages"):
        try:
            rti = rti_events(cfg["rti_pages"], st)
            resolve_page_ids(rti, st)
            rti = [e for e in rti if "id" in e]
            info = event_info([e["id"] for e in rti])
            for e in rti:
                i = info.get(e["id"])
                if i:
                    e["date"], e["name"] = i["date"], i["name"] or e["name"]
            events += [e for e in rti if e.get("date") and start.isoformat() <= e["date"] <= today.isoformat()]
        except Exception as e:
            print(f"  ! Race Timing Ireland list failed: {e}")

    # same event found more than one way: keep the first (RaceResult listing has the best name/date)
    uniq: dict[str, dict] = {}
    for e in events:
        if not SKIP_TYPES.search(e.get("name", "")):
            uniq.setdefault(e["id"], e)
    print(f"  {len(uniq)} RaceResult events in range")

    found: list[Result] = []
    for ev in sorted(uniq.values(), key=lambda e: e.get("date", "")):
        d = ev.get("date", "")
        prev = events_state.get(ev["id"], {})
        # older events in the window: re-check every 6 hours, not every run
        if not since and prev.get("checked") and d and (today - date.fromisoformat(d)).days > 1:
            if datetime.now() - datetime.fromisoformat(prev["checked"]) < timedelta(hours=6):
                continue
        try:
            res = scrape_event(ev)
        except Exception as e:
            print(f"  ! failed {ev.get('name')} [{ev['id']}]: {e}")
            continue
        if res or os.environ.get("DEBUG") == "1":
            print(f"  {d} {ev.get('name')} [{ev['id']}, via {ev.get('via')}]: {len(res)} DDAC")
        events_state[ev["id"]] = {"name": ev.get("name", ""), "date": d, "via": ev.get("via"),
                                  "checked": datetime.now().isoformat(timespec="minutes"),
                                  "ddac": len(res)}
        found += res
        time.sleep(0.5)
    return found
