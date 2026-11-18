from ddac.docs import build_month
from ddac.sources.dublin_graded import parse_page
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


HYTEK = """<html><head><title>Dublin Graded 7 - Women 3000m</title></head><body><pre>
Women 3000 Meter Run Grade B
=====================================================
    Name                    Club                     Finals
=====================================================
  1 Jane Walsh              Raheny Shamrock AC     10:12.33
  2 Mary Leech              Drogheda & District AC 10:41.22
  3 Ann Byrne               Drogheda AC            10:55.01
  4 Kate Reilly             St Peters AC Drogheda  11:02.10
</pre></body></html>"""

TABLE = """<html><head><title>Men 800m A</title></head><body><h3>Men 800m A</h3>
<table><tr><th>Pos</th><th>Name</th><th>Club</th><th>Time</th></tr>
<tr><td>1</td><td>Sean Carrigg</td><td>Clonliffe Harriers</td><td>1:56.21</td></tr>
<tr><td>5</td><td>Paul Smith</td><td>Drogheda &amp; District</td><td>2:01.40</td></tr>
</table></body></html>"""


def test_graded_pre():
    rs = parse_page(HYTEK, {"source": "dublin_graded", "event_id": "graded26-7",
                            "event_name": "Dublin Graded 7", "event_date": "2026-07-15", "url": "u"})
    got = {r.athlete: (r.match, r.time, r.place) for r in rs}
    assert got["Mary Leech"] == ("confident", "10:41.22", "2")
    assert got["Ann Byrne"][0] == "ambiguous"
    assert "Kate Reilly" not in got and "Jane Walsh" not in got
    assert all("3000" in r.race for r in rs)


def test_graded_table():
    rs = parse_page(TABLE, {"source": "dublin_graded", "event_id": "graded26-7",
                            "event_name": "Dublin Graded 7", "event_date": "2026-07-15", "url": "u"})
    assert len(rs) == 1 and rs[0].athlete == "Paul Smith" and rs[0].time == "2:01.40"
    assert rs[0].race == "Men 800m A"


def test_month_doc():
    rs = rows_to_results(MRR_HEADERS, MRR_ROWS, BASE)
    md = build_month(rs, "2026-11")
    assert "## Test 10k" in md and "Aoife MURPHY was first DDAC finisher" in md
    assert "⚠️ check club" in md and "Needs checking" in md
    print(md)
