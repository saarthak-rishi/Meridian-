"""
UI windows for meridian.

each function renders one panel. these are dumb renderers -- they take
ready-to-display data and draw it. no network calls, no math allowed
in this file. if a panel needs more data, add it upstream in
data_provider or analytics.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ---------------------------------------------------------------------------
# palette  (intentionally restrained -- 2 mood colors + greys + 1 accent)
# ---------------------------------------------------------------------------

COLOR_BG: str       = "#0E1117"
COLOR_PANEL: str    = "#13161D"
COLOR_BORDER: str   = "#1F242E"
COLOR_DIVIDER: str  = "#262B36"
COLOR_TEXT: str     = "#E2E5EB"
COLOR_DIM: str      = "#9097A4"
COLOR_FAINT: str    = "#5C6370"
COLOR_UP: str       = "#22A87D"   # gains
COLOR_DOWN: str     = "#E04F5F"   # losses
COLOR_NEUTRAL: str  = "#7E8AA0"
COLOR_ACCENT: str   = "#D9A441"   # MA overlay, focus highlights

MONO: str = "ui-monospace, 'JetBrains Mono', Consolas, 'SF Mono', Menlo, monospace"


# ---------------------------------------------------------------------------
# formatters
# ---------------------------------------------------------------------------

def _fmt_num(x: float, places: int = 2) -> str:
    try:
        x = float(x)
        return f"{x:,.{places}f}" if x else "—"
    except Exception:
        return "—"


def _fmt_signed(x: float, places: int = 2) -> str:
    try:
        x = float(x)
        return f"{x:+,.{places}f}"
    except Exception:
        return "—"


def _fmt_volume(x: int) -> str:
    """volume in indian lakh / crore notation."""
    try:
        x = int(x)
        if not x:
            return "—"
        a = abs(x)
        if a >= 1_00_00_000:
            return f"{x/1_00_00_000:.2f} Cr"
        if a >= 1_00_000:
            return f"{x/1_00_000:.2f} L"
        return f"{x:,}"
    except Exception:
        return "—"


def _fmt_fx(x: float) -> str:
    try:
        x = float(x)
        if not x:
            return "—"
        return f"{x:.4f}" if x < 1 else f"{x:,.2f}"
    except Exception:
        return "—"


def _unicode_sparkline(values: List[float], width: int = 8) -> str:
    """tiny inline sparkline rendered with unicode block characters."""
    blocks = "▁▂▃▄▅▆▇█"
    if not values or len(values) < 2:
        return ""
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = list(values)
    lo, hi = min(sampled), max(sampled)
    if hi == lo:
        return blocks[len(blocks) // 2] * len(sampled)
    span = hi - lo
    n = len(blocks)
    return "".join(blocks[min(n - 1, int(((v - lo) / span) * n))] for v in sampled)


# ---------------------------------------------------------------------------
# small UI primitive -- consistent section header
# ---------------------------------------------------------------------------

def _section_label(text: str) -> None:
    """uppercase, dimmed, letter-spaced section header with hairline underline."""
    st.markdown(
        f"<div style='font-family:{MONO};color:{COLOR_DIM};"
        f"font-size:10px;letter-spacing:2px;text-transform:uppercase;"
        f"margin:0 0 10px 0;padding-bottom:5px;"
        f"border-bottom:1px solid {COLOR_BORDER};'>{text}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# macro strip -- flat dense tape (no card chrome, just hairline dividers)
# ---------------------------------------------------------------------------

def render_macro_strip(macro: Dict[str, Dict[str, float]]) -> None:
    """top-of-screen tape -- one row, columns separated by hairlines."""
    if not macro:
        return

    cells = []
    for i, (name, data) in enumerate(macro.items()):
        price = float(data.get("price", 0.0))
        chg = float(data.get("change", 0.0))
        pct = float(data.get("pct_change", 0.0))
        color = COLOR_UP if chg >= 0 else COLOR_DOWN
        arrow = "▲" if chg >= 0 else "▼"
        border = "" if i == 0 else f"border-left:1px solid {COLOR_DIVIDER};"
        cells.append(
            f"<div style='flex:1;padding:9px 18px;{border}'>"
            f"<div style='color:{COLOR_DIM};font-size:9px;letter-spacing:1.5px;"
            f"text-transform:uppercase;'>{name}</div>"
            f"<div style='color:{COLOR_TEXT};font-size:18px;font-weight:500;"
            f"margin-top:3px;font-variant-numeric:tabular-nums;'>{price:,.2f}</div>"
            f"<div style='color:{color};font-size:11px;margin-top:1px;"
            f"font-variant-numeric:tabular-nums;'>"
            f"{arrow} {_fmt_signed(chg)}"
            f"<span style='color:{COLOR_FAINT};margin:0 6px;'>·</span>"
            f"{_fmt_signed(pct)}%</div>"
            f"</div>"
        )

    st.markdown(
        f"<div style='display:flex;font-family:{MONO};"
        f"background:{COLOR_PANEL};border:1px solid {COLOR_BORDER};"
        f"border-radius:2px;'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# window A -- candlestick + MA  (+ last-price marker line)
# ---------------------------------------------------------------------------

def render_candlestick_chart(df: pd.DataFrame, ticker: str, ma_col: str = "MA5") -> None:
    """
    OHLC candles with the moving average overlaid and a dotted line at
    the last close (with a price tag on the right axis).
    """
    _section_label(f"{ticker} · 1m candles · {ma_col.lower()} overlay")

    if df is None or df.empty:
        st.info("no historical price data available.")
        return

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=COLOR_UP, decreasing_line_color=COLOR_DOWN,
        increasing_fillcolor=COLOR_UP, decreasing_fillcolor=COLOR_DOWN,
        line=dict(width=1),
        name="OHLC", showlegend=False,
    ))
    if ma_col in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[ma_col],
            mode="lines",
            line=dict(color=COLOR_ACCENT, width=1.2),
            name=ma_col,
        ))

    # last-close marker -- tiny touch that makes it feel like a real terminal
    try:
        last_close = float(df["Close"].iloc[-1])
        fig.add_hline(
            y=last_close,
            line=dict(color=COLOR_TEXT, width=0.7, dash="dot"),
            annotation_text=f" {last_close:,.2f} ",
            annotation_position="right",
            annotation=dict(
                font=dict(family=MONO, color=COLOR_BG, size=10),
                bgcolor=COLOR_TEXT,
                borderpad=2,
                showarrow=False,
            ),
        )
    except Exception:
        pass

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=COLOR_PANEL, plot_bgcolor=COLOR_PANEL,
        height=400,
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(family=MONO, color=COLOR_TEXT, size=10),
        xaxis=dict(
            gridcolor=COLOR_BORDER, rangeslider=dict(visible=False),
            showspikes=True, spikecolor=COLOR_FAINT,
            spikethickness=1, spikedash="dot",
        ),
        yaxis=dict(
            gridcolor=COLOR_BORDER, side="right", tickformat=",.2f",
            showspikes=True, spikecolor=COLOR_FAINT,
            spikethickness=1, spikedash="dot",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", x=0.01, y=0.99,
            font=dict(color=COLOR_DIM, size=10),
        ),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# window A (live) -- TradingView Advanced Chart widget
# ---------------------------------------------------------------------------

def render_tradingview_chart(
    symbol: str,
    exchange: str = "NSE",
    height: int = 620,
) -> None:
    """
    embed TradingView's free Advanced Chart widget.

    way more useful than a static plotly chart -- proper intraday candles,
    drawing tools, dozens of built-in indicators, multiple timeframes, and
    real (15-min delayed for free NSE) data. zero auth, no api key.

    runs inside streamlit.components.v1.html because <script> tags don't
    execute when injected via st.markdown.

    Args:
        symbol:   plain NSE symbol, e.g. "RELIANCE", "TCS", "NIFTY".
        exchange: TradingView exchange prefix. defaults to "NSE".
        height:   widget height in pixels.
    """
    # local import -- keeps the module's top-level imports minimal
    from streamlit.components.v1 import html as _st_html

    sym = (symbol or "").strip().upper()
    _section_label(f"{sym.lower()} · live chart · tradingview")

    tv_symbol = f"{exchange}:{sym}"

    # use the standard streamlit-gallery pattern: explicit width/height in
    # the config (not autosize) so the chart fills the iframe reliably.
    widget_html = f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <div class="tradingview-widget-copyright">
        <a href="https://www.tradingview.com/symbols/{tv_symbol}/"
           rel="noopener nofollow" target="_blank">
          {sym} chart by tradingview
        </a>
      </div>
      <script type="text/javascript"
              src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
              async>
      {{
        "width": "100%",
        "height": {height},
        "symbol": "{tv_symbol}",
        "interval": "D",
        "timezone": "Asia/Kolkata",
        "theme": "dark",
        "style": "1",
        "locale": "in",
        "toolbar_bg": "{COLOR_PANEL}",
        "backgroundColor": "{COLOR_PANEL}",
        "gridColor": "{COLOR_BORDER}",
        "enable_publishing": false,
        "allow_symbol_change": false,
        "withdateranges": true,
        "hide_side_toolbar": false,
        "hide_top_toolbar": false,
        "hide_legend": false,
        "save_image": false,
        "studies": [
          "MASimple@tv-basicstudies",
          "Volume@tv-basicstudies"
        ],
        "support_host": "https://www.tradingview.com"
      }}
      </script>
    </div>
    <style>
      .tradingview-widget-copyright {{
        font-family: {MONO};
        font-size: 9px;
        color: {COLOR_FAINT};
        text-align: right;
        padding: 4px 6px;
        letter-spacing: 0.5px;
      }}
      .tradingview-widget-copyright a {{
        color: {COLOR_FAINT};
        text-decoration: none;
      }}
    </style>
    """
    _st_html(widget_html, height=height + 36)


