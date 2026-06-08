"""
data fetching layer.

handles all the network calls -- live nse equity quotes, historical bars
from yahoo, indian macro indices, INR forex rates, and rss news headlines.
every function catches its own errors and returns a sensible default so
the dashboard never crashes when an upstream api is flaky.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

import feedparser
import pandas as pd
import yfinance as yf

# nsepython is the primary live quote source. guarded import because it
# sometimes touches the network at import time and can fail on first load.
try:
    from nsepython import nse_eq
    _NSE_AVAILABLE: bool = True
except Exception:
    nse_eq = None
    _NSE_AVAILABLE = False

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    )


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

NSE_SUFFIX: str = ".NS"

# top-of-screen tape (mix of equity benchmarks + the USD/INR cross because
# it sets the tone for everything else on an indian trading day).
MACRO_TICKERS: Dict[str, str] = {
    "NIFTY 50":   "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "INDIA VIX":  "^INDIAVIX",
    "USD/INR":    "USDINR=X",
}

# the four INR crosses i actually care about
FOREX_PAIRS: Dict[str, str] = {
    "USD/INR": "USDINR=X",
    "EUR/INR": "EURINR=X",
    "GBP/INR": "GBPINR=X",
    "JPY/INR": "JPYINR=X",
}

RSS_FEEDS: List[str] = [
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
]


# ---------------------------------------------------------------------------
# equity quote
# ---------------------------------------------------------------------------

def get_stock_quote(ticker: str) -> Dict[str, Any]:
    """
    fetch the latest cash-market quote for an NSE stock.

    tries nsepython first (richer snapshot from NSE), then falls back to a
    short yfinance pull if NSE rate-limits or blocks the request.

    Args:
        ticker: plain NSE symbol without suffix, e.g. "RELIANCE".

    Returns:
        Dict with last_price, change, pct_change, day_high, day_low, vwap,
        volume, previous_close, timestamp, source. empty dict {} if both
        sources fail.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {}

    # primary: yfinance (consistent, no rate-limits, works for every NSE stock)
    try:
        yf_ticker = yf.Ticker(f"{ticker}{NSE_SUFFIX}")
        hist = yf_ticker.history(period="5d", interval="1d")
        if hist.empty:
            raise ValueError(f"empty yfinance history for {ticker}")

        # yfinance returns the current (incomplete) trading day as the last
        # row, with OHLC = NaN until the day ends. drop those and use the
        # most recent COMPLETE bar instead.
        valid = hist.dropna(subset=["Open", "High", "Low", "Close"])
        if valid.empty:
            raise ValueError(f"no complete bars in yfinance history for {ticker}")
        last = valid.iloc[-1]

        if len(valid) >= 2:
            prev_close = float(valid.iloc[-2]["Close"])
        else:
            # only one complete bar -- use its own open as the reference
            prev_close = float(last["Open"])

        last_price = float(last["Close"])
        change = last_price - prev_close
        pct = (change / prev_close * 100.0) if prev_close else 0.0
        # typical-price VWAP proxy from the daily bar (no intraday tape on yahoo)
        vwap_proxy = float((last["High"] + last["Low"] + last["Close"]) / 3.0)

        quote: Dict[str, Any] = {
            "symbol":         ticker,
            "last_price":     last_price,
            "change":         float(change),
            "pct_change":     float(pct),
            "day_high":       float(last["High"]),
            "day_low":        float(last["Low"]),
            "vwap":           vwap_proxy,
            "volume":         int(last.get("Volume", 0) or 0),
            "previous_close": prev_close,
            "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source":         "yfinance",
        }
    except Exception as e:
        logger.error("yfinance quote failed for %s: %s", ticker, e)
        return {}

    # enhancement: pull live VWAP + volume from nsepython if it has them
    # (yfinance only gives daily bars, so its VWAP is a proxy. nsepython
    # can return a real intraday VWAP for liquid stocks during market hours.)
    if _NSE_AVAILABLE and nse_eq is not None:
        try:
            raw = nse_eq(ticker)
            if isinstance(raw, dict):
                price_info = raw.get("priceInfo", {}) or {}
                sec_wise = raw.get("securityWiseDP", {}) or {}
                nse_vwap = float(price_info.get("vwap", 0.0) or 0.0)
                nse_volume = int(sec_wise.get("quantityTraded", 0) or 0)
                nse_last = float(price_info.get("lastPrice", 0.0) or 0.0)
                # only swap in positive values (sanity check)
                if nse_vwap > 0:
                    quote["vwap"] = nse_vwap
                if nse_volume > 0:
                    quote["volume"] = nse_volume
                if nse_last > 0:
                    quote["last_price"] = nse_last
                    quote["change"] = float(price_info.get("change", 0.0) or 0.0)
                    quote["pct_change"] = float(price_info.get("pChange", 0.0) or 0.0)
                if nse_vwap > 0 or nse_volume > 0 or nse_last > 0:
                    quote["source"] = "yfinance+nsepython"
        except Exception as e:
            logger.warning("nsepython enhancement failed for %s: %s", ticker, e)

    return quote


# ---------------------------------------------------------------------------
# historical OHLCV
# ---------------------------------------------------------------------------

