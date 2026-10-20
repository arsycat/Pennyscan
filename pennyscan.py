#!/usr/bin/env python3
"""
PennyScan v3 — Penny Stock Breakout Scanner
===========================================
Double-click this file (or run `python pennyscan.py`). It will:
  1. install any missing packages automatically
  2. show a simple menu of scan presets
  3. pull a live universe of low-priced stocks from Yahoo's screener
  4. score each one for a breakout setup
  5. save a dated PDF report (plus results.csv) next to this file and open it

Advanced (optional) command-line use:
  python pennyscan.py --preset deep
  python pennyscan.py --max-price 3 --limit 400 --min-score 50
  python pennyscan.py --tickers mylist.txt

Screening tool only, not advice. Penny stocks are illiquid, volatile and
frequently manipulated; most breakouts fail. Size positions accordingly.
"""

import argparse
import importlib
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
INTERACTIVE = len(sys.argv) == 1  # double-clicked / no flags


# ---------------------------------------------------------------------------
# 0. Dependencies — install on first run
# ---------------------------------------------------------------------------
def ensure(pkg, import_name=None):
    try:
        return importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"Installing {pkg} (first run only) …")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=False)
        return importlib.import_module(import_name or pkg)


np = ensure("numpy")
pd = ensure("pandas")
requests = ensure("requests")
yf = ensure("yfinance")
ensure("reportlab")

# Yahoo screener needs a recent yfinance
if not hasattr(yf, "screen"):
    print("Upgrading yfinance …")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yfinance"],
                   check=False)
    importlib.reload(yf)


# ---------------------------------------------------------------------------
# 1. Presets
# ---------------------------------------------------------------------------
PRESETS = {
    "quick": dict(label="Quick scan  — top 150 by volume, under $5 (≈2 min)",
                  limit=150, max_price=5.0, min_avg_vol=500_000, min_score=40),
    "deep": dict(label="Deep scan   — top 400 by volume, under $5 (≈5 min)",
                 limit=400, max_price=5.0, min_avg_vol=300_000, min_score=40),
    "sub1": dict(label="Sub-$1 only — the riskiest tier (≈2 min)",
                 limit=200, max_price=1.0, min_avg_vol=1_000_000, min_score=35),
    "tight": dict(label="Tight setups — strict scoring, fewer but cleaner names (≈3 min)",
                  limit=250, max_price=5.0, min_avg_vol=500_000, min_score=55),
    "under1": dict(label="Under $1    — quick-scan settings, price capped at $1 (≈2 min)",
                   limit=150, max_price=1.0, min_avg_vol=500_000, min_score=40),
    "long": dict(label="Long-term   — strict: 50-day base, 50/200-day uptrend, beats S&P, "
                       "cap ≥ $25M (≈5 min)",
                 limit=400, max_price=5.0, min_avg_vol=500_000, min_score=60, long_term=True),
}

# Long-term rulebook (used when a preset sets long_term=True)
LT = dict(
    base_days=50,        # consolidation window (vs 20 for swing presets)
    max_range=30,        # base must be tighter than 30% high-to-low
    min_price=0.50,      # sub-50c names are structurally too dilutive for holding
    min_dollar_vol=1_000_000,
    max_atr_pct=8.0,     # 14-day ATR as % of price — screens out chaos
    min_pct_of_52w_high=0.55,  # not a wrecked chart (price ≥ 55% of 52-wk high)
    min_market_cap=25_000_000,
    history="1y",
)


def pause():
    if INTERACTIVE:
        input("\nPress Enter to close …")


