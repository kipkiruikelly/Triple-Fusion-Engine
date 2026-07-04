"""
app_new.py
ML-based Quantitative Trading System, refactored entry point.

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

# Per-endpoint request stats since process start (in-memory, resets on restart).
_endpoint_stats = {}
_endpoint_lock  = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env (gitignored) so credentials live in one file instead of the
# service configuration. Existing environment variables take precedence.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
except ImportError:
    pass


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
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "users.db"))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Session / cookie hardening ────────────────────────────────────────────
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("SECURE_COOKIES", "").lower() == "true":
        # Enable when all traffic is HTTPS (Caddy), breaks plain-HTTP logins.
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["REMEMBER_COOKIE_SECURE"] = True

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
        # Session ids are "id:session_token"; a mismatched token means the
        # user reset their password and this session is revoked.
        raw, _, tok = str(user_id).partition(":")
        try:
            user = db.session.get(User, int(raw))
        except (TypeError, ValueError):
            return None
        if user and (user.session_token or "") != tok:
            return None
        return user

    # ── Register all route modules ────────────────────────────────────────────
    from routes.auth          import register_auth_routes
    from routes.payments      import register_payment_routes
    from routes.predictions   import register_prediction_routes
    from routes.trading       import register_trading_routes
    from routes.portfolio     import register_portfolio_routes
    from routes.analytics     import register_analytics_routes
    from routes.admin         import register_admin_routes
    from routes.notifications import register_notification_routes
    from routes.paper         import register_paper_routes

    register_auth_routes(app)
    register_payment_routes(app)
    register_prediction_routes(app, _metrics)
    register_trading_routes(app)
    register_portfolio_routes(app)
    register_analytics_routes(app)
    register_admin_routes(app, _endpoint_stats, _APP_START)
    register_notification_routes(app)
    register_paper_routes(app)

    # ── Theme (account-backed dark/light/system) ──────────────────────────────
    # Every template renders <html {{ theme_attr }}> so logged-in users get the
    # right theme server-side (no flash, works without JS). The preference
    # chain is: account setting, then bl-theme cookie, then OS setting via the
    # prefers-color-scheme fallback baked into _theme.html.

    @app.context_processor
    def _inject_theme():
        from flask import request
        from flask_login import current_user
        from markupsafe import Markup
        pref = ""
        is_account = False
        if getattr(current_user, "is_authenticated", False):
            pref = current_user.theme_preference or "system"
            is_account = True
        else:
            cookie = request.cookies.get("bl-theme", "")
            if cookie in ("light", "dark", "system"):
                pref = cookie
        attr = Markup(' data-theme="%s"' % pref) if pref in ("light", "dark") else Markup("")
        return {"theme_pref": pref, "theme_is_account": is_account, "theme_attr": attr}

    # ── Error pages ───────────────────────────────────────────────────────────

    @app.errorhandler(404)
    def _not_found(e):
        from flask import render_template, request
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Not found"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def _server_error(e):
        from flask import render_template, request
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Internal server error"}), 500
        return render_template("500.html"), 500

    # ── Infrastructure routes (health, metrics, sw.js, model-metrics) ─────────

    @app.route("/sw.js")
    def service_worker():
        return app.send_static_file("sw.js"), 200, {"Content-Type": "application/javascript"}

    @app.route("/offline")
    def offline_page():
        from flask import render_template
        return render_template("offline.html")

    # ── Public info pages ─────────────────────────────────────────────────────

    @app.route("/faq")
    def faq_page():
        from flask import render_template
        return render_template("faq.html")

    @app.route("/privacy-policy")
    def privacy_page():
        from flask import render_template
        return render_template("privacy.html")

    @app.route("/terms")
    def terms_page():
        from flask import render_template
        return render_template("terms.html")

    @app.route("/resources")
    def resources_page():
        from flask import render_template
        return render_template("resources.html")

    @app.route("/api/resources")
    def api_resources_public():
        from models import ResourceLink
        rows = (ResourceLink.query.filter_by(active=True)
                .order_by(ResourceLink.sort).all())
        cats = {}
        order = ["Learn Trading", "Market Data & News", "Regulators & Safety",
                 "Our Platform"]
        for r in rows:
            cats.setdefault(r.category, []).append(
                {"title": r.title, "url": r.url, "description": r.description,
                 "icon": r.icon})
        ordered = ([c for c in order if c in cats]
                   + [c for c in cats if c not in order])
        return jsonify({"ok": True, "categories": [
            {"name": c, "links": cats[c]} for c in ordered]})

    @app.route("/methodology")
    def methodology_page():
        from flask import render_template
        return render_template("methodology.html")

    @app.route("/data-sources")
    def data_sources_page():
        from flask import render_template
        return render_template("data_sources.html")

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
                            "error": "No metrics file, run train_professional.py first"})
        try:
            with open(path) as f:
                data = _json.load(f)
            return jsonify({"ok": True, **data})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── Request counter / stats / maintenance mode ────────────────────────────

    @app.before_request
    def _count_request():
        from flask import request, render_template
        from flask_login import current_user
        g.start_time = time.time()
        _metrics["requests"] += 1

        # Maintenance mode: admins and auth/admin/static routes stay reachable.
        if _maintenance_enabled():
            path = request.path
            exempt = (path.startswith(("/admin", "/login", "/logout", "/static",
                                       "/health", "/forgot-password", "/reset-password"))
                      or path == "/sw.js")
            is_admin = (current_user.is_authenticated
                        and getattr(current_user, "role_level", 0) >= 1)
            if not exempt and not is_admin:
                return render_template("maintenance.html"), 503

        # Throttled last-seen tracking for active-user metrics.
        if current_user.is_authenticated:
            try:
                now = datetime.utcnow()
                if (current_user.last_seen is None
                        or (now - current_user.last_seen).total_seconds() > 300):
                    current_user.last_seen = now
                    db.session.commit()
            except Exception:
                db.session.rollback()

    @app.after_request
    def _track_endpoint(response):
        try:
            elapsed_ms = (time.time() - g.get("start_time", time.time())) * 1000
            from flask import request
            key = f"{request.method} {request.url_rule.rule if request.url_rule else request.path}"
            with _endpoint_lock:
                s = _endpoint_stats.setdefault(key, {"count": 0, "total_ms": 0.0, "errors": 0})
                s["count"]    += 1
                s["total_ms"] += elapsed_ms
                if response.status_code >= 500:
                    s["errors"] += 1
        except Exception:
            pass
        return response

    # ── Error logging to DB ───────────────────────────────────────────────────

    from flask import got_request_exception

    def _log_exception(sender, exception, **extra):
        import traceback
        from flask import request
        from models import ErrorLog
        try:
            db.session.rollback()
            db.session.add(ErrorLog(
                severity="error",
                endpoint=(request.endpoint or request.path)[:120],
                method=request.method,
                message=str(exception)[:500] or type(exception).__name__,
                trace=traceback.format_exc()[-4000:],
                ip=request.remote_addr,
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    got_request_exception.connect(_log_exception, app)

    # ── DB init ───────────────────────────────────────────────────────────────

    with app.app_context():
        db.create_all()
        _run_migrations(db)
        _seed_defaults(db)

    # ── Background alert checker ──────────────────────────────────────────────
    _start_alert_thread(app, db)

    # ── Ops thread: accuracy engine, drift monitor, daily digest ─────────────
    if os.environ.get("DISABLE_OPS_THREAD", "").lower() != "true":
        from ops import start_ops_thread
        start_ops_thread(app, db)

    return app


# ── Settings cache ────────────────────────────────────────────────────────────

_settings_cache = {"maintenance": False, "checked_at": 0.0}

def _maintenance_enabled():
    """Check the maintenance_mode setting, cached for 15s to spare SQLite."""
    now = time.time()
    if now - _settings_cache["checked_at"] > 15:
        try:
            from models import AppSetting
            from extensions import db as _db
            row = _db.session.get(AppSetting, "maintenance_mode")
            _settings_cache["maintenance"] = bool(row and row.value == "1")
        except Exception:
            _settings_cache["maintenance"] = False
        _settings_cache["checked_at"] = now
    return _settings_cache["maintenance"]


def invalidate_settings_cache():
    _settings_cache["checked_at"] = 0.0


# ── Seed defaults ─────────────────────────────────────────────────────────────

def _seed_defaults(db):
    """Seed TickerConfig from the built-in list and default app settings."""
    from models import TickerConfig, AppSetting
    from utils import PRO_TICKERS
    try:
        if TickerConfig.query.count() == 0:
            names = {"QQQ": "Invesco QQQ Trust", "AAPL": "Apple Inc.", "NVDA": "NVIDIA Corp.",
                     "TSLA": "Tesla Inc.", "MSFT": "Microsoft Corp.", "GOOGL": "Alphabet Inc.",
                     "META": "Meta Platforms", "AMZN": "Amazon.com Inc.",
                     "NDX": "Nasdaq-100 Index", "DIA": "SPDR Dow Jones ETF"}
            for sym in PRO_TICKERS:
                db.session.add(TickerConfig(symbol=sym, name=names.get(sym), enabled=True))
        from models import ResourceLink
        if ResourceLink.query.count() == 0:
            seed_links = [
                ("Learn Trading", "Investopedia", "https://www.investopedia.com/trading-4427765",
                 "Plain-English explanations of every trading concept", "📚", 1),
                ("Learn Trading", "Babypips School of Pipsology", "https://www.babypips.com/learn/forex",
                 "The classic free forex course, from beginner to advanced", "🎓", 2),
                ("Learn Trading", "NSE Investor Education", "https://www.nse.co.ke/investor-education/",
                 "Nairobi Securities Exchange guides for Kenyan investors", "🇰🇪", 3),
                ("Market Data & News", "Yahoo Finance", "https://finance.yahoo.com",
                 "Quotes, charts, and news for global markets", "📈", 1),
                ("Market Data & News", "TradingView", "https://www.tradingview.com",
                 "Professional charting and community trade ideas", "📊", 2),
                ("Market Data & News", "Pyth Price Feeds", "https://www.pyth.network/price-feeds",
                 "Explore the oracle feeds that verify our prices", "🔮", 3),
                ("Regulators & Safety", "Capital Markets Authority Kenya", "https://www.cma.or.ke",
                 "Kenya's markets regulator. Check if a broker is licensed", "🛡", 1),
                ("Regulators & Safety", "Central Bank of Kenya", "https://www.centralbank.go.ke",
                 "Forex rates and warnings about unlicensed schemes", "🏦", 2),
                ("Regulators & Safety", "CMA Investor Alerts", "https://www.cma.or.ke/cautionary-statements/",
                 "Official alerts about fraudulent investment operations", "⚠️", 3),
                ("Our Platform", "Track Record", "/track-record",
                 "Our live, ungraded-nothing prediction accuracy", "✅", 1),
                ("Our Platform", "Methodology", "/methodology",
                 "How the models work and how accuracy is graded", "🔬", 2),
                ("Our Platform", "FAQ", "/faq", "Common questions answered", "❓", 3),
            ]
            for cat, title, url, desc, icon, sort in seed_links:
                db.session.add(ResourceLink(category=cat, title=title, url=url,
                                            description=desc, icon=icon, sort=sort))
        defaults = {
            "app_name":          "BullLogic",
            "maintenance_mode":  "0",
            "registration_open": "1",
            "feature_signals":   "1",
            "feature_mpesa":     "1",
            "pro_monthly_kes":   os.environ.get("PRO_MONTHLY_KES", "3500"),
            "pro_annual_kes":    os.environ.get("PRO_ANNUAL_KES", "23000"),
        }
        for k, v in defaults.items():
            if AppSetting.query.get(k) is None:
                db.session.add(AppSetting(key=k, value=v))
        db.session.commit()
    except Exception:
        db.session.rollback()


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
        ("user",                "role",            "VARCHAR(10) DEFAULT 'user'"),
        ("user",                "status",          "VARCHAR(12) DEFAULT 'active'"),
        ("user",                "created_at",      "DATETIME"),
        ("user",                "last_seen",       "DATETIME"),
        # Existing accounts predate verification; treat them as verified so
        # the feature only gates new signups.
        ("user",                "email_verified",  "BOOLEAN DEFAULT 1"),
        ("user",                "auth_provider",   "VARCHAR(10) DEFAULT 'local'"),
        ("user",                "google_sub",      "VARCHAR(64)"),
        ("user",                "session_token",   "VARCHAR(32)"),
        ("payment",             "flagged",         "BOOLEAN DEFAULT 0"),
        ("prediction_history",  "src_source",      "VARCHAR(12)"),
        ("prediction_history",  "src_conf_pct",    "FLOAT"),
        ("prediction_history",  "src_divergence",  "FLOAT"),
        ("user_preferences",    "risk_intro_seen", "BOOLEAN DEFAULT 0"),
        ("user_preferences",    "usage_notice_enabled", "BOOLEAN DEFAULT 1"),
        ("prediction_history",  "interval",        "VARCHAR(4) DEFAULT '1d'"),
        ("price_alert",         "note",            "VARCHAR(100)"),
        ("price_alert",         "triggered_at",    "DATETIME"),
        ("user",                "theme_preference", "VARCHAR(10) DEFAULT 'system'"),
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

        # Indexes for the hot query paths (idempotent).
        indexes = [
            ("ix_ph_user",      "prediction_history", "user_id"),
            ("ix_ph_ticker",    "prediction_history", "ticker, interval, predicted_at"),
            ("ix_pa_pred",      "prediction_accuracy", "prediction_id"),
            ("ix_notif_user",   "notification",       "user_id, read"),
            ("ix_act_user",     "activity_log",       "user_id, created_at"),
            ("ix_pay_user",     "payment",            "user_id"),
            ("ix_pay_status",   "payment",            "status"),
            ("ix_alert_user",   "price_alert",        "user_id, triggered"),
            ("ix_pos_user",     "portfolio_position", "user_id, status"),
            ("ix_journal_user", "trade_journal",      "user_id"),
            ("ix_user_seen",    "user",               "last_seen"),
        ]
        for name, table, cols in indexes:
            try:
                if inspector.has_table(table):
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS {name} ON "{table}" ({cols})'))
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
                f"Note: {alert.note or '-'}\n\n"
                f", BullLogic"
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
                                            f"Note: {alert.note or '-'}"
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
