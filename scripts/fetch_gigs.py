#!/usr/bin/env python3
"""
GigRadar NW - daily gig aggregator for North West England.

Sources (each skipped gracefully if its key is missing):
  1. Ticketmaster Discovery API   (arenas, academies)
  2. Skiddle API                  (indie clubs, promoters - best NW coverage)
  3. Ents24 API                   (aggregates See Tickets / Ticketweb / WeGotTickets)
  4. Bandsintown API              (artist-level enrichment)
  5. Venue pages via JSON-LD      (any venue listed in venue_pages.txt)

Output:
  data/gigs.json      - deduplicated gig list the app reads
  data/last_run.json  - per-source health report shown in app Settings
"""

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

WINDOW_DAYS = 120          # how far ahead to look
REQUEST_TIMEOUT = 25
UA = {"User-Agent": "GigRadarNW/1.0 (personal non-commercial gig aggregator)"}

# Search centres covering the North West (lat, lon, label)
CENTRES = [
    (53.4808, -2.2426, "Manchester"),
    (53.4084, -2.9916, "Liverpool"),
    (53.7632, -2.7031, "Preston"),
]
RADIUS_MILES = 30

# Rough NW bounding box used to filter artist-level sources
NW_BOX = {"lat_min": 52.95, "lat_max": 54.6, "lon_min": -3.65, "lon_max": -1.85}

today = date.today()
date_from = today.isoformat()
date_to = (today + timedelta(days=WINDOW_DAYS)).isoformat()

report = {"run_at": datetime.now(timezone.utc).isoformat(), "sources": {}}


def log(msg):
    print(msg, flush=True)


def mark(source, status, count=0, note=""):
    report["sources"][source] = {"status": status, "events": count, "note": note}
    log(f"[{source}] {status} - {count} events {('- ' + note) if note else ''}")


def get_json(url, **kw):
    r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=UA, **kw)
    r.raise_for_status()
    return r.json()