def choose_preset() -> str:
    print("=" * 62)
    print("   PENNYSCAN v3  ·  penny stock breakout scanner")
    print("=" * 62)
    keys = list(PRESETS)
    for i, k in enumerate(keys, 1):
        print(f"  {i}. {PRESETS[k]['label']}")
    print()
    while True:
        raw = input(f"Pick a scan [1-{len(keys)}, Enter = 1]: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        print(f"  please enter a number 1-{len(keys)}")


def choose_markets() -> list[str]:
    print("\n  1. US only (USD)      2. Canada only (CAD)      3. Both")
    while True:
        raw = input("Which market? [1-3, Enter = 3]: ").strip() or "3"
        if raw == "1":
            return ["US"]
        if raw == "2":
            return ["CA"]
        if raw == "3":
            return ["US", "CA"]
        print("  please enter 1, 2 or 3")


# ---------------------------------------------------------------------------
# 2. Universe
# ---------------------------------------------------------------------------
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*"}


MARKETS = {
    "US": dict(label="US-listed (USD)", currency="USD",
               exchanges=["NMS", "NGM", "NCM", "NYQ", "ASE"], vol_scale=1.0),
    "CA": dict(label="Canada-listed (CAD)", currency="CAD",
               exchanges=["TOR", "VAN", "CNQ", "NEO"], vol_scale=0.4),  # TSXV volumes run lower
}


def universe_yahoo(max_price, min_avg_vol, limit, market="US"):
    from yfinance import EquityQuery
    q = EquityQuery("and", [
        EquityQuery("lt", ["intradayprice", max_price]),
        EquityQuery("gt", ["intradayprice", 0.05]),
        EquityQuery("gt", ["avgdailyvol3m", min_avg_vol]),
        EquityQuery("is-in", ["exchange"] + MARKETS[market]["exchanges"]),
    ])
    out, offset = [], 0
    while len(out) < limit:
        size = min(250, limit - len(out))
        res = yf.screen(q, offset=offset, size=size, sortField="dayvolume", sortAsc=False)
        quotes = (res or {}).get("quotes", [])
        if not quotes:
            break
        out += [x["symbol"] for x in quotes if "symbol" in x]
        offset += len(quotes)
        if len(quotes) < size:
            break
        time.sleep(0.4)
    return out[:limit]


def universe_nasdaq(max_price, min_avg_vol, limit, market="US"):
    if market != "US":
        return []
    r = requests.get("https://api.nasdaq.com/api/screener/stocks",
                     params={"tableonly": "true", "limit": 6000}, headers=HEADERS, timeout=30)
    rows = r.json()["data"]["table"]["rows"]

    def num(s):
        try:
            return float(str(s).replace("$", "").replace(",", ""))
        except ValueError:
            return float("nan")
    picks = []
    for row in rows:
        sym = row.get("symbol", "")
        if not sym or any(c in sym for c in "/^ "):
            continue
        p, v = num(row.get("lastsale")), num(row.get("volume"))
        if 0.05 < p < max_price and v >= min_avg_vol:
            picks.append((v, sym))
    picks.sort(reverse=True)
    return [s for _, s in picks[:limit]]


def build_universe(max_price, min_avg_vol, limit, market="US"):
    """Returns list of (ticker, market)."""
    vol = int(min_avg_vol * MARKETS[market]["vol_scale"])
    for name, fn in (("Yahoo screener", universe_yahoo), ("NASDAQ screener", universe_nasdaq)):
        try:
            print(f"[{market}] building universe from {name} …", end=" ", flush=True)
            u = fn(max_price, vol, limit, market)
            if u:
                print(f"{len(u)} tickers")
                return [(t, market) for t in u]
            print("empty")
        except Exception as e:  # noqa: BLE001
            print(f"failed ({type(e).__name__})")
    return []


def guess_market(ticker: str) -> str:
    return "CA" if ticker.upper().endswith((".TO", ".V", ".CN", ".NE")) else "US"


def lookup_sector(ticker: str) -> tuple[str, str, float]:
    """Sector / industry / market cap from Yahoo. Only called for matched names."""
    try:
        info = yf.Ticker(ticker).info or {}
        return (info.get("sector") or "Unknown", info.get("industry") or "",
                float(info.get("marketCap") or 0))
    except Exception:  # noqa: BLE001
        return "Unknown", "", 0.0


# ---------------------------------------------------------------------------
# 3. Scoring
# ---------------------------------------------------------------------------
@dataclass
class Row:
    ticker: str
    market: str
    currency: str
    sector: str
    industry: str
    market_cap: float
    price: float
    resistance: float
    dist_to_res_pct: float
    base_range_pct: float
    vol_ratio: float
    avg_dollar_vol: int
    rsi: float
    trend_up: bool
    score: float
    setup: str


def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def analyze_long_term(t, df, max_price, market, bench_ret3m):
    """Stricter rulebook for multi-week/month holds. Returns Row or None."""
    if df is None or len(df) < 160:
        return None
    df = df.dropna()
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    price = float(close.iloc[-1])
    if not (LT["min_price"] <= price <= max_price):
        return None
    adv = float((close * vol).tail(20).mean())
    if adv < LT["min_dollar_vol"]:
        return None

    # --- trend structure: price > SMA50 > SMA200 (or SMA150 if <200 bars), SMA50 rising
    sma50 = close.rolling(50).mean()
    long_n = 200 if len(close) >= 200 else 150
    sma_long = close.rolling(long_n).mean()
    if not (price > sma50.iloc[-1] > sma_long.iloc[-1]):
        return None
    if sma50.iloc[-1] <= sma50.iloc[-51]:  # trend into the base must be up
        return None

    # --- not a wrecked chart: within reach of the 52-week high
    hi52 = float(high.tail(252).max())
    if price < LT["min_pct_of_52w_high"] * hi52:
        return None

    # --- volatility sanity: 14-day ATR as % of price
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.tail(14).mean() / price * 100)
    if atr_pct > LT["max_atr_pct"]:
        return None

    # --- 50-day base, tight, price pressing the top of it
    base = df.iloc[-(LT["base_days"] + 1):-1]
    hi, lo = float(base["High"].max()), float(base["Low"].min())
    rng = (hi - lo) / lo * 100
    if rng > LT["max_range"]:
        return None
    dist = (hi - price) / price * 100
    if not (-6 <= dist <= 6):
        return None

    # --- volume: accumulation (up-day volume > down-day volume over the base) + recent expansion
    chg = base["Close"].diff()
    up_v = base["Volume"][chg > 0].mean() or 0
    dn_v = base["Volume"][chg < 0].mean() or 1
    accum = up_v / dn_v
    bv = base["Volume"].mean()
    vr = float(vol.tail(5).mean() / bv) if bv > 0 else 0

    # --- relative strength vs benchmark over 3 months
    ret3m = price / float(close.iloc[-63]) - 1 if len(close) > 63 else 0.0
    rs = ret3m - bench_ret3m

    r = rsi(close)
    r_now = float(r.iloc[-1])

    score, notes = 0.0, []
    score += 20 * (1 - rng / LT["max_range"]); notes.append(f"{rng:.0f}% 50-day base")
    if -2 <= dist <= 3:
        score += 20; notes.append("at resistance")
    elif dist > 3:
        score += 20 * (1 - (dist - 3) / 3); notes.append("approaching resistance")
    else:
        score += 14; notes.append("early breakout")
    if accum >= 1.5:
        score += 15; notes.append(f"accumulation {accum:.1f}x")
    elif accum >= 1.15:
        score += 8; notes.append(f"accumulation {accum:.1f}x")
    if vr >= 1.5:
        score += 10; notes.append(f"volume {vr:.1f}x")
    elif vr >= 1.2:
        score += 5
    if rs >= 0.15:
        score += 15; notes.append(f"beats S&P by {rs*100:.0f}pts")
    elif rs > 0:
        score += 8; notes.append("beats S&P")
    else:
        score -= 5; notes.append("lags S&P")
    score += 10  # trend structure already passed
    if 50 <= r_now <= 68:
        score += 10; notes.append("RSI healthy")
    elif r_now > 75:
        score -= 10; notes.append("overbought")
    if price >= 0.85 * hi52:
        score += 5; notes.append("near 52-wk high")

    return Row(t, market, MARKETS[market]["currency"], "", "", 0.0,
               round(price, 3), round(hi, 3), round(dist, 1), round(rng, 1), round(vr, 2),
               int(adv), round(r_now, 1), True, round(max(score, 0), 1), ", ".join(notes))


