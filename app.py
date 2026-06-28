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
import time
import logging
import warnings
warnings.filterwarnings("ignore")

from datetime import date, datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, g, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from concurrent.futures import ThreadPoolExecutor
from predictor import run_prediction, ml_signal
from mt5_trading import trader as mt5_trader
from azure_storage import download_models_from_azure, azure_enabled

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_APP_START   = time.time()
_metrics     = {"requests": 0, "predictions": 0, "total_latency": 0.0}

app = Flask(__name__, template_folder="Web Pages", static_folder="Static Files")
app.secret_key = os.environ.get("SECRET_KEY", "smp-dev-key-2025")

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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_pro(self):
        return self.plan == 'pro'

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
    ]:
        if _col not in _cols:
            _conn.execute(_ddl)
    _conn.commit(); _conn.close()


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


@app.route("/pricing")
def pricing():
    return render_template("pricing.html",
                           stripe_pub_key=STRIPE_PUB_KEY,
                           stripe_enabled=_STRIPE_OK)


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


# ── Main routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
@login_required
def home():
    return render_template("index.html")


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
        "backtest_dates": "[]", "backtest_vals": "[]", "backtest_tickers": "[]",
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


if __name__ == "__main__":
    print("ML-based Quantitative Trading System")
    print("Running at: http://127.0.0.1:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
