"""RaceResult parsing, using column layouts copied from real events
(Pop Up Races 430955, Race Timing Ireland 377688, JustRuns 435742)."""
from ddac.sources import raceresult as rr

POPUP_FIELDS = ["BIB", "ID", "RANK1", "DisplayName", "CLUB",
                'if([CONTEST.isTeam]=1;[DivisionRank.p] & " " & [Division];[GenderRank.p] & " " & [GenderMF])',
                "AGEGROUP1.NAME", "PicturesIcon", "VideoIcon",
                'if([FINISHED]=1;"[img:pictures.png|height:1.1rem]";"")', "Finish.CHIP", "Finish",
                "[PicturesLink]", "[VideoLink]", '"https://finish-photos.popupraces.workers.dev/p/430955/" & [BIB]']
RTI_FIELDS = ["BIB", "ID", "AutoRank.p", "Bib", "DisplayName", "Nation.Flag", "Year", "Club",
              "{Selector}.Label", "{Selector}.CHIP", "{Selector}.GUN"]
JR_FIELDS = ["BIB", "ID", "WithStatus([TotalRankp])", "DisplayName", "SexMF", "AGEGROUP.NAMESHORT",
             "CLUB", "ChipTime", "GunTime"]


def test_map_fields_popup():
    c = rr.map_fields(POPUP_FIELDS)
    assert (c["place"], c["athlete"], c["club"], c["category"], c["time"]) == (2, 3, 4, 6, 10)


def test_map_fields_rti():
    c = rr.map_fields(RTI_FIELDS)
    assert (c["place"], c["athlete"], c["club"], c["time"]) == (2, 4, 7, 9)


def test_map_fields_justruns():
    c = rr.map_fields(JR_FIELDS)
    assert (c["place"], c["athlete"], c["club"], c["category"], c["time"]) == (2, 3, 6, 5, 7)


def test_scrape_event(monkeypatch):
    cfg = {"key": "k", "server": "my4.raceresult.com", "contests": {"1": "5km", "2": "10km"},
           "eventname": "Test Run",
           "TabConfig": {"Lists": [
               {"Name": "01-LIVE|LIVE", "Mode": "hidden", "Contest": "1"},
               {"Name": "PUR|Full Results", "Mode": "", "Contest": "1"},
               {"Name": "PUR|Full Results (All Master Age Groups)", "Mode": "", "Contest": "1"},
               {"Name": "PUR|Full Results", "Mode": "", "Contest": "2"}]}}
    rows5 = [["1", "1", "1", "Emmet MC NAMARA", "Fethard A.C.", "1. M", "M", "", "", "", "0:15:58", "0:15:59", "", "", ""],
             ["9", "9", "12", "Aoife MURPHY", "Drogheda & District A.C.", "1. F", "F40", "", "", "", "0:21:10", "0:21:15", "", "", ""]]
    rows10 = [["5", "5", "3", "Kelly, Sean", "Drogheda AC", "3. M", "M50", "", "", "", "0:40:01", "0:40:05", "", "", ""]]
    calls = []

    def fake_get(url, as_json=False, tries=2):
        calls.append(url)
        if "/config" in url:
            return cfg
        data = {"#1_5km": rows5} if "contest=1" in url else {"#1_10km": {"Male": rows10}}
        return {"DataFields": POPUP_FIELDS, "data": data}

    monkeypatch.setattr(rr, "get", fake_get)
    res = rr.scrape_event({"id": "430955", "date": "2026-11-01", "via": "popupraces"})
    got = {(r.athlete, r.race, r.place, r.time, r.category, r.match) for r in res}
    assert got == {("Aoife Murphy", "5km", "12", "0:21:10", "F40", "confident"),
                   ("Sean Kelly", "10km", "3", "0:40:01", "M50", "ambiguous")}
    assert not any("Master" in c for c in calls)  # weaker age-group list skipped
    assert res[0].extra["via"] == "popupraces"


POPUP_LIST = """<article class="card"><div class="entry-thumb"><a href="https://www.popupraces.ie/race/run-the-line-2026/"><img></a></div>
<h1 class="entry-title"><a href="https://www.popupraces.ie/race/run-the-line-2026/">Run the Line 2026</a></h1>
<div class="mobile-date-old"><i class='fa fa-calendar'></i> 14-11-2026 <i class='fa fa-clock-o'></i> 10:00</div></article>
<article class="card"><h1 class="entry-title"><a href="https://www.popupraces.ie/race/x-5k/">X 5k</a></h1>
<div><i></i> 08-11-2026 <i></i> 12:00</div></article>"""


def test_popupraces_list():
    evs = rr.parse_popupraces_list(POPUP_LIST)
    assert evs == [
        {"page": "https://www.popupraces.ie/race/run-the-line-2026/", "name": "Run the Line 2026",
         "date": "2026-11-14", "via": "popupraces"},
        {"page": "https://www.popupraces.ie/race/x-5k/", "name": "X 5k", "date": "2026-11-08", "via": "popupraces"}]


def test_embedded_id():
    html = 'let rrp=new RRPublish(document.getElementById("divRRPublish"), 377688, "results");'
    assert rr.RRPUBLISH_RE.search(html).group(1) == "377688"


def test_athletes_build():
    from ddac.athletes import build, previous_editions, series_key
    from ddac.models import Result
    base = dict(source="myrunresults", club_raw="DDAC", url="")
    rs = [Result(event_id="1", event_name="Annagassan 10km 2025", event_date="2025-11-15", race="10km",
                 athlete="Colin LEONARD", time="36:10", place="12", category="M40", cat_place="2", **base),
          Result(event_id="2", event_name="Annagassan 10km 2026", event_date="2026-11-14", race="10km",
                 athlete="Colin Leonard", time="35:40", place="3", category="M40", cat_place="1", **base),
          Result(event_id="2", event_name="Annagassan 10km 2026", event_date="2026-11-14", race="10km",
                 athlete="Joe Bloggs", time="40:00", place="50", match="ambiguous", **base)]
    db = build(rs)
    assert len(db) == 1  # ambiguous match left out
    colin = next(iter(db.values()))
    assert colin["races"] == 2 and colin["latest"] == "2026-11-14"
    assert series_key("Annagassan 10km 2026") == "annagassan 10km"
    prev = previous_editions(colin, "annagassan 10km", "2026-11-14")
    assert [p["time"] for p in prev] == ["36:10"]
    assert "3rd overall — Annagassan 10km 2026 (2026-11-14)" in colin["highlights"]
    assert any(h.startswith("2nd M40") for h in colin["highlights"])
