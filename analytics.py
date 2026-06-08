"""
math + sentiment.

pure functions only -- no streamlit, no network calls. takes raw data
from data_provider and returns processed structures the UI can render.
keeping this layer side-effect-free means every function is trivially
unit-testable on its own.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# VADER is the lightweight rule-based scorer NLTK ships. it's more than
# enough for terse financial headlines and doesn't need any model files
# beyond a small lexicon.
try:
    import nltk
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
except Exception:
    nltk = None
    SentimentIntensityAnalyzer = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VADER bootstrap
# ---------------------------------------------------------------------------

# cut-offs from the original VADER paper. anything inside [-0.05, 0.05]
# is treated as neutral so we don't over-react to tiny lexical noise.
POSITIVE_THRESHOLD: float = 0.05
NEGATIVE_THRESHOLD: float = -0.05

_SIA: Optional["SentimentIntensityAnalyzer"] = None


def _get_vader() -> Optional["SentimentIntensityAnalyzer"]:
    """lazy singleton for VADER. downloads the lexicon on first call if missing."""
    global _SIA
    if _SIA is not None:
        return _SIA
    if SentimentIntensityAnalyzer is None:
        logger.error("nltk not installed -- sentiment scoring disabled")
        return None
    try:
        _SIA = SentimentIntensityAnalyzer()
    except LookupError:
        # lexicon missing -- try a one-shot download then retry
        try:
            nltk.download("vader_lexicon", quiet=True)
            _SIA = SentimentIntensityAnalyzer()
        except Exception as e:
            logger.error("failed to bootstrap vader_lexicon: %s", e)
            return None
    except Exception as e:
        logger.error("unexpected VADER init error: %s", e)
        return None
    return _SIA


# ---------------------------------------------------------------------------
# sentiment
# ---------------------------------------------------------------------------

def analyze_headline_sentiment(headline: str) -> Tuple[str, float]:
    """
    score a single news headline with VADER.

    Args:
        headline: raw headline text.

    Returns:
        (label, compound_score) where label is one of
        "Positive" / "Negative" / "Neutral" and compound is in [-1, 1].
        returns ("Neutral", 0.0) on any failure.
    """
    sia = _get_vader()
    if sia is None or not headline:
        return ("Neutral", 0.0)
    try:
        scores = sia.polarity_scores(headline)
        compound = float(scores.get("compound", 0.0))
        if compound >= POSITIVE_THRESHOLD:
            label = "Positive"
        elif compound <= NEGATIVE_THRESHOLD:
            label = "Negative"
        else:
            label = "Neutral"
        return (label, compound)
    except Exception as e:
        logger.warning("VADER scoring failed: %s", e)
        return ("Neutral", 0.0)


def score_news_batch(headlines: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    attach sentiment + score fields to every headline dict in a batch.

    Args:
        headlines: list of dicts with at least a "title" key (as returned
                   by data_provider.get_rss_news_feed).

    Returns:
        a NEW list (input is not mutated) where each item has two extra
        keys -- "sentiment" (label str) and "score" (compound float).
    """
    enriched: List[Dict[str, Any]] = []
    for h in headlines or []:
        label, score = analyze_headline_sentiment(str(h.get("title", "")))
        item: Dict[str, Any] = dict(h)
        item["sentiment"] = label
        item["score"] = score
        enriched.append(item)
    return enriched


def aggregate_sentiment(scored: List[Dict[str, Any]]) -> float:
    """
    mean VADER compound score across a list of already-scored headlines.

    Returns:
        mean compound in [-1, 1]; 0.0 for an empty list.
    """
    if not scored:
        return 0.0
    vals = [float(x.get("score", 0.0)) for x in scored]
    return float(np.mean(vals)) if vals else 0.0


# ---------------------------------------------------------------------------
# technical indicators
# ---------------------------------------------------------------------------

def add_moving_average(
    df: pd.DataFrame,
    window: int = 5,
    column: str = "Close",
) -> pd.DataFrame:
    """
    append a simple moving-average column to an OHLCV DataFrame.

    Args:
        df:     source DataFrame (must contain `column`).
        window: look-back window in bars.
        column: source column for the MA calculation.

    Returns:
        copy of `df` with a new column named "MA{window}". returns the
        input unchanged if it's empty or the source column is missing.
    """
    if df is None or df.empty or column not in df.columns:
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    out[f"MA{int(window)}"] = (
        out[column].rolling(window=int(window), min_periods=1).mean()
    )
    return out


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    samples = [
        "Nifty hits all-time high on strong FII inflows",
        "Rupee crashes to record low; markets in panic",
        "RBI keeps repo rate unchanged at 6.5%",
    ]
    for s in samples:
        print(s, "->", analyze_headline_sentiment(s))
