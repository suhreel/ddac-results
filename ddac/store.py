"""JSON-backed store: results found so far + per-source state (what's been checked)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT, load_config
from .models import Result


class Store:
    def __init__(self):
        d = ROOT / load_config()["output"]["data_dir"]
        d.mkdir(parents=True, exist_ok=True)
        self.results_path = d / "results.json"
        self.state_path = d / "state.json"
        self.results: dict[str, dict] = self._load(self.results_path, {})
        self.state: dict = self._load(self.state_path, {})
        self.new_keys: list[str] = []
        self.updated_keys: list[str] = []

    @staticmethod
    def _load(p: Path, default):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return default

    def add(self, r: Result) -> str | None:
        """Add or update a result. Returns 'new', 'updated' or None (unchanged)."""
        d = r.to_dict()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        old = self.results.get(r.key)
        if old is None:
            d["first_seen"] = now
            self.results[r.key] = d
            self.new_keys.append(r.key)
            return "new"
        compare = ("time", "place", "club_raw", "category", "cat_place", "match")
        if any(old.get(k) != d.get(k) for k in compare):
            d["first_seen"] = old.get("first_seen", now)
            d["updated"] = now
            self.results[r.key] = d
            self.updated_keys.append(r.key)
            return "updated"
        return None

    def source_state(self, source: str) -> dict:
        return self.state.setdefault(source, {})

    def save(self):
        self.results_path.write_text(
            json.dumps(self.results, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        self.state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.state_path.write_text(json.dumps(self.state, indent=1, sort_keys=True), encoding="utf-8")

    def all_results(self) -> list[Result]:
        return [Result.from_dict(d) for d in self.results.values()]
