"""
app.py
ML-based Quantitative Trading System

Flask web application with user authentication and subscription tiers.
Free accounts: 5 predictions/day. Pro accounts: unlimited.

Usage:
    python app.py

Then open: http://127.0.0.1:5000

Author: Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
"""

import os
import time
import logging
import warnings
warnings.filterwarnings("ignore")

from datetime import date
from flask import Flask, render_template, request, jsonify, redirect, url_for, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from predictor import run_prediction
from mt5_trading import trader as mt5_trader
from azure_storage import download_models_from_azure, azure_enabled

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
    id                   = db.Column(db.Integer, primary_key=True)
    username             = db.Column(db.String(80), unique=True, nullable=False)
    email                = db.Column(db.String(120), unique=True, nullable=False)
    password_hash        = db.Column(db.String(256), nullable=False)
    plan                 = db.Column(db.String(20), default='free')
    predictions_today    = db.Column(db.Integer, default=0)
    last_prediction_date = db.Column(db.Date, nullable=True)

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
    return render_template("pricing.html")


@app.route("/upgrade", methods=["POST"])
@login_required
def upgrade():
    current_user.plan = 'pro'
    db.session.commit()
    return redirect(url_for('home'))


# ── Main routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
@login_required
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
@login_required
def predict():
    ticker = request.form.get("ticker", "").upper().strip()

    if not ticker:
        return render_template("index.html", error="Please enter a stock ticker symbol.")

    if len(ticker) > 10 or not ticker.replace(".", "").replace("-", "").isalpha():
        return render_template("index.html",
                               error=f'"{ticker}" is not a valid ticker. Try AAPL, TSLA, or MSFT.')

    if not consume_quota(current_user):
        return render_template("index.html",
                               error=f"You've used all {FREE_DAILY_LIMIT} free predictions for today. "
                                     "Upgrade to Pro for unlimited access.",
                               show_upgrade=True)

    try:
        result = run_prediction(ticker)
        return render_template("result.html", **result)
    except ValueError as e:
        return render_template("index.html", error=str(e))
    except Exception:
        return render_template("index.html",
                               error=f'Could not fetch data for "{ticker}". Please check the symbol and try again.')


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
    t0 = time.time()
    try:
        _try_azure_download(ticker.upper())
        result = run_prediction(ticker.upper())
        for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21"]:
            result.pop(key, None)
        _metrics["predictions"] += 1
        _metrics["total_latency"] += time.time() - t0
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


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

def _try_azure_download(ticker: str):
    """Download models from Azure if not present locally."""
    models_dir = os.path.join(BASE_DIR, "Saved Models")
    needed = f"lr_model_{ticker}.pkl"
    if not os.path.exists(os.path.join(models_dir, needed)):
        if azure_enabled():
            logger.info("Models for %s not found locally — trying Azure...", ticker)
            download_models_from_azure(ticker)


if __name__ == "__main__":
    print("ML-based Quantitative Trading System")
    print("Running at: http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
