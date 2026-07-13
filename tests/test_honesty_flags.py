"""Honesty-flag tests.

Endpoints backed by demonstration/mock data must say so in the payload
(simulated: true) so no client or panel demo can mistake them for live
account or market state. These tests lock that contract in.
"""

from conftest import login


SIMULATED_ENDPOINTS = [
    "/api/portfolio",
    "/api/portfolio/equity-curve",
    "/api/market/movers",
    "/api/activity/recent",
    "/api/competitions",
]

REAL_ENDPOINTS = [
    "/api/settings",
    "/api/profile",
    "/api/notifications",
    "/api/notifications/count",
    "/api/predictions/recent",
    "/api/leaderboard/users",
    "/api/achievements/user",
]


class TestSimulatedFlags:

    def test_mock_endpoints_are_labeled(self, client, make_user):
        make_user("flaguser")
        login(client, "flaguser")
        for ep in SIMULATED_ENDPOINTS:
            resp = client.get(ep)
            assert resp.status_code == 200, ep
            body = resp.get_json()
            assert body.get("simulated") is True, (
                f"{ep} serves demonstration data but does not say so")
            assert body.get("data_source") == "simulated", (
                f"{ep} must carry data_source=simulated")

    def test_real_endpoints_are_not_labeled(self, client, make_user):
        make_user("flaguser2")
        login(client, "flaguser2")
        for ep in REAL_ENDPOINTS:
            resp = client.get(ep)
            assert resp.status_code == 200, ep
            body = resp.get_json()
            assert body.get("simulated") is not True, (
                f"{ep} is backed by real state; must not be flagged simulated")

    def test_dashboard_flagged_without_engine(self, client, make_user):
        """No trading engine is connected in tests, so the dashboard's
        placeholder portfolio block must be labeled."""
        make_user("flaguser3")
        login(client, "flaguser3")
        body = client.get("/api/dashboard").get_json()
        assert body.get("simulated") is True


class TestSentimentHonesty:

    def test_sentiment_simulated_without_live_sources(self, monkeypatch):
        """With no NEWSAPI_KEY, the composite rests on the placeholder
        reddit model and must be flagged."""
        import sentiment
        monkeypatch.setattr(sentiment, "NEWS_API_KEY", "")
        result = sentiment.get_sentiment("AAPL", use_cache=False)
        assert result.get("simulated") is True
        assert "reddit" in result.get("simulated_sources", [])
        signal = sentiment.get_sentiment_signal("AAPL")
        assert signal.get("simulated") is True
