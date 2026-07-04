"""routes/pages.py — page routes for the unified dashboard shell.

Every page here renders a child template of _base.html (the shared
sidebar/header layout). Pages that already had routes elsewhere keep
them: /watchlist and /profile live in routes/predictions.py and
/leaderboard in routes/predictions.py.
"""

from datetime import datetime

from flask import render_template
from flask_login import login_required, current_user


def register_page_routes(app):

    # _base.html greets the user and shows today's date on every page.
    @app.context_processor
    def _inject_now():
        return {"now": datetime.now()}

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/trading")
    @login_required
    def trading_page():
        return render_template("trading.html")

    @app.route("/predictions")
    @login_required
    def predictions_page():
        return render_template("predictions.html")

    @app.route("/competitions")
    @login_required
    def competitions_page():
        return render_template("competitions.html")

    @app.route("/achievements")
    @login_required
    def achievements_page():
        from gamification import ACHIEVEMENTS
        from models import UserAchievement
        rows = UserAchievement.query.filter_by(user_id=current_user.id).all()
        return render_template(
            "achievements.html",
            achievements=list(ACHIEVEMENTS.values()),
            unlocked_ids={r.achievement_id for r in rows},
            earned_dates={r.achievement_id: r.earned_at for r in rows},
        )

    @app.route("/settings")
    @login_required
    def settings_page():
        return render_template("settings.html")
