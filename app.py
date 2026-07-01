"""
app_new.py
ML-based Quantitative Trading System — refactored entry point.

Flask application factory wiring all route modules together.
Drop-in replacement for app.py: start with `python app_new.py` or point
gunicorn at `app_new:app`.

Usage:
    python app_new.py

Author: BullLogic
"""

import json as _json
import logging
import os
import threading
import time
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime

from flask import Flask, jsonify, g, redirect, url_for
from azure_storage import azure_enabled

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_APP_START = time.time()
_metrics   = {"requests": 0, "predictions": 0, "total_latency": 0.0}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── App factory ───────────────────────────────────────────────────────────────

def create_app():
    app = Flask(__name__, template_folder="Web Pages", static_folder="Static Files")
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        if os.environ.get("FLASK_DEBUG", "false").lower() == "true":
            secret_key = "smp-dev-key-2025"
        else:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set outside debug mode"
            )
    app.secret_key = secret_key

    # ── SQLAlchemy ────────────────────────────────────────────────────────────
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "users.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Flask-Mail ────────────────────────────────────────────────────────────
    app.config["MAIL_SERVER"]         = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    app.config["MAIL_PORT"]           = int(os.environ.get("MAIL_PORT", 587))
    app.config["MAIL_USE_TLS"]        = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    app.config["MAIL_USERNAME"]       = os.environ.get("MAIL_USERNAME", "")
    app.config["MAIL_PASSWORD"]       = os.environ.get("MAIL_PASSWORD", "")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get(
        "MAIL_DEFAULT_SENDER", os.environ.get("MAIL_USERNAME", "noreply@bulllogic.app"))

    # ── Extensions ────────────────────────────────────────────────────────────
    from extensions import db, login_manager, mail
    db.init_app(app)
    login_manager.init_app(app)
    if mail:
        mail.init_app(app)

    # ── Login manager user loader ─────────────────────────────────────────────
    from models import User
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Register all route modules ────────────────────────────────────────────
    from routes.auth          import register_auth_routes
    from routes.payments      import register_payment_routes
    from routes.predictions   import register_prediction_routes
    from routes.trading       import register_trading_routes
    from routes.portfolio     import register_portfolio_routes
    from routes.analytics     import register_analytics_routes
    from routes.admin         import register_admin_routes
    from routes.notifications import register_notification_routes

    register_auth_routes(app)
    register_payment_routes(app)
    register_prediction_routes(app, _metrics)
    register_trading_routes(app)
    register_portfolio_routes(app)
    register_analytics_routes(app)
    register_admin_routes(app)
    register_notification_routes(app)

    # ── Infrastructure routes (health, metrics, sw.js, model-metrics) ─────────

    @app.route("/sw.js")
    def service_worker():
        return app.send_static_file("sw.js"), 200, {"Content-Type": "application/javascript"}

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "uptime_s": round(time.time() - _APP_START, 1)})

    @app.route("/metrics")
    def app_metrics():
        reqs = _metrics["requests"]
        avg  = (_metrics["total_latency"] / _metrics["predictions"]
                if _metrics["predictions"] > 0 else 0)
        return jsonify({
            "uptime_s":          round(time.time() - _APP_START, 1),
            "total_requests":    reqs,
            "total_predictions": _metrics["predictions"],
            "avg_latency_s":     round(avg, 3),
            "azure_enabled":     azure_enabled(),
        })

    @app.route("/model-metrics")
    def model_metrics_page():
        from flask_login import login_required
        from flask import render_template
        from functools import wraps
        return render_template("model_metrics.html")

    @app.route("/api/model-metrics")
    def api_model_metrics():
        from flask_login import current_user
        from flask import render_template
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Login required"}), 401
        path = os.path.join(BASE_DIR, "Data", "model_metrics.json")
        if not os.path.exists(path):
            return jsonify({"ok": False,
                            "error": "No metrics file — run train_professional.py first"})
        try:
            with open(path) as f:
                data = _json.load(f)
            return jsonify({"ok": True, **data})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── Request counter ───────────────────────────────────────────────────────

    @app.before_request
    def _count_request():
        g.start_time = time.time()
        _metrics["requests"] += 1

    # ── DB init ───────────────────────────────────────────────────────────────

    with app.app_context():
        db.create_all()
        _run_migrations(db)

    # ── Background alert checker ──────────────────────────────────────────────
    _start_alert_thread(app, db)

    return app


