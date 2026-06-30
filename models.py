"""models.py — all SQLAlchemy ORM models."""

from datetime import date, datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

FREE_DAILY_LIMIT = 5


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
    pro_expires_at          = db.Column(db.Date, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
