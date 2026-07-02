"""emails.py, transactional email for BullLogic.

Branded HTML templates with plain-text fallbacks, sent through Flask-Mail.
Works with Gmail SMTP (app password) or a transactional provider such as
Brevo; both are plain SMTP and configured entirely from the environment:
MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD,
MAIL_DEFAULT_SENDER.

send_email() is fire-and-forget in a daemon thread so request handlers
never block on SMTP.
"""

import logging
import threading

log = logging.getLogger(__name__)

_BRAND = "#FF6B35"
_BG = "#0F1217"
_CARD = "#1A1F2E"
_TEXT = "#E2E8F0"
_MUTED = "#7A8499"


def _shell(title, body_html):
    """Shared branded wrapper for every email."""
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:{_BG};font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:28px 0">
<tr><td align="center">
<table role="presentation" width="520" cellpadding="0" cellspacing="0"
       style="background:{_CARD};border-radius:12px;padding:32px;max-width:92%">
  <tr><td style="font-size:22px;font-weight:bold;color:#ffffff;padding-bottom:4px">
    Bull<span style="color:{_BRAND}">Logic</span></td></tr>
  <tr><td style="font-size:17px;font-weight:bold;color:{_TEXT};padding:16px 0 8px">{title}</td></tr>
  <tr><td style="font-size:14px;line-height:1.7;color:{_TEXT}">{body_html}</td></tr>
  <tr><td style="font-size:11px;color:{_MUTED};padding-top:26px;border-top:1px solid #2A3150">
    You received this email because of activity on your BullLogic account.
    BullLogic predictions are informational only and are not financial advice.
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _button(url, label):
    return (f'<div style="padding:18px 0"><a href="{url}" '
            f'style="background:{_BRAND};color:#ffffff;text-decoration:none;'
            f'padding:12px 26px;border-radius:8px;font-weight:bold;'
            f'display:inline-block">{label}</a></div>'
            f'<div style="font-size:12px;color:{_MUTED}">If the button does not work, '
            f'copy this link into your browser:<br>{url}</div>')


def send_email(app, subject, recipient, html, text):
    """Queue an email on a background thread. Returns False when mail is
    not configured so callers can react (e.g. show the link on screen)."""
    from extensions import mail
    if not mail or not app.config.get("MAIL_USERNAME"):
        log.warning("mail not configured, dropping email %r to %s", subject, recipient)
        return False

    def _send():
        try:
            from flask_mail import Message
            with app.app_context():
                mail.send(Message(subject=subject, recipients=[recipient],
                                  body=text, html=html))
        except Exception:
            log.exception("email send failed: %r to %s", subject, recipient)

    threading.Thread(target=_send, daemon=True).start()
    return True


def send_verification(app, user, verify_url):
    html = _shell("Confirm your email address",
                  f"Hi {user.username},<br><br>"
                  "Welcome to BullLogic. Confirm your email address to unlock "
                  "predictions and payments. This link is valid for 24 hours."
                  + _button(verify_url, "Verify my email"))
    text = (f"Hi {user.username},\n\nWelcome to BullLogic. Open the link below "
            f"to verify your email address (valid 24 hours):\n\n{verify_url}\n\n"
            "BullLogic. Not financial advice.")
    return send_email(app, "Verify your BullLogic email", user.email, html, text)


def send_password_reset(app, user, reset_url):
    html = _shell("Reset your password",
                  f"Hi {user.username},<br><br>"
                  "We received a request to reset your BullLogic password. "
                  "The link below is valid for 1 hour and can be used once. "
                  "If you did not ask for this, you can safely ignore this email."
                  + _button(reset_url, "Choose a new password"))
    text = (f"Hi {user.username},\n\nOpen the link below to reset your BullLogic "
            f"password (valid 1 hour, single use):\n\n{reset_url}\n\n"
            "If you did not request this, ignore this email.")
    return send_email(app, "Reset your BullLogic password", user.email, html, text)


def send_receipt(app, user, payment):
    amount = f"{payment.currency or 'KES'} {payment.amount or 0:,.0f}"
    plan = "1 year" if (payment.days or 30) >= 365 else f"{payment.days or 30} days"
    rows = "".join(
        f'<tr><td style="color:{_MUTED};padding:4px 0">{k}</td>'
        f'<td style="text-align:right;color:{_TEXT}">{v}</td></tr>'
        for k, v in [
            ("Amount", amount),
            ("Plan", f"BullLogic Pro, {plan}"),
            ("Method", (payment.provider or "").upper()),
            ("Receipt", payment.receipt or payment.reference or "n/a"),
            ("Date", payment.completed_at.strftime("%d %b %Y %H:%M UTC")
                     if payment.completed_at else ""),
        ])
    html = _shell("Payment received, karibu Pro!",
                  f"Hi {user.username},<br><br>"
                  "Your payment was confirmed and your Pro access is active."
                  f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                  f'style="margin:16px 0;font-size:13px">{rows}</table>'
                  "Keep this email as your receipt. Questions? Reply to this "
                  "email or see the FAQ on the site.")
    text = (f"Hi {user.username},\n\nPayment confirmed. {amount} for BullLogic Pro "
            f"({plan}).\nReceipt: {payment.receipt or payment.reference}\n\n"
            "Keep this email as your receipt.")
    return send_email(app, f"BullLogic receipt: {amount}", user.email, html, text)
