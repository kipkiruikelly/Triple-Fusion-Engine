"""routes/notifications.py — alerts, Telegram, Discord, in-app notifications, digest."""

import os
import threading
from datetime import datetime

from flask import render_template, request, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import PriceAlert, TelegramConfig, DiscordConfig, Notification
from utils import _add_notification, _send_telegram, _send_discord, _log_activity


def register_notification_routes(app):

    # ── Price alerts ───────────────────────────────────────────────────────────

    @app.route("/alerts")
    @login_required
    def alerts_page():
        user_alerts = PriceAlert.query.filter_by(user_id=current_user.id)\
                                      .order_by(PriceAlert.created_at.desc()).all()
        return render_template("alerts.html", alerts=user_alerts)

    @app.route("/api/alerts", methods=["GET"])
    @login_required
    def api_alerts_list():
        rows = PriceAlert.query.filter_by(user_id=current_user.id)\
                               .order_by(PriceAlert.created_at.desc()).all()
        return jsonify([{
            "id": a.id, "ticker": a.ticker, "price": a.price,
            "direction": a.direction, "note": a.note or "",
            "triggered": a.triggered,
            "created_at":   a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
            "triggered_at": a.triggered_at.strftime("%Y-%m-%d %H:%M") if a.triggered_at else None,
        } for a in rows])

    @app.route("/api/alerts/add", methods=["POST"])
    @login_required
    def api_alerts_add():
        data      = request.get_json() or {}
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

    # ── Telegram ───────────────────────────────────────────────────────────────

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
        _send_telegram(chat_id,
                       f"✅ BullLogic connected for *{current_user.username}*. "
                       "You'll receive price alerts here.")
        return jsonify({"ok": True})

    @app.route("/api/telegram/status")
    @login_required
    def telegram_status():
        cfg = TelegramConfig.query.filter_by(user_id=current_user.id).first()
        return jsonify({"configured": bool(cfg),
                        "chat_id": cfg.chat_id if cfg else None,
                        "enabled": cfg.enabled if cfg else False})

    @app.route("/api/telegram/remove", methods=["POST"])
    @login_required
    def telegram_remove():
        TelegramConfig.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        return jsonify({"ok": True})

    # ── Discord ────────────────────────────────────────────────────────────────

    @app.route("/api/discord/configure", methods=["POST"])
    @login_required
    def api_discord_configure():
        url = (request.get_json() or {}).get("webhook_url", "").strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            return jsonify({"ok": False, "error": "Invalid Discord webhook URL"}), 400
        cfg = DiscordConfig.query.filter_by(user_id=current_user.id).first()
        if cfg:
            cfg.webhook_url = url
            cfg.enabled     = True
        else:
            cfg = DiscordConfig(user_id=current_user.id, webhook_url=url)
            db.session.add(cfg)
        db.session.commit()
        _send_discord(url, "BullLogic Connected",
                      f"Hi {current_user.username}! Discord alerts are now active.", 0xFF6B35)
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
        _send_discord(cfg.webhook_url, "BullLogic Test",
                      "This is a test notification from BullLogic.", 0xFF6B35)
        return jsonify({"ok": True})

    # ── In-app notifications ───────────────────────────────────────────────────

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

    # ── Daily email digest ─────────────────────────────────────────────────────

    @app.route("/api/digest/send", methods=["POST"])
    @login_required
    def api_digest_send():
        from utils import SCREENER_TICKERS
        from predictor import ml_signal
        user = current_user
        try:
            signals = []
            for t in SCREENER_TICKERS[:6]:
                try:
                    sig = ml_signal(t, "1d")
                    signals.append(
                        f"  {t}: {sig.get('action','?')} (conf {sig.get('confidence',0):.0%})"
                    )
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
            from extensions import mail
            if mail and app.config.get("MAIL_USERNAME") and user.email:
                from flask_mail import Message as MailMessage
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
