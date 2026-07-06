"""Pyth client parsing, source verification, and failover ordering."""

import time

import pyth_client
import market_data
import finnhub_service


def test_fixed_point_parsing():
    entry = {"price": {"price": "18413250000", "conf": "18000000",
                       "expo": -8, "publish_time": int(time.time())}}
    parsed = pyth_client._parse_entry(entry)
    assert abs(parsed["price"] - 184.1325) < 1e-9
    assert abs(parsed["conf"] - 0.18) < 1e-9


def test_symbol_mapping_rules():
    assert pyth_client.expected_pyth_symbol("BTC") == "Crypto.BTC/USD"
    assert pyth_client.expected_pyth_symbol("EURUSD") == "FX.EUR/USD"
    assert pyth_client.expected_pyth_symbol("GOLD") == "Metal.XAU/USD"
    assert pyth_client.expected_pyth_symbol("AAPL") == "Equity.US.AAPL/USD"


def test_stale_equity_is_market_closed_not_error():
    old = {"price": 184.0, "conf": 0.1, "publish_time": time.time() - 7200}
    d = pyth_client._decorate(old, "Equity.US.AAPL/USD")
    assert d["market_closed"] is True and d["fresh"] is False
    # Crypto trades around the clock, stale crypto is just stale.
    d2 = pyth_client._decorate(old, "Crypto.BTC/USD")
    assert d2["market_closed"] is False and d2["fresh"] is False


def _fake_pyth(price, fresh=True):
    return {"price": price, "conf": 0.1, "publish_time": int(time.time()),
            "age_s": 1.0, "fresh": fresh, "source": "pyth",
            "market_closed": False}


def test_agreeing_sources_are_verified(app, monkeypatch):
    monkeypatch.setattr(market_data, "get_quote",
                        lambda s: {"price": 100.0, "prev": 99.0, "chg": 1.0, "pct": 1.0})
    monkeypatch.setattr(market_data, "_pyth_feed_map",
                        lambda syms: {"TVER": ("feed1", "Equity.US.TVER/USD")})
    monkeypatch.setattr(pyth_client, "get_prices",
                        lambda fm: {"TVER": _fake_pyth(100.2)})
    with app.app_context():
        q = market_data.get_quotes_verified(["TVER"])["TVER"]
    assert q["verified"] is True and q["source"] == "yfinance+pyth"
    assert q["divergence_pct"] is not None and q["divergence_pct"] < 0.5


def test_diverging_sources_flagged_never_silent(app, monkeypatch):
    monkeypatch.setattr(market_data, "get_quote",
                        lambda s: {"price": 100.0, "prev": 99.0, "chg": 1.0, "pct": 1.0})
    monkeypatch.setattr(market_data, "_pyth_feed_map",
                        lambda syms: {"TDIV": ("feed2", "Equity.US.TDIV/USD")})
    monkeypatch.setattr(pyth_client, "get_prices",
                        lambda fm: {"TDIV": _fake_pyth(105.0)})
    with app.app_context():
        q = market_data.get_quotes_verified(["TDIV"])["TDIV"]
    assert q["verified"] is False
    assert q["divergence_pct"] > market_data.VERIFY_TOLERANCE_PCT
    assert q["pyth_price"] == 105.0        # both values exposed, nothing hidden


def test_failover_to_pyth_when_yfinance_down(app, monkeypatch):
    monkeypatch.setattr(market_data, "get_quote", lambda s: None)
    monkeypatch.setattr(market_data, "_pyth_feed_map",
                        lambda syms: {"TFAIL": ("feed3", "Crypto.TFAIL/USD")})
    monkeypatch.setattr(pyth_client, "get_prices",
                        lambda fm: {"TFAIL": _fake_pyth(42.5)})
    before = market_data._source_stats["failovers"]
    with app.app_context():
        q = market_data.get_quotes_verified(["TFAIL"])["TFAIL"]
    assert q["source"] == "pyth" and q["price"] == 42.5
    assert market_data._source_stats["failovers"] == before + 1


def test_all_sources_down_returns_none(app, monkeypatch):
    monkeypatch.setattr(market_data, "get_quote", lambda s: None)
    monkeypatch.setattr(market_data, "_pyth_feed_map", lambda syms: {})
    with app.app_context():
        assert market_data.get_quotes_verified(["TNONE"])["TNONE"] is None


def _fake_finnhub(price):
    return {"price": price, "prev": price - 1, "chg": 1.0, "pct": 1.0}


def test_finnhub_verifies_when_no_pyth_feed(app, monkeypatch):
    monkeypatch.setattr(finnhub_service, "FINNHUB_KEY", "dummy")
    monkeypatch.setattr(market_data, "get_quote",
                        lambda s: {"price": 100.0, "prev": 99.0, "chg": 1.0, "pct": 1.0})
    monkeypatch.setattr(market_data, "_pyth_feed_map", lambda syms: {})
    monkeypatch.setattr(finnhub_service, "get_quote", lambda s: _fake_finnhub(100.2))
    with app.app_context():
        q = market_data.get_quotes_verified(["TFHV"])["TFHV"]
    assert q["verified"] is True and q["source"] == "yfinance+finnhub"
    assert q["divergence_pct"] is not None and q["divergence_pct"] < 0.5


def test_finnhub_divergence_flagged(app, monkeypatch):
    monkeypatch.setattr(finnhub_service, "FINNHUB_KEY", "dummy")
    monkeypatch.setattr(market_data, "get_quote",
                        lambda s: {"price": 100.0, "prev": 99.0, "chg": 1.0, "pct": 1.0})
    monkeypatch.setattr(market_data, "_pyth_feed_map", lambda syms: {})
    monkeypatch.setattr(finnhub_service, "get_quote", lambda s: _fake_finnhub(105.0))
    with app.app_context():
        q = market_data.get_quotes_verified(["TFHD"])["TFHD"]
    assert q["verified"] is False
    assert q["divergence_pct"] > market_data.VERIFY_TOLERANCE_PCT
    assert q["finnhub_price"] == 105.0        # both values exposed, nothing hidden


def test_failover_to_finnhub_when_yfinance_and_pyth_down(app, monkeypatch):
    monkeypatch.setattr(finnhub_service, "FINNHUB_KEY", "dummy")
    monkeypatch.setattr(market_data, "get_quote", lambda s: None)
    monkeypatch.setattr(market_data, "_pyth_feed_map", lambda syms: {})
    monkeypatch.setattr(finnhub_service, "get_quote", lambda s: _fake_finnhub(42.5))
    before = market_data._source_stats["failovers"]
    with app.app_context():
        q = market_data.get_quotes_verified(["TFHF"])["TFHF"]
    assert q["source"] == "finnhub" and q["price"] == 42.5
    assert market_data._source_stats["failovers"] == before + 1


def test_no_finnhub_key_preserves_old_behaviour(app, monkeypatch):
    monkeypatch.setattr(finnhub_service, "FINNHUB_KEY", "")
    monkeypatch.setattr(market_data, "get_quote",
                        lambda s: {"price": 100.0, "prev": 99.0, "chg": 1.0, "pct": 1.0})
    monkeypatch.setattr(market_data, "_pyth_feed_map", lambda syms: {})
    with app.app_context():
        q = market_data.get_quotes_verified(["TNOKEY"])["TNOKEY"]
    assert q["source"] == "yfinance" and q["verified"] is False