# ── Migrations ────────────────────────────────────────────────────────────────

def _run_migrations(db):
    """Add new columns to existing DB without dropping data."""
    from sqlalchemy import text, inspect
    engine = db.engine
    inspector = inspect(engine)

    def _col_exists(table, col):
        return any(c["name"] == col for c in inspector.get_columns(table))

    migrations = [
        ("user",                "pro_expires_at",  "DATE"),
        ("user",                "alerts_enabled",  "BOOLEAN DEFAULT 1"),
        ("prediction_history",  "interval",        "VARCHAR(4) DEFAULT '1d'"),
        ("price_alert",         "note",            "VARCHAR(100)"),
        ("price_alert",         "triggered_at",    "DATETIME"),
    ]
    with engine.connect() as conn:
        for table, column, coltype in migrations:
            try:
                if inspector.has_table(table) and not _col_exists(table, column):
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"
                    ))
                    conn.commit()
            except Exception:
                pass


# ── Alert background thread ────────────────────────────────────────────────────

def _start_alert_thread(app, db):
    """Start the price-alert polling thread inside the given app context."""
    from models import PriceAlert, TelegramConfig, User

    def _send_alert_email(user, alert, price):
        from extensions import mail
        if not mail or not app.config.get("MAIL_USERNAME"):
            return
        if not user.alerts_enabled:
            return
        try:
            from flask_mail import Message as MailMessage
            subject = f"BullLogic Alert: {alert.ticker} hit ${price:.4f}"
            body    = (
                f"Hi {user.username},\n\n"
                f"Your price alert for {alert.ticker} has triggered.\n\n"
                f"Condition: Price {alert.direction} ${alert.price:.4f}\n"
                f"Current price: ${price:.4f}\n"
                f"Note: {alert.note or '—'}\n\n"
                f"— BullLogic"
            )
            with app.app_context():
                mail.send(MailMessage(subject=subject, recipients=[user.email], body=body))
        except Exception:
            pass

    def _check_alerts():
        import yfinance as yf
        from utils import _send_telegram
        with app.app_context():
            while True:
                try:
                    pending = PriceAlert.query.filter_by(triggered=False).all()
                    if pending:
                        prices = {}
                        for t in {a.ticker for a in pending}:
                            try:
                                prices[t] = float(yf.Ticker(t).fast_info.last_price or 0)
                            except Exception:
                                pass
                        for alert in pending:
                            price = prices.get(alert.ticker, 0)
                            if price <= 0:
                                continue
                            hit = ((alert.direction == "above" and price >= alert.price) or
                                   (alert.direction == "below" and price <= alert.price))
                            if hit:
                                alert.triggered    = True
                                alert.triggered_at = datetime.utcnow()
                                user = db.session.get(User, alert.user_id)
                                if user:
                                    threading.Thread(
                                        target=_send_alert_email, args=(user, alert, price),
                                        daemon=True
                                    ).start()
                                    tg = TelegramConfig.query.filter_by(
                                        user_id=user.id, enabled=True).first()
                                    if tg:
                                        msg = (
                                            f"🔔 *BullLogic Alert*\n"
                                            f"*{alert.ticker}* hit `${price:.4f}`\n"
                                            f"Condition: price {alert.direction} `${alert.price:.4f}`\n"
                                            f"Note: {alert.note or '—'}"
                                        )
                                        threading.Thread(
                                            target=_send_telegram,
                                            args=(tg.chat_id, msg), daemon=True
                                        ).start()
                        db.session.commit()
                except Exception:
                    pass
                time.sleep(120)

    t = threading.Thread(target=_check_alerts, daemon=True)
    t.start()


# ── Entry point ───────────────────────────────────────────────────────────────

app = create_app()

if __name__ == "__main__":
    # Dev-only entry point. For persistent/background hosting use wsgi.py
    # (waitress), which has no interactive debugger and no reloader.
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    print("ML-based Quantitative Trading System (refactored)")
    print(f"Running at: http://{host}:{port}\n")
    app.run(debug=debug, host=host, port=port)
