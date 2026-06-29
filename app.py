"""
app.py
ML-based Quantitative Trading System

Flask web application with user authentication and subscription tiers.
Free accounts: 5 predictions/day. Pro accounts: unlimited.

Usage:
    python app.py

Then open: http://127.0.0.1:5000

Author: BullLogic
"""

import os
import csv
import io
import json as _json_std
import hashlib
import secrets
import threading
import time
import logging
import warnings
warnings.filterwarnings("ignore")

from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, g, flash, Response, make_response, stream_with_context
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from concurrent.futures import ThreadPoolExecutor
from predictor import run_prediction, ml_signal
from mt5_trading import trader as mt5_trader
from azure_storage import download_models_from_azure, azure_enabled

try:
    from flask_mail import Mail, Message as MailMessage
    _MAIL_AVAILABLE = True
except ImportError:
    _MAIL_AVAILABLE = False

try:
    import stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    _STRIPE_OK = bool(_stripe.api_key)
except ImportError:
    _stripe = None
    _STRIPE_OK = False

STRIPE_PUB_KEY          = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_PRICE_MONTHLY    = os.environ.get("STRIPE_PRICE_ID_MONTHLY", "")
STRIPE_PRICE_ANNUAL     = os.environ.get("STRIPE_PRICE_ID_ANNUAL", "")
STRIPE_WEBHOOK_SECRET   = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

try:
    from mpesa import stk_push, query_status, MPESA_OK, PRO_MONTHLY_KES, PRO_ANNUAL_KES
except Exception:
    MPESA_OK = False
    PRO_MONTHLY_KES = 3500
    PRO_ANNUAL_KES  = 23000
    def stk_push(*a, **kw): raise RuntimeError("M-Pesa not configured")
    def query_status(*a, **kw): raise RuntimeError("M-Pesa not configured")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_APP_START   = time.time()
_metrics     = {"requests": 0, "predictions": 0, "total_latency": 0.0}

app = Flask(__name__, template_folder="Web Pages", static_folder="Static Files")
app.secret_key = os.environ.get("SECRET_KEY", "smp-dev-key-2025")

# ── Flask-Mail ────────────────────────────────────────────────────────────────
app.config["MAIL_SERVER"]   = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
app.config["MAIL_PORT"]     = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"]  = os.environ.get("MAIL_USE_TLS",  "true").lower() == "true"
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER",
                                                    os.environ.get("MAIL_USERNAME", "noreply@bulllogic.app"))
