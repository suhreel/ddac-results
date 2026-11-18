"""Members list: used to confirm 'ambiguous' club matches and to spot members
who left the club field blank. Only names are stored."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache

from . import ROOT, load_config


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = n.lower().replace("’", "'")
    n = re.sub(r"#\d+", " ", n)               # bib numbers e.g. "Barry MINNOCK #7643"
    n = re.sub(r"[^a-z' -]", " ", n)
    n = re.sub(r"\bo\s*'\s*", "o", n)         # O'Brien / O Brien -> obrien
    n = re.sub(r"\bmc\s+", "mc", n)
    n = n.replace("'", "").replace("-", " ")
    parts = n.split()
    # handle "SURNAME, First" ordering by sorting tokens
    return " ".join(sorted(parts))


@lru_cache(maxsize=1)
def load_members() -> set[str]:
    """Members come from the MEMBERS_JSON secret (so names never sit in the
    repo), or a local file when testing."""
    raw = os.environ.get("MEMBERS_JSON")
    if not raw:
        path = ROOT / load_config()["members"]["file"]
        if not path.exists():
            return set()
        raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return {norm_name(n) for n in data.get("names", [])}


def is_member(name: str) -> bool:
    members = load_members()
    return bool(members) and norm_name(name) in members
