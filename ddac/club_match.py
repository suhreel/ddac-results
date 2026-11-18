"""Decide whether a club name (or a raw results line) belongs to DDAC.

Returns one of:
  "confident"  - definitely DDAC (incl. common typos)
  "ambiguous"  - says Drogheda but not District; include and flag for review
  None         - not DDAC
"""
from __future__ import annotations

import re
from functools import lru_cache

from rapidfuzz import fuzz

from . import load_config

TARGET = "drogheda district ac"


def normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("&", " ").replace("’", "'")
    t = re.sub(r"\ba\.?\s?c\.?(?=\s|$)", " ac ", t)          # A.C. / A C / ac. -> ac
    t = re.sub(r"\bathletics? club\b", " ac ", t)
    t = re.sub(r"\bathletic(s)?\b", " athletic ", t)
    t = re.sub(r"\bst\.?\s", "st ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\band\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return load_config()["club"]


def _excluded(n: str) -> bool:
    words = f" {n} "
    return any(f" {e} " in words for e in _cfg()["exclude"])


def match_club(club: str) -> str | None:
    """Match a club *field* value."""
    n = normalise(club)
    if not n or _excluded(n):
        return None
    cfg = _cfg()
    if n in cfg["confident_aliases"]:
        return "confident"
    # "drogheda district" with any trailing words (e.g. "drogheda district ac juveniles")
    if re.search(r"\bdrogheda\s+d\w*\b", n) and fuzz.partial_ratio("district", n) >= 80:
        return "confident"
    if fuzz.ratio(n, TARGET) >= cfg["fuzzy_threshold"]:
        return "confident"
    if fuzz.ratio(n, "drogheda district") >= cfg["fuzzy_threshold"]:
        return "confident"
    if n in cfg["ambiguous_aliases"]:
        return "ambiguous"
    # typo'd "drogheda" on its own, e.g. "droghda ac"
    if fuzz.ratio(n, "drogheda ac") >= 88 or fuzz.ratio(n, "drogheda") >= 88:
        return "ambiguous"
    return None


_LINE_CONFIDENT = re.compile(
    r"\b(ddac|dr?ogh?e?d?a\s*(?:&|and)?\s*d[iu]s?t?r?i?c?t?\w*)\b", re.I)
_LINE_DROGHEDA = re.compile(r"\bdr?ogh?e?d?a\b", re.I)


def match_line(line: str) -> str | None:
    """Match a raw results line where the club column can't be isolated
    (e.g. fixed-width text results). Less precise than match_club."""
    n = normalise(line)
    if not n:
        return None
    if re.search(r"\bddac\b", n):
        return "confident"
    m = _LINE_CONFIDENT.search(n)
    if m and fuzz.partial_ratio("drogheda district", m.group(0)) >= 85:
        return "confident"
    m = _LINE_DROGHEDA.search(n)
    if m:
        # rule out other clubs named just before or after "drogheda"
        window = n[max(0, m.start() - 20): m.end() + 25]
        if _excluded(window):
            return None
        return "ambiguous"
    return None