mail = Mail(app) if _MAIL_AVAILABLE else None

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY",  "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = (
    'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'users.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db           = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

FREE_DAILY_LIMIT = 5


# ── User model ──────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id                      = db.Column(db.Integer, primary_key=True)
    username                = db.Column(db.String(80), unique=True, nullable=False)
    email                   = db.Column(db.String(120), unique=True, nullable=False)
    password_hash           = db.Column(db.String(256), nullable=False)
    plan                    = db.Column(db.String(20), default='free')
    predictions_today       = db.Column(db.Integer, default=0)
    last_prediction_date    = db.Column(db.Date, nullable=True)
    stripe_customer_id      = db.Column(db.String(64), nullable=True)
    stripe_subscription_id  = db.Column(db.String(64), nullable=True)
    alerts_enabled          = db.Column(db.Boolean, default=True)
    pro_expires_at          = db.Column(db.Date, nullable=True)   # for M-Pesa time-limited Pro

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_pro(self):
        if self.plan == 'pro':
            # Stripe plan: no expiry
            if self.pro_expires_at is None:
                return True
            # M-Pesa plan: check expiry date
            return self.pro_expires_at >= date.today()
        return False

    @property
    def predictions_remaining(self):
        if self.is_pro:
            return None
        today = date.today()
        if self.last_prediction_date != today:
            return FREE_DAILY_LIMIT
        return max(0, FREE_DAILY_LIMIT - self.predictions_today)


# ── PredictionHistory model ──────────────────────────────────────────────────

class PredictionHistory(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker       = db.Column(db.String(12), nullable=False)
    interval     = db.Column(db.String(4), nullable=False)
    current_price= db.Column(db.Float, nullable=False)
    lr_pred      = db.Column(db.Float, nullable=False)
    rf_pred      = db.Column(db.Float, nullable=False)
    direction    = db.Column(db.String(8), nullable=False)
    confidence   = db.Column(db.Float, nullable=False)
    predicted_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── WatchlistItem model ──────────────────────────────────────────────────────

class WatchlistItem(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker   = db.Column(db.String(12), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'ticker'),)


class PriceAlert(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker       = db.Column(db.String(12), nullable=False)
    price        = db.Column(db.Float, nullable=False)
    direction    = db.Column(db.String(8), nullable=False)  # "above" or "below"
    note         = db.Column(db.String(100), nullable=True)
    triggered    = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    triggered_at = db.Column(db.DateTime, nullable=True)


class PortfolioPosition(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker      = db.Column(db.String(12), nullable=False)
    side        = db.Column(db.String(8), nullable=False)   # "long" or "short"
    entry_price = db.Column(db.Float, nullable=False)
    quantity    = db.Column(db.Float, nullable=False)
    exit_price  = db.Column(db.Float, nullable=True)
    status      = db.Column(db.String(8), default='open')   # "open" or "closed"
    opened_at   = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at   = db.Column(db.DateTime, nullable=True)
    note        = db.Column(db.String(200), nullable=True)


class ApiKey(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key         = db.Column(db.String(64), unique=True, nullable=False)
    name        = db.Column(db.String(50), nullable=False, default='Default')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    last_used   = db.Column(db.DateTime, nullable=True)
    calls_today = db.Column(db.Integer, default=0)
    calls_date  = db.Column(db.Date, nullable=True)


class PredictionAccuracy(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    prediction_id = db.Column(db.Integer, db.ForeignKey('prediction_history.id'), nullable=False)
    actual_price  = db.Column(db.Float, nullable=True)
    direction_ok  = db.Column(db.Boolean, nullable=True)
    pct_error     = db.Column(db.Float, nullable=True)
    checked_at    = db.Column(db.DateTime, nullable=True)


class PasswordResetToken(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token      = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)


class TelegramConfig(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    chat_id  = db.Column(db.String(32), nullable=False)
    enabled  = db.Column(db.Boolean, default=True)


class Notification(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type       = db.Column(db.String(20), nullable=False, default='info')
    title      = db.Column(db.String(100), nullable=False)
    body       = db.Column(db.String(300), nullable=True)
    read       = db.Column(db.Boolean, default=False)
    link       = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TradeJournal(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker     = db.Column(db.String(12), nullable=True)
    title      = db.Column(db.String(100), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    mood       = db.Column(db.String(10), nullable=True)
    tags       = db.Column(db.String(200), nullable=True)
    trade_type = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DiscordConfig(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    webhook_url = db.Column(db.String(400), nullable=False)
    enabled     = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class GiftCode(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    code       = db.Column(db.String(24), unique=True, nullable=False)
    days       = db.Column(db.Integer, nullable=False, default=30)
    used       = db.Column(db.Boolean, default=False)
    used_by    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at    = db.Column(db.DateTime, nullable=True)
    note       = db.Column(db.String(100), nullable=True)


class UserWebhook(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    url        = db.Column(db.String(500), nullable=False)
    name       = db.Column(db.String(50), nullable=False, default='My Webhook')
    events     = db.Column(db.String(100), nullable=True)
    secret     = db.Column(db.String(32), nullable=True)
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_fired = db.Column(db.DateTime, nullable=True)
    fire_count = db.Column(db.Integer, default=0)


class ActivityLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action     = db.Column(db.String(50), nullable=False)
    detail     = db.Column(db.String(200), nullable=True)
    ip         = db.Column(db.String(45), nullable=True)
    ua         = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TwoFactorAuth(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    secret       = db.Column(db.String(32), nullable=False)
    enabled      = db.Column(db.Boolean, default=False)
    backup_codes = db.Column(db.String(300), nullable=True)


class UserPreferences(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    digest_enabled = db.Column(db.Boolean, default=False)
    theme          = db.Column(db.String(10), default='dark')
    default_ticker = db.Column(db.String(12), default='AAPL')
    timezone       = db.Column(db.String(50), default='UTC')


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def consume_quota(user):
    """Deducts one prediction from the user's daily quota. Returns False if exceeded."""
    today = date.today()
    if user.last_prediction_date != today:
        user.predictions_today    = 0
        user.last_prediction_date = today
    if not user.is_pro and user.predictions_today >= FREE_DAILY_LIMIT:
        return False
    user.predictions_today += 1
    db.session.commit()
    return True


# ── Init DB & load models ───────────────────────────────────────────────────

os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
with app.app_context():
    db.create_all()
    # Migrate: add new columns if they don't exist yet
    import sqlite3 as _sqlite3
    _conn = _sqlite3.connect(os.path.join(BASE_DIR, 'instance', 'users.db'))
    _cols = {r[1] for r in _conn.execute("PRAGMA table_info(user)")}
    for _col, _ddl in [
        ("stripe_customer_id",     "ALTER TABLE user ADD COLUMN stripe_customer_id TEXT"),
        ("stripe_subscription_id", "ALTER TABLE user ADD COLUMN stripe_subscription_id TEXT"),
        ("alerts_enabled",         "ALTER TABLE user ADD COLUMN alerts_enabled INTEGER DEFAULT 1"),
        ("pro_expires_at",         "ALTER TABLE user ADD COLUMN pro_expires_at DATE"),
    ]:
        if _col not in _cols:
            _conn.execute(_ddl)
    _conn.commit(); _conn.close()

    # Migrate new tables (safe no-op if already exist)
    import sqlite3 as _sqlite3b
    _c2 = _sqlite3b.connect(os.path.join(BASE_DIR, 'instance', 'users.db'))
    for _tbl, _ddl in [
        ("price_alert",
         "CREATE TABLE IF NOT EXISTS price_alert (id INTEGER PRIMARY KEY, user_id INTEGER, ticker TEXT, price REAL, direction TEXT, note TEXT, triggered INTEGER DEFAULT 0, created_at DATETIME, triggered_at DATETIME, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("portfolio_position",
         "CREATE TABLE IF NOT EXISTS portfolio_position (id INTEGER PRIMARY KEY, user_id INTEGER, ticker TEXT, side TEXT, entry_price REAL, quantity REAL, exit_price REAL, status TEXT DEFAULT 'open', opened_at DATETIME, closed_at DATETIME, note TEXT, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("api_key",
         "CREATE TABLE IF NOT EXISTS api_key (id INTEGER PRIMARY KEY, user_id INTEGER, key TEXT UNIQUE, name TEXT DEFAULT 'Default', created_at DATETIME, last_used DATETIME, calls_today INTEGER DEFAULT 0, calls_date DATE, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("prediction_accuracy",
         "CREATE TABLE IF NOT EXISTS prediction_accuracy (id INTEGER PRIMARY KEY, prediction_id INTEGER, actual_price REAL, direction_ok INTEGER, pct_error REAL, checked_at DATETIME, FOREIGN KEY(prediction_id) REFERENCES prediction_history(id))"),
        ("password_reset_token",
         "CREATE TABLE IF NOT EXISTS password_reset_token (id INTEGER PRIMARY KEY, user_id INTEGER, token TEXT UNIQUE, expires_at DATETIME, used INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("telegram_config",
         "CREATE TABLE IF NOT EXISTS telegram_config (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, chat_id TEXT, enabled INTEGER DEFAULT 1, FOREIGN KEY(user_id) REFERENCES user(id))"),
    ]:
        _c2.execute(_ddl)
    _c2.commit(); _c2.close()

    # Wave-3 migrations
    import sqlite3 as _sqlite3c
    _c3 = _sqlite3c.connect(os.path.join(BASE_DIR, 'instance', 'users.db'))
    for _tbl3, _ddl3 in [
        ("notification",
         "CREATE TABLE IF NOT EXISTS notification (id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT DEFAULT 'info', title TEXT, body TEXT, read INTEGER DEFAULT 0, link TEXT, created_at DATETIME, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("trade_journal",
         "CREATE TABLE IF NOT EXISTS trade_journal (id INTEGER PRIMARY KEY, user_id INTEGER, ticker TEXT, title TEXT, body TEXT, mood TEXT, tags TEXT, trade_type TEXT, created_at DATETIME, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("discord_config",
         "CREATE TABLE IF NOT EXISTS discord_config (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, webhook_url TEXT, enabled INTEGER DEFAULT 1, created_at DATETIME, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("gift_code",
         "CREATE TABLE IF NOT EXISTS gift_code (id INTEGER PRIMARY KEY, code TEXT UNIQUE, days INTEGER DEFAULT 30, used INTEGER DEFAULT 0, used_by INTEGER, created_at DATETIME, used_at DATETIME, note TEXT)"),
        ("user_webhook",
         "CREATE TABLE IF NOT EXISTS user_webhook (id INTEGER PRIMARY KEY, user_id INTEGER, url TEXT, name TEXT DEFAULT 'My Webhook', events TEXT, secret TEXT, active INTEGER DEFAULT 1, created_at DATETIME, last_fired DATETIME, fire_count INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("activity_log",
         "CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, detail TEXT, ip TEXT, ua TEXT, created_at DATETIME, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("two_factor_auth",
         "CREATE TABLE IF NOT EXISTS two_factor_auth (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, secret TEXT, enabled INTEGER DEFAULT 0, backup_codes TEXT, FOREIGN KEY(user_id) REFERENCES user(id))"),
        ("user_preferences",
         "CREATE TABLE IF NOT EXISTS user_preferences (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, digest_enabled INTEGER DEFAULT 0, theme TEXT DEFAULT 'dark', default_ticker TEXT DEFAULT 'AAPL', timezone TEXT DEFAULT 'UTC', FOREIGN KEY(user_id) REFERENCES user(id))"),
    ]:
        _c3.execute(_ddl3)
    _c3.commit(); _c3.close()


# ── Auth routes ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    error = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password   = request.form.get("password", "")
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        error = "Invalid username / email or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        if not username or not email or not password:
            error = "All fields are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif User.query.filter_by(email=email).first():
            error = "An account with that email already exists."
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for('home'))

    return render_template("register.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route("/stripe/checkout", methods=["POST"])
@login_required
def stripe_checkout():
    if not _STRIPE_OK:
        # Fallback: free upgrade (dev mode)
        current_user.plan = 'pro'
        db.session.commit()
        return redirect(url_for('home'))
    price_id = request.form.get("price_id", STRIPE_PRICE_MONTHLY)
    if price_id not in (STRIPE_PRICE_MONTHLY, STRIPE_PRICE_ANNUAL):
        return redirect(url_for('pricing'))
    base_url = request.host_url.rstrip("/")
    session = _stripe.checkout.Session.create(
        customer_email=current_user.email,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=base_url + url_for("stripe_success") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=base_url + url_for("stripe_cancel"),
        metadata={"user_id": str(current_user.id)},
    )
    return redirect(session.url, code=303)


@app.route("/stripe/success")
@login_required
def stripe_success():
    session_id = request.args.get("session_id")
    if session_id and _STRIPE_OK:
        try:
            session = _stripe.checkout.Session.retrieve(session_id)
            current_user.stripe_customer_id     = session.customer
            current_user.stripe_subscription_id = session.subscription
            current_user.plan = 'pro'
            db.session.commit()
        except Exception:
            pass
    return render_template("stripe_success.html")


@app.route("/stripe/cancel")
def stripe_cancel():
    return redirect(url_for('pricing'))


@app.route("/stripe/portal", methods=["POST"])
@login_required
def stripe_portal():
    if not _STRIPE_OK or not current_user.stripe_customer_id:
        return redirect(url_for('profile'))
    session = _stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=request.host_url.rstrip("/") + url_for("profile"),
    )
    return redirect(session.url, code=303)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not _STRIPE_OK:
        return jsonify({"ok": True})
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    try:
        event = _stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "invalid signature"}), 400

    if event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        sub = event["data"]["object"]
        user = User.query.filter_by(stripe_subscription_id=sub["id"]).first()
        if user:
            user.plan = 'free'
            db.session.commit()
    elif event["type"] == "customer.subscription.updated":
        sub = event["data"]["object"]
        user = User.query.filter_by(stripe_subscription_id=sub["id"]).first()
        if user:
            user.plan = 'pro' if sub["status"] == "active" else 'free'
            db.session.commit()
    elif event["type"] == "invoice.payment_failed":
        sub_id = event["data"]["object"].get("subscription")
        if sub_id:
            user = User.query.filter_by(stripe_subscription_id=sub_id).first()
            if user:
                user.plan = 'free'
                db.session.commit()

    return jsonify({"ok": True})


# ── M-Pesa routes ────────────────────────────────────────────────────────────

# In-memory store for pending STK Push requests {checkout_request_id: user_id, plan}
# (A real deployment would use Redis or a DB table)
_mpesa_pending = {}


@app.route("/mpesa/pay", methods=["POST"])
@login_required
def mpesa_pay():
    if not MPESA_OK:
        return jsonify({"ok": False, "error": "M-Pesa payments are not configured yet."}), 503
    data  = request.get_json() or {}
    phone = data.get("phone", "").strip().replace(" ", "").replace("-", "")
    plan  = data.get("plan", "monthly")   # "monthly" or "annual"

    # Normalise phone: 07XXXXXXXX → 2547XXXXXXXX
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    if not phone.startswith("254") or len(phone) != 12 or not phone.isdigit():
        return jsonify({"ok": False, "error": "Enter a valid Safaricom number (07XXXXXXXX)."}), 400

    amount = PRO_ANNUAL_KES if plan == "annual" else PRO_MONTHLY_KES
    days   = 365 if plan == "annual" else 30
    desc   = f"BullLogic Pro {'1 year' if plan == 'annual' else '30 days'}"

    try:
        resp = stk_push(phone, amount, "BullLogicPro", desc)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if resp.get("ResponseCode") != "0":
        return jsonify({"ok": False,
                        "error": resp.get("ResponseDescription", "STK push failed")}), 400

    checkout_id = resp["CheckoutRequestID"]
    _mpesa_pending[checkout_id] = {"user_id": current_user.id, "days": days}

    return jsonify({
        "ok":                True,
        "checkout_request_id": checkout_id,
        "message":           f"Check your phone ({phone}) and enter your M-Pesa PIN.",
    })


@app.route("/mpesa/status", methods=["POST"])
@login_required
def mpesa_status():
    """Poll: has the STK Push been paid yet?"""
    checkout_id = (request.get_json() or {}).get("checkout_request_id", "")
    if not checkout_id:
        return jsonify({"ok": False, "paid": False, "error": "Missing checkout_request_id"}), 400
    try:
        resp = query_status(checkout_id)
    except Exception as e:
        return jsonify({"ok": False, "paid": False, "error": str(e)}), 500

    result_code = str(resp.get("ResultCode", "-1"))
    if result_code == "0":
        # Payment confirmed — grant Pro
        pending = _mpesa_pending.pop(checkout_id, {})
        uid   = pending.get("user_id", current_user.id)
        days  = pending.get("days", 30)
        user  = db.session.get(User, uid)
        if user:
            user.plan = 'pro'
            user.pro_expires_at = date.today() + timedelta(days=days)
            db.session.commit()
        return jsonify({"ok": True, "paid": True,
                        "message": f"Payment confirmed! Pro access granted for {days} days."})
    elif result_code == "1032":
        # User cancelled
        _mpesa_pending.pop(checkout_id, None)
        return jsonify({"ok": True, "paid": False, "cancelled": True,
                        "message": "You cancelled the payment on your phone."})
    else:
        # Still pending or failed
        return jsonify({"ok": True, "paid": False,
                        "result_code": result_code,
                        "message": resp.get("ResultDesc", "Waiting for payment…")})


@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    """Safaricom sends payment confirmation here (server-to-server)."""
    data = request.get_json(silent=True) or {}
    try:
        body   = data["Body"]["stkCallback"]
        code   = body.get("ResultCode", -1)
        chk_id = body.get("CheckoutRequestID", "")
        if code == 0 and chk_id in _mpesa_pending:
            pending = _mpesa_pending.pop(chk_id)
            user    = db.session.get(User, pending["user_id"])
            if user:
                user.plan = 'pro'
                user.pro_expires_at = date.today() + timedelta(days=pending["days"])
                db.session.commit()
    except Exception:
        pass
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})


@app.route("/pricing")
def pricing():
    return render_template("pricing.html",
                           stripe_pub_key=STRIPE_PUB_KEY,
                           stripe_enabled=_STRIPE_OK,
                           mpesa_enabled=MPESA_OK,
                           pro_monthly_kes=PRO_MONTHLY_KES,
                           pro_annual_kes=PRO_ANNUAL_KES)


# ── Main routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    if current_user.is_authenticated:
        return render_template("index.html")
    return render_template("landing.html")


VALID_INTERVALS = {"1d", "1h", "15m"}


@app.route("/predict", methods=["POST"])
@login_required
def predict():
    ticker   = request.form.get("ticker", "").upper().strip()
    interval = request.form.get("interval", "1d").strip()

    if interval not in VALID_INTERVALS:
        interval = "1d"

    if not ticker:
        return render_template("index.html", error="Please enter a stock ticker symbol.",
                               interval=interval)

    if len(ticker) > 10 or not ticker.replace(".", "").replace("-", "").isalpha():
        return render_template("index.html",
                               error=f'"{ticker}" is not a valid ticker. Try AAPL, TSLA, or MSFT.',
                               interval=interval)

    if not consume_quota(current_user):
        return render_template("index.html",
                               error=f"You've used all {FREE_DAILY_LIMIT} free predictions for today. "
                                     "Upgrade to Pro for unlimited access.",
                               show_upgrade=True, interval=interval)

    try:
        _try_azure_download(ticker, interval)
        result = run_prediction(ticker, interval)
        # Save to prediction history
        try:
            ph = PredictionHistory(
                user_id=current_user.id,
                ticker=ticker,
                interval=interval,
                current_price=result["current_price"],
                lr_pred=result["lr_pred"],
                rf_pred=result["rf_pred"],
                direction=result["direction"],
                confidence=result["confidence"],
            )
            db.session.add(ph)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return render_template("result.html", **result)
    except ValueError as e:
        return render_template("index.html", error=str(e), interval=interval)
    except FileNotFoundError:
        return render_template("index.html",
                               error=f'No trained model for "{ticker}". '
                                     'Supported: AAPL, MSFT, TSLA, NVDA, GOOGL, AMZN, META, QQQ, SPY, DIA, ADBE, NFLX, AMD, V, JPM, CRM.',
                               interval=interval)
    except Exception:
        return render_template("index.html",
                               error=f'Could not fetch data for "{ticker}". Please check the symbol and try again.',
                               interval=interval)


# ── Market / Watchlist / History / Profile routes ────────────────────────────

@app.route("/market")
@login_required
def market():
    return render_template("market.html")


@app.route("/watchlist")
@login_required
def watchlist():
    items = WatchlistItem.query.filter_by(user_id=current_user.id).order_by(WatchlistItem.added_at).all()
    return render_template("watchlist.html", watchlist=[i.ticker for i in items])


@app.route("/api/watchlist/add", methods=["POST"])
@login_required
def watchlist_add():
    ticker = (request.get_json() or {}).get("ticker", "").upper().strip()
    if not ticker or len(ticker) > 10:
        return jsonify({"ok": False, "error": "Invalid ticker"}), 400
    try:
        db.session.add(WatchlistItem(user_id=current_user.id, ticker=ticker))
        db.session.commit()
        return jsonify({"ok": True})
    except Exception:
        db.session.rollback()
        return jsonify({"ok": False, "error": "Already in watchlist"}), 409


@app.route("/api/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    ticker = (request.get_json() or {}).get("ticker", "").upper().strip()
    WatchlistItem.query.filter_by(user_id=current_user.id, ticker=ticker).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/watchlist/signals")
@login_required
def watchlist_signals():
    """Return live ML signals for every ticker in the user's watchlist."""
    items = WatchlistItem.query.filter_by(user_id=current_user.id).all()
    tickers = [i.ticker for i in items]
    if not tickers:
        return jsonify({})

    def _get(ticker):
        sig = ml_signal(ticker, "1d")
        price = sig.get("current_price", 0)
        lr    = sig.get("lr_pred", price)
        chg   = round((lr - price) / price * 100, 2) if price else 0
        return ticker, {
            "price": price,
            "chg":   chg,
            "dir":   sig.get("action", "HOLD"),
            "conf":  sig.get("confidence", 0),
        }

    with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as ex:
        results = dict(ex.map(lambda t: _get(t), tickers))

    return jsonify(results)


@app.route("/history")
@login_required
def history():
    records = (PredictionHistory.query
               .filter_by(user_id=current_user.id)
               .order_by(PredictionHistory.predicted_at.desc())
               .limit(100).all())
    return render_template("history.html", records=records)


@app.route("/profile")
@login_required
def profile():
    total = PredictionHistory.query.filter_by(user_id=current_user.id).count()
    return render_template("profile.html", total_predictions=total)


@app.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    current_pw = request.form.get("current_password", "")
    new_pw     = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")
    total      = PredictionHistory.query.filter_by(user_id=current_user.id).count()
    if not current_user.check_password(current_pw):
        return render_template("profile.html", total_predictions=total,
                               pw_error="Current password is incorrect.")
    if len(new_pw) < 6:
        return render_template("profile.html", total_predictions=total,
                               pw_error="New password must be at least 6 characters.")
    if new_pw != confirm_pw:
        return render_template("profile.html", total_predictions=total,
                               pw_error="Passwords do not match.")
    current_user.set_password(new_pw)
    db.session.commit()
    return render_template("profile.html", total_predictions=total,
                           pw_success="Password updated successfully.")


@app.route("/profile/alerts", methods=["POST"])
@login_required
def toggle_alerts():
    current_user.alerts_enabled = not current_user.alerts_enabled
    db.session.commit()
    return jsonify({"ok": True, "alerts_enabled": current_user.alerts_enabled})


# ── MT5 routes (Pro only) ───────────────────────────────────────────────────

def pro_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Login required"}), 401
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro subscription required"}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/mt5")
@login_required
def mt5_dashboard():
    if not current_user.is_pro:
        return redirect(url_for('pricing'))
    return render_template("mt5.html", backend=mt5_trader.backend)


@app.route("/mt5/connect", methods=["POST"])
@pro_required
def mt5_connect():
    data               = request.get_json()
    account            = int(data.get("account", 0))
    password           = data.get("password", "")
    server             = data.get("server", "")
    host               = data.get("host", "localhost")
    port               = int(data.get("port", 18812))
    metaapi_token      = data.get("metaapi_token", "")
    metaapi_account_id = data.get("metaapi_account_id", "")
    return jsonify(mt5_trader.connect(account, password, server, host, port,
                                      metaapi_token, metaapi_account_id))


@app.route("/mt5/disconnect", methods=["POST"])
@pro_required
def mt5_disconnect():
    mt5_trader.disconnect()
    return jsonify({"ok": True})


@app.route("/mt5/start", methods=["POST"])
@pro_required
def mt5_start():
    data      = request.get_json()
    symbol    = data.get("symbol", "EURUSD")
    timeframe = data.get("timeframe", "M5")
    risk_pct  = float(data.get("risk_pct", 1.0))
    interval  = int(data.get("interval", 60))
    use_ml    = bool(data.get("use_ml", True))
    return jsonify(mt5_trader.start_trading(symbol, timeframe, risk_pct, interval, use_ml))


@app.route("/mt5/stop", methods=["POST"])
@pro_required
def mt5_stop():
    return jsonify(mt5_trader.stop_trading())


@app.route("/mt5/close_all", methods=["POST"])
@pro_required
def mt5_close_all():
    data   = request.get_json()
    symbol = data.get("symbol", "EURUSD")
    n      = mt5_trader.close_all(symbol)
    return jsonify({"ok": True, "closed": n})


@app.route("/mt5/status")
@pro_required
def mt5_status():
    return jsonify(mt5_trader.get_status())


@app.route("/api/predict/", methods=["GET"])
def api_predict_empty():
    return jsonify({"status": "error", "message": "Please provide a ticker symbol, e.g. /api/predict/AAPL"}), 400


@app.route("/api/predict/<ticker>", methods=["GET"])
def api_predict(ticker):
    if not current_user.is_authenticated:
        return jsonify({"status": "error", "message": "Authentication required."}), 401
    if not consume_quota(current_user):
        return jsonify({"status": "error",
                        "message": f"Daily limit of {FREE_DAILY_LIMIT} predictions reached. "
                                   "Upgrade to Pro for unlimited access."}), 429
    interval = request.args.get("interval", "1d")
    if interval not in VALID_INTERVALS:
        interval = "1d"
    t0 = time.time()
    try:
        _try_azure_download(ticker.upper(), interval)
        result = run_prediction(ticker.upper(), interval)
        for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21"]:
            result.pop(key, None)
        _metrics["predictions"] += 1
        _metrics["total_latency"] += time.time() - t0
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ── Quick Trade routes ───────────────────────────────────────────────────────

@app.route("/api/trade/connect", methods=["POST"])
@login_required
def trade_connect():
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Pro required"}), 403
    data = request.get_json() or {}
    mode = data.get("mode", "paper")
    if mode == "metaapi":
        result = mt5_trader.connect(0, "", "",
                                    metaapi_token=data.get("token", ""),
                                    metaapi_account_id=data.get("account_id", ""))
    elif mode == "paper":
        result = mt5_trader.connect(0, "", "")
    else:
        return jsonify({"ok": False, "error": "Unknown mode"}), 400
    return jsonify(result)


@app.route("/api/trade/disconnect", methods=["POST"])
@login_required
def trade_disconnect():
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Pro required"}), 403
    mt5_trader.disconnect()
    return jsonify({"ok": True})


@app.route("/api/trade/status", methods=["GET"])
@login_required
def trade_status():
    if not current_user.is_pro:
        return jsonify({"ok": False, "connected": False}), 403
    s = mt5_trader.get_status()
    return jsonify({
        "ok":        True,
        "connected": s["connected"],
        "mode":      s.get("mode", "none"),
        "account":   s.get("account", {}),
        "positions": s.get("positions", []),
    })


@app.route("/api/trade/order", methods=["POST"])
@login_required
def trade_order():
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Pro required"}), 403
    if not mt5_trader.connected:
        return jsonify({"ok": False, "error": "Not connected — use Connect Paper Account first"}), 400
    data     = request.get_json() or {}
    ticker   = data.get("ticker", "").upper()
    action   = data.get("action", "").upper()
    risk_pct = float(data.get("risk_pct", 1.0))
    atr      = float(data.get("atr", 0))
    if action not in ("BUY", "SELL"):
        return jsonify({"ok": False, "error": "action must be BUY or SELL"}), 400
    if not ticker:
        return jsonify({"ok": False, "error": "ticker required"}), 400
    try:
        result = mt5_trader.place_order(ticker, action, risk_pct, atr)
        if result.get("ok"):
            mt5_trader.refresh_account()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/trade/close", methods=["POST"])
@login_required
def trade_close():
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Pro required"}), 403
    if not mt5_trader.connected:
        return jsonify({"ok": False, "error": "Not connected"}), 400
    data   = request.get_json() or {}
    ticker = data.get("ticker", "").upper()
    n      = mt5_trader.close_all(ticker)
    mt5_trader.refresh_account()
    return jsonify({"ok": True, "closed": n})


# ── Multi-timeframe predictions ───────────────────────────────────────────────

@app.route("/api/mtf/<ticker>", methods=["GET"])
@login_required
def api_mtf(ticker):
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Pro required"}), 403
    ticker = ticker.upper()
    try:
        _try_azure_download(ticker, "1d")
        _try_azure_download(ticker, "1h")
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1d = ex.submit(run_prediction, ticker, "1d")
            f1h = ex.submit(run_prediction, ticker, "1h")
            r1d = f1d.result()
            r1h = f1h.result()
        import yfinance as yf
        hist = yf.download(ticker, period="5d", interval="1d",
                           auto_adjust=True, progress=False)
        if hasattr(hist.columns, "get_level_values"):
            hist.columns = hist.columns.get_level_values(0)
        prev_close = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else 0.0
        return jsonify({
            "ok":         True,
            "ticker":     ticker,
            "prev_close": prev_close,
            "1d": {
                "pred":         r1d["primary_pred"],
                "direction":    r1d["direction"],
                "change_pct":   r1d["change_pct"],
                "price_change": r1d["price_change"],
                "confidence":   r1d["confidence"],
            },
            "1h": {
                "pred":         r1h["primary_pred"],
                "direction":    r1h["direction"],
                "change_pct":   r1h["change_pct"],
                "price_change": r1h["price_change"],
                "confidence":   r1h["confidence"],
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Backtest endpoints ───────────────────────────────────────────────────────

@app.route("/performance")
def performance():
    """Public live track record page — no login required."""
    import sqlite3, json as _json
    import numpy as _np, pandas as _pd

    db_path = os.path.join(BASE_DIR, "Data", "paper_trades.db")
    bt_path = os.path.join(BASE_DIR, "Data", "backtest_summary.json")

    stats = {
        "started": None, "total_ret": 0, "n_trades": 0, "win_rate": 0,
        "profit_factor": 0, "sharpe": 0, "sortino": 0, "max_dd": 0,
        "equity": 10_000, "trades": [], "equity_dates": "[]", "equity_vals": "[]",
        "backtest_dates": "[]", "backtest_vals": "[]", "backtest_tickers": [],
    }

    # ── Live paper-trade equity ──
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            closed  = conn.execute(
                "SELECT * FROM paper_positions WHERE status='closed' ORDER BY exit_date"
            ).fetchall()
            eq_rows = conn.execute(
                "SELECT date, equity FROM paper_equity ORDER BY date"
            ).fetchall()
            conn.close()

            if eq_rows:
                eq_s = _pd.Series(
                    [r["equity"] for r in eq_rows],
                    index=_pd.to_datetime([r["date"] for r in eq_rows])
                )
                stats["equity"]       = round(float(eq_s.iloc[-1]), 2)
                stats["total_ret"]    = round((eq_s.iloc[-1] - 10_000) / 10_000 * 100, 2)
                stats["started"]      = eq_rows[0]["date"]
                stats["equity_dates"] = _json.dumps([r["date"] for r in eq_rows])
                stats["equity_vals"]  = _json.dumps([round(r["equity"], 2) for r in eq_rows])
                dr    = eq_s.pct_change().dropna()
                if dr.std() > 0:
                    stats["sharpe"]   = round(float(dr.mean() / dr.std() * _np.sqrt(252)), 3)
                dside = dr[dr < 0]
                if len(dside) > 1 and dside.std() > 0:
                    stats["sortino"]  = round(float(dr.mean() / dside.std() * _np.sqrt(252)), 3)
                peak  = eq_s.cummax()
                stats["max_dd"]       = round(float(((eq_s - peak) / peak).min() * 100), 2)

            if closed:
                wins   = [r for r in closed if (r["pnl"] or 0) > 0]
                losses = [r for r in closed if (r["pnl"] or 0) <= 0]
                gw     = sum(r["pnl"] for r in wins)
                gl     = abs(sum(r["pnl"] for r in losses))
                stats["n_trades"]      = len(closed)
                stats["win_rate"]      = round(len(wins) / len(closed) * 100, 1)
                stats["profit_factor"] = round(gw / gl if gl > 0 else 0, 2)
                stats["trades"]        = [dict(r) for r in closed[-20:]]
        except Exception:
            pass

    # ── Backtested equity curves ──
    if os.path.exists(bt_path):
        try:
            with open(bt_path) as f:
                bt = _json.load(f)
            combined = bt.get("combined", [])
            if combined:
                stats["backtest_dates"] = _json.dumps([p["date"] for p in combined])
                stats["backtest_vals"]  = _json.dumps([p["value"] for p in combined])
            tickers_data = bt.get("tickers", {})
            ticker_rows  = []
            for t, td in tickers_data.items():
                m = td.get("metrics", {})
                if m.get("n_trades", 0) > 0:
                    ticker_rows.append({
                        "ticker":        t,
                        "n_trades":      m["n_trades"],
                        "win_rate":      m["win_rate"],
                        "profit_factor": m["profit_factor"],
                        "sharpe":        m["sharpe"],
                        "total_return":  m["total_return"],
                        "bh_return":     m["bh_return"],
                    })
            stats["backtest_tickers"] = ticker_rows
        except Exception:
            pass

    return render_template("performance.html", **stats)


@app.route("/backtest")
@login_required
def backtest():
    return render_template("backtest.html")

@app.route("/api/backtest", methods=["POST"])
@login_required
def api_backtest():
    if not current_user.is_pro:
        return jsonify({"ok": False, "error": "Backtesting requires a Pro plan."}), 403
    data = request.get_json() or {}
    ticker   = data.get("ticker", "AAPL").upper()
    interval = data.get("interval", "1d")
    period   = data.get("period", "2y")
    capital  = float(data.get("initial_capital", 10_000))
    risk_pct = float(data.get("risk_pct", 1.0))

    if interval not in ("1d", "1h"):
        return jsonify({"ok": False, "error": "interval must be 1d or 1h"}), 400
    if period not in ("6mo", "1y", "2y"):
        return jsonify({"ok": False, "error": "period must be 6mo, 1y, or 2y"}), 400
    if not (100 <= capital <= 10_000_000):
        return jsonify({"ok": False, "error": "Capital must be between $100 and $10,000,000"}), 400
    if not (0.1 <= risk_pct <= 10):
        return jsonify({"ok": False, "error": "Risk must be between 0.1% and 10%"}), 400

    try:
        from backtester import run_backtest
        result = run_backtest(ticker, interval, period, capital, risk_pct)
        result["ok"] = True
        return jsonify(result)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Backtest error for %s", ticker)
        return jsonify({"ok": False, "error": f"Backtest failed: {str(e)}"}), 500


# ── Monitoring endpoints ─────────────────────────────────────────────────────

@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js"), 200, {"Content-Type": "application/javascript"}


@app.route("/health")
def health():
    return jsonify({
        "status":   "ok",
        "uptime_s": round(time.time() - _APP_START, 1),
    })


@app.route("/metrics")
def metrics():
    reqs = _metrics["requests"]
    avg  = (_metrics["total_latency"] / _metrics["predictions"]
            if _metrics["predictions"] > 0 else 0)
    return jsonify({
        "uptime_s":        round(time.time() - _APP_START, 1),
        "total_requests":  reqs,
        "total_predictions": _metrics["predictions"],
        "avg_latency_s":   round(avg, 3),
        "azure_enabled":   azure_enabled(),
    })


# ── Request hooks ────────────────────────────────────────────────────────────

@app.before_request
def before_request():
    g.start_time = time.time()
    _metrics["requests"] += 1


# ── Azure helper ─────────────────────────────────────────────────────────────

def _try_azure_download(ticker: str, interval: str = "1d"):
    """Download models from Azure if not present locally."""
    models_dir = os.path.join(BASE_DIR, "Saved Models")
    suffix = "" if interval == "1d" else f"_{interval}"
    needed = f"lr_model_{ticker}{suffix}.pkl"
    if not os.path.exists(os.path.join(models_dir, needed)):
        if azure_enabled():
            logger.info("Models for %s (%s) not found locally — trying Azure...", ticker, interval)
            download_models_from_azure(ticker)


# ── Screener ─────────────────────────────────────────────────────────────────

SCREENER_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "QQQ", "NDX", "NFLX", "AMD", "V", "JPM", "ADBE", "CRM",
]

@app.route("/screener")
@login_required
def screener():
    return render_template("screener.html")


@app.route("/api/screener")
@login_required
def api_screener():
    interval = request.args.get("interval", "1d")
    if interval not in ("1d", "1h"):
        interval = "1d"
    tickers = request.args.getlist("tickers") or SCREENER_TICKERS

    def _scan(ticker):
        try:
            sig = ml_signal(ticker, interval)
            return ticker, {
                "ticker":    ticker,
                "action":    sig.get("action", "HOLD"),
                "price":     sig.get("current_price", 0),
                "lr_pred":   sig.get("lr_pred", 0),
                "confidence":sig.get("confidence", 0),
                "rsi":       sig.get("rsi", 50),
                "macd_hist": sig.get("macd_hist", 0),
                "atr":       sig.get("atr", 0),
            }
        except Exception:
            return ticker, {"ticker": ticker, "action": "HOLD", "price": 0,
                            "lr_pred": 0, "confidence": 0, "rsi": 50,
                            "macd_hist": 0, "atr": 0}

    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as ex:
        results = dict(ex.map(lambda t: _scan(t), tickers))

    rows = sorted(results.values(), key=lambda x: x["confidence"], reverse=True)
    return jsonify({"ok": True, "interval": interval, "rows": rows})


# ── Price Alerts ──────────────────────────────────────────────────────────────

@app.route("/alerts")
@login_required
def alerts_page():
    user_alerts = PriceAlert.query.filter_by(
        user_id=current_user.id
    ).order_by(PriceAlert.created_at.desc()).all()
    return render_template("alerts.html", alerts=user_alerts)


@app.route("/api/alerts", methods=["GET"])
@login_required
def api_alerts_list():
    rows = PriceAlert.query.filter_by(user_id=current_user.id).order_by(
        PriceAlert.created_at.desc()).all()
    return jsonify([{
        "id": a.id, "ticker": a.ticker, "price": a.price,
        "direction": a.direction, "note": a.note or "",
        "triggered": a.triggered,
        "created_at": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
        "triggered_at": a.triggered_at.strftime("%Y-%m-%d %H:%M") if a.triggered_at else None,
    } for a in rows])


@app.route("/api/alerts/add", methods=["POST"])
@login_required
def api_alerts_add():
    data = request.get_json() or {}
    ticker    = data.get("ticker", "").upper().strip()
    price     = data.get("price")
    direction = data.get("direction", "above").lower()
    note      = data.get("note", "")[:100]
    if not ticker or price is None:
        return jsonify({"ok": False, "error": "ticker and price required"}), 400
    if direction not in ("above", "below"):
        return jsonify({"ok": False, "error": "direction must be above or below"}), 400
    try:
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "price must be a number"}), 400
    alert = PriceAlert(user_id=current_user.id, ticker=ticker,
                       price=price, direction=direction, note=note)
    db.session.add(alert)
    db.session.commit()
    return jsonify({"ok": True, "id": alert.id})


@app.route("/api/alerts/remove", methods=["POST"])
@login_required
def api_alerts_remove():
    alert_id = (request.get_json() or {}).get("alert_id")
    alert = PriceAlert.query.filter_by(id=alert_id, user_id=current_user.id).first()
    if not alert:
        return jsonify({"ok": False, "error": "Alert not found"}), 404
    db.session.delete(alert)
    db.session.commit()
    return jsonify({"ok": True})


def _send_telegram(chat_id: str, text: str):
    """Fire-and-forget Telegram message."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    import requests as _req
    try:
        _req.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception:
        pass


def _send_alert_email(user: "User", alert: "PriceAlert", price: float):
    """Send price alert email if mail is configured and user has alerts enabled."""
    if not mail or not app.config.get("MAIL_USERNAME"):
        return
    if not user.alerts_enabled:
        return
    try:
        subject = f"BullLogic Alert: {alert.ticker} hit ${price:.4f}"
        body = (
            f"Hi {user.username},\n\n"
            f"Your price alert for {alert.ticker} has triggered.\n\n"
            f"Condition: Price {alert.direction} ${alert.price:.4f}\n"
            f"Current price: ${price:.4f}\n"
            f"Note: {alert.note or '—'}\n\n"
            f"— BullLogic"
        )
        msg = MailMessage(subject=subject, recipients=[user.email], body=body)
        with app.app_context():
            mail.send(msg)
    except Exception:
        pass


def _check_alerts():
    """Background thread: poll open alerts every 2 min, mark triggered, notify."""
    import yfinance as yf
    with app.app_context():
        while True:
            try:
                pending = PriceAlert.query.filter_by(triggered=False).all()
                if pending:
                    unique_tickers = list({a.ticker for a in pending})
                    prices = {}
                    for t in unique_tickers:
                        try:
                            prices[t] = float(yf.Ticker(t).fast_info.last_price or 0)
                        except Exception:
                            pass
                    for alert in pending:
                        price = prices.get(alert.ticker, 0)
                        if price <= 0:
                            continue
                        hit = (alert.direction == "above" and price >= alert.price) or \
                              (alert.direction == "below" and price <= alert.price)
                        if hit:
                            alert.triggered    = True
                            alert.triggered_at = datetime.utcnow()
                            # Notify
                            user = db.session.get(User, alert.user_id)
                            if user:
                                threading.Thread(
                                    target=_send_alert_email, args=(user, alert, price), daemon=True
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
                                        target=_send_telegram, args=(tg.chat_id, msg), daemon=True
                                    ).start()
                    db.session.commit()
            except Exception:
                pass
            time.sleep(120)


_alert_thread = threading.Thread(target=_check_alerts, daemon=True)
_alert_thread.start()


# ── Portfolio Tracker ─────────────────────────────────────────────────────────

@app.route("/portfolio")
@login_required
def portfolio():
    return render_template("portfolio.html")


@app.route("/api/portfolio/positions", methods=["GET"])
@login_required
def portfolio_positions():
    import yfinance as yf
    positions = PortfolioPosition.query.filter_by(user_id=current_user.id).order_by(
        PortfolioPosition.opened_at.desc()).all()

    # Fetch live prices for open positions
    open_tickers = list({p.ticker for p in positions if p.status == "open"})
    live_prices = {}
    if open_tickers:
        def _px(t):
            try:
                return t, float(yf.Ticker(t).fast_info.last_price or 0)
            except Exception:
                return t, 0.0
        with ThreadPoolExecutor(max_workers=min(len(open_tickers), 6)) as ex:
            live_prices = dict(ex.map(_px, open_tickers))

    rows = []
    for p in positions:
        ep = p.entry_price
        qty = p.quantity
        if p.status == "open":
            lp = live_prices.get(p.ticker, ep)
            pnl = (lp - ep) * qty if p.side == "long" else (ep - lp) * qty
            pnl_pct = (pnl / (ep * qty) * 100) if ep * qty else 0
        else:
            lp = p.exit_price or ep
            pnl = (lp - ep) * qty if p.side == "long" else (ep - lp) * qty
            pnl_pct = (pnl / (ep * qty) * 100) if ep * qty else 0
        rows.append({
            "id": p.id, "ticker": p.ticker, "side": p.side,
            "entry_price": ep, "quantity": qty,
            "live_price": round(lp, 4),
            "exit_price": p.exit_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "status": p.status,
            "opened_at": p.opened_at.strftime("%Y-%m-%d") if p.opened_at else "",
            "closed_at": p.closed_at.strftime("%Y-%m-%d") if p.closed_at else None,
            "note": p.note or "",
        })
    return jsonify({"ok": True, "positions": rows})


@app.route("/api/portfolio/open", methods=["POST"])
@login_required
def portfolio_open():
    data = request.get_json() or {}
    ticker      = data.get("ticker", "").upper().strip()
    side        = data.get("side", "long").lower()
    entry_price = data.get("entry_price")
    quantity    = data.get("quantity")
    note        = data.get("note", "")[:200]
    if not ticker or entry_price is None or quantity is None:
        return jsonify({"ok": False, "error": "ticker, entry_price, quantity required"}), 400
    if side not in ("long", "short"):
        return jsonify({"ok": False, "error": "side must be long or short"}), 400
    try:
        entry_price = float(entry_price)
        quantity    = float(quantity)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "entry_price and quantity must be numbers"}), 400
    pos = PortfolioPosition(user_id=current_user.id, ticker=ticker, side=side,
                            entry_price=entry_price, quantity=quantity, note=note)
    db.session.add(pos)
    db.session.commit()
    return jsonify({"ok": True, "id": pos.id})


@app.route("/api/portfolio/close", methods=["POST"])
@login_required
def portfolio_close():
    data       = request.get_json() or {}
    pos_id     = data.get("position_id")
    exit_price = data.get("exit_price")
    pos = PortfolioPosition.query.filter_by(id=pos_id, user_id=current_user.id,
                                            status="open").first()
    if not pos:
        return jsonify({"ok": False, "error": "Position not found"}), 404
    if exit_price is None:
        return jsonify({"ok": False, "error": "exit_price required"}), 400
    pos.exit_price = float(exit_price)
    pos.status     = "closed"
    pos.closed_at  = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/portfolio/delete", methods=["POST"])
@login_required
def portfolio_delete():
    pos_id = (request.get_json() or {}).get("position_id")
    pos = PortfolioPosition.query.filter_by(id=pos_id, user_id=current_user.id).first()
    if not pos:
        return jsonify({"ok": False, "error": "Position not found"}), 404
    db.session.delete(pos)
    db.session.commit()
    return jsonify({"ok": True})


# ── History CSV export ────────────────────────────────────────────────────────

@app.route("/history/export")
@login_required
def history_export():
    records = (PredictionHistory.query
               .filter_by(user_id=current_user.id)
               .order_by(PredictionHistory.predicted_at.desc())
               .all())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Ticker", "Interval", "Current Price",
                     "LR Pred", "RF Pred", "Direction", "Confidence"])
    for r in records:
        writer.writerow([
            r.predicted_at.strftime("%Y-%m-%d %H:%M") if r.predicted_at else "",
            r.ticker, r.interval,
            round(r.current_price, 4), round(r.lr_pred, 4), round(r.rf_pred, 4),
            r.direction, round(r.confidence, 1),
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bulllogic_history.csv"},
    )


# ── News feed ─────────────────────────────────────────────────────────────────

@app.route("/api/news/<ticker>")
@login_required
def api_news(ticker):
    import yfinance as yf
    try:
        raw = yf.Ticker(ticker.upper()).news or []
        items = []
        for n in raw[:8]:
            ct = n.get("content", {})
            title = ct.get("title") or n.get("title", "")
            pub   = ct.get("pubDate") or n.get("providerPublishTime", "")
            link  = ct.get("canonicalUrl", {}).get("url") or n.get("link", "")
            pub_fmt = ""
            if isinstance(pub, int):
                pub_fmt = datetime.utcfromtimestamp(pub).strftime("%b %d, %Y")
            elif isinstance(pub, str) and pub:
                try:
                    pub_fmt = datetime.fromisoformat(pub[:19]).strftime("%b %d, %Y")
                except Exception:
                    pub_fmt = pub[:10]
            items.append({"title": title, "link": link, "published": pub_fmt})
        return jsonify({"ok": True, "ticker": ticker.upper(), "news": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Prediction Accuracy ───────────────────────────────────────────────────────

@app.route("/api/accuracy/check", methods=["POST"])
@login_required
def api_accuracy_check():
    """Check yesterday's predictions and record accuracy."""
    import yfinance as yf
    import pandas as pd
    yesterday = date.today() - timedelta(days=1)
    unchecked = (PredictionHistory.query
                 .outerjoin(PredictionAccuracy,
                            PredictionHistory.id == PredictionAccuracy.prediction_id)
                 .filter(PredictionHistory.user_id == current_user.id,
                         PredictionHistory.interval == "1d",
                         db.func.date(PredictionHistory.predicted_at) <= yesterday,
                         PredictionAccuracy.id == None)
                 .limit(20).all())
    checked = 0
    for pred in unchecked:
        try:
            hist = yf.download(pred.ticker, period="5d", interval="1d",
                               auto_adjust=True, progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            if len(hist) < 1:
                continue
            actual = float(hist["Close"].iloc[-1])
            expected_dir = pred.direction.lower()
            actual_up    = actual > pred.current_price
            dir_ok       = (expected_dir == "up" and actual_up) or \
                           (expected_dir == "down" and not actual_up)
            pct_err      = abs(pred.lr_pred - actual) / actual * 100
            acc = PredictionAccuracy(
                prediction_id=pred.id,
                actual_price=round(actual, 4),
                direction_ok=dir_ok,
                pct_error=round(pct_err, 2),
                checked_at=datetime.utcnow(),
            )
            db.session.add(acc)
            checked += 1
        except Exception:
            pass
    db.session.commit()
    return jsonify({"ok": True, "checked": checked})


@app.route("/api/accuracy")
@login_required
def api_accuracy():
    """Return accuracy statistics for the current user."""
    import pandas as _pd
    rows = (db.session.query(PredictionAccuracy, PredictionHistory)
            .join(PredictionHistory, PredictionAccuracy.prediction_id == PredictionHistory.id)
            .filter(PredictionHistory.user_id == current_user.id)
            .order_by(PredictionHistory.predicted_at.desc())
            .limit(200).all())
    if not rows:
        return jsonify({"ok": True, "count": 0, "direction_accuracy": None,
                        "avg_pct_error": None, "recent": []})
    total      = len(rows)
    dir_ok     = sum(1 for a, _ in rows if a.direction_ok)
    avg_err    = sum(a.pct_error for a, _ in rows if a.pct_error is not None) / total
    recent = [{
        "ticker":    ph.ticker,
        "date":      ph.predicted_at.strftime("%Y-%m-%d") if ph.predicted_at else "",
        "predicted": round(ph.lr_pred, 2),
        "actual":    round(acc.actual_price, 2) if acc.actual_price else None,
        "dir_ok":    acc.direction_ok,
        "pct_err":   round(acc.pct_error, 2) if acc.pct_error else None,
    } for acc, ph in rows[:20]]
    return jsonify({
        "ok": True, "count": total,
        "direction_accuracy": round(dir_ok / total * 100, 1),
        "avg_pct_error": round(avg_err, 2),
        "recent": recent,
    })


# ── API Key Management ────────────────────────────────────────────────────────

_API_DAILY_LIMIT = 100   # calls/day for free tier via API key

@app.route("/api/keys", methods=["GET"])
@login_required
def api_keys_list():
    keys = ApiKey.query.filter_by(user_id=current_user.id).order_by(
        ApiKey.created_at.desc()).all()
    return jsonify([{
        "id": k.id, "name": k.name,
        "key_preview": k.key[:8] + "..." + k.key[-4:],
        "created_at": k.created_at.strftime("%Y-%m-%d") if k.created_at else "",
        "last_used": k.last_used.strftime("%Y-%m-%d %H:%M") if k.last_used else None,
        "calls_today": k.calls_today,
    } for k in keys])


@app.route("/api/keys/create", methods=["POST"])
@login_required
def api_keys_create():
    if ApiKey.query.filter_by(user_id=current_user.id).count() >= 5:
        return jsonify({"ok": False, "error": "Maximum 5 API keys per account"}), 400
    name = (request.get_json() or {}).get("name", "Default")[:50]
    key  = secrets.token_hex(32)
    ak   = ApiKey(user_id=current_user.id, key=key, name=name)
    db.session.add(ak)
    db.session.commit()
    return jsonify({"ok": True, "key": key, "id": ak.id, "name": name})


@app.route("/api/keys/delete", methods=["POST"])
@login_required
def api_keys_delete():
    key_id = (request.get_json() or {}).get("key_id")
    ak = ApiKey.query.filter_by(id=key_id, user_id=current_user.id).first()
    if not ak:
        return jsonify({"ok": False, "error": "Key not found"}), 404
    db.session.delete(ak)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/v1/predict/<ticker>", methods=["GET"])
def api_v1_predict(ticker):
    """API key authenticated prediction endpoint."""
    key_str  = request.args.get("key") or request.headers.get("X-API-Key", "")
    if not key_str:
        return jsonify({"status": "error", "message": "API key required. Pass ?key=YOUR_KEY"}), 401

    ak = ApiKey.query.filter_by(key=key_str).first()
    if not ak:
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    owner = db.session.get(User, ak.user_id)
    if not owner:
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    # Rate limiting for free users
    today = date.today()
    if ak.calls_date != today:
        ak.calls_today = 0
        ak.calls_date  = today
    if not owner.is_pro and ak.calls_today >= _API_DAILY_LIMIT:
        return jsonify({"status": "error",
                        "message": f"Daily API limit of {_API_DAILY_LIMIT} reached. Upgrade to Pro."}), 429

    ak.calls_today += 1
    ak.last_used    = datetime.utcnow()
    db.session.commit()

    interval = request.args.get("interval", "1d")
    if interval not in ("1d", "1h", "15m"):
        interval = "1d"
    try:
        result = run_prediction(ticker.upper(), interval)
        for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21", "lw_chart"]:
            result.pop(key, None)
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ── Admin Dashboard ───────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "bulllogic-admin-2025")


def _admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("admin_token") or request.args.get("admin_token", "")
        if token != ADMIN_PASSWORD:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            resp = make_response(redirect(url_for("admin_dashboard")))
            resp.set_cookie("admin_token", ADMIN_PASSWORD, httponly=True, samesite="Lax")
            return resp
        error = "Wrong password."
    return render_template("admin_login.html", error=error)


@app.route("/admin")
@_admin_required
def admin_dashboard():
    today = date.today()
    stats = {
        "total_users":       User.query.count(),
        "pro_users":         User.query.filter_by(plan="pro").count(),
        "total_predictions": PredictionHistory.query.count(),
        "predictions_today": PredictionHistory.query.filter(
            db.func.date(PredictionHistory.predicted_at) == today).count(),
        "total_alerts":      PriceAlert.query.count(),
        "open_positions":    PortfolioPosition.query.filter_by(status="open").count(),
        "api_keys":          ApiKey.query.count(),
    }
    top_tickers = (db.session.query(
        PredictionHistory.ticker,
        db.func.count(PredictionHistory.id).label("cnt")
    ).group_by(PredictionHistory.ticker)
     .order_by(db.func.count(PredictionHistory.id).desc())
     .limit(10).all())
    recent_users = User.query.order_by(User.id.desc()).limit(10).all()
    return render_template("admin.html", stats=stats,
                           top_tickers=top_tickers, recent_users=recent_users)


# ── Telegram setup ────────────────────────────────────────────────────────────

@app.route("/api/telegram/configure", methods=["POST"])
@login_required
def telegram_configure():
    data    = request.get_json() or {}
    chat_id = str(data.get("chat_id", "")).strip()
    enabled = bool(data.get("enabled", True))
    if not chat_id:
        return jsonify({"ok": False, "error": "chat_id required"}), 400
    cfg = TelegramConfig.query.filter_by(user_id=current_user.id).first()
    if cfg:
        cfg.chat_id = chat_id
        cfg.enabled = enabled
    else:
        cfg = TelegramConfig(user_id=current_user.id, chat_id=chat_id, enabled=enabled)
        db.session.add(cfg)
    db.session.commit()
    # Send a test message
    _send_telegram(chat_id, f"✅ BullLogic connected for *{current_user.username}*. You'll receive price alerts here.")
    return jsonify({"ok": True})


@app.route("/api/telegram/status", methods=["GET"])
@login_required
def telegram_status():
    cfg = TelegramConfig.query.filter_by(user_id=current_user.id).first()
    return jsonify({"configured": bool(cfg), "chat_id": cfg.chat_id if cfg else None,
                    "enabled": cfg.enabled if cfg else False})


@app.route("/api/telegram/remove", methods=["POST"])
@login_required
def telegram_remove():
    TelegramConfig.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ── AI Market Analyst ─────────────────────────────────────────────────────────

@app.route("/api/ai/analyze/<ticker>", methods=["POST"])
@login_required
def ai_analyze(ticker):
    """Use Claude to generate a market commentary for a given ticker + prediction."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"ok": False, "error": "AI analyst not configured (ANTHROPIC_API_KEY missing)."}), 503
    try:
        import anthropic as _anthropic
        data = request.get_json() or {}
        interval      = data.get("interval", "1d")
        current_price = data.get("current_price", 0)
        lr_pred       = data.get("lr_pred", 0)
        direction     = data.get("direction", "—")
        confidence    = data.get("confidence", 0)
        rsi           = data.get("rsi", 50)
        macd_signal   = data.get("macd_signal", "—")
        ict_bias      = data.get("ict_bias", "—")
        pd_zone       = data.get("pd_zone", "—")

        prompt = (
            f"You are a professional quantitative trader and market analyst. "
            f"Provide a concise, actionable market commentary (3-4 short paragraphs) for {ticker.upper()} "
            f"based on the following ML prediction data:\n\n"
            f"- Timeframe: {interval}\n"
            f"- Current Price: ${current_price}\n"
            f"- ML Predicted Next Price: ${lr_pred}\n"
            f"- Direction: {direction} (Confidence: {confidence}%)\n"
            f"- RSI(14): {rsi}\n"
            f"- MACD: {macd_signal}\n"
            f"- ICT Bias: {ict_bias}\n"
            f"- PD Zone: {pd_zone}\n\n"
            f"Cover: (1) what the data implies about short-term momentum, "
            f"(2) key levels to watch, (3) risk factors, (4) suggested approach. "
            f"Be direct and professional. No disclaimers."
        )

        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text
        return jsonify({"ok": True, "analysis": analysis})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Earnings & Economic Calendar ──────────────────────────────────────────────

CALENDAR_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "NFLX", "AMD", "V", "JPM", "ADBE", "CRM", "AMZN",
]

@app.route("/calendar")
@login_required
def calendar_page():
    return render_template("calendar.html")


@app.route("/api/calendar/earnings")
@login_required
def api_calendar_earnings():
    import yfinance as yf
    import pandas as pd
    results = []
    today   = date.today()

    def _fetch(ticker):
        try:
            t    = yf.Ticker(ticker)
            raw  = t.earnings_dates
            if raw is None or raw.empty:
                return
            idx = raw.index.tz_localize(None) if raw.index.tz else raw.index
            for dt in idx:
                d = dt.date()
                if d >= today and (d - today).days <= 90:
                    results.append({
                        "ticker": ticker,
                        "date":   d.strftime("%Y-%m-%d"),
                        "days":   (d - today).days,
                    })
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_fetch, CALENDAR_TICKERS))

    results.sort(key=lambda x: x["date"])
    return jsonify({"ok": True, "events": results})


@app.route("/api/calendar/macro")
@login_required
def api_calendar_macro():
    """Static upcoming macro events (updated manually or via external API)."""
    # In production, replace with a proper economic calendar API
    import calendar as _cal
    today  = date.today()
    events = []
    # Generate approximate recurring events for next 90 days
    for offset in range(0, 90):
        d = today + timedelta(days=offset)
        # FOMC meetings are roughly every 6-7 weeks; approximate first Wednesday
        if d.weekday() == 2 and offset % 42 < 7:
            events.append({"name": "FOMC Meeting (approx)", "date": d.strftime("%Y-%m-%d"),
                           "impact": "high", "category": "fed"})
        # CPI roughly 2nd Tuesday of each month
        if d.weekday() == 1 and 8 <= d.day <= 14:
            events.append({"name": "CPI Report (approx)", "date": d.strftime("%Y-%m-%d"),
                           "impact": "high", "category": "inflation"})
        # NFP first Friday of month
        if d.weekday() == 4 and d.day <= 7:
            events.append({"name": "Non-Farm Payrolls (approx)", "date": d.strftime("%Y-%m-%d"),
                           "impact": "high", "category": "employment"})
    return jsonify({"ok": True, "events": events[:20]})


# ── Risk / Position Size Calculator ──────────────────────────────────────────

@app.route("/risk")
@login_required
def risk_calculator():
    return render_template("risk.html")


@app.route("/api/risk/calculate", methods=["POST"])
@login_required
def api_risk_calculate():
    data        = request.get_json() or {}
    account     = float(data.get("account",    10000))
    risk_pct    = float(data.get("risk_pct",   1.0))
    entry       = float(data.get("entry",      100))
    stop_loss   = float(data.get("stop_loss",  95))
    target      = float(data.get("target",     110))
    ticker      = data.get("ticker",           "").upper()

    if entry <= 0 or stop_loss <= 0:
        return jsonify({"ok": False, "error": "Invalid prices"}), 400

    risk_amount  = account * risk_pct / 100
    risk_per_sh  = abs(entry - stop_loss)
    if risk_per_sh == 0:
        return jsonify({"ok": False, "error": "Entry and stop loss cannot be equal"}), 400

    shares       = risk_amount / risk_per_sh
    position_val = shares * entry
    rr_ratio     = abs(target - entry) / risk_per_sh if risk_per_sh else 0
    potential_pnl = (target - entry) * shares

    # Kelly criterion (simplified: win_rate estimated from confidence, odds from RR)
    # Use a neutral 55% win rate as default since we don't have historical data inline
    win_rate_est  = 0.55
    kelly_fraction = win_rate_est - (1 - win_rate_est) / rr_ratio if rr_ratio > 0 else 0
    kelly_shares  = max(0, account * kelly_fraction / entry)

    return jsonify({
        "ok":           True,
        "shares":       round(shares, 4),
        "position_val": round(position_val, 2),
        "risk_amount":  round(risk_amount, 2),
        "risk_per_sh":  round(risk_per_sh, 4),
        "rr_ratio":     round(rr_ratio, 2),
        "potential_pnl":round(potential_pnl, 2),
        "kelly_shares": round(kelly_shares, 4),
        "kelly_pct":    round(kelly_fraction * 100, 2),
    })


# ── Forgot / Reset Password ───────────────────────────────────────────────────

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    sent = False
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user  = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            expires = datetime.utcnow() + timedelta(hours=2)
            rt = PasswordResetToken(user_id=user.id, token=token, expires_at=expires)
            db.session.add(rt)
            db.session.commit()
            reset_url = request.host_url.rstrip("/") + url_for("reset_password", token=token)
            if mail and app.config.get("MAIL_USERNAME"):
                try:
                    msg = MailMessage(
                        subject="BullLogic — Password Reset",
                        recipients=[user.email],
                        body=(
                            f"Hi {user.username},\n\n"
                            f"Click the link below to reset your password (valid for 2 hours):\n"
                            f"{reset_url}\n\n"
                            f"If you didn't request this, ignore this email.\n\n— BullLogic"
                        ),
                    )
                    mail.send(msg)
                except Exception:
                    pass
        # Always show success to avoid email enumeration
        sent = True
    return render_template("forgot_password.html", sent=sent, error=error)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    rt = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not rt or rt.expires_at < datetime.utcnow():
        return render_template("reset_password.html", invalid=True)
    error = None
    if request.method == "POST":
        pw      = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif pw != confirm:
            error = "Passwords do not match."
        else:
            user = db.session.get(User, rt.user_id)
            if user:
                user.set_password(pw)
            rt.used = True
            db.session.commit()
            return redirect(url_for("login"))
    return render_template("reset_password.html", token=token, error=error, invalid=False)


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE 3 — ADVANCED ANALYTICS & PLATFORM (25 new features)
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import pyotp as _pyotp
    _PYOTP_OK = True
except ImportError:
    _pyotp = None
    _PYOTP_OK = False

_POSITIVE_WORDS = {
    "rally","surge","soar","rise","gain","beat","record","profit","strong","growth",
    "upgrade","outperform","positive","boost","buy","breakout","milestone","expand",
    "exceed","robust","recover","rebound","launch","partner","deal","approve",
}
_NEGATIVE_WORDS = {
    "crash","fall","plunge","drop","loss","miss","decline","weak","cut","sell",
    "underperform","warning","concern","risk","debt","layoff","downgrade","recall",
    "investigation","lawsuit","fraud","default","bankruptcy","halt","suspend","probe",
}

_SECTOR_ETFS = {
    "Technology":       "XLK",
    "Healthcare":       "XLV",
    "Financials":       "XLF",
    "Consumer Disc":    "XLY",
    "Industrials":      "XLI",
    "Energy":           "XLE",
    "Consumer Staples": "XLP",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
    "Utilities":        "XLU",
    "Communication":    "XLC",
}


# ── Wave-3 helper functions ───────────────────────────────────────────────────

def _add_notification(user_id, ntype, title, body=None, link=None):
    try:
        with app.app_context():
            n = Notification(user_id=user_id, type=ntype, title=title, body=body, link=link)
            db.session.add(n)
            db.session.commit()
    except Exception:
        pass


def _fire_webhooks(user_id, event, payload):
    import hmac as _hmac
    try:
        hooks = UserWebhook.query.filter_by(user_id=user_id, active=True).all()
        for hook in hooks:
            evts = (hook.events or "alert,signal").split(",")
            if event not in evts:
                continue
            try:
                import requests as _req
                body_str = _json_std.dumps({"event": event, "data": payload})
                headers = {"Content-Type": "application/json", "X-BullLogic-Event": event}
                if hook.secret:
                    sig = _hmac.new(hook.secret.encode(), body_str.encode(), "sha256").hexdigest()
                    headers["X-BullLogic-Signature"] = f"sha256={sig}"
                _req.post(hook.url, data=body_str, headers=headers, timeout=5)
                hook.last_fired = datetime.utcnow()
                hook.fire_count = (hook.fire_count or 0) + 1
                db.session.commit()
            except Exception:
                pass
    except Exception:
        pass


def _send_discord(webhook_url, title, body, color=0x00AA55):
    try:
        import requests as _req
        _req.post(webhook_url, json={
            "embeds": [{"title": title, "description": body,
                        "color": color, "footer": {"text": "BullLogic"}}]
        }, timeout=5)
    except Exception:
        pass


def _log_activity(user_id, action, detail=None):
    try:
        ip = request.remote_addr if request else None
        ua = (request.headers.get("User-Agent") or "")[:200] if request else None
        entry = ActivityLog(user_id=user_id, action=action, detail=detail, ip=ip, ua=ua)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass


# ── Real-time SSE price stream ────────────────────────────────────────────────

@app.route("/api/stream/prices")
@login_required
def stream_prices():
    import yfinance as yf
    tickers = request.args.getlist("t") or ["AAPL", "MSFT", "TSLA", "NVDA", "SPY"]
    tickers = [t.upper() for t in tickers[:15]]

    def generate():
        while True:
            batch = {}
            for t in tickers:
                try:
                    fi = yf.Ticker(t).fast_info
                    lp = float(fi.last_price or 0)
                    pc = float(fi.previous_close or 0)
                    batch[t] = {
                        "price": round(lp, 4),
                        "prev":  round(pc, 4),
                        "chg":   round(lp - pc, 4),
                        "pct":   round((lp - pc) / pc * 100 if pc else 0, 2),
                    }
                except Exception:
                    pass
            yield f"data: {_json_std.dumps(batch)}\n\n"
            time.sleep(8)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Batch price snapshot (sidebar live prices) ───────────────────────────────

@app.route("/api/prices/batch")
@login_required
def api_prices_batch():
    import yfinance as yf
    tickers = request.args.getlist("t") or []
    tickers = [t.upper() for t in tickers[:60]]
    result = {}
    def _fetch(t):
        try:
            fi = yf.Ticker(t).fast_info
            lp = float(fi.last_price or 0)
            pc = float(fi.previous_close or 0)
            pct = round((lp - pc) / pc * 100 if pc else 0, 2)
            result[t] = {"price": round(lp, 4), "change_pct": pct}
        except Exception:
            result[t] = None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as ex:
        ex.map(_fetch, tickers)
    return jsonify(result)


# ── Fear & Greed Index ────────────────────────────────────────────────────────

@app.route("/api/fear-greed")
@login_required
def api_fear_greed():
    try:
        import yfinance as yf
        import pandas as pd
        import ta as _ta

        spy_hist = yf.download("SPY", period="1y", interval="1d", auto_adjust=True, progress=False)
        if isinstance(spy_hist.columns, pd.MultiIndex):
            spy_hist.columns = spy_hist.columns.get_level_values(0)
        spy_close = spy_hist["Close"].dropna()

        mom_score = 50.0
        if len(spy_close) >= 125:
            ma125 = spy_close.rolling(125).mean().iloc[-1]
            ratio = float(spy_close.iloc[-1]) / float(ma125)
            mom_score = max(0.0, min(100.0, (ratio - 0.9) / 0.2 * 100))

        vix_hist = yf.download("^VIX", period="30d", interval="1d", auto_adjust=True, progress=False)
        if isinstance(vix_hist.columns, pd.MultiIndex):
            vix_hist.columns = vix_hist.columns.get_level_values(0)
        vix_level = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 20.0
        vol_score = max(0.0, min(100.0, (40 - vix_level) / 30 * 100))

        rsi_val = 50.0
        if len(spy_close) >= 14:
            rsi_val = float(_ta.momentum.rsi(spy_close, window=14).iloc[-1])

        h52 = float(spy_close.rolling(252, min_periods=100).max().iloc[-1])
        l52 = float(spy_close.rolling(252, min_periods=100).min().iloc[-1])
        hl_score = (float(spy_close.iloc[-1]) - l52) / (h52 - l52) * 100 if h52 != l52 else 50.0

        composite = max(0, min(100, int(round(
            mom_score * 0.30 + vol_score * 0.30 + rsi_val * 0.20 + hl_score * 0.20
        ))))

        if composite >= 75:   label, color = "Extreme Greed", "#00C853"
        elif composite >= 55: label, color = "Greed",          "#69F0AE"
        elif composite >= 45: label, color = "Neutral",        "#FFD54F"
        elif composite >= 25: label, color = "Fear",           "#FF8A65"
        else:                 label, color = "Extreme Fear",   "#FF5252"

        return jsonify({
            "ok": True, "score": composite, "label": label, "color": color,
            "vix": round(vix_level, 1), "rsi": round(rsi_val, 1),
            "components": {
                "momentum":   round(mom_score),
                "volatility": round(vol_score),
                "rsi":        round(rsi_val),
                "breadth":    round(hl_score),
            },
        })
    except Exception as e:
        return jsonify({"ok": True, "score": 50, "label": "Neutral", "color": "#FFD54F",
                        "vix": 0, "rsi": 50, "components": {}, "error": str(e)})


# ── Correlation matrix ────────────────────────────────────────────────────────

@app.route("/api/correlation")
@login_required
def api_correlation():
    try:
        import yfinance as yf
        import pandas as pd

        tickers = request.args.getlist("t")
        if not tickers:
            items = WatchlistItem.query.filter_by(user_id=current_user.id).all()
            tickers = [i.ticker for i in items]
        if len(tickers) < 2:
            return jsonify({"ok": False, "error": "Add at least 2 tickers to your watchlist"})
        tickers = [t.upper() for t in tickers[:12]]

        raw = yf.download(tickers, period="3mo", interval="1d", auto_adjust=True, progress=False)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])
        close = close.dropna(axis=1, how="all")
        rets  = close.pct_change().dropna()
        corr  = rets.corr().round(3)

        return jsonify({"ok": True, "tickers": list(corr.columns), "matrix": corr.values.tolist()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── News sentiment ────────────────────────────────────────────────────────────

@app.route("/api/sentiment/<ticker>")
@login_required
def api_sentiment(ticker):
    try:
        import yfinance as yf
        news = yf.Ticker(ticker.upper()).news or []
        scores, headlines = [], []
        for item in news[:15]:
            content = item.get("content") or {}
            title   = (content.get("title") or item.get("title") or "").lower()
            pos = sum(1 for w in _POSITIVE_WORDS if w in title)
            neg = sum(1 for w in _NEGATIVE_WORDS if w in title)
            s   = (pos - neg) / (pos + neg) if (pos + neg) else 0
            scores.append(s)
            url = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
            headlines.append({"title": title[:120], "score": round(s, 2), "url": url})

        avg = round(sum(scores) / len(scores), 3) if scores else 0
        if avg > 0.25:   label, color = "Bullish",          "#69F0AE"
        elif avg > 0.0:  label, color = "Slightly Bullish", "#B9F6CA"
        elif avg > -0.25:label, color = "Slightly Bearish", "#FFAB91"
        else:            label, color = "Bearish",          "#FF5252"

        return jsonify({
            "ok": True, "ticker": ticker.upper(),
            "score": avg, "label": label, "color": color,
            "article_count": len(news), "analyzed": len(scores),
            "headlines": headlines[:8],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── ML feature importance ─────────────────────────────────────────────────────

@app.route("/api/feature-importance/<ticker>")
@login_required
def api_feature_importance(ticker):
    try:
        import joblib
        ticker = ticker.upper()
        models_dir = os.path.join(BASE_DIR, "Saved Models")
        rf_path   = os.path.join(models_dir, f"rf_model_{ticker}.pkl")
        feat_path = os.path.join(models_dir, f"feature_cols_sklearn_{ticker}.pkl")
        if not os.path.exists(rf_path):
            return jsonify({"ok": False, "error": f"No model found for {ticker}. Run a prediction first."})
        rf   = joblib.load(rf_path)
        feat = joblib.load(feat_path)
        pairs = sorted(zip(feat, rf.feature_importances_.tolist()), key=lambda x: x[1], reverse=True)[:15]
        return jsonify({
            "ok": True, "ticker": ticker,
            "features": [{"name": n, "importance": round(v, 4)} for n, v in pairs],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Monte Carlo portfolio simulation ──────────────────────────────────────────

@app.route("/api/monte-carlo", methods=["POST"])
@login_required
def api_monte_carlo():
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np

        data    = request.get_json() or {}
        tickers = data.get("tickers", ["AAPL"])[:10]
        weights = data.get("weights")
        capital = float(data.get("capital", 10000))
        days    = int(data.get("days", 252))
        sims    = min(int(data.get("simulations", 500)), 1000)

        raw = yf.download(tickers, period="2y", interval="1d", auto_adjust=True, progress=False)
        prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers[0])
        rets = prices.pct_change().dropna()

        w = np.array(weights if weights and len(weights) == len(tickers) else [1 / len(tickers)] * len(tickers))
        w = w / w.sum()
        port_r = rets.dot(w)
        mu, sigma = float(port_r.mean()), float(port_r.std())

        paths = np.zeros((sims, days))
        for i in range(sims):
            r = np.random.normal(mu, sigma, days)
            paths[i] = capital * np.cumprod(1 + r)

        final = paths[:, -1]
        p5, p25, p50, p75, p95 = np.percentile(final, [5, 25, 50, 75, 95])
        step = max(1, days // 60)

        return jsonify({
            "ok": True, "simulations": sims, "days": days, "capital": capital,
            "final": {"p5": round(p5, 2), "p25": round(p25, 2),
                      "p50": round(p50, 2), "p75": round(p75, 2), "p95": round(p95, 2)},
            "chart": {
                "p5":  [round(v, 2) for v in np.percentile(paths, 5,  axis=0)[::step]],
                "p50": [round(v, 2) for v in np.percentile(paths, 50, axis=0)[::step]],
                "p95": [round(v, 2) for v in np.percentile(paths, 95, axis=0)[::step]],
            },
            "prob_profit": round(float((final > capital).mean() * 100), 1),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Volume anomaly scanner ────────────────────────────────────────────────────

@app.route("/api/scanner/volume")
@login_required
def api_scanner_volume():
    import yfinance as yf
    import pandas as pd
    results = []

    def _chk_vol(t):
        try:
            hist = yf.download(t, period="30d", interval="1d", auto_adjust=True, progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            if len(hist) < 10:
                return
            avg_vol = float(hist["Volume"].iloc[:-1].mean())
            today   = float(hist["Volume"].iloc[-1])
            ratio   = today / avg_vol if avg_vol > 0 else 1.0
            price   = float(hist["Close"].iloc[-1])
            chg     = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100)
            results.append({"ticker": t, "price": round(price, 2),
                            "volume": int(today), "avg_volume": int(avg_vol),
                            "volume_ratio": round(ratio, 2), "pct_change": round(chg, 2)})
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_chk_vol, SCREENER_TICKERS))
    results.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return jsonify({"ok": True, "rows": results})


# ── Short squeeze scanner ─────────────────────────────────────────────────────

@app.route("/api/scanner/short-squeeze")
@login_required
def api_scanner_short_squeeze():
    import yfinance as yf
    import pandas as pd
    import ta as _ta
    results = []

    def _chk_sq(t):
        try:
            info = yf.Ticker(t).info
            sf   = (info.get("shortPercentOfFloat") or 0) * 100
            sr   = info.get("shortRatio") or 0
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            hist = yf.download(t, period="30d", interval="1d", auto_adjust=True, progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            rsi_val = None
            if len(hist) >= 14:
                rsi_val = round(float(_ta.momentum.rsi(hist["Close"], window=14).iloc[-1]), 1)
            mom = 0.0
            if len(hist) >= 5:
                mom = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-5] - 1) * 100), 2)
            results.append({
                "ticker": t, "price": round(float(price), 2),
                "short_float_pct": round(float(sf), 1),
                "days_to_cover": round(float(sr), 1),
                "rsi": rsi_val, "momentum_5d": mom,
                "squeeze_score": round(float(sf) * 0.5 + max(0, mom) * 0.5, 1),
            })
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(_chk_sq, SCREENER_TICKERS))
    results.sort(key=lambda x: x["squeeze_score"], reverse=True)
    return jsonify({"ok": True, "rows": results})


# ── Sector heatmap ────────────────────────────────────────────────────────────

@app.route("/api/scanner/sector-heatmap")
@login_required
def api_scanner_sector_heatmap():
    import yfinance as yf
    import pandas as pd
    results = []

    def _chk_sector(item):
        sector, etf = item
        try:
            hist = yf.download(etf, period="5d", interval="1d", auto_adjust=True, progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            if len(hist) < 2:
                return
            d1 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100), 2)
            d5 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[0]  - 1) * 100), 2)
            results.append({"sector": sector, "etf": etf,
                            "price": round(float(hist["Close"].iloc[-1]), 2),
                            "d1": d1, "d5": d5,
                            "volume": int(hist["Volume"].iloc[-1])})
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_chk_sector, _SECTOR_ETFS.items()))
    results.sort(key=lambda x: x["d1"], reverse=True)
    return jsonify({"ok": True, "sectors": results})


# ── Short interest + institutional holders ────────────────────────────────────

@app.route("/api/short-interest/<ticker>")
@login_required
def api_short_interest(ticker):
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker.upper())
        info = t.info
        holders = []
        try:
            ih = t.institutional_holders
            if ih is not None and not ih.empty:
                for _, row in ih.head(6).iterrows():
                    holders.append({
                        "holder": str(row.get("Holder", "")),
                        "shares": int(row.get("Shares", 0)),
                        "pct":    round(float(row.get("% Out", 0)) * 100, 2),
                    })
        except Exception:
            pass
        return jsonify({
            "ok": True, "ticker": ticker.upper(),
            "short_pct":   round(float((info.get("shortPercentOfFloat") or 0) * 100), 2),
            "short_ratio": round(float(info.get("shortRatio") or 0), 2),
            "float_shares": int(info.get("floatShares") or 0),
            "institutional_pct": round(float((info.get("heldPercentInstitutions") or 0) * 100), 1),
            "insider_pct":       round(float((info.get("heldPercentInsiders") or 0) * 100), 1),
            "top_holders": holders,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Options chain ─────────────────────────────────────────────────────────────

@app.route("/api/options/<ticker>")
@login_required
def api_options(ticker):
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker.upper())
        exps = t.options
        if not exps:
            return jsonify({"ok": False, "error": "No options data available"})
        exp = request.args.get("exp") or exps[0]
        chain = t.option_chain(exp)
        price = float(t.fast_info.last_price or 0)

        def _fmt(df, otype):
            rows = []
            for _, r in df.iterrows():
                try:
                    vol = r.get("volume", 0)
                    oi  = r.get("openInterest", 0)
                    rows.append({
                        "strike":  float(r.get("strike", 0) or 0),
                        "iv":      round(float(r.get("impliedVolatility", 0) or 0) * 100, 1),
                        "volume":  int(vol) if vol == vol else 0,  # NaN check
                        "oi":      int(oi)  if oi  == oi  else 0,
                        "bid":     float(r.get("bid", 0) or 0),
                        "ask":     float(r.get("ask", 0) or 0),
                        "itm":     bool(r.get("inTheMoney", False)),
                        "type":    otype,
                    })
                except Exception:
                    pass
            return rows

        calls = _fmt(chain.calls, "call")
        puts  = _fmt(chain.puts,  "put")
        near  = sorted(calls + puts, key=lambda x: abs(x["strike"] - price))[:20]
        return jsonify({
            "ok": True, "ticker": ticker.upper(), "expiry": exp,
            "expirations": list(exps[:6]), "price": round(price, 2),
            "calls": calls[:15], "puts": puts[:15], "near_atm": near,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Dividend history ──────────────────────────────────────────────────────────

@app.route("/api/dividends/<ticker>")
@login_required
def api_dividends(ticker):
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker.upper())
        info = t.info
        divs = t.dividends
        history = []
        if divs is not None and not divs.empty:
            for dt, val in divs.tail(12).items():
                history.append({"date": str(dt.date()), "amount": round(float(val), 4)})
        return jsonify({
            "ok": True, "ticker": ticker.upper(),
            "dividend_yield": round(float((info.get("dividendYield") or 0) * 100), 2),
            "forward_annual": round(float(info.get("dividendRate") or 0), 4),
            "payout_ratio":   round(float((info.get("payoutRatio") or 0) * 100), 1),
            "ex_dividend_date": str(info.get("exDividendDate") or ""),
            "history": list(reversed(history)),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Insider transactions ──────────────────────────────────────────────────────

@app.route("/api/insiders/<ticker>")
@login_required
def api_insiders(ticker):
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        rows = []
        try:
            insiders = t.insider_transactions
            if insiders is not None and not insiders.empty:
                for _, r in insiders.head(10).iterrows():
                    rows.append({
                        "insider":  str(r.get("Insider", "")),
                        "relation": str(r.get("Relation", "")),
                        "date":     str(r.get("Start Date", "")),
                        "shares":   int(r.get("Shares", 0) or 0),
                        "value":    int(r.get("Value", 0) or 0),
                        "type":     str(r.get("Transaction", "")),
                    })
        except Exception:
            pass
        return jsonify({"ok": True, "ticker": ticker.upper(), "transactions": rows})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Analyst price targets ─────────────────────────────────────────────────────

@app.route("/api/analyst-targets/<ticker>")
@login_required
def api_analyst_targets(ticker):
    try:
        import yfinance as yf
        info = yf.Ticker(ticker.upper()).info
        return jsonify({
            "ok": True, "ticker": ticker.upper(),
            "current_price":  round(float(info.get("currentPrice") or 0), 2),
            "target_mean":    round(float(info.get("targetMeanPrice") or 0), 2),
            "target_high":    round(float(info.get("targetHighPrice") or 0), 2),
            "target_low":     round(float(info.get("targetLowPrice") or 0), 2),
            "target_median":  round(float(info.get("targetMedianPrice") or 0), 2),
            "recommendation": str(info.get("recommendationKey") or "n/a"),
            "analyst_count":  int(info.get("numberOfAnalystOpinions") or 0),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ── Scanner page ──────────────────────────────────────────────────────────────

@app.route("/scanner")
@login_required
def scanner_page():
    return render_template("scanner.html", user=current_user)


# ── Notification bell API ─────────────────────────────────────────────────────

@app.route("/api/notifications")
@login_required
def api_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
                               .order_by(Notification.created_at.desc()).limit(30).all()
    unread = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    return jsonify({
        "ok": True, "unread": unread,
        "notifications": [{
            "id": n.id, "type": n.type, "title": n.title, "body": n.body,
            "read": n.read, "link": n.link,
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
        } for n in notifs],
    })


@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_notifications_read():
    nid = (request.get_json() or {}).get("id")
    if nid:
        n = Notification.query.filter_by(id=nid, user_id=current_user.id).first()
        if n:
            n.read = True
            db.session.commit()
    else:
        Notification.query.filter_by(user_id=current_user.id, read=False)\
                          .update({"read": True})
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/clear", methods=["POST"])
@login_required
def api_notifications_clear():
    Notification.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ── Trade Journal ─────────────────────────────────────────────────────────────

@app.route("/journal")
@login_required
def journal_page():
    return render_template("journal.html", user=current_user)


@app.route("/api/journal")
@login_required
def api_journal_list():
    q = TradeJournal.query.filter_by(user_id=current_user.id)\
                          .order_by(TradeJournal.created_at.desc())
    tag = request.args.get("tag")
    if tag:
        q = q.filter(TradeJournal.tags.ilike(f"%{tag}%"))
    ticker = request.args.get("ticker")
    if ticker:
        q = q.filter(TradeJournal.ticker == ticker.upper())
    entries = q.limit(100).all()
    return jsonify({"ok": True, "entries": [{
        "id": e.id, "ticker": e.ticker, "title": e.title, "body": e.body[:300],
        "mood": e.mood, "tags": e.tags, "trade_type": e.trade_type,
        "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
    } for e in entries]})


@app.route("/api/journal/add", methods=["POST"])
@login_required
def api_journal_add():
    data  = request.get_json() or {}
    title = (data.get("title") or "").strip()[:100]
    body  = (data.get("body") or "").strip()
    if not title or not body:
        return jsonify({"ok": False, "error": "Title and body required"}), 400
    entry = TradeJournal(
        user_id    = current_user.id,
        ticker     = (data.get("ticker") or "").upper()[:12] or None,
        title      = title,
        body       = body[:5000],
        mood       = data.get("mood"),
        tags       = (data.get("tags") or "")[:200],
        trade_type = data.get("trade_type"),
    )
    db.session.add(entry)
    db.session.commit()
    _add_notification(current_user.id, "system", "Journal entry saved", title)
    return jsonify({"ok": True, "id": entry.id})


@app.route("/api/journal/delete", methods=["POST", "DELETE"])
@login_required
def api_journal_delete():
    eid = (request.get_json() or {}).get("id")
    e   = TradeJournal.query.filter_by(id=eid, user_id=current_user.id).first()
    if not e:
        return jsonify({"ok": False, "error": "Not found"}), 404
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True})


# ── Discord webhook ───────────────────────────────────────────────────────────

@app.route("/api/discord/configure", methods=["POST"])
@login_required
def api_discord_configure():
    url = (request.get_json() or {}).get("webhook_url", "").strip()
    if not url.startswith("https://discord.com/api/webhooks/"):
        return jsonify({"ok": False, "error": "Invalid Discord webhook URL"}), 400
    cfg = DiscordConfig.query.filter_by(user_id=current_user.id).first()
    if cfg:
        cfg.webhook_url = url
        cfg.enabled = True
    else:
        cfg = DiscordConfig(user_id=current_user.id, webhook_url=url)
        db.session.add(cfg)
    db.session.commit()
    _send_discord(url, "BullLogic Connected", f"Hi {current_user.username}! Discord alerts are now active.", 0xFF6B35)
    return jsonify({"ok": True})


@app.route("/api/discord/status")
@login_required
def api_discord_status():
    cfg = DiscordConfig.query.filter_by(user_id=current_user.id).first()
    return jsonify({"ok": True, "configured": cfg is not None,
                    "enabled": cfg.enabled if cfg else False})


@app.route("/api/discord/remove", methods=["POST"])
@login_required
def api_discord_remove():
    DiscordConfig.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/discord/test", methods=["POST"])
@login_required
def api_discord_test():
    cfg = DiscordConfig.query.filter_by(user_id=current_user.id).first()
    if not cfg:
        return jsonify({"ok": False, "error": "Discord not configured"}), 400
    _send_discord(cfg.webhook_url, "BullLogic Test", "This is a test notification from BullLogic.", 0xFF6B35)
    return jsonify({"ok": True})


# ── Gift codes ────────────────────────────────────────────────────────────────

@app.route("/api/gift-codes/generate", methods=["POST"])
def api_gift_codes_generate():
    admin_cookie = request.cookies.get("admin_token", "")
    admin_pw     = os.environ.get("ADMIN_PASSWORD", "bulllogic-admin")
    if not admin_cookie or not secrets.compare_digest(admin_cookie, admin_pw):
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    data = request.get_json() or {}
    days = int(data.get("days", 30))
    count = min(int(data.get("count", 1)), 20)
    note  = (data.get("note") or "")[:100]
    codes = []
    for _ in range(count):
        code = secrets.token_hex(6).upper()
        gc   = GiftCode(code=code, days=days, note=note)
        db.session.add(gc)
        codes.append(code)
    db.session.commit()
    return jsonify({"ok": True, "codes": codes, "days": days})


@app.route("/api/gift-codes/redeem", methods=["POST"])
@login_required
def api_gift_codes_redeem():
    code = (request.get_json() or {}).get("code", "").upper().strip()
    gc   = GiftCode.query.filter_by(code=code, used=False).first()
    if not gc:
        return jsonify({"ok": False, "error": "Invalid or already used code"}), 400
    gc.used    = True
    gc.used_by = current_user.id
    gc.used_at = datetime.utcnow()
    user = db.session.get(User, current_user.id)
    if user.plan != "pro":
        user.plan = "pro"
        user.pro_expires_at = date.today() + timedelta(days=gc.days)
    else:
        if user.pro_expires_at:
            user.pro_expires_at = user.pro_expires_at + timedelta(days=gc.days)
        else:
            user.pro_expires_at = date.today() + timedelta(days=gc.days)
    db.session.commit()
    _add_notification(current_user.id, "gift", "Pro activated!",
                      f"Your gift code added {gc.days} days of Pro access.", "/profile")
    return jsonify({"ok": True, "days_added": gc.days,
                    "pro_until": str(user.pro_expires_at)})


# ── Two-factor authentication ─────────────────────────────────────────────────

@app.route("/api/2fa/setup")
@login_required
def api_2fa_setup():
    if not _PYOTP_OK:
        return jsonify({"ok": False, "error": "2FA library not installed (pip install pyotp)"}), 503
    rec = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if rec and rec.enabled:
        return jsonify({"ok": False, "error": "2FA already enabled"}), 400
    secret = _pyotp.random_base32()
    if rec:
        rec.secret = secret
    else:
        rec = TwoFactorAuth(user_id=current_user.id, secret=secret)
        db.session.add(rec)
    db.session.commit()
    uri = _pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="BullLogic"
    )
    return jsonify({"ok": True, "secret": secret, "uri": uri})


@app.route("/api/2fa/enable", methods=["POST"])
@login_required
def api_2fa_enable():
    if not _PYOTP_OK:
        return jsonify({"ok": False, "error": "2FA library not installed"}), 503
    code = (request.get_json() or {}).get("code", "")
    rec  = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if not rec:
        return jsonify({"ok": False, "error": "Run /api/2fa/setup first"}), 400
    totp = _pyotp.TOTP(rec.secret)
    if not totp.verify(code, valid_window=1):
        return jsonify({"ok": False, "error": "Invalid code"}), 400
    backup = [secrets.token_hex(4).upper() for _ in range(8)]
    rec.enabled      = True
    rec.backup_codes = _json_std.dumps(backup)
    db.session.commit()
    _add_notification(current_user.id, "system", "2FA Enabled",
                      "Two-factor authentication is now active on your account.")
    _log_activity(current_user.id, "2fa_enable")
    return jsonify({"ok": True, "backup_codes": backup})


@app.route("/api/2fa/disable", methods=["POST"])
@login_required
def api_2fa_disable():
    if not _PYOTP_OK:
        return jsonify({"ok": False, "error": "2FA library not installed"}), 503
    data = request.get_json() or {}
    code = data.get("code", "")
    rec  = TwoFactorAuth.query.filter_by(user_id=current_user.id, enabled=True).first()
    if not rec:
        return jsonify({"ok": False, "error": "2FA is not enabled"}), 400
    totp = _pyotp.TOTP(rec.secret)
    pw   = data.get("password", "")
    user = db.session.get(User, current_user.id)
    if not user.check_password(pw):
        return jsonify({"ok": False, "error": "Incorrect password"}), 400
    if not totp.verify(code, valid_window=1):
        return jsonify({"ok": False, "error": "Invalid 2FA code"}), 400
    rec.enabled = False
    db.session.commit()
    _log_activity(current_user.id, "2fa_disable")
    return jsonify({"ok": True})


@app.route("/api/2fa/status")
@login_required
def api_2fa_status():
    rec = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    return jsonify({"ok": True, "enabled": rec.enabled if rec else False,
                    "available": _PYOTP_OK})


# ── User webhooks ─────────────────────────────────────────────────────────────

@app.route("/api/webhooks")
@login_required
def api_webhooks_list():
    hooks = UserWebhook.query.filter_by(user_id=current_user.id).all()
    return jsonify({"ok": True, "webhooks": [{
        "id": h.id, "name": h.name, "url": h.url[:60] + "...",
        "events": h.events, "active": h.active,
        "fire_count": h.fire_count,
        "last_fired": h.last_fired.strftime("%Y-%m-%d %H:%M") if h.last_fired else None,
    } for h in hooks]})


@app.route("/api/webhooks/add", methods=["POST"])
@login_required
def api_webhooks_add():
    data = request.get_json() or {}
    url  = (data.get("url") or "").strip()
    if not url.startswith("http"):
        return jsonify({"ok": False, "error": "URL must start with http"}), 400
    if UserWebhook.query.filter_by(user_id=current_user.id).count() >= 5:
        return jsonify({"ok": False, "error": "Max 5 webhooks per account"}), 400
    hook = UserWebhook(
        user_id = current_user.id,
        url     = url[:500],
        name    = (data.get("name") or "My Webhook")[:50],
        events  = (data.get("events") or "alert,signal")[:100],
        secret  = secrets.token_hex(16),
    )
    db.session.add(hook)
    db.session.commit()
    return jsonify({"ok": True, "id": hook.id, "secret": hook.secret})


@app.route("/api/webhooks/delete", methods=["POST"])
@login_required
def api_webhooks_delete():
    wid  = (request.get_json() or {}).get("id")
    hook = UserWebhook.query.filter_by(id=wid, user_id=current_user.id).first()
    if not hook:
        return jsonify({"ok": False, "error": "Not found"}), 404
    db.session.delete(hook)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/webhooks/test", methods=["POST"])
@login_required
def api_webhooks_test():
    wid  = (request.get_json() or {}).get("id")
    hook = UserWebhook.query.filter_by(id=wid, user_id=current_user.id).first()
    if not hook:
        return jsonify({"ok": False, "error": "Not found"}), 404
    _fire_webhooks(current_user.id, "alert", {
        "message": "BullLogic webhook test",
        "ticker": "AAPL", "price": 195.0, "timestamp": datetime.utcnow().isoformat(),
    })
    return jsonify({"ok": True})


# ── Activity log ──────────────────────────────────────────────────────────────

@app.route("/api/activity-log")
@login_required
def api_activity_log():
    entries = ActivityLog.query.filter_by(user_id=current_user.id)\
                               .order_by(ActivityLog.created_at.desc()).limit(50).all()
    return jsonify({"ok": True, "entries": [{
        "action": e.action, "detail": e.detail, "ip": e.ip,
        "ua": (e.ua or "")[:60],
        "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
    } for e in entries]})


# ── User preferences ──────────────────────────────────────────────────────────

@app.route("/api/preferences", methods=["GET"])
@login_required
def api_preferences_get():
    prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
    return jsonify({
        "ok": True,
        "digest_enabled": prefs.digest_enabled if prefs else False,
        "theme":          prefs.theme          if prefs else "dark",
        "default_ticker": prefs.default_ticker if prefs else "AAPL",
        "timezone":       prefs.timezone        if prefs else "UTC",
    })


@app.route("/api/preferences", methods=["POST"])
@login_required
def api_preferences_set():
    data  = request.get_json() or {}
    prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
    if not prefs:
        prefs = UserPreferences(user_id=current_user.id)
        db.session.add(prefs)
    if "digest_enabled" in data:
        prefs.digest_enabled = bool(data["digest_enabled"])
    if "theme" in data and data["theme"] in ("dark", "light"):
        prefs.theme = data["theme"]
    if "default_ticker" in data:
        prefs.default_ticker = (data["default_ticker"] or "AAPL").upper()[:12]
    if "timezone" in data:
        prefs.timezone = (data["timezone"] or "UTC")[:50]
    db.session.commit()
    return jsonify({"ok": True})


# ── Daily email digest ────────────────────────────────────────────────────────

@app.route("/api/digest/send", methods=["POST"])
@login_required
def api_digest_send():
    user = current_user
    try:
        signals = []
        for t in SCREENER_TICKERS[:6]:
            try:
                sig = ml_signal(t, "1d")
                signals.append(f"  {t}: {sig.get('action','?')} (conf {sig.get('confidence',0):.0%})")
            except Exception:
                pass
        body_lines = [
            f"Good morning {user.username}!",
            "",
            "BullLogic Daily Market Digest",
            "=" * 30,
            "",
            "Top Scanner Signals:",
            *signals,
            "",
            "Log in at bulllogic.app for full analysis.",
            "",
            "— BullLogic",
        ]
        if mail and app.config.get("MAIL_USERNAME") and user.email:
            msg = MailMessage(
                subject="BullLogic — Daily Market Digest",
                recipients=[user.email],
                body="\n".join(body_lines),
            )
            mail.send(msg)
            _log_activity(user.id, "digest_sent")
            return jsonify({"ok": True, "message": "Digest sent to your email"})
        return jsonify({"ok": False, "error": "Email not configured"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


if __name__ == "__main__":
    print("ML-based Quantitative Trading System")
    print("Running at: http://127.0.0.1:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
