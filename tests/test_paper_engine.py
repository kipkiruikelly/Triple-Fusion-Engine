"""Paper trading engine tests: sizing math, friction, stop/target execution,
metrics against known fixtures, the daily loss breaker, append-only honesty,
and the guarantee that no broker/order code is reachable from the paper
system. All tests run offline against the throwaway test DB."""

import os
from datetime import datetime, timedelta

import pytest

import paper_engine
from paper_engine import (apply_entry_friction, apply_exit_friction,
                          commission, position_size, trade_pnl, check_exit,
                          compute_metrics, asset_class, market_open,
                          DEFAULT_CONFIG)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CFG = dict(DEFAULT_CONFIG)


@pytest.fixture()
def clean_paper(app, db):
    """Remove every paper table row before and after each test."""
    from models import PaperTrade, PaperTradeEvent, PaperEquitySnapshot, AppSetting

    def _wipe():
        with app.app_context():
            PaperTradeEvent.query.delete()
            PaperTrade.query.delete()
            PaperEquitySnapshot.query.delete()
            for key in ("paper_config", "paper_trading_enabled",
                        "paper_trading_started_at"):
                row = db.session.get(AppSetting, key)
                if row:
                    db.session.delete(row)
            db.session.commit()

    _wipe()
    yield
    _wipe()


# ── Position sizing ───────────────────────────────────────────────────────────

def test_position_size_risks_fixed_fraction():
    # risking 1% of 100,000 = 1,000 over a 5.0 stop distance -> 200 units
    assert position_size(100_000, 1.0, 5.0) == pytest.approx(200.0)
    # hitting the stop then loses exactly the risk amount
    qty = position_size(100_000, 1.0, 5.0)
    assert qty * 5.0 == pytest.approx(1_000.0)


def test_position_size_degenerate_inputs_return_zero():
    assert position_size(0, 1.0, 5.0) == 0.0
    assert position_size(100_000, 1.0, 0.0) == 0.0
    assert position_size(-5, 1.0, 5.0) == 0.0
    assert position_size(100_000, 0.0, 5.0) == 0.0


# ── Friction ──────────────────────────────────────────────────────────────────

def test_entry_friction_always_hurts():
    cfg = {**CFG, "spread_bps": 10.0}
    assert apply_entry_friction(100.0, "LONG", cfg) == pytest.approx(100.10)
    assert apply_entry_friction(100.0, "SHORT", cfg) == pytest.approx(99.90)


def test_exit_friction_always_hurts():
    cfg = {**CFG, "spread_bps": 10.0}
    assert apply_exit_friction(100.0, "LONG", cfg) == pytest.approx(99.90)
    assert apply_exit_friction(100.0, "SHORT", cfg) == pytest.approx(100.10)


def test_commission_is_bps_of_notional():
    cfg = {**CFG, "commission_bps": 10.0}
    assert commission(50_000.0, cfg) == pytest.approx(50.0)
    assert commission(-50_000.0, cfg) == pytest.approx(50.0)


def test_round_trip_with_friction_never_beats_frictionless():
    cfg = {**CFG, "spread_bps": 5.0, "commission_bps": 10.0}
    entry = apply_entry_friction(100.0, "LONG", cfg)
    exit_ = apply_exit_friction(110.0, "LONG", cfg)
    comm = commission(100 * entry, cfg) + commission(100 * exit_, cfg)
    pnl = trade_pnl("LONG", 100, entry, exit_, comm)
    frictionless = 100 * (110.0 - 100.0)
    assert pnl < frictionless


def test_trade_pnl_short_side():
    # short 10 units at 100, cover at 90, no commission -> +100
    assert trade_pnl("SHORT", 10, 100.0, 90.0, 0.0) == pytest.approx(100.0)
    assert trade_pnl("SHORT", 10, 100.0, 110.0, 0.0) == pytest.approx(-100.0)


# ── Stop / target / reversal / timeout execution ─────────────────────────────

class _T:
    """Minimal open-trade stand-in for check_exit."""
    def __init__(self, side, stop, target, hours_held=1, max_hold=240):
        self.side = side
        self.stop_price = stop
        self.target_price = target
        self.max_hold_hours = max_hold
        self.entry_time = datetime.utcnow() - timedelta(hours=hours_held)


def test_long_stop_and_target():
    t = _T("LONG", stop=95.0, target=110.0)
    assert check_exit(t, {"price": 94.5})[0] == "stop"
    assert check_exit(t, {"price": 111.0})[0] == "target"
    assert check_exit(t, {"price": 100.0}) == (None, None)


def test_short_stop_and_target():
    t = _T("SHORT", stop=105.0, target=90.0)
    assert check_exit(t, {"price": 106.0})[0] == "stop"
    assert check_exit(t, {"price": 89.0})[0] == "target"
    assert check_exit(t, {"price": 100.0}) == (None, None)


