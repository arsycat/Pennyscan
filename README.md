# PennyScan — runs itself, read it on your phone

A penny-stock breakout scanner that GitHub runs for you every weekday after the
market closes. The PDF reports land in the `reports/` folder of this repo, so
you can open them from the GitHub app or any phone browser.

## One-time setup (5 minutes, easiest from a computer)

1. **Create a free GitHub account** at github.com if you don't have one.
2. **Create a new repository**: click the **+** (top right) → *New repository* →
   name it `pennyscan` → set it to **Private** → *Create repository*.
3. **Upload these files**: on the empty repo page click *uploading an existing
   file*, then drag in **everything from this folder, including the hidden
   `.github` folder** (just drag
   the whole unzipped folder's contents in). Click *Commit changes*.
   - If the `.github` folder didn't upload (it's hidden), create it by hand:
     *Add file → Create new file*, type `.github/workflows/scan.yml` as the
     name, paste the contents of that file, commit.
4. **Allow the workflow to write**: *Settings → Actions → General → Workflow
   permissions → "Read and write permissions"* → Save.
5. **Run it once by hand**: *Actions* tab → *PennyScan daily* → *Run workflow*
   → pick a preset → *Run workflow*. It takes 3–6 minutes.

That's it. From now on it runs automatically on weekdays at 4:45 pm Eastern.

## Reading it on your phone

- Install the **GitHub** app (iOS / Android) and sign in, or just use the browser.
- Open the repo → `reports/` → tap `latest_quick.pdf` or `latest_long.pdf`.
  Those two files are always the most recent scan. Dated copies sit beside
  them for the last 30 days.
- To bookmark: the URL is
  `https://github.com/YOUR-USERNAME/pennyscan/blob/main/reports/latest_quick.pdf`

## Running a scan on demand from your phone

Open the repo → *Actions* → *PennyScan daily* → *Run workflow* → choose a preset
(`quick`, `deep`, `sub1`, `tight`, `under1`, `long`) and a market (`US`, `CA`,
`both`) → *Run workflow*. A few minutes later the new PDF appears in `reports/`.

## Presets

| Preset  | What it does |
|---------|--------------|
| quick   | top 150 by volume under $5, swing-trade breakout rules |
| deep    | same rules, top 400 |
| sub1    | under $1, looser score, 1M+ average volume |
| tight   | under $5, strict score ≥ 55 |
| under1  | quick-scan rules capped at $1 |
| long    | long-term rulebook: 50-day base, 50/200-day uptrend, beats the S&P, cap ≥ $25M |

## Still works on a computer

`python pennyscan.py` — double-click or run it; it shows a menu and opens the PDF.

---

*Screening tool only, not advice. Penny stocks are illiquid, volatile and
frequently manipulated; most breakouts fail.*
