# DDAC Results

Collects **Drogheda & District AC** results from results websites every 20 minutes,
logs them, builds a monthly results document for the newsletter and the Sunday
paper, and emails a digest whenever new DDAC results appear.

**Phase 1 sources:** MyRunResults, Dublin Graded track meets.
More sources (Race Timing Ireland, Pop Up Races, JustRuns, Athletics Ireland,
Leinster, NI, etc.) plug in as extra files in `ddac/sources/`.

## What you get

| Output | Where |
|---|---|
| Monthly results doc (summary per race + DDAC results table) | `docs/results/2026-11.md` etc. |
| Email digest of new/updated results | Your inbox, within ~20 minutes |
| All results as data (for later phases) | `data/results.json` |

Results whose club name is unclear (e.g. "Drogheda AC" without "District")
are included but marked **⚠️ check club**. Members found with a blank club
field are marked **⚠️ no club listed**.

---

## One-time setup (about 15 minutes)

### 1. Create the repo
1. On GitHub: **New repository** → name `ddac-results` → **Public** → Create.
   - Public keeps GitHub Actions free with no minute limit. Runs every 20 minutes would use
     roughly 6,000 minutes a month — three times the free allowance for a
     private repo.
   - Nothing private is stored in the repo: the members list lives in an encrypted
     GitHub secret, never in the files. The repo only holds results that are
     already public on the results sites.
2. In **GitHub Desktop**: File → Add local repository → choose this folder →
   Publish / push to the new repo.

### 2. Add email secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `GMAIL_USER` | `simongregorydesign@gmail.com` |
| `GMAIL_APP_PASSWORD` | Gmail App Password (Google Account → Security → App passwords) |
| `NOTIFY_TO` | Who gets the digest (comma-separated, e.g. you + the PRO) |

### 3. First run (test + backfill)
1. Repo → **Actions** → enable workflows if asked.
2. **Scrape results** → **Run workflow**:
   - Since: `2026-11-01`
   - Debug: ✅
   - Email: ☐ (off for the first run)
3. When it finishes, open the run → check the log for `DDAC results` counts,
   and download **debug-pages** (saved pages + screenshots) if anything looks off —
   send it to Claude to adjust the scraper.
4. Check `docs/results/2026-11.md` in the repo.

After that it runs by itself every 20 minutes (:07, :27, :47).

### 4. Members list from Box (weekly, Mondays)
Used to confirm "Drogheda AC"-style matches and catch members with no club listed.
Only names are kept; everything else in the spreadsheet is discarded.

1. Go to <https://app.box.com/developers/console> (signed in as the account that
   can see the members spreadsheet) → **Create New App** → **Custom App** →
   **User Authentication (OAuth 2.0)**.
2. In **Configuration**: Redirect URI `http://localhost`; Application Scopes:
   **Read all files and folders**. Save. Copy the **Client ID** and **Client Secret**.
3. On your computer: `pip install requests` then `python box_auth.py` → sign in →
   paste the localhost address back → it prints a **refresh token**.
4. Find the spreadsheet's **file ID**: open it in Box, the number at the end of
   the URL (`app.box.com/file/1234567890`). If a new file is saved each week,
   use the **folder ID** instead (`app.box.com/folder/...`) — the newest
   spreadsheet in the folder is used.
5. Create a GitHub **fine-grained personal access token**
   (GitHub → Settings → Developer settings → Fine-grained tokens): only this repo,
   permission **Secrets: Read and write**. This lets the workflow store Box's
   rotating token and the members list.
6. Add secrets:

| Secret | Value |
|---|---|
| `BOX_CLIENT_ID` / `BOX_CLIENT_SECRET` | From step 2 |
| `BOX_REFRESH_TOKEN` | From step 3 (use within an hour) |
| `BOX_FILE_ID` *or* `BOX_FOLDER_ID` | From step 4 |
| `GH_PAT` | Token from step 5 |

7. Actions → **Sync members list from Box** → Run workflow. Check the log says
   `Members updated: N names`.

> Box refresh tokens last 60 days and change on every use. The weekly run renews
> it automatically. If the workflow is ever off for 2 months, rerun step 3.
> If the download fails or the list looks wrong (much shorter than last week),
> you get an email and the previous list stays in use.

---

## Day to day

- **Flagged results:** if a ⚠️ result is DDAC, add that club spelling (lowercase,
  no punctuation, no "and"/"&") to `confident_aliases` in `config.yaml`. If it's
  another club, add it to `exclude`.
- **Run now / backfill:** Actions → Scrape results → Run workflow.
- **Errors:** you get at most one error email a day if a source fails.

## Running locally
```bash
pip install -r requirements.txt
python -m playwright install chromium
python run.py --dry-run                 # prints what it finds, saves nothing
DEBUG=1 python run.py --sources myrunresults --since 2026-11-01 --no-email
pytest                                  # tests
```

## How matching works
`ddac/club_match.py` cleans the club name (case, punctuation, "&"/"and",
"A.C."/"Athletic Club" → "AC") then:
- **Confident:** DDAC, Drogheda & District (any form), and close misspellings
  (fuzzy match ≥ 85%).
- **Ambiguous (⚠️):** Drogheda / Drogheda AC without "District" — unless the
  athlete is on the members list, then confident.
- **Never:** Ace AC, St Peter's, Boyne and anything else in `exclude`.

## Costs
Free: GitHub Actions (public repo), Gmail SMTP, Box API.
