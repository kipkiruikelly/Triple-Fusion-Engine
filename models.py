"""models.py, all SQLAlchemy ORM models."""

from datetime import date, datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

FREE_DAILY_LIMIT = 5

# Role hierarchy for admin access control (higher = more privileged)
ROLE_LEVELS = {'user': 0, 'viewer': 1, 'support': 2, 'admin': 3}


class User(UserMixin, db.Model):
    id                      = db.Column(db.Integer, primary_key=True)
    username                = db.Column(db.String(80), unique=True, nullable=False)
    email                   = db.Column(db.String(120), unique=True, nullable=False)
    password_hash           = db.Column(db.String(256), nullable=False)
    plan                    = db.Column(db.String(20), default='free')
    role                    = db.Column(db.String(10), default='user')    # user|viewer|support|admin
    status                  = db.Column(db.String(12), default='active')  # active|deactivated|banned
    created_at              = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen               = db.Column(db.DateTime, nullable=True)
    email_verified          = db.Column(db.Boolean, default=False)
    auth_provider           = db.Column(db.String(10), default='local')   # local|google
    google_sub              = db.Column(db.String(64), unique=True, nullable=True)
    session_token           = db.Column(db.String(32), nullable=True)    # rotates to kill sessions

    def get_id(self):
        # flask-login session id carries the session_token; rotating the
        # token after a password reset invalidates every other session.
        return f"{self.id}:{self.session_token or ''}"
    predictions_today       = db.Column(db.Integer, default=0)
    last_prediction_date    = db.Column(db.Date, nullable=True)
    stripe_customer_id      = db.Column(db.String(64), nullable=True)
    stripe_subscription_id  = db.Column(db.String(64), nullable=True)
    alerts_enabled          = db.Column(db.Boolean, default=True)
    pro_expires_at          = db.Column(db.Date, nullable=True)
    theme_preference        = db.Column(db.String(10), default='system')  # light|dark|system

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_level(self):
        return ROLE_LEVELS.get(self.role or 'user', 0)

    @property
    def is_pro(self):
        if self.plan == 'pro':
            if self.pro_expires_at is None:
                return True
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


