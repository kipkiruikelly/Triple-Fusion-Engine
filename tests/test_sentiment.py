"""
Tests for sentiment.py — VADER scoring, news fetching, composite sentiment,
and trading signal generation.

All external API calls (requests.get) are mocked via unittest.mock.patch
so that tests never hit the network.
"""

import json
from unittest.mock import MagicMock, patch

# Ensure the project root is on sys.path (conftest does this, but
# a direct `pytest tests/test_sentiment.py` call also works).
from sentiment import (
    _vader_sentiment,
    batch_sentiment,
    fetch_news_headlines,
    get_sentiment,
    get_sentiment_signal,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_article(title: str, source: str = "TestSource",
                  published_at: str = "2025-01-01T00:00:00Z") -> dict:
    """Return a single article dict in NewsAPI response format."""
    return {
        "title": title,
        "source": {"name": source},
        "publishedAt": published_at,
    }


def _make_newsapi_response(articles, status_code: int = 200):
    """Return a mock ``requests.Response`` like NewsAPI would send."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"articles": articles, "totalResults": len(articles)}
    resp.text = json.dumps({"articles": articles})
    return resp


# ── _vader_sentiment tests ──────────────────────────────────────────────────────

class TestVaderSentiment:
    """Tests for the lightweight VADER-inspired lexicon scorer."""

    def test_bullish_text(self):
        """Highly bullish words should yield a score > 0.5."""
        score = _vader_sentiment("The stock surged and soared to record highs")
        assert score > 0.5, f"Expected bullish score > 0.5, got {score}"

    def test_bearish_text(self):
        """Highly bearish words should yield a score < -0.5."""
        score = _vader_sentiment("Market crash triggered plunge and collapse fears")
        assert score < -0.5, f"Expected bearish score < -0.5, got {score}"

    def test_neutral_text(self):
        """Text with no sentiment-bearing words should return 0.0."""
        score = _vader_sentiment("The company released a statement today about operations")
        assert score == 0.0, f"Expected neutral score 0.0, got {score}"

    def test_empty_string(self):
        """Empty string should return 0.0 without error."""
        assert _vader_sentiment("") == 0.0

    def test_very_long_text(self):
        """Very long repetitive bullish text should still score high."""
        long_text = "surge " * 500 + " rally " * 500
        score = _vader_sentiment(long_text)
        assert score > 0.5, f"Expected > 0.5 for long bullish text, got {score}"

    def test_negation_flips_sentiment(self):
        """'not good' should be negative while 'good' alone is positive."""
        score_good = _vader_sentiment("good")
        score_not_good = _vader_sentiment("not good")
        # "good" is not in the lexicon, so both will be 0.0 — test "not strong" instead
        score_strong = _vader_sentiment("strong")
        score_not_strong = _vader_sentiment("not strong")
        assert score_strong > 0, f"Expected positive for 'strong', got {score_strong}"
        assert score_not_strong < 0, (
            f"Expected negative for 'not strong', got {score_not_strong}"
        )
        assert score_not_strong < score_strong, (
            "Negation should flip polarity so 'not strong' < 'strong'"
        )


# ── fetch_news_headlines tests ──────────────────────────────────────────────────

class TestFetchNewsHeadlines:
    """Tests for the NewsAPI headline fetcher."""

    @patch("sentiment.requests.get")
    def test_successful_fetch(self, mock_get: MagicMock):
        """A normal API response returns extracted headlines."""
        mock_get.return_value = _make_newsapi_response([
            _make_article("AAPL surges on earnings beat"),
            _make_article("Apple stock at all-time high"),
        ])
        headlines = fetch_news_headlines("AAPL")
        assert len(headlines) == 2
        assert headlines[0]["title"] == "AAPL surges on earnings beat"
        assert headlines[0]["source"] == "TestSource"
        assert "published_at" in headlines[0]

    @patch("sentiment.requests.get")
    def test_http_401_returns_empty(self, mock_get: MagicMock):
        """A 401 Unauthorised should result in an empty list."""
        mock_get.return_value = _make_newsapi_response([], status_code=401)
        assert fetch_news_headlines("AAPL") == []

    @patch("sentiment.requests.get")
    def test_http_429_returns_empty(self, mock_get: MagicMock):
        """A 429 Too Many Requests should result in an empty list."""
        mock_get.return_value = _make_newsapi_response([], status_code=429)
        assert fetch_news_headlines("AAPL") == []

    @patch("sentiment.requests.get")
    def test_empty_response(self, mock_get: MagicMock):
        """API returning zero articles produces an empty list."""
        mock_get.return_value = _make_newsapi_response([])
        assert fetch_news_headlines("AAPL") == []

    @patch("sentiment.requests.get")
    def test_network_exception_returns_empty(self, mock_get: MagicMock):
        """A network-level exception is caught and returns empty list."""
        mock_get.side_effect = ConnectionError("DNS failure")
        assert fetch_news_headlines("AAPL") == []

    @patch("sentiment.NEWS_API_KEY", "")
    def test_no_api_key_returns_empty(self):
        """When NEWS_API_KEY is falsy, no HTTP call is made and list is empty."""
        # fetch_news_headlines checks the module-level NEWS_API_KEY
        with patch("sentiment.requests.get") as mock_get:
            result = fetch_news_headlines("AAPL")
            assert result == []
            mock_get.assert_not_called()


# ── get_sentiment tests ─────────────────────────────────────────────────────────

class TestGetSentiment:
    """Composite sentiment calculation with caching."""

    @patch("sentiment.fetch_news_headlines")
    @patch("sentiment._reddit_sentiment")
    @patch("sentiment._reddit_mention_count")
    def test_with_cache(
        self, mock_mentions: MagicMock, mock_reddit: MagicMock,
        mock_news: MagicMock,
    ):
        """When cache is valid, _fetch_news_headlines is not called again."""
        mock_news.return_value = [
            {"title": "strong rally", "source": "N", "published_at": ""}
        ]
        mock_reddit.return_value = 0.5
        mock_mentions.return_value = 30

        # First call populates cache
        sent1 = get_sentiment("CACHETEST", use_cache=True)

        # Second call should hit cache
        sent2 = get_sentiment("CACHETEST", use_cache=True)

        assert sent1["ticker"] == "CACHETEST"
        assert sent2["ticker"] == "CACHETEST"
        # The dict (same reference) should be returned
        assert sent2 is sent1

    @patch("sentiment.fetch_news_headlines")
    @patch("sentiment._reddit_sentiment")
    @patch("sentiment._reddit_mention_count")
    def test_without_cache(
        self, mock_mentions: MagicMock, mock_reddit: MagicMock,
        mock_news: MagicMock,
    ):
        """When use_cache=False, a fresh result is always computed."""
        mock_news.return_value = [
            {"title": "strong rally", "source": "N", "published_at": ""}
        ]
        mock_reddit.return_value = 0.5
        mock_mentions.return_value = 30

        sent1 = get_sentiment("NOCACHE", use_cache=False)
        sent2 = get_sentiment("NOCACHE", use_cache=False)

        # Timestamps should differ (same second may be equal, but objects differ)
        assert sent1["timestamp"] != sent2["timestamp"] or sent1 is not sent2

    @patch("sentiment.fetch_news_headlines")
    @patch("sentiment._reddit_sentiment")
    @patch("sentiment._reddit_mention_count")
    @patch("sentiment.time.time")
    def test_cache_expiry(
        self, mock_time: MagicMock, mock_mentions: MagicMock,
        mock_reddit: MagicMock, mock_news: MagicMock,
    ):
        """After CACHE_TTL passes the cache is invalidated and recomputed."""
        mock_news.return_value = [
            {"title": "strong rally", "source": "N", "published_at": ""}
        ]
        mock_reddit.return_value = 0.5
        mock_mentions.return_value = 30

        from sentiment import CACHE_TTL_SECONDS

        # First call caches at t=1000
        mock_time.return_value = 1000.0
        sent1 = get_sentiment("CACHEEXP", use_cache=True)

        # Second call at t=1000+TTL-1 should still hit cache
        mock_time.return_value = 1000.0 + CACHE_TTL_SECONDS - 1
        sent2 = get_sentiment("CACHEEXP", use_cache=True)
        assert sent2 is sent1, "Should use cached result before TTL expires"

        # Third call at t=1000+TTL+1 should recompute
        mock_time.return_value = 1000.0 + CACHE_TTL_SECONDS + 1
        sent3 = get_sentiment("CACHEEXP", use_cache=True)
        assert sent3 is not sent1, "Should recompute after TTL"

    @patch("sentiment.fetch_news_headlines")
    @patch("sentiment._reddit_sentiment")
    @patch("sentiment._reddit_mention_count")
    def test_empty_news_falls_back_to_reddit(
        self, mock_mentions: MagicMock, mock_reddit: MagicMock,
        mock_news: MagicMock,
    ):
        """When news headlines are empty, sentiment relies on Reddit only."""
        mock_news.return_value = []
        mock_reddit.return_value = 0.3
        mock_mentions.return_value = 25

        sent = get_sentiment("NONEWS", use_cache=False)
        # Only reddit component
        assert "reddit" in sent["components"]
        assert "news" not in sent["components"]
        assert sent["sources"] == 1

    def test_batch_sentiment(self):
        """batch_sentiment calls get_sentiment for each ticker."""
        with patch(
            "sentiment.get_sentiment",
            return_value={"ticker": "X", "score": 0.5, "magnitude": 0.6,
                          "sources": 1, "components": {}, "timestamp": ""},
        ):
            results = batch_sentiment(["AAA", "BBB"])
            assert list(results.keys()) == ["AAA", "BBB"]


# ── get_sentiment_signal tests ──────────────────────────────────────────────────

class TestGetSentimentSignal:
    """Trading signal conversion."""

    @patch("sentiment.get_sentiment")
    def test_bullish_bias(self, mock_gs: MagicMock):
        """Score > 0.2 and magnitude > 0.3 produces 'bullish' bias."""
        mock_gs.return_value = {
            "ticker": "TEST", "score": 0.5, "magnitude": 0.7,
            "sources": 2, "components": {}, "timestamp": "",
        }
        signal = get_sentiment_signal("TEST")
        assert signal["bias"] == "bullish"

    @patch("sentiment.get_sentiment")
    def test_bearish_bias(self, mock_gs: MagicMock):
        """Score < -0.2 and magnitude > 0.3 produces 'bearish' bias."""
        mock_gs.return_value = {
            "ticker": "TEST", "score": -0.6, "magnitude": 0.8,
            "sources": 2, "components": {}, "timestamp": "",
        }
        signal = get_sentiment_signal("TEST")
        assert signal["bias"] == "bearish"

    @patch("sentiment.get_sentiment")
    def test_neutral_bias(self, mock_gs: MagicMock):
        """Score near zero or low magnitude produces 'neutral' bias."""
        mock_gs.return_value = {
            "ticker": "TEST", "score": 0.1, "magnitude": 0.2,
            "sources": 2, "components": {}, "timestamp": "",
        }
        signal = get_sentiment_signal("TEST")
        assert signal["bias"] == "neutral"

    @patch("sentiment.get_sentiment")
    def test_strong_magnitude(self, mock_gs: MagicMock):
        """Magnitude > 0.6 yields strength='strong'."""
        mock_gs.return_value = {
            "ticker": "TEST", "score": 0.5, "magnitude": 0.7,
            "sources": 2, "components": {}, "timestamp": "",
        }
        signal = get_sentiment_signal("TEST")
        assert signal["strength"] == "strong"

    @patch("sentiment.get_sentiment")
    def test_weak_magnitude(self, mock_gs: MagicMock):
        """Magnitude <= 0.3 yields strength='weak'."""
        mock_gs.return_value = {
            "ticker": "TEST", "score": 0.3, "magnitude": 0.2,
            "sources": 2, "components": {}, "timestamp": "",
        }
        signal = get_sentiment_signal("TEST")
        assert signal["strength"] == "weak"
