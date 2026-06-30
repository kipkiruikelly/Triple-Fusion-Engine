"""routes/admin.py — admin login and dashboard."""

import os
import secrets
from datetime import date

from flask import render_template, request, jsonify, redirect, url_for, make_response
from flask_login import current_user

from extensions import db
from models import User, PredictionHistory, PriceAlert, PortfolioPosition, ApiKey

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "bulllogic-admin-2025")


def _admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("admin_token") or request.args.get("admin_token", "")
        if not token or not secrets.compare_digest(token, ADMIN_PASSWORD):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def register_admin_routes(app):

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        error = None
        if request.method == "POST":
            pw = request.form.get("password", "")
            if secrets.compare_digest(pw, ADMIN_PASSWORD):
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
        top_tickers  = (db.session.query(
            PredictionHistory.ticker,
            db.func.count(PredictionHistory.id).label("cnt")
        ).group_by(PredictionHistory.ticker)
         .order_by(db.func.count(PredictionHistory.id).desc())
         .limit(10).all())
        recent_users = User.query.order_by(User.id.desc()).limit(10).all()
        return render_template("admin.html", stats=stats,
                               top_tickers=top_tickers, recent_users=recent_users)
