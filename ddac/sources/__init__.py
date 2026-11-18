from . import dublin_graded, myrunresults

# name -> module with run(store, cfg, since=None) -> list[Result]
SOURCES = {
    "myrunresults": myrunresults,
    "dublin_graded": dublin_graded,
}
