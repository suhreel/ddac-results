from . import dublin_graded, myrunresults, raceresult

# name -> module with run(store, cfg, since=None) -> list[Result]
SOURCES = {
    "myrunresults": myrunresults,
    "dublin_graded": dublin_graded,
    "raceresult": raceresult,   # also Pop Up Races, JustRuns, Race Timing Ireland
}
