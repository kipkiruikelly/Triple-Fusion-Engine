"""Live-trading safety gate tests.

These assert the non-negotiable invariant: with a default environment
(no ENABLE_LIVE_TRADING), no code path in mt5_trading can place a real
broker order. Paper trading must remain the only active execution path.
"""

import pytest

from mt5_trading import MT5Trader, live_trading_enabled, _LIVE_DISABLED_MSG


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    """Every test starts with the flag absent (the shipped default)."""
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)


class TestLiveTradingGate:

    def test_disabled_by_default(self):
        assert live_trading_enabled() is False

    def test_enabled_only_by_explicit_opt_in(self, monkeypatch):
        for value in ("", "0", "false", "no", "off", "banana"):
            monkeypatch.setenv("ENABLE_LIVE_TRADING", value)
            assert live_trading_enabled() is False, value
        for value in ("1", "true", "True", "YES", "on"):
            monkeypatch.setenv("ENABLE_LIVE_TRADING", value)
            assert live_trading_enabled() is True, value

    def test_metaapi_connect_refused(self):
        t = MT5Trader()
        result = t.connect(0, "", "", metaapi_token="fake-token",
                           metaapi_account_id="fake-account")
        assert result["ok"] is False
        assert result["error"] == _LIVE_DISABLED_MSG
        assert t.connected is False

    def test_live_mt5_connect_refused(self):
        t = MT5Trader()
        result = t.connect(12345678, "password", "Broker-Server")
        assert result["ok"] is False
        assert result["error"] == _LIVE_DISABLED_MSG
        assert t.connected is False

    def test_paper_connect_still_works(self):
        t = MT5Trader()
        result = t.connect(0, "", "")
        assert result["ok"] is True
        assert result["mode"] == "paper"
        assert t.is_paper is True

    def test_place_order_refused_on_non_paper_path(self):
        """Even if a trader object somehow reaches a live state, the
        order method itself refuses before touching any backend."""
        t = MT5Trader()
        t.connected = True
        t._paper = None            # not paper
        t._mapi = object()         # pretend MetaApi is attached
        result = t.place_order("EURUSD", "BUY", risk_pct=1.0, atr=0.001)
        assert result["ok"] is False
        assert result["error"] == _LIVE_DISABLED_MSG

    def test_close_all_refused_on_non_paper_path(self):
        t = MT5Trader()
        t.connected = True
        t._paper = None
        t._mapi = object()
        assert t.close_all("EURUSD") == 0

    def test_paper_is_the_only_active_execution_path(self):
        """With defaults, the only way to an executed trade is the
        virtual PaperAccount."""
        t = MT5Trader()
        t.connect(0, "", "")
        assert t.is_paper is True
        assert t.is_metaapi is False
        assert t._mt5_instance is None
