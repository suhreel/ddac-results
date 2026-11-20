"""Commit this run's results on top of whatever is on GitHub now.

Two runs can finish close together (e.g. a backfill and a scheduled run);
a plain rebase then conflicts on data/results.json and the run's results are
lost. Instead: take the latest results from GitHub, add this run's results
on top (same result key -> this run's copy wins), rebuild the docs, and
commit that. Used by the workflow's "Commit results" step.
"""
from __future__ import annotations

import json
import subprocess
import sys

from ddac import ROOT, load_config

DATA = ["data/results.json", "data/state.json"]


def sh(*args, check=True) -> str:
    return subprocess.run(args, cwd=ROOT, check=check, capture_output=True, text=True).stdout


def remote_json(path: str) -> dict:
    out = subprocess.run(["git", "show", f"origin/main:{path}"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}


def main() -> int:
    sh("git", "fetch", "-q", "origin", "main")
    local = {p: json.loads((ROOT / p).read_text(encoding="utf-8")) for p in DATA}
    remote = {p: remote_json(p) for p in DATA}

    results = {**remote["data/results.json"], **local["data/results.json"]}
    state = remote["data/state.json"]
    for k, v in local["data/state.json"].items():  # per-source state: merge event maps
        if isinstance(v, dict) and isinstance(state.get(k), dict):
            merged = {**state[k], **v}
            for sub in ("events", "page_ids"):
                if isinstance(state[k].get(sub), dict) and isinstance(v.get(sub), dict):
                    merged[sub] = {**state[k][sub], **v[sub]}
            state[k] = merged
        else:
            state[k] = v

    # move onto GitHub's latest commit, keeping our working files
    sh("git", "reset", "-q", "--soft", "origin/main")
    (ROOT / DATA[0]).write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (ROOT / DATA[1]).write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")

    from ddac.athletes import write as write_athletes, write_csv
    from ddac.docs import write_months
    from ddac.store import Store
    rs = Store().all_results()
    write_months(rs, {r.event_date[:7] for r in rs})
    write_athletes(rs)
    write_csv(rs)

    out_dir = load_config()["output"]["results_dir"]
    sh("git", "add", "-A", *DATA, "data/athletes.json", "data/results.csv", "data/athletes.csv",
       out_dir, "docs/athletes.md")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("Nothing new to commit.")
        return 0
    from datetime import datetime, timezone
    sh("git", "commit", "-q", "-m", f"Results update {datetime.now(timezone.utc):%Y-%m-%d %H:%M}")
    for attempt in range(3):
        if subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=ROOT).returncode == 0:
            print(f"Pushed {len(results)} results.")
            return 0
        print("Push rejected (someone else pushed) — merging again.")
        sh("git", "reset", "-q", "--soft", "HEAD~1")
        return main()
    return 1


if __name__ == "__main__":
    sys.exit(main())
