"""
meridian -- a small indian markets dashboard.

streamlit entry point. wires the data -> analytics -> UI flow together
and handles the global ticker search.

to run:
    streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone

import streamlit as st

import analytics as an
import components as ui
import data_provider as dp


# ---------------------------------------------------------------------------
# page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Meridian",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# global styling
# ---------------------------------------------------------------------------

GLOBAL_CSS = f"""
<style>
    .stApp {{ background-color: {ui.COLOR_BG}; }}

    /* kill streamlit's default white header / toolbar / footer */
    header[data-testid="stHeader"] {{
        background-color: {ui.COLOR_BG} !important;
        height: 0 !important;
        visibility: hidden !important;
    }}
    [data-testid="stToolbar"]      {{ display: none !important; }}
    [data-testid="stDecoration"]   {{ display: none !important; }}
    [data-testid="stStatusWidget"] {{ display: none !important; }}
    #MainMenu {{ display: none !important; }}
    footer    {{ display: none !important; }}

    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1700px !important;
    }}

    h1, h2, h3, h4, h5, h6 {{
        font-family: {ui.MONO} !important;
        color: {ui.COLOR_TEXT} !important;
        letter-spacing: 0.5px;
    }}

    /* ticker search input */
    .stTextInput input {{
        background-color: {ui.COLOR_PANEL} !important;
        color: {ui.COLOR_TEXT} !important;
        font-family: {ui.MONO} !important;
        border: 1px solid {ui.COLOR_BORDER} !important;
        border-radius: 2px !important;
        letter-spacing: 1.5px !important;
        font-size: 14px !important;
        padding: 10px 14px !important;
        height: 42px !important;
    }}
    .stTextInput input:focus {{
        border-color: {ui.COLOR_ACCENT} !important;
        box-shadow: 0 0 0 1px {ui.COLOR_ACCENT} !important;
        outline: none !important;
    }}
    .stTextInput input::placeholder {{
        color: {ui.COLOR_FAINT} !important;
        letter-spacing: 0.5px;
    }}

    .stAlert {{
        background-color: {ui.COLOR_PANEL} !important;
        border: 1px solid {ui.COLOR_BORDER} !important;
        color: {ui.COLOR_TEXT} !important;
        font-family: {ui.MONO} !important;
    }}

    hr {{
        border: none !important;
        border-top: 1px solid {ui.COLOR_BORDER} !important;
        margin: 10px 0 !important;
    }}

    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: {ui.COLOR_BG}; }}
    ::-webkit-scrollbar-thumb {{ background: {ui.COLOR_DIVIDER}; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #3A4150; }}
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# cached wrappers -- short TTLs so the dashboard still feels live
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def _cached_quote(ticker: str):
    return dp.get_stock_quote(ticker)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_history(ticker: str, period: str):
    return dp.get_historical_data(ticker, period)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_macro():
    return dp.get_macro_indicators()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_forex():
    return dp.get_forex_rates()


@st.cache_data(ttl=180, show_spinner=False)
def _cached_news(limit: int):
    return dp.get_rss_news_feed(limit=limit)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# IST is a fixed UTC+5:30 offset -- avoids needing tzdata installed.
_IST = timezone(timedelta(hours=5, minutes=30))


def _nse_status_now() -> tuple[str, bool, datetime]:
    """
    return (label, is_open, ist_now).
    NSE cash market hours: mon-fri 09:15-15:30 IST.
    """
    now = datetime.now(_IST)
    weekday_open = now.weekday() < 5
    market_open = dtime(9, 15) <= now.time() < dtime(15, 30)
    is_open = weekday_open and market_open
    return ("nse open" if is_open else "nse closed"), is_open, now


# ---------------------------------------------------------------------------
# header -- brand · search · status/clock
# ---------------------------------------------------------------------------

brand_col, search_col, status_col = st.columns([1, 2, 1], gap="medium")

with brand_col:
    st.markdown(
        f"<div style='padding-top:8px;font-family:{ui.MONO};'>"
        f"<span style='color:{ui.COLOR_TEXT};font-size:20px;font-weight:600;"
        f"letter-spacing:4px;'>MERIDIAN</span>"
        f"<span style='color:{ui.COLOR_FAINT};font-size:9px;margin-left:10px;"
        f"letter-spacing:1.5px;'>v1.0</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

with search_col:
    raw_ticker = st.text_input(
        label="search",
        value="RELIANCE",
        max_chars=20,
        label_visibility="collapsed",
        placeholder="search ticker  ·  e.g. RELIANCE, TCS, INFY",
        key="ticker_input",
    )
    ticker = (raw_ticker or "").strip().upper()

with status_col:
    status_label, is_open, ist_now = _nse_status_now()
    status_color = ui.COLOR_UP if is_open else ui.COLOR_FAINT
    st.markdown(
        f"<div style='padding-top:6px;text-align:right;font-family:{ui.MONO};'>"
        f"<div style='color:{ui.COLOR_TEXT};font-size:14px;"
        f"font-variant-numeric:tabular-nums;'>"
        f"{ist_now.strftime('%H:%M')}"
        f" <span style='color:{ui.COLOR_FAINT};font-size:10px;'>IST</span>"
        f"</div>"
        f"<div style='color:{status_color};font-size:10px;letter-spacing:1.5px;"
        f"text-transform:uppercase;margin-top:2px;'>● {status_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("<hr>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# macro strip (always visible)
# ---------------------------------------------------------------------------

ui.render_macro_strip(_cached_macro())
st.markdown("<hr>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# need a ticker to render the workspace
# ---------------------------------------------------------------------------

if not ticker:
    st.warning("type a ticker above to load the workspace.")
    st.stop()


# ---------------------------------------------------------------------------
# fetch + process
# ---------------------------------------------------------------------------

with st.spinner(f"loading {ticker}..."):
    quote    = _cached_quote(ticker)
    forex    = _cached_forex()
    news_raw = _cached_news(30)

# (historical bars + MA no longer needed -- TradingView handles charting)
scored_news       = an.score_news_batch(news_raw)
sentiment_overall = an.aggregate_sentiment(scored_news)


# ---------------------------------------------------------------------------
# 2-column desk
# ---------------------------------------------------------------------------

left_col, right_col = st.columns([3, 2], gap="medium")

with left_col:
    ui.render_tradingview_chart(ticker)
    st.markdown("<hr>", unsafe_allow_html=True)
    ui.render_metric_board(quote, sentiment_overall)

with right_col:
    ui.render_forex_desk(forex)
    st.markdown("<hr>", unsafe_allow_html=True)
    ui.render_news_feed(scored_news, max_items=25)


# ---------------------------------------------------------------------------
# footer
# ---------------------------------------------------------------------------

st.markdown("<hr>", unsafe_allow_html=True)
st.markdown(
    f"<div style='color:{ui.COLOR_FAINT};font-family:{ui.MONO};"
    f"font-size:10px;letter-spacing:0.5px;display:flex;"
    f"justify-content:space-between;margin-top:4px;'>"
    f"<span>meridian · indian markets dashboard</span>"
    f"<span>data: nse · yfinance · moneycontrol · et</span>"
    f"</div>",
    unsafe_allow_html=True,
)
