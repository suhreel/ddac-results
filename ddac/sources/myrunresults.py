"""MyRunResults (myrunresults.com).

The results list and results tables are JavaScript-driven: event rows are
clickable rather than plain links, and tables paginate client-side. So this
uses headless Chromium and works in layers, most reliable first:

  1. Capture any JSON the page loads (if results arrive via an API call).
  2. Otherwise read the rendered table, set the largest page size, and click
     through pagination and each race/distance tab.

Run with DEBUG=1 to save the HTML/screenshot of every page visited (in debug/).
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


def _json_rows(payloads: list) -> tuple[list[str], list[list[str]]] | None:
    """Find a list of result-like dicts in captured JSON."""
    def walk(o):
        if isinstance(o, list) and o and isinstance(o[0], dict):
            keys = {k.lower() for k in o[0]}
            if any("club" in k or "team" in k for k in keys) and any("name" in k for k in keys):
                return o
        if isinstance(o, dict):
            for v in o.values():
                r = walk(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = walk(v)
                if r:
                    return r
        return None
    for p in payloads:
        rows = walk(p)
        if rows:
            headers = list(rows[0].keys())
            return headers, [[str(r.get(h, "") or "") for h in headers] for r in rows]
    return None


def _read_table(page) -> tuple[list[str], list[list[str]], list[str]]:
    data = page.evaluate("""() => {
        const t = Array.from(document.querySelectorAll('table'))
          .sort((a,b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
        if (!t) return {headers: [], rows: [], links: []};
        const headers = Array.from(t.querySelectorAll('thead th, tr:first-child th'))
          .map(th => th.innerText.replace(/[⬆⬇▲▼]/g,'').trim());
        const trs = Array.from(t.querySelectorAll('tbody tr'));
        return {
          headers,
          rows: trs.map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())),
          links: trs.map(tr => { const a = tr.querySelector('a[href]'); return a ? a.href : ''; })
        };
    }""")
    return data["headers"], data["rows"], data["links"]


def _set_max_page_size(page) -> None:
    for sel in ["select[name$='_length']", "select.page-size", "select"]:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 5)):
            try:
                opts = loc.nth(i).locator("option").all_inner_texts()
                nums = [o for o in opts if o.strip().isdigit()]
                if nums:
                    loc.nth(i).select_option(label=max(nums, key=int))
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                continue
    # link-style page size controls ("10 20 50 100")
    for label in ("100", "50"):
        loc = page.get_by_text(label, exact=True)
        if loc.count():
            try:
                loc.first.click()
                page.wait_for_timeout(1500)
                return
            except Exception:
                pass


def _click_next(page) -> bool:
    for sel in ["a:has-text('Next'):not(.disabled)", "button:has-text('Next'):not([disabled])",
                "li:not(.disabled) > a:has-text('Next')", ".paginate_button.next:not(.disabled)"]:
        loc = page.locator(sel)
        if loc.count():
            el = loc.first
            cls = (el.get_attribute("class") or "") + (el.evaluate("e => e.parentElement.className") or "")
            if "disabled" in cls:
                return False
            before = page.evaluate("() => document.querySelector('tbody') ? document.querySelector('tbody').innerText.slice(0,200) : ''")
            el.click()
            page.wait_for_timeout(1200)
            after = page.evaluate("() => document.querySelector('tbody') ? document.querySelector('tbody').innerText.slice(0,200) : ''")
            return after != before
    return False


def _race_tabs(page, tags: str) -> list[str]:
    """Distance/race tabs, e.g. '10k', '5k'. Uses the distances listed for the event
    plus anything that looks like a tab."""
    texts = page.evaluate("""() => Array.from(document.querySelectorAll(
        '[role=tab], .nav-tabs a, .nav-pills a, .tabs a, .race-tabs a, ul.nav a, button.tab'))
        .map(e => e.innerText.trim()).filter(t => t && t.length < 40)""")
    dist = re.compile(r"^\s*\d+(\.\d+)?\s*(k|km|mile|miles|m)\b|marathon|half|relay|fun run|kids|junior|walk", re.I)
    tabs = [t for t in texts if dist.search(t)]
    return list(dict.fromkeys(tabs))


def scrape_event(page, ev: dict) -> list[Result]:
    url = f"{BASE}/events/{ev['slug']}/{ev['id']}/results"
    payloads: list = []

    def on_resp(resp):
        if "json" in (resp.headers.get("content-type") or ""):
            try:
                payloads.append(resp.json())
            except Exception:
                pass

    page.on("response", on_resp)
    page.goto(url, wait_until="networkidle")
    dump(page, f"mrr_event_{ev['id']}")
    base = {"source": NAME, "event_id": ev["id"], "event_name": ev["name"],
            "event_date": ev["date"], "url": url}
    results: list[Result] = []

    tabs = _race_tabs(page, ev.get("tags", "")) or [""]
    for tab in tabs:
        if tab:
            try:
                page.get_by_text(tab, exact=True).first.click()
                page.wait_for_timeout(1500)
            except Exception:
                continue
        payloads.clear()
        _set_max_page_size(page)
        j = _json_rows(payloads)
        if j and os.environ.get("DEBUG") == "1":
            print(f"    JSON headers: {j[0]}")
            print(f"    JSON row 1:   {j[1][0] if j[1] else ''}")
        if j:
            results += rows_to_results(j[0], j[1], {**base, "race": tab})
            continue
        seen = set()
        for _ in range(200):  # page cap
            headers, rows, links = _read_table(page)
            sig = json.dumps(rows[:3])
            if sig in seen:
                break
            seen.add(sig)
            results += rows_to_results(headers, rows, {**base, "race": tab}, links)
            if not _click_next(page):
                break
    page.remove_listener("response", on_resp)
    # de-duplicate (tabs sometimes show the same table)
    uniq = {r.key: r for r in results}
    return list(uniq.values())


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