def benchmark_ret3m() -> float:
    try:
        spy = yf.Ticker("SPY").history(period="6mo", auto_adjust=True)["Close"]
        return float(spy.iloc[-1] / spy.iloc[-63] - 1)
    except Exception:  # noqa: BLE001
        return 0.0


def analyze(t, df, min_price, max_price, min_dollar_vol, market="US", base_days=20, max_range=35):
    if df is None or len(df) < 60:
        return None
    df = df.dropna()
    close, vol = df["Close"], df["Volume"]
    price = float(close.iloc[-1])
    if not (min_price <= price <= max_price):
        return None
    adv = float((close * vol).tail(20).mean())
    if adv < min_dollar_vol:
        return None

    base = df.iloc[-(base_days + 1):-1]
    hi, lo = float(base["High"].max()), float(base["Low"].min())
    rng = (hi - lo) / lo * 100
    dist = (hi - price) / price * 100
    if rng > max_range:
        return None

    bv = base["Volume"].mean()
    vr = float(vol.tail(3).mean() / bv) if bv > 0 else 0
    half = len(base) // 2
    contracting = base["Volume"].iloc[half:].mean() < base["Volume"].iloc[:half].mean()

    r = rsi(close)
    r_now, r_prev = float(r.iloc[-1]), float(r.iloc[-4])
    e9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    e21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    trend = bool(e9 > e21)
    above50 = price > float(close.tail(50).mean())

    score, notes = 25 * (1 - rng / max_range), []
    if -3 <= dist <= 3:
        score += 25; notes.append("at resistance")
    elif 3 < dist <= 8:
        score += 25 * (1 - (dist - 3) / 5); notes.append("approaching resistance")
    elif -8 <= dist < -3:
        score += 15; notes.append("early breakout")
    else:
        return None
    if vr >= 2:
        score += 25; notes.append(f"volume {vr:.1f}×")
    elif vr >= 1.3:
        score += 15 + 10 * (vr - 1.3) / 0.7; notes.append(f"volume {vr:.1f}×")
    elif contracting:
        score += 8; notes.append("volume drying up")
    if trend:
        score += 10
    if above50:
        score += 5
    if 50 <= r_now <= 70 and r_now > r_prev:
        score += 10; notes.append("RSI rising")
    elif r_now > 75:
        score -= 10; notes.append("overbought")

    return Row(t, market, MARKETS[market]["currency"], "", "", 0.0,
               round(price, 3), round(hi, 3), round(dist, 1), round(rng, 1), round(vr, 2),
               int(adv), round(r_now, 1), trend, round(max(score, 0), 1), ", ".join(notes))


