"""Accuracy engine: grading, honest insufficient-data, drift alerts."""

from datetime import datetime, timedelta

import pandas as pd


def _seed_predictions(db, uid, ticker, n_up, n_down, days_ago=3):
    from models import PredictionHistory
    base = datetime.utcnow() - timedelta(days=days_ago)
    ids = []
    for i in range(n_up + n_down):
        ph = PredictionHistory(user_id=uid, ticker=ticker, interval="1d",
                               current_price=100.0, lr_pred=105.0, rf_pred=104.0,
                               direction="UP" if i < n_up else "DOWN",
                               confidence=60.0, predicted_at=base)
        db.session.add(ph)
        db.session.flush()
        ids.append(ph.id)
    db.session.commit()
    return ids, base


def test_resolver_grades_directions(app, db, make_user, monkeypatch):
    import ops
    import market_data
    uid = make_user("accuser")
    with app.app_context():
        ids, base = _seed_predictions(db, uid, "PYTACC", 6, 6)
        # market closed UP at 102 → UP correct, DOWN wrong
        fake = pd.DataFrame({"Close": [102.0]},
                            index=pd.DatetimeIndex([base + timedelta(days=1)]))
        monkeypatch.setattr(market_data, "get_history",
                            lambda *a, **k: (fake, {"stale": False}))
        graded, unresolvable = ops.resolve_pending(db)
        assert graded == 12
        stats = ops.ticker_stats(db, "PYTACC", "1d")
        assert stats["n"] == 12 and stats["direction_accuracy"] == 50.0


def test_insufficient_data_is_honest(app, db, make_user, monkeypatch):
    import ops
    import market_data
    uid = make_user("accuser2")
    with app.app_context():
        ids, base = _seed_predictions(db, uid, "PYTFEW", 3, 0)
        fake = pd.DataFrame({"Close": [102.0]},
                            index=pd.DatetimeIndex([base + timedelta(days=1)]))
        monkeypatch.setattr(market_data, "get_history",
                            lambda *a, **k: (fake, {"stale": False}))
        ops.resolve_pending(db)
        stats = ops.ticker_stats(db, "PYTFEW", "1d")
        assert stats["sufficient"] is False
        assert stats["direction_accuracy"] is None    # never fabricated


def test_drift_alert_fires_below_floor(app, db, make_user, monkeypatch):
    import ops
    import market_data
    from models import Notification, AppSetting
    make_user("staffer", role="admin")
    uid = make_user("accuser3")
    with app.app_context():
        ids, base = _seed_predictions(db, uid, "PYTDRIFT", 2, 10)  # mostly wrong
        fake = pd.DataFrame({"Close": [102.0]},
                            index=pd.DatetimeIndex([base + timedelta(days=1)]))
        monkeypatch.setattr(market_data, "get_history",
                            lambda *a, **k: (fake, {"stale": False}))
        ops.resolve_pending(db)
        alerts = ops.check_drift(db)
        assert any("PYTDRIFT" in a for a in alerts)
        assert Notification.query.filter_by(type="drift").count() >= 1
        # dedupe: immediate second check must not re-alert
        assert not any("PYTDRIFT" in a for a in ops.check_drift(db))
        AppSetting.query.filter_by(key="drift_state").delete()
        Notification.query.filter_by(type="drift").delete()
        db.session.commit()