def test_reversal_exit():
    t = _T("LONG", stop=95.0, target=110.0)
    assert check_exit(t, {"price": 100.0}, signal_action="SELL")[0] == "reversal"
    s = _T("SHORT", stop=105.0, target=90.0)
    assert check_exit(s, {"price": 100.0}, signal_action="BUY")[0] == "reversal"


def test_timeout_exit():
    t = _T("LONG", stop=95.0, target=110.0, hours_held=300, max_hold=240)
    assert check_exit(t, {"price": 100.0})[0] == "timeout"


def test_stop_beats_reversal_priority():
    t = _T("LONG", stop=95.0, target=110.0)
    assert check_exit(t, {"price": 94.0}, signal_action="SELL")[0] == "stop"


def test_no_quote_no_exit():
    t = _T("LONG", stop=95.0, target=110.0, hours_held=999)
    assert check_exit(t, None) == (None, None)
    assert check_exit(t, {"price": None}) == (None, None)


# ── Metrics against known fixtures ────────────────────────────────────────────

def test_metrics_insufficient_below_min_trades():
    m = compute_metrics([10.0] * 9, [100, 101, 102], min_trades=10)
    assert m["sufficient"] is False
    assert "sharpe" not in m and "win_rate_pct" not in m


def test_metrics_known_fixture():
    # 12 closed trades: 8 wins of +100, 4 losses of -50
    pnls = [100.0] * 8 + [-50.0] * 4
    # equity path 100 -> 110 -> 104.5: returns +10%, -5%
    # mean r = 0.025, std(ddof=1) = 0.1060660172
    # sharpe = 0.025 / 0.1060660172 * sqrt(252) = 3.742
    # max drawdown = (104.5 - 110) / 110 = -5.0%
    eq = [100.0, 110.0, 104.5]
    m = compute_metrics(pnls, eq, min_trades=10)
    assert m["sufficient"] is True
    assert m["trades"] == 12
    assert m["win_rate_pct"] == pytest.approx(66.7, abs=0.05)
    assert m["profit_factor"] == pytest.approx(800.0 / 200.0, abs=1e-9)
    assert m["avg_win"] == pytest.approx(100.0)
    assert m["avg_loss"] == pytest.approx(-50.0)
    assert m["net_pnl"] == pytest.approx(600.0)
    assert m["total_return_pct"] == pytest.approx(4.5, abs=1e-9)
    assert m["sharpe"] == pytest.approx(3.742, abs=0.001)
    assert m["max_drawdown_pct"] == pytest.approx(-5.0, abs=1e-9)


def test_metrics_all_wins_profit_factor_none():
    m = compute_metrics([10.0] * 12, [100, 101, 102, 103], min_trades=10)
    assert m["profit_factor"] is None       # no losses: undefined, not inflated
    assert m["win_rate_pct"] == 100.0


def test_metrics_flat_equity_sharpe_none():
    m = compute_metrics([1.0] * 12, [100.0, 100.0, 100.0], min_trades=10)
    assert m["sharpe"] is None              # zero variance: honest None


# ── Asset classes and market hours ────────────────────────────────────────────

def test_asset_class_mapping():
    assert asset_class("BTC") == "crypto"
    assert asset_class("EURUSD") == "forex"
    assert asset_class("GOLD") == "commodity"
    assert asset_class("QQQ") == "etf"
    assert asset_class("NDX") == "index"
    assert asset_class("AAPL") == "equity"


def test_market_hours():
    wed_1500 = datetime(2026, 7, 1, 15, 0)     # Wednesday, RTH
    sat_1500 = datetime(2026, 7, 4, 15, 0)     # Saturday
    wed_0500 = datetime(2026, 7, 1, 5, 0)      # Wednesday pre-market
    assert market_open("crypto", sat_1500) is True
    assert market_open("equity", wed_1500) is True
    assert market_open("equity", sat_1500) is False
    assert market_open("equity", wed_0500) is False
    assert market_open("forex", sat_1500) is False
    assert market_open("forex", wed_1500) is True


# ── Engine integration (offline, fake quotes) ─────────────────────────────────

def _quote(price):
    return {"price": price, "source": "test", "conf_pct": None}


