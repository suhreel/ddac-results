"""Athlete database, rebuilt from the stored results on every run.

  data/athletes.json   one record per DDAC athlete: every result, plus highlights
  docs/athletes.md     readable index

Results flagged "ambiguous" (club said "Drogheda" without "District" and the
athlete isn't on the members list) are left out until confirmed, so people
from other Drogheda clubs don't end up in DDAC's records.

Each result carries a `series` key (the event name with years and edition
numbers removed) so the same race can be compared year on year, e.g.
"Annagassan 10km 2025" and "Annagassan 10km 2026" -> "annagassan 10km".
Nothing here claims a PB: times are only ever compared within the same series.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date

from . import ROOT, load_config
from .members import norm_name
from .models import Result


def series_key(event_name: str) -> str:
    n = (event_name or "").lower()
    n = re.sub(r"\b(19|20)\d{2}\b", " ", n)                    # years
    n = re.sub(r"\b\d+(st|nd|rd|th)\b", " ", n)                 # "10th annual"
    n = re.sub(r"\b(annual|edition)\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _num(p: str) -> int | None:
    m = re.match(r"\d+", (p or "").strip())
    return int(m.group(0)) if m else None


def highlights(r: Result) -> list[str]:
    out = []
    p, cp = _num(r.place), _num(r.cat_place)
    if p and p <= 3:
        where = f"in {r.race}" if r.source == "dublin_graded" else "overall"  # track: place within that race
        out.append(f"{ {1: '1st', 2: '2nd', 3: '3rd'}[p]} {where}")
    cat = r.category if re.search(r"[A-Za-z0-9]", r.category or "") else ""
    if cp and cp <= 3 and cat and cp != p:
        out.append(f"{ {1: '1st', 2: '2nd', 3: '3rd'}[cp]} {cat}")
    return out


def build(results: list[Result]) -> dict:
    people: dict[str, dict] = {}
    names: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        if r.match == "ambiguous" or not r.athlete:
            continue
        k = norm_name(r.athlete)
        if not k:
            continue
        names[k][r.athlete] += 1
        p = people.setdefault(k, {"results": []})
        p["results"].append({
            "date": r.event_date, "event": r.event_name, "series": series_key(r.event_name),
            "race": r.race, "time": r.time, "place": r.place, "category": r.category,
            "cat_place": r.cat_place, "source": r.source, "url": r.url,
            "highlights": highlights(r),
        })
    for k, p in people.items():
        p["name"] = names[k].most_common(1)[0][0]
        rs = sorted(p["results"], key=lambda x: x["date"], reverse=True)
        p["results"] = rs
        p["races"] = len(rs)
        p["first_seen"] = rs[-1]["date"]
        p["latest"] = rs[0]["date"]
        p["highlights"] = [f"{h} — {x['event']} ({x['date']})" for x in rs for h in x["highlights"]]
    return dict(sorted(people.items(), key=lambda kv: kv[1]["name"].lower()))


def previous_editions(athlete: dict, series: str, before: str) -> list[dict]:
    """The athlete's results at earlier editions of the same race (newest first).
    Used for like-for-like year-on-year comparisons only."""
    return [x for x in athlete["results"] if x["series"] == series and x["date"] < before]


def write(results: list[Result]) -> list[str]:
    cfg = load_config()["output"]
    db = build(results)
    jpath = ROOT / cfg["data_dir"] / "athletes.json"
    jpath.write_text(json.dumps(db, indent=1, ensure_ascii=False), encoding="utf-8")

    lines = ["# DDAC Athletes", "",
             f"_Auto-generated {date.today().isoformat()} from the results database. "
             f"{len(db)} athletes. Highlights are podium and category podium finishes "
             "taken straight from official results; nothing here is a PB claim._", "",
             "| Athlete | Races | First seen | Latest | Highlights |", "|---|---|---|---|---|"]
    for p in db.values():
        hl = "; ".join(p["highlights"][:3]) + (" …" if len(p["highlights"]) > 3 else "")
        lines.append(f"| {p['name']} | {p['races']} | {p['first_seen']} | {p['latest']} | {hl} |")
    mpath = ROOT / "docs" / "athletes.md"
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [str(jpath.relative_to(ROOT)), str(mpath.relative_to(ROOT))]


def write_csv(results: list[Result]) -> list[str]:
    """Flat CSV copies for Google Sheets (=IMPORTDATA on the raw GitHub URL)."""
    import csv
    d = ROOT / load_config()["output"]["data_dir"]
    rpath, apath = d / "results.csv", d / "athletes.csv"
    rows = sorted(results, key=lambda r: (r.event_date, r.event_name, r.race), reverse=True)
    with open(rpath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Event", "Race", "Athlete", "Time", "Place", "Category", "Cat place",
                    "Club as listed", "Check", "Source", "Results link"])
        for r in rows:
            w.writerow([r.event_date, r.event_name, r.race, r.athlete, r.time, r.place, r.category,
                        r.cat_place, r.club_raw, "" if r.match == "confident" else r.match,
                        (r.extra or {}).get("via") or r.source, r.url])
    with open(apath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Athlete", "Races", "First seen", "Latest", "Highlights"])
        for p in build(results).values():
            w.writerow([p["name"], p["races"], p["first_seen"], p["latest"], "; ".join(p["highlights"])])
    return [str(rpath.relative_to(ROOT)), str(apath.relative_to(ROOT))]
