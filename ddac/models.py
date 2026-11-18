from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict


@dataclass
class Result:
    source: str               # e.g. "myrunresults"
    event_id: str             # stable id within the source
    event_name: str
    event_date: str           # ISO yyyy-mm-dd when known, else raw text
    race: str                 # distance / race within the event, e.g. "5k", "Men's 1500m B"
    athlete: str
    club_raw: str
    time: str = ""
    place: str = ""
    category: str = ""
    cat_place: str = ""
    url: str = ""
    raw: str = ""             # original row text, kept for checking
    match: str = "confident"  # confident | ambiguous | member-only
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        base = f"{self.source}|{self.event_id}|{self.race}|{self.athlete.lower()}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Result":
        # ignore bookkeeping fields added by the store (key, first_seen, updated)
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})
