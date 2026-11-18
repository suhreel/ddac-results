"""One-time helper: get the first Box refresh token.

  python box_auth.py

1. Opens the Box sign-in page. Sign in with the account that owns the members spreadsheet.
2. Box redirects to http://localhost/?code=... (the page won't load — that's fine).
3. Copy the whole address from the browser bar and paste it here.
4. Copy the refresh token printed at the end into the BOX_REFRESH_TOKEN secret.
"""
import getpass
import urllib.parse
import webbrowser

import requests

client_id = input("Box Client ID: ").strip()
client_secret = getpass.getpass("Box Client Secret (hidden): ").strip()

url = "https://account.box.com/api/oauth2/authorize?" + urllib.parse.urlencode(
    {"response_type": "code", "client_id": client_id, "redirect_uri": "http://localhost"})
print("\nOpening:", url)
webbrowser.open(url)

pasted = input("\nPaste the full http://localhost/?code=... address: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [pasted])[0]

r = requests.post("https://api.box.com/oauth2/token", data={
    "grant_type": "authorization_code", "code": code,
    "client_id": client_id, "client_secret": client_secret,
    "redirect_uri": "http://localhost"}, timeout=30)
r.raise_for_status()
print("\nBOX_REFRESH_TOKEN =", r.json()["refresh_token"])
print("Add it as a GitHub secret within the next hour, then run the 'Sync members list' workflow once.")
