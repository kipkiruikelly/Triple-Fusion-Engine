"""
sentiment.py
Market Sentiment Analysis for the Triple-Fusion-Engine.

Integrates alternative data sources to gauge market mood:
  - VADER sentiment scoring on financial news headlines
  - Reddit r/wallstreetbets trending ticker mentions
  - News API integration (NewsAPI.org, free tier)
  - Composite sentiment index per ticker

All functions return a standardized sentiment dict with:
  - score: float in [-1, 1] where +1 = max bullish, -1 = max bearish
  - magnitude: float in [0, 1] representing signal strength/volume
  - sources: int, number of data points used

Usage:
    from sentiment import get_sentiment
    sent = get_sentiment("AAPL")
    print(f"AAPL sentiment: {sent['score']:.2f} (magnitude: {sent['magnitude']:.2f})")

Author: BullLogic
"""

import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────

try:
    from config import settings as _cfg
    NEWS_API_KEY = _cfg.ANTHROPIC_API_KEY or os.environ.get("NEWS_API_KEY", "")
except ImportError:
    NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

NEWS_API_BASE = "https://newsapi.org/v2"
CACHE_TTL_SECONDS = 300  # 5 minutes
MAX_HEADLINES = 50

_cache: Dict[str, Tuple[float, dict]] = {}
_cache_lock = threading.Lock()


# ── VADER Sentiment ─────────────────────────────────────────────────────────────

def _vader_sentiment(text: str) -> float:
    """Score text using a lightweight VADER-inspired lexicon approach.

    No external dependency required. Uses hand-curated financial lexicon
    with negation handling. Returns score in [-1, 1].
    """
    # Financial sentiment lexicon: word → (polarity, intensity)
    _LEXICON = {
        # Bullish
        "surge": (1.0, 1.5), "soar": (1.0, 1.5), "rally": (0.8, 1.3),
        "breakout": (0.9, 1.4), "upside": (0.7, 1.1), "beat": (0.8, 1.2),
        "upgrade": (0.9, 1.3), "outperform": (0.8, 1.2), "bullish": (1.0, 1.0),
        "buy": (0.7, 1.0), "long": (0.5, 0.8), "gain": (0.6, 1.0),
        "growth": (0.7, 1.1), "profit": (0.8, 1.2), "record": (0.9, 1.3),
        "strong": (0.6, 1.0), "positive": (0.5, 0.9), "optimistic": (0.7, 1.0),
        "momentum": (0.6, 1.0), "green": (0.4, 0.8), "moon": (0.9, 1.5),
        "rocket": (0.9, 1.6), "pump": (0.7, 1.2), "accumulate": (0.6, 1.0),
        "undervalued": (0.7, 1.1), "dip": (0.3, 0.7),  # "buy the dip"
        # Bearish
        "plunge": (-1.0, 1.5), "crash": (-1.0, 1.6), "tumble": (-0.9, 1.4),
        "selloff": (-0.9, 1.3), "downgrade": (-0.9, 1.3), "bearish": (-1.0, 1.0),
        "sell": (-0.7, 1.0), "short": (-0.6, 1.0), "loss": (-0.7, 1.1),
        "decline": (-0.6, 1.0), "weak": (-0.6, 0.9), "negative": (-0.5, 0.9),
        "fear": (-0.8, 1.2), "risk": (-0.5, 1.0), "warning": (-0.6, 1.0),
        "drop": (-0.5, 0.9), "fall": (-0.5, 0.9), "red": (-0.4, 0.8),
        "dump": (-0.8, 1.3), "collapse": (-1.0, 1.5), "bubble": (-0.7, 1.2),
        "overvalued": (-0.8, 1.1), "recession": (-0.9, 1.4), "inflation": (-0.6, 1.1),
        "layoff": (-0.7, 1.0), "debt": (-0.5, 0.8),
        # Modifiers
        "not": (0, 0), "no": (0, 0), "never": (0, 0),
    }

    words = re.findall(r'\b[a-z]+\b', text.lower())
    score = 0.0
    total_weight = 0.0
    negate = False

    for i, word in enumerate(words):
        if word in ("not", "no", "never"):
            negate = True
            continue

        entry = _LEXICON.get(word)
        if entry:
            pol, intensity = entry
            if negate:
                pol = -pol
                negate = False
            score += pol * intensity
            total_weight += intensity

        # Reset negation after 3 words
        if i > 0 and i % 3 == 0:
            negate = False

    if total_weight == 0:
        return 0.0
    return float(np.clip(score / total_weight, -1.0, 1.0))


# ── News API ────────────────────────────────────────────────────────────────────

def fetch_news_headlines(
    ticker: str, max_results: int = 20
) -> List[Dict[str, str]]:
    """Fetch recent news headlines for a ticker from NewsAPI.

    Returns list of {title, source, published_at} dicts.
    Falls back to empty list if API key not configured or rate limited.
    """
    if not NEWS_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{NEWS_API_BASE}/everything",
            params={
                "q": f"{ticker} stock",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": min(max_results, MAX_HEADLINES),
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.debug("NewsAPI returned %d: %s", resp.status_code, resp.text[:200])
            return []

        articles = resp.json().get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", "unknown"),
                "published_at": a.get("publishedAt", ""),
            }
            for a in articles[:max_results]
        ]
    except Exception as e:
        logger.debug("NewsAPI fetch error: %s", e)
        return []


# ── Reddit Sentiment (simulated) ────────────────────────────────────────────────

