"""Run the DDAC results scrapers.

  python run.py                                  # all enabled sources
  python run.py --sources myrunresults           # one source
  python run.py --since 2026-10-01 --no-email    # backfill without emailing
  DEBUG=1 python run.py --sources myrunresults   # save page HTML to debug/
"""
from __future__ import annotations

import argparse
import sys
import traceback

from ddac import load_config
from ddac.docs import write_months
from ddac.notify import send_alert, send_digest
from ddac.sources import SOURCES
from ddac.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="", help="comma-separated; default = all enabled")
    ap.add_argument("--since", help="backfill events on/after this date (YYYY-MM-DD)")
    ap.add_argument("--until", help="with --since: stop at this date (RaceResult backfill in chunks)")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="don't save anything")
    ap.add_argument("--reset", action="store_true", help="forget all stored results and rebuild the docs")
    args = ap.parse_args()

    cfg = load_config()
    wanted = [s for s in args.sources.split(",") if s] or \
             [n for n, c in cfg["sources"].items() if c.get("enabled")]
    store = Store()
    if args.reset:
        store.results, store.state = {}, {}
    failures = []
    for name in wanted:
        if name not in SOURCES:
            print(f"Unknown source {name}")
            continue
        print(f"== {name}")
        try:
            results = SOURCES[name].run(store, {**cfg["sources"][name], "until": args.until}, since=args.since)
        except Exception:
            failures.append(name)
            traceback.print_exc()
            continue
        counts = {"new": 0, "updated": 0}
        for r in results:
            s = store.add(r)
            if s:
                counts[s] += 1
        print(f"   {len(results)} DDAC results ({counts['new']} new, {counts['updated']} updated)")

    new = [store.results[k] for k in store.new_keys]
    upd = [store.results[k] for k in store.updated_keys]
    if args.dry_run:
        print("Dry run — nothing saved.")
        for d in new + upd:
            print(f"  {d['event_date']} {d['event_name']} | {d['athlete']} | {d['time']} | {d['match']}")
        return 0

    store.save()
    months = {d["event_date"][:7] for d in new + upd}
    if args.reset:
        from ddac import ROOT
        for f in (ROOT / cfg["output"]["results_dir"]).glob("*.md"):
            f.unlink()
        months = {d["event_date"][:7] for d in store.results.values()}
    if months:
        print("Updated docs:", ", ".join(write_months(store.all_results(), months)))
    from ddac.athletes import write as write_athletes, write_csv
    print("Athletes:", ", ".join(write_athletes(store.all_results()) + write_csv(store.all_results())))
    if not args.no_email:
        from ddac.models import Result
        send_digest([Result.from_dict(d) for d in new], [Result.from_dict(d) for d in upd])
    if failures and not args.no_email:
        # at most one error email per day
        from datetime import date
        if store.state.get("last_alert") != date.today().isoformat():
            send_alert("Scraper error", f"These sources failed: {', '.join(failures)}. See the GitHub Actions log.")
            store.state["last_alert"] = date.today().isoformat()
            store.save()
    return 1 if failures and len(failures) == len(wanted) else 0


if __name__ == "__main__":
    sys.exit(main())
