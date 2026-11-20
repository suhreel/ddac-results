"""Build the monthly results documents (Markdown) used for the newsletter
and the Sunday newspaper report. One file per month: docs/results/YYYY-MM.md.
Each race gets a short summary paragraph followed by DDAC results."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from . import ROOT, load_config
from .models import Result

FLAG = {"ambiguous": "⚠️ check club", "member-only": "⚠️ no club listed"}
SOURCE_LABEL = {"myrunresults": "MyRunResults", "dublin_graded": "Dublin Athletics (graded)",
                "raceresult": "RaceResult"}
VIA_LABEL = {"popupraces": "Pop Up Races", "racetimingireland": "Race Timing Ireland",
             "justruns": "JustRuns Events"}


def _secs(t: str) -> float:
    try:
        parts = [float(p) for p in re.split(r"[:]", t.strip())]
    except ValueError:
        return 1e9
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def fmt_time(t: str) -> str:
    """00:44:10 -> 44:10, 01:02:03 -> 1:02:03."""
    t = (t or "").strip()
    m = re.match(r"^0?0:(\d{2}:\d{2}(?:\.\d+)?)$", t)
    if m:
        return m.group(1).lstrip("0") if m.group(1).startswith("0") and len(m.group(1)) > 4 else m.group(1)
    m = re.match(r"^0(\d:\d{2}:\d{2}.*)$", t)
    return m.group(1) if m else t


def _place_num(p: str) -> int:
    m = re.match(r"\d+", p or "")
    return int(m.group(0)) if m else 10**6


def _nice_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%a %-d %b %Y")
    except ValueError:
        return iso


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def summary(event_name: str, event_date: str, rs: list[Result]) -> str:
    """Plain template summary (free). Phase 3 can swap this for an AI-written one."""
    athletes = sorted({r.athlete for r in rs})
    races = sorted({r.race for r in rs if r.race})
    n = len(athletes)
    when = _nice_date(event_date)
    track = rs[0].source == "dublin_graded"
    if track:
        s = (f"{n} DDAC athlete{'s' if n != 1 else ''} competed at {event_name} on {when}"
             f"{', across ' + ', '.join(races[:4]) + ('…' if len(races) > 4 else '') if races else ''}.")
        winners = [r for r in rs if _place_num(r.place) == 1]
        if winners:
            s += " Race wins for " + ", ".join(f"{w.athlete} ({w.race}, {fmt_time(w.time)})" for w in winners[:3]) + "."
        return s
    s = (f"{n} DDAC athlete{'s' if n != 1 else ''} took part in the {event_name} on {when}"
         f"{' (' + ', '.join(races) + ')' if races and len(races) > 1 else ''}.")
    by_race = defaultdict(list)
    for r in rs:
        by_race[r.race].append(r)
    bits = []
    for race, group in by_race.items():
        first = min(group, key=lambda r: (_place_num(r.place), _secs(r.time)))
        place = f", {_ordinal(_place_num(first.place))} overall" if _place_num(first.place) < 10**6 else ""
        label = f" in the {race}" if race and len(by_race) > 1 else ""
        bits.append(f"{first.athlete} was first DDAC finisher{label} in {fmt_time(first.time)}{place}")
    if bits:
        s += " " + "; ".join(bits) + "."
    return s


def build_month(results: list[Result], month: str) -> str:
    rs = [r for r in results if (r.event_date or "")[:7] == month]
    events = defaultdict(list)
    for r in rs:
        events[(r.event_date, r.event_name, r.source)].append(r)
    title = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    lines = [f"# DDAC Results — {title}", "",
             f"_Auto-generated {date.today().isoformat()}. {len(events)} events, {len(rs)} results._", ""]
    review = [r for r in rs if r.match != "confident"]
    if review:
        lines += ["> **Needs checking:** " + f"{len(review)} result(s) marked ⚠️ — club name unclear. "
                  "Confirm and add the spelling to `config.yaml` if it's DDAC.", ""]
    for (d, name, src), group in sorted(events.items(), key=lambda x: x[0][0], reverse=True):
        lines += [f"## {name}", f"**{_nice_date(d)}** · {VIA_LABEL.get((group[0].extra or {}).get('via'), SOURCE_LABEL.get(src, src))} · [results]({group[0].url})",
                  "", summary(name, d, group), ""]
        by_race = defaultdict(list)
        for r in group:
            by_race[r.race].append(r)
        for race, items in sorted(by_race.items()):
            if race and len(by_race) > 1:
                lines += [f"**{race}**", ""]
            lines += ["| Pos | Athlete | Cat | Time | |", "|---|---|---|---|---|"]
            for r in sorted(items, key=lambda r: (_place_num(r.place), _secs(r.time))):
                c = r.category if re.search(r"[A-Za-z0-9]", r.category or "") else ""
                cat = f"{c} ({r.cat_place})" if c and r.cat_place and r.cat_place != r.place else c
                lines.append(f"| {r.place} | {r.athlete} | {cat} | {fmt_time(r.time)} | {FLAG.get(r.match, '')} |")
            lines.append("")
    return "\n".join(lines)


def write_months(results: list[Result], months: set[str]) -> list[str]:
    out_dir = ROOT / load_config()["output"]["results_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for m in sorted(months):
        if not re.match(r"^\d{4}-\d{2}$", m):
            continue
        p = out_dir / f"{m}.md"
        p.write_text(build_month(results, m), encoding="utf-8")
        written.append(str(p.relative_to(ROOT)))
    return written