def in_nw(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return (NW_BOX["lat_min"] <= lat <= NW_BOX["lat_max"]
            and NW_BOX["lon_min"] <= lon <= NW_BOX["lon_max"])


# ---------------------------------------------------------------- normalising
def fold(s):
    """lowercase, strip accents/punctuation - used for matching keys"""
    s = (s or "").replace("&", " and ")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def artist_key(name):
    k = fold(name)
    k = re.sub(r"^the ", "", k)
    return re.sub(r"\s+", " ", k)


SPLIT_PATTERNS = [" + ", " plus ", " w/ ", " with special guests", " - ", " – ",
                  ": ", " presents ", " feat", " ft.", " & friends"]


def extract_artist(title):
    """Best-effort headline artist from a listing title like 'X + support - tour'."""
    t = (title or "").strip()
    low = t.lower()
    cut = len(t)
    for p in SPLIT_PATTERNS:
        i = low.find(p)
        if 0 < i < cut:
            cut = i
    t = t[:cut].strip(" -–:|")
    t = re.sub(r"\s*\((sold out|14\+|18\+|rescheduled|extra date)[^)]*\)\s*$", "", t,
               flags=re.I)
    return t or title


def venue_key(name, lat=None, lon=None):
    if lat is not None and lon is not None:
        try:
            return f"geo:{round(float(lat), 3)},{round(float(lon), 3)}"
        except (TypeError, ValueError):
            pass
    k = fold(name)
    for w in (" the ", " at ", " loft", " theatre", " basement", " attic"):
        k = (" " + k + " ").replace(w, " ").strip()
    return "name:" + re.sub(r"\s+", " ", k)


def gig_record(*, title, artist, dt, time_str, venue, city, postcode,
               lat, lon, source, url, price, genres=None, image=None):
    return {
        "title": (title or artist or "").strip(),
        "artist": (artist or extract_artist(title) or "").strip(),
        "date": dt, "time": time_str or "",
        "venue": (venue or "").strip(), "city": (city or "").strip(),
        "postcode": (postcode or "").strip(),
        "lat": lat, "lng": lon,
        "genres": sorted({g.strip().lower() for g in (genres or []) if g and g.strip()}),
        "image": image or "",
        "sources": [{"name": source, "url": url or "", "price": price}],
    }


# ----------------------------------------------------------------- 1. ticketmaster
def fetch_ticketmaster(out):
    key = os.environ.get("TICKETMASTER_KEY", "").strip()
    if not key:
        return mark("ticketmaster", "skipped", note="no key")
    n = 0
    try:
        for lat, lon, _ in CENTRES:
            for page in range(3):
                js = get_json(
                    "https://app.ticketmaster.com/discovery/v2/events.json",
                    params={"apikey": key, "latlong": f"{lat},{lon}",
                            "radius": RADIUS_MILES, "unit": "miles",
                            "classificationName": "Music", "countryCode": "GB",
                            "size": 200, "page": page, "sort": "date,asc",
                            "startDateTime": f"{date_from}T00:00:00Z",
                            "endDateTime": f"{date_to}T23:59:59Z"})
                events = js.get("_embedded", {}).get("events", [])
                for e in events:
                    v = (e.get("_embedded", {}).get("venues") or [{}])[0]
                    loc = v.get("location", {})
                    start = e.get("dates", {}).get("start", {})
                    if not start.get("localDate"):
                        continue
                    price = None
                    for pr in e.get("priceRanges", []) or []:
                        if pr.get("min"):
                            price = pr["min"]
                            break
                    img = ""
                    for im in e.get("images", []) or []:
                        if im.get("ratio") == "16_9" and im.get("width", 0) >= 600:
                            img = im.get("url", "")
                            break
                    atts = e.get("_embedded", {}).get("attractions") or []
                    artist = atts[0]["name"] if atts else extract_artist(e.get("name"))
                    genres = []
                    for c in e.get("classifications", []) or []:
                        for f in ("genre", "subGenre"):
                            nm = (c.get(f) or {}).get("name", "")
                            if nm and nm.lower() not in ("undefined", "other"):
                                genres.append(nm)
                    out.append(gig_record(
                        title=e.get("name"), artist=artist,
                        dt=start["localDate"], time_str=start.get("localTime", ""),
                        venue=v.get("name"), city=(v.get("city") or {}).get("name"),
                        postcode=v.get("postalCode"),
                        lat=loc.get("latitude"), lon=loc.get("longitude"),
                        source="Ticketmaster", url=e.get("url"), price=price,
                        genres=genres, image=img))
                    n += 1
                if page + 1 >= js.get("page", {}).get("totalPages", 1):
                    break
                time.sleep(0.3)
        mark("ticketmaster", "ok", n)
    except Exception as ex:
        mark("ticketmaster", "error", n, str(ex)[:160])


# --------------------------------------------------------------------- 2. skiddle
def fetch_skiddle(out):
    key = os.environ.get("SKIDDLE_KEY", "").strip()
    if not key:
        return mark("skiddle", "skipped", note="no key")
    n = 0
    try:
        for lat, lon, _ in CENTRES:
            offset = 0
            while offset < 400:
                js = get_json(
                    "https://www.skiddle.com/api/v1/events/search/",
                    params={"api_key": key, "latitude": lat, "longitude": lon,
                            "radius": RADIUS_MILES, "eventcode": "LIVE",
                            "order": "date", "limit": 100, "offset": offset,
                            "minDate": date_from, "maxDate": date_to,
                            "description": 0})
                results = js.get("results", []) or []
                for e in results:
                    v = e.get("venue", {}) or {}
                    artists = [a.get("name") for a in (e.get("artists") or [])
                               if a.get("name")]
                    artist = artists[0] if artists else extract_artist(
                        e.get("eventname"))
                    out.append(gig_record(
                        title=e.get("eventname"), artist=artist,
                        dt=e.get("date"), time_str=e.get("openingtimes", {})
                            .get("doorsopen", "") if isinstance(
                                e.get("openingtimes"), dict) else "",
                        venue=v.get("name"), city=v.get("town"),
                        postcode=v.get("postcode"),
                        lat=v.get("latitude"), lon=v.get("longitude"),
                        source="Skiddle", url=e.get("link"),
                        price=e.get("entryprice") or None,
                        genres=[g.get("name") for g in (e.get("genres") or [])
                                if isinstance(g, dict)],
                        image=e.get("largeimageurl") or e.get("imageurl") or ""))
                    n += 1
                if len(results) < 100:
                    break
                offset += 100
                time.sleep(0.3)
        mark("skiddle", "ok", n)
    except Exception as ex:
        mark("skiddle", "error", n, str(ex)[:160])


# ---------------------------------------------------------------------- 3. ents24
ENTS24_POSTCODES = ["M1 1AD", "L1 4BW", "PR1 2HE"]  # Manchester, Liverpool, Preston


def fetch_ents24(out):
    cid = os.environ.get("ENTS24_CLIENT_ID", "").strip()
    sec = os.environ.get("ENTS24_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        return mark("ents24", "skipped", note="no credentials")
    n = 0
    try:
        tok = requests.post("https://api.ents24.com/auth/token",
                            data={"client_id": cid, "client_secret": sec},
                            timeout=REQUEST_TIMEOUT, headers=UA)
        tok.raise_for_status()
        access = tok.json().get("access_token")
        headers = dict(UA, Authorization=access)
        for pc in ENTS24_POSTCODES:
            page = ""
            for _ in range(8):
                params = {"location": f"postcode:{pc}",
                          "radius_distance": RADIUS_MILES, "distance_unit": "mi",
                          "date_from": date_from, "date_to": date_to,
                          "results_per_page": 100, "incl_artists": 1,
                          "incl_tickets": 1, "full_description": 0}
                if page:
                    params["page"] = page
                r = requests.get("https://api.ents24.com/event/list",
                                 params=params, headers=headers,
                                 timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                events = r.json() or []
                for e in events:
                    if not isinstance(e, dict):
                        continue
                    artists = [a.get("name") for a in (e.get("artists") or [])
                               if isinstance(a, dict) and a.get("name")]
                    genre = e.get("genre") or ""
                    # keep only music-ish entries
                    if not artists and not genre:
                        continue
                    v = e.get("venue", {}) or {}
                    addr = v.get("address", {}) or {}
                    geo = v.get("location", {}) or {}
                    start = e.get("startDate") or e.get("date") or ""
                    dt, tm = (start[:10], start[11:16]) if "T" in start \
                        else (start[:10], e.get("startTimeString", "") or "")
                    if not dt:
                        continue
                    price = None
                    for t in e.get("tickets") or []:
                        try:
                            price = float(t.get("price"))
                            break
                        except (TypeError, ValueError):
                            continue
                    out.append(gig_record(
                        title=e.get("title") or e.get("name"),
                        artist=artists[0] if artists else None,
                        dt=dt, time_str=tm,
                        venue=v.get("name"), city=addr.get("town"),
                        postcode=addr.get("postcode"),
                        lat=geo.get("lat"), lon=geo.get("lon"),
                        source="Ents24", url=e.get("webLink") or e.get("url"),
                        price=price,
                        genres=[genre] if genre else [],
                        image=(e.get("image") or {}).get("url", "")
                              if isinstance(e.get("image"), dict) else ""))
                    n += 1
                page = r.headers.get("X-Next-Page", "")
                if not page or len(events) < 100:
                    break
                time.sleep(0.3)
        mark("ents24", "ok", n)
    except Exception as ex:
        mark("ents24", "error", n, str(ex)[:160])


# ----------------------------------------------------------------- 4. bandsintown
def fetch_bandsintown(out, known_artists):
    app_id = os.environ.get("BANDSINTOWN_APP_ID", "").strip()
    if not app_id:
        return mark("bandsintown", "skipped", note="no app id")
    n = 0
    try:
        for name in sorted(known_artists)[:60]:   # enrichment cap
            try:
                js = get_json(
                    "https://rest.bandsintown.com/artists/"
                    f"{requests.utils.quote(name)}/events",
                    params={"app_id": app_id, "date": "upcoming"})
            except Exception:
                continue
            if not isinstance(js, list):
                continue
            for e in js:
                v = e.get("venue", {}) or {}
                if not in_nw(v.get("latitude"), v.get("longitude")):
                    continue
                start = e.get("datetime", "")
                if not start:
                    continue
                offer = (e.get("offers") or [{}])[0]
                out.append(gig_record(
                    title=e.get("title") or name, artist=name,
                    dt=start[:10], time_str=start[11:16],
                    venue=v.get("name"), city=v.get("city"),
                    postcode=v.get("postal_code"),
                    lat=v.get("latitude"), lon=v.get("longitude"),
                    source="Bandsintown", url=offer.get("url") or e.get("url"),
                    price=None))
                n += 1
            time.sleep(0.25)
        mark("bandsintown", "ok", n)
    except Exception as ex:
        mark("bandsintown", "error", n, str(ex)[:160])


# ------------------------------------------------- 5. venue pages (JSON-LD reader)
LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def iter_ld_events(node):
    if isinstance(node, list):
        for x in node:
            yield from iter_ld_events(x)
    elif isinstance(node, dict):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any("Event" in str(x) for x in types):
            yield node
        for key in ("@graph", "itemListElement", "events", "subEvent"):
            if key in node:
                yield from iter_ld_events(node[key])
        if "item" in node:
            yield from iter_ld_events(node["item"])


def fetch_venue_pages(out):
    path = ROOT / "venue_pages.txt"
    if not path.exists():
        return mark("venue_pages", "skipped", note="no venue_pages.txt")
    urls = [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
    if not urls:
        return mark("venue_pages", "skipped", note="list empty")
    n, errs = 0, 0
    for u in urls:
        try:
            html = requests.get(u, timeout=REQUEST_TIMEOUT, headers=UA).text
        except Exception:
            errs += 1
            continue
        for blob in LD_RE.findall(html):
            try:
                data = json.loads(blob.strip())
            except Exception:
                continue
            for ev in iter_ld_events(data):
                start = str(ev.get("startDate", ""))
                if len(start) < 10:
                    continue
                dt = start[:10]
                if not (date_from <= dt <= date_to):
                    continue
                loc = ev.get("location") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = loc.get("address") or {}
                if isinstance(addr, str):
                    addr = {"addressLocality": "", "postalCode": ""}
                geo = loc.get("geo") or {}
                offers = ev.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") or offers.get("lowPrice")
                try:
                    price = float(price) if price not in (None, "") else None
                except (TypeError, ValueError):
                    price = None
                performers = ev.get("performer") or []
                if isinstance(performers, dict):
                    performers = [performers]
                artist = next((p.get("name") for p in performers
                               if isinstance(p, dict) and p.get("name")), None)
                out.append(gig_record(
                    title=ev.get("name"), artist=artist,
                    dt=dt, time_str=start[11:16] if "T" in start else "",
                    venue=loc.get("name"), city=addr.get("addressLocality"),
                    postcode=addr.get("postalCode"),
                    lat=geo.get("latitude"), lon=geo.get("longitude"),
                    source="Venue site", url=offers.get("url") or ev.get("url") or u,
                    price=price,
                    image=ev.get("image") if isinstance(ev.get("image"), str)
                          else ""))
                n += 1
        time.sleep(0.4)
    mark("venue_pages", "ok" if errs == 0 else "partial", n,
         f"{errs} page(s) failed" if errs else "")


# ----------------------------------------------------------------------- dedupe
def merge(primary, extra):
    have = {s["name"] for s in primary["sources"]}
    for s in extra["sources"]:
        if s["name"] not in have:
            primary["sources"].append(s)
    for f in ("time", "postcode", "city", "image"):
        if not primary[f] and extra[f]:
            primary[f] = extra[f]
    if primary["lat"] is None and extra["lat"] is not None:
        primary["lat"], primary["lng"] = extra["lat"], extra["lng"]
    primary["genres"] = sorted(set(primary["genres"]) | set(extra["genres"]))
    if len(extra["title"] or "") > len(primary["title"] or ""):
        primary["title"] = extra["title"]


def dedupe(raw):
    keyed = {}
    alias = {}   # (artist, date, name-based venue key) -> canonical key
    for g in raw:
        if not g["date"] or not (g["artist"] or g["title"]):
            continue
        try:
            if g["lat"] is not None:
                g["lat"], g["lng"] = float(g["lat"]), float(g["lng"])
                if not in_nw(g["lat"], g["lng"]):
                    continue
        except (TypeError, ValueError):
            g["lat"] = g["lng"] = None
        ak = artist_key(g["artist"] or g["title"])
        nk = (ak, g["date"], venue_key(g["venue"]))          # name-only key
        k = (ak, g["date"], venue_key(g["venue"], g["lat"], g["lng"]))
        if k in keyed:
            merge(keyed[k], g)
        elif nk in alias:                 # coordless twin of a geo record
            merge(keyed[alias[nk]], g)
        elif k != nk and nk in keyed:     # geo twin of an earlier coordless record
            merge(g, keyed.pop(nk))
            keyed[k] = g
        else:
            keyed[k] = g
        if k != nk:
            alias[nk] = k
    gigs = sorted(keyed.values(), key=lambda x: (x["date"], x["time"]))
    for g in gigs:
        g["id"] = hashlib.md5(
            f"{artist_key(g['artist'])}|{g['date']}|{venue_key(g['venue'], g['lat'], g['lng'])}"
            .encode()).hexdigest()[:12]
        for s in g["sources"]:
            try:
                s["price"] = round(float(s["price"]), 2) if s["price"] not in (
                    None, "") else None
            except (TypeError, ValueError):
                s["price"] = None
    return gigs


# ------------------------------------------------------------------------- main
def main():
    raw = []
    fetch_ticketmaster(raw)
    fetch_skiddle(raw)
    fetch_ents24(raw)
    fetch_venue_pages(raw)
    known = {g["artist"] for g in raw if g["artist"]}
    fetch_bandsintown(raw, known)

    gigs = dedupe(raw)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "North West England",
        "window_days": WINDOW_DAYS,
        "count": len(gigs),
        "sample": False,
        "gigs": gigs,
    }
    (DATA / "gigs.json").write_text(json.dumps(payload, indent=1))
    report["total_after_dedupe"] = len(gigs)
    report["total_raw"] = len(raw)
    (DATA / "last_run.json").write_text(json.dumps(report, indent=1))
    log(f"DONE - {len(raw)} raw -> {len(gigs)} unique gigs")

    ok_sources = [s for s, v in report["sources"].items()
                  if v["status"] in ("ok", "partial")]
    if not ok_sources:
        log("ERROR: every source failed or was skipped")
        sys.exit(1)


if __name__ == "__main__":
    main()