def fetch(t, retries=2, period="6mo"):
    for a in range(retries + 1):
        try:
            df = yf.Ticker(t).history(period=period, auto_adjust=True)
            return None if df is None or df.empty else df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:  # noqa: BLE001
            if a < retries:
                time.sleep(1.5 * (a + 1))
    return None


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------
def write_pdf(table: "pd.DataFrame", meta: dict, path: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8.5, leading=11)
    note = ParagraphStyle("note", parent=body, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)

    doc = SimpleDocTemplate(path, pagesize=landscape(letter),
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title="PennyScan report")
    story = [
        Paragraph("PennyScan — breakout setups", styles["Title"]),
        Paragraph(f"{meta['when']} &nbsp;·&nbsp; preset <b>{meta['preset']}</b> &nbsp;·&nbsp; "
                  f"scanned {meta['scanned']} tickers &nbsp;·&nbsp; {meta['matched']} matched "
                  f"&nbsp;·&nbsp; price ≤ ${meta['max_price']:.2f}", note),
        Spacer(1, 10),
    ]

    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=body, fontSize=9.5, leading=12, spaceBefore=8, spaceAfter=2,
                        textColor=colors.HexColor("#333333"), fontName="Helvetica-Bold")

    header = ["Ticker", "Score", "Price", "Resistance", "To res.", "Base range",
              "Vol ratio", "Avg $ vol", "Mkt cap", "RSI", "Industry / setup"]
    widths = [0.7, 0.5, 0.7, 0.8, 0.65, 0.75, 0.65, 0.75, 0.65, 0.45, 2.8]

    def cap(v):
        return "—" if not v else (f"${v/1e9:.2f}B" if v >= 1e9 else f"${v/1e6:.0f}M")

    def make_table(rows: "pd.DataFrame", cur: str):
        sym = "C$" if cur == "CAD" else "$"
        data = [header]
        for r in rows.itertuples():
            ind = f"<i>{escape(r.industry)}</i> — " if r.industry else ""
            data.append([
                Paragraph(f'<b><link href="https://finance.yahoo.com/chart/{r.ticker}" '
                          f'color="#1a4fd6">{r.ticker}</link></b>', cell),
                f"{r.score:.0f}",
                f"{sym}{r.price:,.3f}", f"{sym}{r.resistance:,.3f}", f"{r.dist_to_res_pct:+.1f}%",
                f"{r.base_range_pct:.0f}%", f"{r.vol_ratio:.1f}x",
                f"{sym}{r.avg_dollar_vol/1e6:.2f}M", cap(r.market_cap), f"{r.rsi:.0f}",
                Paragraph(ind + escape(r.setup), cell),
            ])
        t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#555555")),
            ("ALIGN", (1, 1), (-2, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#999999")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#dddddd")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f6")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, r in enumerate(rows.itertuples(), start=1):
            s = min(max(r.score, 0), 100) / 100
            bg = colors.Color(1 - 0.55 * s, 0.55 + 0.35 * s, 0.45, alpha=0.35)
            style += [("BACKGROUND", (1, i), (1, i), bg),
                      ("FONTNAME", (1, i), (1, i), "Helvetica-Bold")]
            if r.dist_to_res_pct < 0:
                style.append(("TEXTCOLOR", (4, i), (4, i), colors.HexColor("#1e8a3c")))
        t.setStyle(TableStyle(style))
        return t

    for mkt in ("US", "CA"):
        part = table[table["market"] == mkt]
        if part.empty:
            continue
        cur = MARKETS[mkt]["currency"]
        story.append(Paragraph(f"{MARKETS[mkt]['label']} — {len(part)} setups", h2))
        for sector, grp in part.groupby("sector", sort=True):
            grp = grp.sort_values("score", ascending=False)
            story.append(Paragraph(f"{escape(sector)}  ({len(grp)})", h3))
            story.append(make_table(grp, cur))
        story.append(Spacer(1, 8))
    story.append(Spacer(1, 6))

    if meta.get("long_term"):
        story.append(Paragraph(
            "<b>Long-term rulebook.</b> Every name here passed all of: price above a rising 50-day average, "
            "which is above the 200-day; price within 45% of its 52-week high; 14-day ATR under 8% of price; "
            "a 50-day base tighter than 30% with price within 6% of its top; ≥ $1M average daily dollar volume; "
            "price ≥ $0.50; market cap ≥ $25M. Score rewards tight bases, up-day vs down-day volume "
            "(<i>accumulation</i>), 3-month performance versus the S&amp;P 500, and a healthy RSI.", note))
        story.append(Spacer(1, 6))
    base_label = "50-day" if meta.get("long_term") else "20-day"
    story.append(Paragraph(
        f"<b>How to read it.</b> <i>Resistance</i> is the {base_label} high; <i>To res.</i> is how far price sits "
        "below it (negative = already broke above). <i>Base range</i> is how tight the consolidation is — "
        "tighter is better. <i>Vol ratio</i> compares recent volume to the base average. "
        "Score 70+ is a strong setup, 40–55 is early. Canadian names are in CAD, US names in USD; "
        "results are grouped by sector within each market. Tickers link to their Yahoo chart. "
        "This is a screen, not a recommendation: confirm the chart, check recent filings for dilution or "
        "offerings, and use stops.", note))
    doc.build(story)


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="PennyScan v3")
    p.add_argument("--preset", choices=list(PRESETS))
    p.add_argument("--tickers", help="file with one ticker per line (skips the screener)")
    p.add_argument("--limit", type=int)
    p.add_argument("--max-price", type=float)
    p.add_argument("--min-price", type=float, default=0.10)
    p.add_argument("--min-avg-vol", type=int)
    p.add_argument("--min-dollar-vol", type=float, default=300_000)
    p.add_argument("--min-score", type=float)
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--market", choices=["US", "CA", "both"], help="US, CA or both")
    p.add_argument("--no-open", action="store_true", help="don't open the PDF")
    p.add_argument("--out", default=HERE, help="folder to save reports into")
    p.add_argument("--tag", default="", help="label added to the report filename")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    preset = a.preset or (choose_preset() if INTERACTIVE else "quick")
    cfg = dict(PRESETS[preset])
    for k in ("limit", "max_price", "min_avg_vol", "min_score"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    if a.market:
        markets = ["US", "CA"] if a.market == "both" else [a.market]
    else:
        markets = choose_markets() if INTERACTIVE else ["US", "CA"]

    print()
    if a.tickers:
        with open(a.tickers) as f:
            universe = [(l.strip().upper(), guess_market(l.strip()))
                        for l in f if l.strip() and not l.startswith("#")]
    else:
        universe = []
        for m in markets:
            universe += build_universe(cfg["max_price"], cfg["min_avg_vol"], cfg["limit"], m)
    universe = list(dict.fromkeys(universe))
    if not universe:
        print("\nCouldn't build a stock list from any source. Check your internet connection "
              "and try again, or use --tickers list.txt.")
        pause(); return

    long_term = cfg.get("long_term", False)
    period = LT["history"] if long_term else "6mo"
    bench = benchmark_ret3m() if long_term else 0.0
    if long_term:
        print(f"S&P 500 3-month return: {bench*100:+.1f}%  (relative-strength benchmark)")
    print(f"Downloading {period} of history for {len(universe)} tickers …")
    results, scanned, t0 = [], 0, time.time()
    for i, (t, m) in enumerate(universe, 1):
        print(f"  {i:>4}/{len(universe)}  {t:<9} found so far: {len(results)}", end="\r", flush=True)
        df = fetch(t, period=period)
        if df is None or len(df) < 60:
            continue
        scanned += 1
        try:
            if long_term:
                row = analyze_long_term(t, df, cfg["max_price"], m, bench)
            else:
                row = analyze(t, df, a.min_price, cfg["max_price"], a.min_dollar_vol, m)
            if row and row.score >= cfg["min_score"]:
                results.append(row)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.12)
    print(f"\nDone in {time.time()-t0:.0f}s — {scanned} scanned, {len(results)} setups found.\n")

    if not results:
        print("No setups matched today. Try the Deep scan or a lower --min-score.")
        pause(); return

    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:a.top * 2 if long_term else a.top]
    print(f"Looking up sector / market cap for {len(results)} matches …")
    for r in results:
        r.sector, r.industry, r.market_cap = lookup_sector(r.ticker)
    if long_term:
        before = len(results)
        results = [r for r in results if r.market_cap == 0 or r.market_cap >= LT["min_market_cap"]]
        if before - len(results):
            print(f"  dropped {before - len(results)} below ${LT['min_market_cap']/1e6:.0f}M market cap")
        results = results[:a.top]
        if not results:
            print("No setups survived the long-term filters today.")
            pause(); return

    table = pd.DataFrame([asdict(r) for r in results])
    table = table.sort_values(["market", "sector", "score"],
                              ascending=[True, True, False]).reset_index(drop=True)
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", None)
    print(table[["ticker", "currency", "sector", "price", "resistance", "dist_to_res_pct",
                 "vol_ratio", "score", "setup"]].to_string(index=False))

    # --- save: PDF first, unique names every run, CSV failure never kills the run ---
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    tag = f"{a.tag}_" if a.tag else ""
    pdf_path = os.path.join(a.out, f"pennyscan_{tag}{stamp}.pdf")
    csv_path = os.path.join(a.out, f"pennyscan_{tag}{stamp}.csv")
    meta = dict(when=datetime.now().strftime("%a %b %d, %Y %I:%M %p"), preset=preset,
                scanned=scanned, matched=len(results), max_price=cfg["max_price"],
                long_term=long_term)
    try:
        write_pdf(table, meta, pdf_path)
        print(f"\nSaved PDF: {pdf_path}")
    except PermissionError:
        pdf_path = pdf_path.replace(".pdf", "_1.pdf")
        write_pdf(table, meta, pdf_path)
        print(f"\nSaved PDF: {pdf_path}")
    try:
        table.to_csv(csv_path, index=False)
        print(f"Saved CSV: {csv_path}")
    except PermissionError:
        print("CSV not saved (a previous one is open in another program) — PDF is fine.")

    if not a.no_open:
        try:
            os.startfile(pdf_path)  # Windows
        except (AttributeError, OSError):
            webbrowser.open("file://" + pdf_path)
    pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:  # noqa: BLE001
        print(f"\nSomething went wrong: {type(e).__name__}: {e}")
        pause()