class PredictionHistory(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker        = db.Column(db.String(12), nullable=False)
    interval      = db.Column(db.String(4), nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    lr_pred       = db.Column(db.Float, nullable=False)
    rf_pred       = db.Column(db.Float, nullable=False)
    direction     = db.Column(db.String(8), nullable=False)
    confidence    = db.Column(db.Float, nullable=False)
    predicted_at  = db.Column(db.DateTime, default=datetime.utcnow)
    # Data-quality context captured at prediction time (nullable, best effort)
    src_source     = db.Column(db.String(12), nullable=True)   # yfinance|pyth|both
    src_conf_pct   = db.Column(db.Float, nullable=True)        # Pyth conf / price * 100
    src_divergence = db.Column(db.Float, nullable=True)        # % gap between sources


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
    direction    = db.Column(db.String(8), nullable=False)
    note         = db.Column(db.String(100), nullable=True)
    triggered    = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    triggered_at = db.Column(db.DateTime, nullable=True)


class PortfolioPosition(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker      = db.Column(db.String(12), nullable=False)
    side        = db.Column(db.String(8), nullable=False)
    entry_price = db.Column(db.Float, nullable=False)
    quantity    = db.Column(db.Float, nullable=False)
    exit_price  = db.Column(db.Float, nullable=True)
    status      = db.Column(db.String(8), default='open')
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
    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    chat_id = db.Column(db.String(32), nullable=False)
    enabled = db.Column(db.Boolean, default=True)


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


class Payment(db.Model):
    """Audit record for every payment attempt (Stripe, M-Pesa, gift code).

    Also serves as the durable store for pending M-Pesa STK pushes so a
    service restart between push and callback cannot lose the payment.
    """
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider     = db.Column(db.String(10), nullable=False)   # 'stripe' | 'mpesa' | 'gift'
    plan         = db.Column(db.String(10), nullable=True)    # 'monthly' | 'annual'
    amount       = db.Column(db.Float, nullable=True)
    currency     = db.Column(db.String(8), nullable=True)
    days         = db.Column(db.Integer, nullable=True)
    phone        = db.Column(db.String(15), nullable=True)
    reference    = db.Column(db.String(80), unique=True, nullable=True)  # CheckoutRequestID / Stripe session id / gift code
    receipt      = db.Column(db.String(40), nullable=True)               # MpesaReceiptNumber
    status       = db.Column(db.String(10), default='pending')  # pending | paid | cancelled | failed | refunded
    flagged      = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


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


class AdminAuditLog(db.Model):
    """Immutable log of every admin action, no delete/update path in the app."""
    id          = db.Column(db.Integer, primary_key=True)
    admin_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action      = db.Column(db.String(50), nullable=False)    # e.g. 'login', 'user.ban', 'payment.refund'
    target_type = db.Column(db.String(30), nullable=True)     # 'user', 'payment', 'ticker', 'setting', ...
    target_id   = db.Column(db.String(40), nullable=True)
    detail      = db.Column(db.String(400), nullable=True)
    ip          = db.Column(db.String(45), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AppSetting(db.Model):
    """Key-value store for app settings and feature flags."""
    key        = db.Column(db.String(50), primary_key=True)
    value      = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class TickerConfig(db.Model):
    """Admin-managed list of supported tickers."""
    id       = db.Column(db.Integer, primary_key=True)
    symbol   = db.Column(db.String(12), unique=True, nullable=False)
    name     = db.Column(db.String(60), nullable=True)
    enabled  = db.Column(db.Boolean, default=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Broadcast(db.Model):
    """History of admin announcements sent to users."""
    id         = db.Column(db.Integer, primary_key=True)
    admin_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(100), nullable=False)
    body       = db.Column(db.String(1000), nullable=False)
    segment    = db.Column(db.String(10), default='all')      # all | free | pro
    channel    = db.Column(db.String(10), default='in-app')   # in-app | email | both
    sent_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ErrorLog(db.Model):
    """Application errors captured by the global error handler."""
    id         = db.Column(db.Integer, primary_key=True)
    severity   = db.Column(db.String(10), default='error', index=True)  # error | warning
    endpoint   = db.Column(db.String(120), nullable=True)
    method     = db.Column(db.String(8), nullable=True)
    message    = db.Column(db.String(500), nullable=False)
    trace      = db.Column(db.Text, nullable=True)
    ip         = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class PythFeed(db.Model):
    """Mapping from our ticker symbols to Pyth Network price feed ids."""
    id          = db.Column(db.Integer, primary_key=True)
    symbol      = db.Column(db.String(12), unique=True, nullable=False)
    feed_id     = db.Column(db.String(70), nullable=False)
    pyth_symbol = db.Column(db.String(40), nullable=True)
    active      = db.Column(db.Boolean, default=True)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow)


class ResourceLink(db.Model):
    """Curated external links shown on the Resources hub, admin managed."""
    id          = db.Column(db.Integer, primary_key=True)
    category    = db.Column(db.String(40), nullable=False)
    title       = db.Column(db.String(80), nullable=False)
    url         = db.Column(db.String(300), nullable=False)
    description = db.Column(db.String(200), nullable=True)
    icon        = db.Column(db.String(10), nullable=True)      # emoji
    sort        = db.Column(db.Integer, default=0)
    active      = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class Feedback(db.Model):
    """User feedback from the in-app widget, scored for sentiment."""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    page       = db.Column(db.String(50), nullable=True)
    rating     = db.Column(db.Integer, nullable=False)     # 1..5
    comment    = db.Column(db.String(500), nullable=True)
    sentiment  = db.Column(db.Float, nullable=True)        # -1..1 word-list score
    resolved   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class PaperTrade(db.Model):
    """One simulated (VIRTUAL money) trade in the platform paper trading
    engine. Append-only: rows are inserted at open, and the exit fields are
    written exactly once at close. Nothing here is ever a real order.
    """
    id             = db.Column(db.Integer, primary_key=True)
    strategy       = db.Column(db.String(20), nullable=False, index=True)   # 'ml_ensemble' | 'alpha_rules'
    model          = db.Column(db.String(40), nullable=True)                # e.g. 'lr+rf', 'alpha_composite'
    ticker         = db.Column(db.String(12), nullable=False, index=True)
    asset_class    = db.Column(db.String(12), nullable=False)               # equity|etf|index|crypto|forex|commodity
    side           = db.Column(db.String(5), nullable=False)                # LONG | SHORT
    qty            = db.Column(db.Float, nullable=False)
    entry_time     = db.Column(db.DateTime, nullable=False)
    entry_price    = db.Column(db.Float, nullable=False)                    # fill after simulated friction
    entry_mkt      = db.Column(db.Float, nullable=False)                    # raw market price at signal time
    price_source   = db.Column(db.String(20), nullable=True)                # yfinance | yfinance+pyth | pyth
    stop_price     = db.Column(db.Float, nullable=False)
    target_price   = db.Column(db.Float, nullable=False)
    max_hold_hours = db.Column(db.Integer, nullable=False)
    confidence     = db.Column(db.Float, nullable=True)
    rationale      = db.Column(db.String(300), nullable=True)
    commission     = db.Column(db.Float, nullable=False, default=0.0)       # total paid, entry+exit
    status         = db.Column(db.String(8), nullable=False, default='open', index=True)
    exit_time      = db.Column(db.DateTime, nullable=True)
    exit_price     = db.Column(db.Float, nullable=True)
    exit_mkt       = db.Column(db.Float, nullable=True)
    exit_reason    = db.Column(db.String(12), nullable=True)                # target|stop|reversal|timeout|manual
    pnl            = db.Column(db.Float, nullable=True)                     # VIRTUAL, net of friction
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)


class PaperTradeEvent(db.Model):
    """Append-only audit trail for the paper trading engine."""
    id         = db.Column(db.Integer, primary_key=True)
    trade_id   = db.Column(db.Integer, db.ForeignKey('paper_trade.id'), nullable=True, index=True)
    event      = db.Column(db.String(20), nullable=False)   # open|close|reject|breaker|toggle|config
    detail     = db.Column(db.String(400), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class PaperEquitySnapshot(db.Model):
    """Mark-to-market VIRTUAL equity per strategy, taken every engine cycle."""
    id         = db.Column(db.Integer, primary_key=True)
    strategy   = db.Column(db.String(20), nullable=False, index=True)
    equity     = db.Column(db.Float, nullable=False)
    open_count = db.Column(db.Integer, nullable=False, default=0)
    taken_at   = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class UserPreferences(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    digest_enabled = db.Column(db.Boolean, default=False)
    theme          = db.Column(db.String(10), default='dark')
    default_ticker = db.Column(db.String(12), default='AAPL')
    timezone       = db.Column(db.String(50), default='UTC')
    risk_intro_seen      = db.Column(db.Boolean, default=False)
    usage_notice_enabled = db.Column(db.Boolean, default=True)
