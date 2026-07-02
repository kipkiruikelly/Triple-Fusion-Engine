"""extensions.py, shared Flask extension instances (no project imports)."""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

try:
    from flask_mail import Mail
    mail = Mail()
    _MAIL_AVAILABLE = True
except ImportError:
    mail = None
    _MAIL_AVAILABLE = False

db           = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'
