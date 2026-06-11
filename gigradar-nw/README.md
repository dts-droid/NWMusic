# GigRadar NW

Your personal North West gig radar: pulls every announced show from
Ticketmaster, Skiddle, Ents24, Bandsintown and venues' own websites,
removes the duplicates, refreshes itself every morning, ranks gigs against
your taste with AI, and (optionally) keeps a Spotify playlist of every
artist playing near you soon.

Everything runs on free services. No server. Total setup time: about 45
minutes, no coding required.

---

## Step 1 — Put this folder on GitHub (10 min)

1. Create a free account at github.com if you don't have one.
2. Top-right **+** → **New repository**. Name it `gigradar-nw`,
   leave it **Public**, tick **Add a README** (we'll replace it), → **Create**.
3. **Add file → Upload files**. Drag in everything from this folder
   EXCEPT the hidden `.github` folder (your computer may not show it —
   that's fine, step 4 handles it). → **Commit changes**.
4. **Add file → Create new file**. In the name box type exactly:
   `.github/workflows/update-gigs.yml`
   (typing the slashes creates the folders). Open
   `github-workflow-COPY-THIS.yml` from this folder on your computer,
   copy ALL of it, paste it in, → **Commit changes**.

## Step 2 — Turn on the website (2 min)

Repo → **Settings → Pages** → under "Branch" choose **main** and **/ (root)**
→ **Save**. After a minute your app is live at:

`https://YOURNAME.github.io/gigradar-nw/`

Open it on your phone — you'll see sample data. **Share → Add to Home
Screen** makes it feel like a real app. Send the link to your friends too.

## Step 3 — Get your free data keys (15 min)

You don't need all four — each one you add widens coverage. Start with
Skiddle + Ticketmaster (instant), add Ents24 when it's approved.

| Key name (exact) | Where to get it | Notes |
|---|---|---|
| `SKIDDLE_KEY` | skiddle.com/api/join.php | Instant, free. Best NW indie coverage. |
| `TICKETMASTER_KEY` | developer.ticketmaster.com → create app | Instant. Arenas & academies. Use the "Consumer Key". |
| `ENTS24_CLIENT_ID` + `ENTS24_CLIENT_SECRET` | developers.ents24.com → register → Control Panel | Free for personal use. Carries See Tickets / Ticketweb / WeGotTickets — this is what catches the Jacaranda, Arts Club, Albert Hall. |
| `BANDSINTOWN_APP_ID` | artists.bandsintown.com/support → request API app id | Optional enrichment. Skip if it's a hassle. |

Add each one in: repo → **Settings → Secrets and variables → Actions →
New repository secret**. Name must match the table exactly; value is the key.

## Step 4 — First run (2 min)

Repo → **Actions** tab → **Update gigs** → **Run workflow** → green
**Run workflow** button. Two minutes later, open your app and tap
**Settings → Reload latest data**. Real gigs. From now on it also runs
itself every morning at 06:30 UTC automatically.

(Heads-up: GitHub pauses schedules on repos with no activity for 60 days,
and the daily data commit normally counts as activity — but if you ever
notice stale data after a long quiet spell, just press Run workflow once.)

## Step 5 — The "Refresh now" button in the app (5 min)

1. GitHub → your profile photo → **Settings → Developer settings →
   Personal access tokens → Fine-grained tokens → Generate new token**.
2. Name it `gigradar`, expiry 1 year, **Only select repositories** →
   pick `gigradar-nw`. Under **Repository permissions** set
   **Actions: Read and write**. Generate and copy it.
3. In the app: **Settings tab** → enter `YOURNAME/gigradar-nw` and the
   token → **Save settings**. The ⟳ Refresh now button is live.

## Step 6 — AI gig matching (3 min)

1. console.anthropic.com → sign up → **API keys** → create one.
   Add £5 of credit — that's months of daily use.
2. App → **Settings** → paste the key → Save.
3. Rate at least 3 artists on the **Artists** tab, then hit
   **✨ Get my matches** on the AI tab.

Your key lives only in your phone's browser. Friends who want AI matches
add their own key on their own phone (their ratings are theirs too).

## Step 7 (optional) — The daily Spotify playlist

Open `https://YOURNAME.github.io/gigradar-nw/spotify-setup.html` and follow
the three steps on the page. It walks you through creating a Spotify app and
hands you three values to add as GitHub secrets (same place as Step 3).
From the next run, a private playlist called **"GigRadar NW — Upcoming"**
appears in your Spotify and refreshes every morning: top tracks from every
artist with an upcoming North West show, soonest first.

---

## Everyday use

- **Today** — next show, this week, your numbers.
- **Gigs** — everything announced; tap a stub for every seller's price,
  Spotify preview and a map.
- **Artists** — rate acts ⭐👍➖👎 to train your matcher.
- **AI** — your taste profile, ranked matches, and new artists to try.
- **Settings** — pipeline health per source, refresh controls, keys.

## Adding a venue the feed missed

Spotted a gig on a poster that the app doesn't have? Edit
`venue_pages.txt` on GitHub (pencil icon), add the venue's events-page
web address on a new line, commit. The next refresh reads that page's
machine-readable listings automatically. If a venue still doesn't show up
after that, its website doesn't publish structured data — tell Claude which
venue and ask for a custom reader for it.

## Small print

Personal, non-commercial use. Listings powered by Ents24, Skiddle,
Ticketmaster and Bandsintown — the app credits them in Settings, as their
terms ask. Ents24's strictest terms prefer data cached under an hour; this
project refreshes daily for personal use, but if you ever open it to the
public, revisit their licence (and Spotify's user limits) first.

## If something breaks

Repo → **Actions** → click the failed run → the red step says what
happened (usually an expired key). The app keeps working on yesterday's
data whenever a source fails — check **Settings** in the app to see
which source it was. Paste any error to Claude for a fix.
