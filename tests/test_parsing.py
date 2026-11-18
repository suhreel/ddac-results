from ddac.docs import build_month
from ddac.sources.dublin_graded import meet_info, parse_rendered
from ddac.tables import map_headers, rows_to_results

MRR_HEADERS = ["Place", "Name", "Gross Time", "Cat", "Champs", "Sub Cat", "Club"]
MRR_ROWS = [
    ["1", "Barry MINNOCK #7643", "00:39:34", "M", "", "M45", "Tullamore Harriers"],
    ["14", "Aoife MURPHY #7001", "00:44:10", "F", "", "F35", "Drogheda & District A.C."],
    ["22", "Sean KELLY #7002", "00:45:02", "M", "", "M50", "Drogheda AC"],
    ["30", "Tom BYRNE #7003", "00:46:00", "M", "", "MS", "Ace AC"],
    ["41", "Ciara DOYLE #7004", "00:47:30", "F", "", "FS", "Drogheda & Distrct AC"],
]
BASE = {"source": "myrunresults", "event_id": "5329", "event_name": "Test 10k",
        "event_date": "2026-11-15", "race": "10k", "url": "https://x"}


def test_header_mapping():
    cols = map_headers(MRR_HEADERS)
    assert cols["place"] == 0 and cols["athlete"] == 1 and cols["time"] == 2
    assert cols["club"] == 6 and cols["category"] == 5
    chip = map_headers(["Pos", "Name", "Club", "Gun Time", "Chip Time"])
    assert chip["time"] == 4


def test_myrunresults_rows():
    rs = rows_to_results(MRR_HEADERS, MRR_ROWS, BASE)
    got = {r.athlete: r.match for r in rs}
    assert got == {"Aoife MURPHY": "confident", "Sean KELLY": "ambiguous", "Ciara DOYLE": "confident"}
    assert rs[0].time == "00:44:10" and rs[0].place == "14"


TABLE = """<html><body><h2>800m. Grade A</h2>
<table><tr><th>Rank</th><th>Name</th><th>Club</th><th>Result</th></tr>
<tr><td>1</td><td>Sean Carrigg</td><td>Clonliffe Harriers</td><td>1:56.21</td></tr>
<tr><td>5</td><td>Paul Smith</td><td>Drogheda &amp; District</td><td>2:01.40</td></tr>
</table></body></html>"""


def test_graded_rendered_table():
    rs = parse_rendered(TABLE, {"source": "dublin_graded", "event_id": "graded26-1",
                                "event_name": "Dublin Graded Meet 1 2026", "event_date": "2026-05-03",
                                "race": "800m. Grade A", "url": "u"})
    assert len(rs) == 1 and rs[0].athlete == "Paul Smith" and rs[0].time == "2:01.40"
    assert rs[0].race == "800m. Grade A" and rs[0].place == "5"


def test_meet_info():
    xml = """<?xml version="1.0"?><competition><name>Dublin Graded Meet 1 2026 </name>
    <startdate>03-05-2025</startdate><rounds><round><datescheduled>2026-05-03</datescheduled></round></rounds></competition>"""
    assert meet_info(xml) == ("Dublin Graded Meet 1 2026", "2026-05-03")


def test_month_doc():
    rs = rows_to_results(MRR_HEADERS, MRR_ROWS, BASE)
    md = build_month(rs, "2026-11")
    assert "## Test 10k" in md and "Aoife MURPHY was first DDAC finisher" in md
    assert "⚠️ check club" in md and "Needs checking" in md
    print(md)


def test_myrunresults_json_mapping():
    from ddac.sources.myrunresults import _mrr_rows
    items = [
        {"runnerId": "1", "runner_Club": "Drogheda and District A.C.", "runner_Place": "37",
         "runner_CatPlace": "31", "runner_SubCatPlace": "2", "runner_FirstName": "Oisín",
         "runner_LastName": "MC ARDLE", "runner_NetTime": "00:21:41", "runner_GrossTime": "00:21:45",
         "runner_Category": "Male", "runner_SubCategory": "MU18", "runner_Class": "5km", "runnerIsDnf": ""},
        {"runnerId": "2", "runner_Club": "St. Peter's A.C. DTC", "runner_FirstName": "Cian",
         "runner_LastName": "GORHAM", "runner_Place": "1", "runner_NetTime": "00:15:15", "runner_Class": "5km"},
        {"runnerId": "3", "runner_Club": "", "runner_Team": "Drogheda & District AC", "runner_FirstName": "Ann",
         "runner_LastName": "BYRNE", "runner_Place": "", "runner_NetTime": "", "runner_Class": "10km",
         "runnerIsDnf": True},
    ]
    h, rows = _mrr_rows(items)
    rs = rows_to_results(h, rows, {**BASE, "race": ""})
    got = {r.athlete: (r.place, r.time, r.category, r.cat_place, r.race, r.match) for r in rs}
    assert got == {
        "Oisín Mc Ardle": ("37", "00:21:41", "MU18", "2", "5km", "confident"),
        "Ann Byrne": ("", "DNF", "", "", "10km", "confident"),
    }