# ---------------------------------------------------------------------------
# window B -- live quote panel
# ---------------------------------------------------------------------------

def render_metric_board(quote: Dict[str, Any], aggregate_sentiment_score: float) -> None:
    """
    live quote panel: headline price, key stats grid, day-range bar,
    and a slim news-sentiment bar (no half-circle gauges -- those scream
    'streamlit template').
    """
    symbol = quote.get("symbol", "")
    _section_label(f"quote · {symbol}")

    if not quote:
        st.info("quote unavailable.")
        return

    last = float(quote.get("last_price", 0.0))
    chg = float(quote.get("change", 0.0))
    pct = float(quote.get("pct_change", 0.0))
    color = COLOR_UP if chg >= 0 else COLOR_DOWN
    arrow = "▲" if chg >= 0 else "▼"

    # headline price row
    st.markdown(
        f"<div style='font-family:{MONO};display:flex;align-items:baseline;"
        f"gap:14px;margin-bottom:14px;flex-wrap:wrap;'>"
        f"<div style='color:{COLOR_TEXT};font-size:30px;font-weight:600;"
        f"letter-spacing:-0.5px;font-variant-numeric:tabular-nums;'>"
        f"₹{last:,.2f}</div>"
        f"<div style='color:{color};font-size:13px;"
        f"font-variant-numeric:tabular-nums;'>"
        f"{arrow} {_fmt_signed(chg)} ({_fmt_signed(pct)}%)</div>"
        f"<div style='color:{COLOR_FAINT};font-size:10px;margin-left:auto;'>"
        f"{quote.get('source','')} · {quote.get('timestamp','')}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 3x2 stats grid
    rows = [
        ("day high",   _fmt_num(quote.get("day_high", 0.0))),
        ("day low",    _fmt_num(quote.get("day_low", 0.0))),
        ("vwap",       _fmt_num(quote.get("vwap", 0.0))),
        ("prev close", _fmt_num(quote.get("previous_close", 0.0))),
        ("volume",     _fmt_volume(int(quote.get("volume", 0)))),
        ("change",     _fmt_signed(chg)),
    ]
    grid = (
        f"<div style='display:grid;grid-template-columns:repeat(3,1fr);"
        f"gap:12px 18px;font-family:{MONO};margin-bottom:16px;'>"
    )
    for label, value in rows:
        grid += (
            f"<div>"
            f"<div style='color:{COLOR_DIM};font-size:9px;text-transform:uppercase;"
            f"letter-spacing:1.2px;'>{label}</div>"
            f"<div style='color:{COLOR_TEXT};font-size:13px;margin-top:2px;"
            f"font-variant-numeric:tabular-nums;'>{value}</div>"
            f"</div>"
        )
    grid += "</div>"
    st.markdown(grid, unsafe_allow_html=True)

    _render_range_bar(
        low=float(quote.get("day_low", 0.0)),
        high=float(quote.get("day_high", 0.0)),
        current=last,
    )
    _render_sentiment_bar(aggregate_sentiment_score)


def _render_range_bar(low: float, high: float, current: float) -> None:
    """horizontal bar showing where current price sits in the day's range."""
    if not (low and high and high > low and current):
        return
    pos = max(0.0, min(100.0, (current - low) / (high - low) * 100.0))
    st.markdown(
        f"<div style='font-family:{MONO};margin-bottom:14px;'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
        f"margin-bottom:5px;'>"
        f"<span style='color:{COLOR_DIM};font-size:9px;text-transform:uppercase;"
        f"letter-spacing:1.2px;'>day range</span>"
        f"<span style='color:{COLOR_FAINT};font-size:10px;"
        f"font-variant-numeric:tabular-nums;'>{pos:.0f}% of range</span>"
        f"</div>"
        f"<div style='position:relative;height:4px;background:{COLOR_BORDER};"
        f"border-radius:2px;'>"
        f"<div style='position:absolute;left:calc({pos}% - 1px);top:-3px;"
        f"width:2px;height:10px;background:{COLOR_TEXT};'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;color:{COLOR_FAINT};"
        f"font-size:10px;margin-top:4px;font-variant-numeric:tabular-nums;'>"
        f"<span>{low:,.2f}</span><span>{high:,.2f}</span>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_sentiment_bar(score: float) -> None:
    """slim horizontal sentiment bar with a marker (replaces the half-circle gauge)."""
    try:
        score = float(score)
    except Exception:
        score = 0.0
    score = max(-1.0, min(1.0, score))
    pos = (score + 1.0) / 2.0 * 100.0
    if score > 0.05:
        color, label = COLOR_UP, "positive"
    elif score < -0.05:
        color, label = COLOR_DOWN, "negative"
    else:
        color, label = COLOR_NEUTRAL, "neutral"

    st.markdown(
        f"<div style='font-family:{MONO};'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
        f"margin-bottom:5px;'>"
        f"<span style='color:{COLOR_DIM};font-size:9px;text-transform:uppercase;"
        f"letter-spacing:1.2px;'>news sentiment</span>"
        f"<span style='color:{color};font-size:11px;'>"
        f"{label} <span style='color:{COLOR_FAINT};'>{score:+.2f}</span></span>"
        f"</div>"
        f"<div style='position:relative;height:5px;background:linear-gradient("
        f"to right,{COLOR_DOWN}40 0%,{COLOR_NEUTRAL}30 50%,{COLOR_UP}40 100%);"
        f"border-radius:2px;'>"
        f"<div style='position:absolute;left:calc({pos}% - 1px);top:-3px;"
        f"width:2px;height:11px;background:{COLOR_TEXT};'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;color:{COLOR_FAINT};"
        f"font-size:9px;margin-top:3px;'>"
        f"<span>-1.0</span><span>0</span><span>+1.0</span>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# window C -- FX desk (clean table + unicode sparklines)
# ---------------------------------------------------------------------------

def render_forex_desk(forex_data: Dict[str, Dict[str, Any]]) -> None:
    """
    tabular FX desk with inline unicode sparklines.

    a table is way more terminal-feeling than 2x2 cards and packs more
    info into less space.
    """
    _section_label("fx · inr crosses")

    if not forex_data:
        st.info("no fx data available.")
        return

    headers = [("pair", "left"), ("rate", "right"), ("chg", "right"),
               ("%chg", "right"), ("5d", "right")]
    header_html = "".join(
        f"<th style='padding:6px 8px;color:{COLOR_DIM};font-size:9px;"
        f"letter-spacing:1.5px;font-weight:500;text-align:{align};"
        f"text-transform:uppercase;border-bottom:1px solid {COLOR_DIVIDER};'>"
        f"{label}</th>"
        for label, align in headers
    )

    rows_html = ""
    for pair, data in forex_data.items():
        rate = float(data.get("rate", 0.0))
        chg = float(data.get("change", 0.0))
        pct = float(data.get("pct_change", 0.0))
        history = data.get("history", []) or []
        color = COLOR_UP if chg >= 0 else COLOR_DOWN
        spark = _unicode_sparkline(history, width=8)
        rows_html += (
            f"<tr style='border-bottom:1px solid {COLOR_BORDER};'>"
            f"<td style='padding:10px 8px;color:{COLOR_TEXT};font-size:12px;'>"
            f"{pair}</td>"
            f"<td style='padding:10px 8px;color:{COLOR_TEXT};font-size:13px;"
            f"text-align:right;font-variant-numeric:tabular-nums;'>"
            f"{_fmt_fx(rate)}</td>"
            f"<td style='padding:10px 8px;color:{color};font-size:12px;"
            f"text-align:right;font-variant-numeric:tabular-nums;'>"
            f"{_fmt_signed(chg, 4)}</td>"
            f"<td style='padding:10px 8px;color:{color};font-size:12px;"
            f"text-align:right;font-variant-numeric:tabular-nums;'>"
            f"{_fmt_signed(pct)}%</td>"
            f"<td style='padding:10px 8px;color:{color};font-size:15px;"
            f"text-align:right;line-height:1;letter-spacing:-1.5px;'>"
            f"{spark}</td>"
            f"</tr>"
        )

    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;font-family:{MONO};'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# window D -- news feed (sentiment marker on the left, no full bg tint)
# ---------------------------------------------------------------------------

def render_news_feed(scored_news: List[Dict[str, Any]], max_items: int = 25) -> None:
    """
    compact news stream. small colored bar on the left flags sentiment;
    headline text stays neutral so it's actually readable.
    """
    _section_label("market headlines")

    if not scored_news:
        st.info("no headlines available.")
        return

    items_html = ""
    for item in scored_news[:max_items]:
        label = str(item.get("sentiment", "Neutral"))
        try:
            score = float(item.get("score", 0.0))
        except Exception:
            score = 0.0
        if label == "Positive":
            accent = COLOR_UP
        elif label == "Negative":
            accent = COLOR_DOWN
        else:
            accent = COLOR_NEUTRAL

        title = (str(item.get("title", ""))
                 .replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))
        link = str(item.get("link", "#"))
        source = str(item.get("source", ""))
        published = str(item.get("published", ""))

        items_html += (
            f"<div style='display:flex;gap:10px;padding:10px 4px;"
            f"border-bottom:1px solid {COLOR_BORDER};'>"
            f"<div style='width:3px;flex-shrink:0;background:{accent};"
            f"margin-top:5px;height:14px;border-radius:1px;'></div>"
            f"<div style='flex:1;min-width:0;'>"
            f"<a href='{link}' target='_blank' rel='noopener' "
            f"style='color:{COLOR_TEXT};text-decoration:none;font-size:12.5px;"
            f"line-height:1.45;'>{title}</a>"
            f"<div style='color:{COLOR_FAINT};font-size:10px;margin-top:4px;'>"
            f"{source} <span style='color:{COLOR_DIVIDER};'>·</span> {published} "
            f"<span style='color:{COLOR_DIVIDER};'>·</span> "
            f"<span style='color:{accent};'>{label.lower()}</span> "
            f"<span style='color:{COLOR_FAINT};'>{score:+.2f}</span>"
            f"</div>"
            f"</div>"
            f"</div>"
        )

    st.markdown(
        f"<div style='height:560px;overflow-y:auto;padding-right:6px;"
        f"font-family:{MONO};'>{items_html}</div>",
        unsafe_allow_html=True,
    )
