"""MyRunResults (myrunresults.com).

The site is a JavaScript app. Results come from a JSON feed:
  POST https://api.myrunresults.com/api/PublicEvent/GetRunnersStatsAll
       body {"option": {"raceId": <event id>, "runnerClass": "<race tab, lowercase>"}}
Each event page lists its races as tabs (".event-results-tab__distance-name").
Headless Chromium opens the results list and each event page, reads the race
tabs, then calls the feed for every race from inside the page.

Run with DEBUG=1 to print per-race counts and save page HTML to debug/.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta

from ..browser import browser_page, dump
from ..models import Result
from ..tables import rows_to_results

BASE = "https://www.myrunresults.com"
LIST_URL = BASE + "/race-results"
EVENT_RE = re.compile(r"/events/([a-z0-9_\-]+)/(\d+)", re.I)
NAME = "myrunresults"


def _parse_date(s: str) -> str:
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return s.strip()


def _slug(name: str) -> str:
    """Fallback slug: lowercase, drop non-alphanumerics, spaces -> underscores."""
    s = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return re.sub(r"\s+", "_", s.strip())


def list_events(page, pages: int) -> list[dict]:
    events = []
    for n in range(pages):
        url = LIST_URL if n == 0 else f"{LIST_URL}?n={n}"
        page.goto(url, wait_until="networkidle")
        dump(page, f"mrr_list_{n}")
        rows = page.evaluate("""() => Array.from(document.querySelectorAll('table tr')).slice(1).map(tr => {
            const tds = Array.from(tr.querySelectorAll('td'));
            const a = tr.querySelector('a[href]');
            return {
              cells: tds.map(td => td.innerText.trim()),
              html: tr.outerHTML,
              href: a ? a.href : (tr.getAttribute('data-href') || tr.getAttribute('onclick') || '')
            };
        })""")
        for i, r in enumerate(rows):
            if len(r["cells"]) < 2:
                continue
            m = EVENT_RE.search(r["href"] or "") or EVENT_RE.search(r["html"])
            title = r["cells"][1].split("\n")[0].strip()
            ev = {"date": _parse_date(r["cells"][0]), "name": title,
                  "tags": r["cells"][1], "row_index": i, "list_page": n}
            if m:
                ev["slug"], ev["id"] = m.group(1), m.group(2)
            events.append(ev)
    # the same event can appear on more than one list page
    uniq = {}
    for ev in events:
        uniq.setdefault((ev["date"], ev["name"]), ev)
    return list(uniq.values())


def resolve_by_click(page, ev: dict) -> None:
    """Rows without a usable link: click the row and record where it navigates."""
    url = LIST_URL if ev["list_page"] == 0 else f"{LIST_URL}?n={ev['list_page']}"
    page.goto(url, wait_until="networkidle")
    rows = page.locator("table tr")
    try:
        with page.expect_navigation(timeout=15_000):
            rows.nth(ev["row_index"] + 1).click()
        m = EVENT_RE.search(page.url)
        if m:
            ev["slug"], ev["id"] = m.group(1), m.group(2)
    except Exception:
        pass


MRR_FIELDS = [  # (output header, JSON keys in order of preference)
    ("Place", ["runner_Place"]),
    ("First Name", ["runner_FirstName"]),
    ("Surname", ["runner_LastName"]),
    ("Club", ["runner_Club", "runner_Team"]),
    ("Chip Time", ["runner_NetTime", "runner_GrossTime"]),
    ("Age Cat", ["runner_SubCategory", "runner_Category"]),
    ("Cat Pos", ["runner_SubCatPlace", "runner_CatPlace"]),
    ("Race", ["runner_Class"]),
]


def _mrr_rows(items: list[dict]) -> tuple[list[str], list[list[str]]]:
    headers = [h for h, _ in MRR_FIELDS]
    rows = []
    for it in items:
        row = []
        for h, keys in MRR_FIELDS:
            v = next((str(it.get(k)).strip() for k in keys if str(it.get(k) or "").strip()), "")
            if h == "Chip Time" and str(it.get("runnerIsDnf") or "").lower() in ("true", "1"):
                v = "DNF"
            row.append(v)
        rows.append(row)
    return headers, rows


API = "https://api.myrunresults.com/api/PublicEvent/GetRunnersStatsAll"

FETCH_CLASS_JS = """async ([api, raceId, runnerClass]) => {
    const all = [];
    for (let skip = 0; skip < 20000; skip += 1000) {
        const r = await fetch(`${api}?toggle=1&skipCount=${skip}&maxResultCount=1000`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({option: {raceId: raceId, runnerClass: runnerClass}})});
        if (!r.ok) return {error: r.status, items: all};
        const j = await r.json();
        const items = (j.result && j.result.items) || j.items || [];
        all.push(...items);
        const total = (j.result && j.result.totalCount) || j.totalCount || 0;
        if (items.length === 0 || all.length >= total) break;
    }
    return {items: all};
}"""


def race_classes(page) -> list[str]:
    """Race/distance tab labels, e.g. ['10 MILE', '10KM', '5KM'] or ['GIRLS U9', ...]."""
    labels = page.evaluate("""() => Array.from(document.querySelectorAll(
        '.event-results-tab__distance-name')).map(e => e.innerText.trim()).filter(Boolean)""")
    return list(dict.fromkeys(labels))


def scrape_event(page, ev: dict) -> list[Result]:
    """Read every race in the event straight from the MyRunResults data feed."""
    url = f"{BASE}/events/{ev['slug']}/{ev['id']}/results"
    first_class: list[str] = []

    def on_req(req):
        if req.url.startswith(API) and req.post_data:
            try:
                first_class.append(json.loads(req.post_data)["option"]["runnerClass"])
            except Exception:
                pass

    page.on("request", on_req)
    page.goto(url, wait_until="networkidle")
    page.remove_listener("request", on_req)
    dump(page, f"mrr_event_{ev['id']}")
    base = {"source": NAME, "event_id": ev["id"], "event_name": ev["name"],
            "event_date": ev["date"], "url": url}

    # the site sends tab labels in lowercase ("10 MILE" -> "10 mile")
    classes = [c.lower() for c in race_classes(page)] or first_class
    classes = list(dict.fromkeys(classes))
    results: list[Result] = []
    counts = {}
    for rc in classes:
        res = page.evaluate(FETCH_CLASS_JS, [API, int(ev["id"]), rc])
        items = res.get("items", [])
        counts[rc] = len(items)
        if res.get("error"):
            print(f"    ! feed error {res['error']} for {rc!r}")
        h, rows = _mrr_rows(items)
        results += rows_to_results(h, rows, {**base, "race": ""})
    if os.environ.get("DEBUG") == "1":
        print(f"    races: {counts}")
    if not classes:
        print("    (no results published yet)")
    return list({r.key: r for r in results}.values())


def run(store, cfg: dict, since: str | None = None) -> list[Result]:
    st = store.source_state(NAME)
    events_state = st.setdefault("events", {})
    today = date.today()
    window = timedelta(days=cfg.get("recheck_days", 4))
    found: list[Result] = []
    with browser_page() as page:
        events = list_events(page, cfg.get("list_pages", 2))
        for ev in events:
            try:
                d = date.fromisoformat(ev["date"])
            except ValueError:
                continue
            cutoff = date.fromisoformat(since) if since else today - window
            if d < cutoff or d > today:
                continue
            # recent events every run; older ones in the window every 6 hours
            prev = events_state.get(ev.get("id", ""), {})
            if not since and prev.get("checked") and (today - d).days > 1:
                last = datetime.fromisoformat(prev["checked"])
                if datetime.now() - last < timedelta(hours=6):
                    continue
            if "id" not in ev:
                resolve_by_click(page, ev)
            if "id" not in ev:
                print(f"  ! could not find link for {ev['name']} ({ev['date']})")
                continue
            print(f"  checking {ev['date']} {ev['name']} [{ev['id']}]")
            try:
                res = scrape_event(page, ev)
            except Exception as e:
                print(f"  ! failed {ev['name']}: {e}")
                continue
            events_state[ev["id"]] = {"name": ev["name"], "date": ev["date"],
                                      "checked": datetime.now().isoformat(timespec="minutes"),
                                      "ddac": len(res)}
            found += res
            time.sleep(1)  # be polite
    return found
