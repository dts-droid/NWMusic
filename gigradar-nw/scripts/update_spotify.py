#!/usr/bin/env python3
"""
GigRadar NW - optional Spotify playlist sync.

Runs after fetch_gigs.py in the daily workflow. If the three Spotify secrets
are not set, it exits quietly and the rest of the system works as normal.

Secrets required (see README step 6):
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN

What it does:
  - finds (or creates) a playlist called "GigRadar NW - Upcoming"
  - searches Spotify for each artist with an upcoming NW gig
  - replaces the playlist with the top 2 tracks per artist, soonest gig first
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PLAYLIST_NAME = "GigRadar NW - Upcoming"
MAX_ARTISTS = 80
TRACKS_PER_ARTIST = 2
TIMEOUT = 20

CID = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
REFRESH = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()

if not (CID and SECRET and REFRESH):
    print("[spotify] secrets not set - skipping playlist sync")
    sys.exit(0)


def die(msg):
    print(f"[spotify] ERROR: {msg}")
    sys.exit(0)  # never fail the whole workflow over the optional step


# --- auth ---------------------------------------------------------------
r = requests.post("https://accounts.spotify.com/api/token",
                  data={"grant_type": "refresh_token",
                        "refresh_token": REFRESH},
                  auth=(CID, SECRET), timeout=TIMEOUT)
if r.status_code != 200:
    die(f"token refresh failed ({r.status_code}): {r.text[:200]}")
TOKEN = r.json()["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}


def api(method, path, **kw):
    r = requests.request(method, f"https://api.spotify.com/v1{path}",
                         headers=H, timeout=TIMEOUT, **kw)
    if r.status_code == 429:
        time.sleep(int(r.headers.get("Retry-After", 2)) + 1)
        r = requests.request(method, f"https://api.spotify.com/v1{path}",
                             headers=H, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json() if r.text else {}


# --- load today's gigs ---------------------------------------------------
gigs_path = ROOT / "data" / "gigs.json"
if not gigs_path.exists():
    die("data/gigs.json missing - run fetch_gigs.py first")
data = json.loads(gigs_path.read_text())

seen, artists = set(), []
for g in data.get("gigs", []):
    name = (g.get("artist") or "").strip()
    key = name.lower()
    if name and key not in seen:
        seen.add(key)
        artists.append(name)
    if len(artists) >= MAX_ARTISTS:
        break
if not artists:
    die("no artists in gigs.json")

# --- find or create the playlist -----------------------------------------
me = api("GET", "/me")["id"]
playlist_id = None
url = "/me/playlists?limit=50"
while url:
    js = api("GET", url)
    for p in js.get("items", []):
        if p.get("name") == PLAYLIST_NAME:
            playlist_id = p["id"]
            break
    url = js.get("next")
    url = url.replace("https://api.spotify.com/v1", "") if url else None
    if playlist_id:
        break
if not playlist_id:
    p = api("POST", f"/users/{me}/playlists",
            json={"name": PLAYLIST_NAME, "public": False,
                  "description": "Artists playing the North West soon. "
                                 "Updated daily by GigRadar NW."})
    playlist_id = p["id"]
    print(f"[spotify] created playlist {playlist_id}")

# --- build track list -----------------------------------------------------
uris, missed = [], []
for name in artists:
    try:
        js = api("GET", "/search",
                 params={"q": f'artist:"{name}"', "type": "artist",
                         "limit": 1, "market": "GB"})
        items = js.get("artists", {}).get("items", [])
        if not items:
            missed.append(name)
            continue
        top = api("GET", f"/artists/{items[0]['id']}/top-tracks",
                  params={"market": "GB"})
        for t in top.get("tracks", [])[:TRACKS_PER_ARTIST]:
            if t["uri"] not in uris:
                uris.append(t["uri"])
        time.sleep(0.15)
    except Exception as ex:
        missed.append(name)
        print(f"[spotify] skipped {name}: {str(ex)[:80]}")

uris = uris[:200]
if not uris:
    die("found no tracks at all")

# --- replace playlist contents --------------------------------------------
api("PUT", f"/playlists/{playlist_id}/tracks", json={"uris": uris[:100]})
if len(uris) > 100:
    api("POST", f"/playlists/{playlist_id}/tracks", json={"uris": uris[100:]})

api("PUT", f"/playlists/{playlist_id}",
    json={"description": f"Artists playing the North West soon - "
                         f"{len(artists)} acts, refreshed "
                         f"{time.strftime('%d %b %Y')}. Built by GigRadar NW."})

print(f"[spotify] playlist updated: {len(uris)} tracks from "
      f"{len(artists) - len(missed)} artists "
      f"({len(missed)} not found on Spotify)")