def get_historical_data(ticker: str, period: str = "1mo") -> pd.DataFrame:
    """
    fetch historical OHLCV bars via yfinance.

    Args:
        ticker: NSE symbol with or without ".NS" suffix. yahoo indices
                like "^NSEI" and fx symbols like "USDINR=X" pass through.
        period: yfinance period string: "5d","1mo","3mo","6mo","1y","2y",
                "5y","ytd","max".

    Returns:
        DataFrame indexed by date with [Open, High, Low, Close, Volume].
        empty DataFrame on failure.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return pd.DataFrame()

    if ticker.startswith("^") or ticker.endswith(NSE_SUFFIX) or "=" in ticker:
        symbol = ticker
    else:
        symbol = f"{ticker}{NSE_SUFFIX}"

    try:
        df = yf.download(symbol, period=period, progress=False, auto_adjust=False)
        if df is None or df.empty:
            logger.warning("yfinance returned empty history for %s (period=%s)", symbol, period)
            return pd.DataFrame()

        # flatten multi-index columns when yfinance returns them
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning("missing columns %s in history for %s", missing, symbol)
            return pd.DataFrame()

        df = df[required].dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        logger.error("historical fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# intraday OHLCV (for the live chart)
# ---------------------------------------------------------------------------

def get_intraday_data(
    ticker: str,
    interval: str = "5m",
    period: str = "3d",
) -> pd.DataFrame:
    """
    fetch intraday OHLCV bars via yfinance for the live candlestick chart.

    Usable intervals (yfinance) and their max look-back:
        1m, 2m, 5m  ──  max  7 days
        15m, 30m    ──  max 60 days
        1h          ──  max 730 days

    Args:
        ticker:   NSE symbol, e.g. "RELIANCE".
        interval: bar width ("1m", "5m", "15m", "30m", "1h", …).
        period:   how far back to fetch (depends on interval -- see above).

    Returns:
        DataFrame indexed by datetime with [Open, High, Low, Close, Volume].
        empty DataFrame on failure.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return pd.DataFrame()

    if ticker.startswith("^") or ticker.endswith(NSE_SUFFIX) or "=" in ticker:
        symbol = ticker
    else:
        symbol = f"{ticker}{NSE_SUFFIX}"

    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            logger.warning(
                "yfinance returned empty intraday data for %s (interval=%s, period=%s)",
                symbol, interval, period,
            )
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(
                "missing columns %s in intraday data for %s", missing, symbol,
            )
            return pd.DataFrame()

        df = df[required].dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        logger.error("intraday fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# macro indicators
# ---------------------------------------------------------------------------

def get_macro_indicators() -> Dict[str, Dict[str, float]]:
    """
    fetch the headline macro tape: nifty 50, nifty bank, india vix, usd/inr.

    Returns:
        mapping of name -> {price, change, pct_change}. failed indices
        come back zeroed so the UI never sees a missing key.
    """
    out: Dict[str, Dict[str, float]] = {}
    for name, sym in MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            if hist is None or hist.empty:
                raise ValueError("empty macro history")
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else float(hist["Open"].iloc[-1])
            change = last - prev
            pct = (change / prev * 100.0) if prev else 0.0
            out[name] = {"price": last, "change": float(change), "pct_change": float(pct)}
        except Exception as e:
            logger.error("macro fetch failed for %s (%s): %s", name, sym, e)
            out[name] = {"price": 0.0, "change": 0.0, "pct_change": 0.0}
    return out


# ---------------------------------------------------------------------------
# forex (INR crosses)
# ---------------------------------------------------------------------------

def get_forex_rates() -> Dict[str, Dict[str, Any]]:
    """
    fetch the major INR cross-rates from yfinance.

    each pair also returns a short price history so the UI can draw a
    sparkline next to the current rate.

    Returns:
        mapping of pair name (e.g. "USD/INR") -> {
            rate:        latest close,
            change:      absolute move vs prior close,
            pct_change:  % move vs prior close,
            history:     list of last 5 closes (for sparkline),
        }
        pairs that fail come back zeroed with an empty history list.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name, sym in FOREX_PAIRS.items():
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            if hist is None or hist.empty:
                raise ValueError("empty fx history")
            closes = hist["Close"].dropna().tolist()
            if not closes:
                raise ValueError("no close prices")
            last = float(closes[-1])
            prev = float(closes[-2]) if len(closes) > 1 else float(hist["Open"].iloc[-1])
            change = last - prev
            pct = (change / prev * 100.0) if prev else 0.0
            out[name] = {
                "rate":       last,
                "change":     float(change),
                "pct_change": float(pct),
                "history":    [float(c) for c in closes],
            }
        except Exception as e:
            logger.error("fx fetch failed for %s (%s): %s", name, sym, e)
            out[name] = {"rate": 0.0, "change": 0.0, "pct_change": 0.0, "history": []}
    return out


# ---------------------------------------------------------------------------
# rss news
# ---------------------------------------------------------------------------

def get_rss_news_feed(limit: int = 25) -> List[Dict[str, str]]:
    """
    pull and merge headlines from a few indian financial rss feeds.
    duplicates (matched by title) are dropped on a first-seen-wins basis.

    Args:
        limit: max headlines to return after merge + dedup.

    Returns:
        list of dicts: {title, link, source, published}.
    """
    items: List[Dict[str, str]] = []
    seen_titles: set = set()

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            src_name = (feed.feed.get("title") if hasattr(feed, "feed") else None) or url
            for entry in getattr(feed, "entries", []) or []:
                title = (entry.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                items.append({
                    "title":     title,
                    "link":      entry.get("link", ""),
                    "source":    src_name,
                    "published": entry.get("published", entry.get("updated", "")),
                })
        except Exception as e:
            logger.warning("rss parse failed for %s: %s", url, e)
            continue

    return items[:max(limit, 0)]


# ---------------------------------------------------------------------------
# quick smoke test -- python data_provider.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("== quote: RELIANCE ==")
    print(get_stock_quote("RELIANCE"))
    print("\n== macro ==")
    print(get_macro_indicators())
    print("\n== forex ==")
    print(get_forex_rates())
    print("\n== history (head) ==")
    print(get_historical_data("TCS", "1mo").head())
    print("\n== news (3) ==")
    for n in get_rss_news_feed(limit=3):
        print("-", n["title"])