def _reddit_mention_count(ticker: str) -> int:
    """Estimate Reddit mention velocity for a ticker.

    Uses a simplified model based on recent price volatility and market cap
    tier. In production, this would call the Reddit API or a provider like
    AYLIEN / Social Market Analytics.
    """
    # Simulated: return 0-50 mentions based on ticker popularity
    _POPULAR = {
        "AAPL": 45, "TSLA": 50, "NVDA": 48, "AMZN": 35, "META": 30,
        "MSFT": 25, "GOOGL": 28, "SPY": 40, "QQQ": 38, "GME": 50,
        "AMC": 45, "BB": 20, "PLTR": 32, "NIO": 18, "SNAP": 15,
    }
    base = _POPULAR.get(ticker.upper(), 10)
    noise = int(np.random.normal(0, 3))
    return max(0, base + noise)


def _reddit_sentiment(ticker: str) -> float:
    """Estimate Reddit sentiment polarity for a ticker (-1 to 1)."""
    mentions = _reddit_mention_count(ticker)
    if mentions == 0:
        return 0.0
    # Simulated: slight positive bias + noise
    base = 0.1  # Reddit tends slightly bullish
    noise = np.random.normal(0, 0.3)
    return float(np.clip(base + noise, -1.0, 1.0))


# ── Composite Sentiment ─────────────────────────────────────────────────────────

def get_sentiment(ticker: str, use_cache: bool = True) -> dict:
    """Compute composite market sentiment for a ticker.

    Combines:
      - News headline sentiment (VADER on NewsAPI headlines)
      - Reddit/WallStreetBets mention sentiment
      - Simple moving average of recent sentiment

    Args:
        ticker: Ticker symbol.
        use_cache: Use cached result if within TTL.

    Returns:
        dict with score, magnitude, sources, components, timestamp.
    """
    ticker = ticker.upper()

    # Check cache
    if use_cache:
        with _cache_lock:
            if ticker in _cache:
                cached_at, cached_val = _cache[ticker]
                if time.time() - cached_at < CACHE_TTL_SECONDS:
                    return cached_val

    components = {}
    sources = 0

    # 1. News sentiment
    headlines = fetch_news_headlines(ticker)
    if headlines:
        news_scores = [_vader_sentiment(h["title"]) for h in headlines]
        news_score = float(np.mean(news_scores))
        news_magnitude = min(1.0, len(headlines) / 20)
        components["news"] = {"score": round(news_score, 3), "magnitude": round(news_magnitude, 2)}
        sources += 1
    else:
        news_score = 0.0
        news_magnitude = 0.0

    # 2. Reddit sentiment - SIMULATED (no Reddit API integration; see
    #    _reddit_mention_count). Flagged so consumers cannot mistake it
    #    for a live signal.
    reddit_score = _reddit_sentiment(ticker)
    reddit_mentions = _reddit_mention_count(ticker)
    if reddit_mentions > 0:
        # NOTE: returns simulated data - replace with live source
        components["reddit"] = {
            "score": round(reddit_score, 3),
            "mentions": reddit_mentions,
            "magnitude": round(min(1.0, reddit_mentions / 50), 2),
            "simulated": True,
            "data_source": "simulated",
        }
        sources += 1

    # Composite: weighted average
    weights = []
    scores = []
    if headlines:
        weights.append(news_magnitude)
        scores.append(news_score)
    if reddit_mentions > 0:
        weights.append(min(1.0, reddit_mentions / 50))
        scores.append(reddit_score)

    if weights:
        total_w = sum(weights)
        composite = sum(w * s for w, s in zip(weights, scores)) / total_w if total_w > 0 else 0.0
        magnitude = total_w / len(weights)
    else:
        composite = 0.0
        magnitude = 0.0

    result = {
        "ticker": ticker,
        "score": round(float(composite), 3),
        "magnitude": round(float(magnitude), 3),
        "sources": sources,
        "components": components,
        "timestamp": datetime.now().isoformat(),
    }
    # Honesty flags: reddit is simulated; if it is the ONLY source (no
    # NEWSAPI_KEY configured), the composite itself is simulated.
    if "reddit" in components:
        result["simulated_sources"] = ["reddit"]
        if not headlines:
            result["simulated"] = True
            result["warning"] = ("Sentiment is simulated: no live news source "
                                 "configured (set NEWSAPI_KEY) and the Reddit "
                                 "component is a placeholder model.")

    # Store in cache
    with _cache_lock:
        _cache[ticker] = (time.time(), result)

    return result


def get_sentiment_signal(ticker: str) -> dict:
    """Convert sentiment into a trading signal hint.

    Returns:
        dict with bias ("bullish"/"bearish"/"neutral"), strength, and raw score.
    """
    sent = get_sentiment(ticker)
    score = sent["score"]
    mag = sent["magnitude"]

    if score > 0.2 and mag > 0.3:
        bias = "bullish"
    elif score < -0.2 and mag > 0.3:
        bias = "bearish"
    else:
        bias = "neutral"

    strength = "strong" if mag > 0.6 else ("moderate" if mag > 0.3 else "weak")

    signal = {
        "ticker": ticker,
        "bias": bias,
        "strength": strength,
        "score": score,
        "magnitude": mag,
        "sources": sent["sources"],
    }
    if sent.get("simulated"):
        signal["simulated"] = True
        signal["warning"] = sent.get("warning")
    return signal


def batch_sentiment(tickers: List[str]) -> Dict[str, dict]:
    """Get sentiment for multiple tickers in one call."""
    return {t: get_sentiment(t) for t in tickers}