def test_open_close_lifecycle_and_audit_trail(app, db, clean_paper):
    from models import PaperTrade, PaperTradeEvent
    with app.app_context():
        cfg = paper_engine.load_config(db)
        t = paper_engine.try_open(db, "ml_ensemble", "BTC", "LONG",
                                  _quote(100.0), atr=2.0, cfg=cfg,
                                  model="test", confidence=80,
                                  rationale="unit test")
        assert not isinstance(t, str), f"rejected: {t}"

        # sizing: 1% of 1,000,000 = 10,000 risk over stop 3.0 -> 3333.33 qty
        assert t.qty == pytest.approx(10_000 / 3.0, rel=1e-4)
        # entry friction: LONG fills above market
        assert t.entry_price == pytest.approx(100.0 * 1.0005)
        assert t.entry_mkt == pytest.approx(100.0)
        assert t.stop_price == pytest.approx(t.entry_price - 3.0)
        assert t.target_price == pytest.approx(t.entry_price + 5.0)

        entry_price_before = t.entry_price
        closed = paper_engine.close_trade(db, t, 106.0, "target", cfg)
        assert closed.status == "closed"
        assert closed.exit_reason == "target"
        # exit friction: LONG sells below market
        assert closed.exit_price == pytest.approx(106.0 * 0.9995)
        assert closed.pnl is not None
        # entry fields untouched at close (append-only)
        assert closed.entry_price == entry_price_before

        # a closed trade can never be closed again
        assert paper_engine.close_trade(db, closed, 50.0, "stop", cfg) is None
        assert closed.exit_reason == "target"

        events = [e.event for e in PaperTradeEvent.query
                  .filter_by(trade_id=closed.id).all()]
        assert events == ["open", "close"]


def test_risk_gates(app, db, clean_paper):
    with app.app_context():
        cfg = dict(paper_engine.load_config(db))
        cfg["max_positions"] = 1
        r1 = paper_engine.try_open(db, "ml_ensemble", "BTC", "LONG",
                                   _quote(100.0), 2.0, cfg)
        assert not isinstance(r1, str)
        # duplicate ticker rejected
        assert paper_engine.try_open(db, "ml_ensemble", "BTC", "LONG",
                                     _quote(100.0), 2.0, cfg) == "already open"
        # max positions rejected
        assert paper_engine.try_open(db, "ml_ensemble", "ETH", "LONG",
                                     _quote(100.0), 2.0, cfg) == "max positions"
        # equity market closed on Saturday
        sat = datetime(2026, 7, 4, 15, 0)
        assert paper_engine.try_open(db, "ml_ensemble", "AAPL", "LONG",
                                     _quote(100.0), 2.0, cfg,
                                     now=sat) == "market closed"


def test_daily_loss_breaker_pauses_entries(app, db, clean_paper):
    from models import PaperEquitySnapshot
    with app.app_context():
        cfg = paper_engine.load_config(db)
        # first snapshot today shows equity well above current -> big daily loss
        db.session.add(PaperEquitySnapshot(strategy="ml_ensemble",
                                           equity=1_100_000.0, open_count=0))
        db.session.commit()
        # realized equity is the 1,000,000 start: down 9.09% on the day
        assert paper_engine.breaker_tripped(db, "ml_ensemble", cfg, {}) is True
        r = paper_engine.try_open(db, "ml_ensemble", "BTC", "LONG",
                                  _quote(100.0), 2.0, cfg)
        assert r == "daily loss breaker"

        # calm day: first snapshot at par -> no breaker
        PaperEquitySnapshot.query.delete()
        db.session.add(PaperEquitySnapshot(strategy="ml_ensemble",
                                           equity=1_000_000.0, open_count=0))
        db.session.commit()
        assert paper_engine.breaker_tripped(db, "ml_ensemble", cfg, {}) is False


# ── No real orders, ever ──────────────────────────────────────────────────────

FORBIDDEN_TOKENS = ["mt5", "metaapi", "place_order", "alpaca", "ccxt",
                    "ib_insync", "oanda", "binance", "close_all"]


def test_paper_system_has_no_broker_order_code():
    """The paper trading system must never reference broker/order APIs.
    Scans the actual source of every paper module."""
    for rel in ("paper_engine.py", "alphas.py",
                os.path.join("routes", "paper.py")):
        src = open(os.path.join(BASE_DIR, rel), encoding="utf-8").read().lower()
        for token in FORBIDDEN_TOKENS:
            assert token not in src, f"{rel} references forbidden token {token}"


def test_no_paper_route_places_orders(app):
    """No /paper or /api/paper endpoint is handled by broker code."""
    for rule in app.url_map.iter_rules():
        if "/paper" in rule.rule:
            view = app.view_functions[rule.endpoint]
            mod = getattr(view, "__module__", "")
            assert "mt5" not in mod and "trading" not in mod, \
                f"{rule.rule} handled by {mod}"


def test_public_summary_is_honest_empty_state(client, clean_paper):
    r = client.get("/api/paper/summary")
    d = r.get_json()
    assert d["ok"] is True
    assert d["simulated"] is True
    assert d["enabled"] is False           # engine ships paused
    assert d["started_at"] is None         # nothing seeded
    for s in d["strategies"]:
        assert s["metrics"]["trades"] == 0
        assert s["metrics"]["sufficient"] is False
        assert s["equity"] == s["starting_balance"]


def test_trades_api_labels_simulated(client, clean_paper):
    d = client.get("/api/paper/trades").get_json()
    assert d["simulated"] is True
    assert d["trades"] == []


def test_admin_toggle_requires_admin(client, clean_paper):
    r = client.post("/admin/api/paper/toggle", json={"enabled": True})
    assert r.status_code in (401, 403)
