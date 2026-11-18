import pytest

from ddac.club_match import match_club, match_line

CONFIDENT = [
    "Drogheda & District AC",
    "Drogheda and District A.C.",
    "Drogheda & District Athletic Club",
    "Drogheda District AC",
    "drogheda district",
    "DDAC",
    "Drogheda & Distict AC",
    "Drogheda & Disrict A.C",
    "Droghda & District AC",
    "Drogheda and Dist AC",
    "Drogheda & District",
    "DROGHEDA & DISTRICT ATHLETICS CLUB",
]

AMBIGUOUS = [
    "Drogheda AC",
    "Drogheda A.C.",
    "Drogheda",
    "Drogheda Athletic Club",
    "Droghda AC",
]

NOT_DDAC = [
    "Ace AC",
    "ACE Athletic Club",
    "St Peter's AC",
    "St. Peters A.C. Drogheda",
    "Boyne AC",
    "Dundalk St Gerards AC",
    "Drogheda Triathlon Club",
    "Dunleer AC",
    "Duleek",
    "",
    "Unattached",
    "Raheny Shamrock AC",
]


@pytest.mark.parametrize("club", CONFIDENT)
def test_confident(club):
    assert match_club(club) == "confident", club


@pytest.mark.parametrize("club", AMBIGUOUS)
def test_ambiguous(club):
    assert match_club(club) == "ambiguous", club


@pytest.mark.parametrize("club", NOT_DDAC)
def test_not_ddac(club):
    assert match_club(club) is None, club


def test_lines():
    assert match_line("  12 Mary Leech            Drogheda & District AC   10:41.22") == "confident"
    assert match_line("  4 John Smith  Drogheda & Distrct   2:01.11") == "confident"
    assert match_line("  4 John Smith  Drogheda AC   2:01.11") == "ambiguous"
    assert match_line("  4 John Smith  Raheny Shamrock AC   2:01.11") is None
    assert match_line("  4 John Smith  St Peters AC Drogheda   2:01.11") is None
