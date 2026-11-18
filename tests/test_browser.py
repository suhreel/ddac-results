"""Exercises the MyRunResults browser logic against a local fixture page that
mimics a JS-paginated results table with distance tabs. Skips if no browser."""
import os
from pathlib import Path

import pytest

from ddac.sources import myrunresults as mrr

FIXTURE = Path(__file__).parent / "fixtures" / "mrr_event.html"


def _browser_available():
    if os.environ.get("CHROME_PATH"):
        return True
    return (Path.home() / ".cache" / "ms-playwright").exists()


@pytest.mark.skipif(not _browser_available(), reason="no browser installed")
def test_event_scrape_with_tabs_and_pagination(monkeypatch):
    from ddac.browser import browser_page
    ev = {"id": "1", "slug": "x", "name": "Fixture Race", "date": "2026-11-15", "tags": "10k, 5k"}
    with browser_page() as page:
        # point the scraper at the local fixture instead of the live site
        orig_goto = page.goto
        monkeypatch.setattr(page, "goto", lambda url, **kw: orig_goto(FIXTURE.as_uri(), **kw))
        results = mrr.scrape_event(page, ev)
    races = {r.race for r in results}
    assert races == {"10k", "5k"}
    # clubs cycle every 5 rows: index 1 = DDAC (confident), 3 = Drogheda AC (ambiguous); 45 rows each
    conf = [r for r in results if r.match == "confident"]
    amb = [r for r in results if r.match == "ambiguous"]
    assert len(conf) == 18 and len(amb) == 18, (len(conf), len(amb))
    assert all(r.category in ("M40", "F35") for r in results)
    assert not any("Ace" in r.club_raw for r in results)
