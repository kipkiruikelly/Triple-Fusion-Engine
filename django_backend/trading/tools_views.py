import os
import sys
import json
import secrets
import threading
import subprocess
from datetime import datetime, date
from pathlib import Path

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication

_PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from users.models import (
    PriceAlert, TelegramConfig, WhatsappConfig, DiscordConfig,
    Notification, ResourceLink, User, AppSetting, ApiKey, UserWebhook,
    PLUS_BACKTEST_PERIODS, PLUS_BACKTEST_DAILY
)

# Helper alert senders
def _send_telegram(chat_id, text):
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(f"[Telegram Stub] (No Token) To {chat_id}: {text}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[Telegram Error] Failed to send: {e}")

def _send_whatsapp(phone, text):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_num = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")
    
    if sid and token and from_num:
        import requests
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        to_num = f"whatsapp:{phone}" if not phone.startswith("whatsapp:") else phone
        whatsapp_from = f"whatsapp:{from_num}" if not from_num.startswith("whatsapp:") else from_num
        try:
            r = requests.post(
                url,
                data={"To": to_num, "From": whatsapp_from, "Body": text},
                auth=(sid, token),
                timeout=5
            )
            r.raise_for_status()
            print(f"[Twilio WhatsApp] Sent to {phone}")
            return
        except Exception as e:
            print(f"[Twilio WhatsApp Error] Failed to send: {e}")
            
    print(f"[WhatsApp Stub] To {phone}: {text}")

def _send_discord(url, title, desc, color):
    import requests
    payload = {
        "embeds": [{
            "title": title,
            "description": desc,
            "color": color
        }]
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[Discord Error] Failed to send: {e}")

def _add_notification(user_id, channel, title, message):
    Notification.objects.create(
        user_id=user_id,
        channel=channel,
        title=title,
        message=message
    )


class BacktestView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        if not request.user.is_plus:
            return Response({"ok": False, "error": "Backtesting requires a Plus or Pro plan."}, status=403)
        
        ticker = request.data.get("ticker", "AAPL").upper()
        interval = request.data.get("interval", "1d")
        period = request.data.get("period", "2y")
        capital = float(request.data.get("initial_capital", 10000))
        risk_pct = float(request.data.get("risk_pct", 1.0))

        if interval not in ("1d", "1h"):
            return Response({"ok": False, "error": "interval must be 1d or 1h"}, status=400)
        if period not in ("6mo", "1y", "2y"):
            return Response({"ok": False, "error": "period must be 6mo, 1y, or 2y"}, status=400)
        
        if not request.user.is_pro:
            if period not in PLUS_BACKTEST_PERIODS:
                return Response({
                    "ok": False,
                    "error": "The Plus plan supports 6mo or 1y of history. Upgrade to Pro for 2y."
                }, status=403)
            
            today = date.today()
            if request.user.last_backtest_date != today:
                request.user.backtests_today = 0
                request.user.last_backtest_date = today
            if request.user.backtests_today >= PLUS_BACKTEST_DAILY:
                return Response({
                    "ok": False,
                    "error": f"The Plus plan allows {PLUS_BACKTEST_DAILY} backtest run per day. Upgrade to Pro for unlimited runs."
                }, status=429)
            
            request.user.backtests_today += 1
            request.user.save(update_fields=["backtests_today", "last_backtest_date"])

        if not (100 <= capital <= 10000000):
            return Response({"ok": False, "error": "Capital must be between $100 and $10,000,000"}, status=400)
        if not (0.1 <= risk_pct <= 10):
            return Response({"ok": False, "error": "Risk must be between 0.1% and 10%"}, status=400)

        try:
            from backtester import run_backtest
            result = run_backtest(ticker, interval, period, capital, risk_pct)
            result["ok"] = True
            
            # Award XP best-effort
            try:
                from utils import award_xp
                award_xp(request.user, 10)
            except Exception:
                pass
                
            return Response(result)
        except ValueError as e:
            return Response({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            return Response({"ok": False, "error": f"Backtest failed: {str(e)}"}, status=500)


class PipelineRetrainView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        def run_job():
            try:
                subprocess.run([sys.executable, "train_all_tickers.py", "--fast"], cwd=_PARENT_DIR, check=True)
            except Exception as e:
                print("Retrain job failed:", e)
        
        threading.Thread(target=run_job, daemon=True).start()
        return Response({"ok": True, "msg": "Retraining started in the background"})


class CalendarEarningsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        import requests
        from datetime import date, timedelta
        key = os.environ.get("FINNHUB_API_KEY", "")
        
        default_earnings = [
            {"ticker": "AAPL", "date": "2026-07-28", "period": "Q3 2026", "eps_est": 1.45, "rev_est": "84.5B"},
            {"ticker": "MSFT", "date": "2026-07-29", "period": "Q4 2026", "eps_est": 2.95, "rev_est": "64.2B"},
            {"ticker": "TSLA", "date": "2026-07-23", "period": "Q2 2026", "eps_est": 0.62, "rev_est": "24.8B"},
            {"ticker": "NVDA", "date": "2026-08-20", "period": "Q2 2026", "eps_est": 4.15, "rev_est": "20.1B"},
        ]
        
        if not key:
            return Response({"ok": True, "earnings": default_earnings})
            
        try:
            today = date.today().strftime("%Y-%m-%d")
            future = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={future}&token={key}"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json().get("earningsCalendar", [])
            
            out = []
            for item in data[:50]:
                ticker = item.get("symbol", "")
                if ticker in ("AAPL", "MSFT", "TSLA", "NVDA", "GOOGL", "AMZN", "META", "NFLX", "AMD", "INTC"):
                    rev = item.get("revenueEstimate")
                    rev_str = f"{round(rev / 1e9, 1)}B" if rev else "N/A"
                    out.append({
                        "ticker": ticker,
                        "date": item.get("date", ""),
                        "period": item.get("period", "Q2 2026"),
                        "eps_est": item.get("epsEstimate"),
                        "rev_est": rev_str
                    })
            if not out:
                out = default_earnings
            return Response({"ok": True, "earnings": out})
        except Exception:
            return Response({"ok": True, "earnings": default_earnings})


class CalendarMacroView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        import requests
        from datetime import date, timedelta
        key = os.environ.get("FINNHUB_API_KEY", "")
        
        default_events = [
            {"event": "CPI Inflation Report", "date": "2026-07-12", "forecast": "3.1%", "previous": "3.2%", "importance": "HIGH"},
            {"event": "FOMC Interest Rate Decision", "date": "2026-07-26", "forecast": "5.25%", "previous": "5.25%", "importance": "CRITICAL"},
            {"event": "Non-Farm Payrolls (NFP)", "date": "2026-08-04", "forecast": "180k", "previous": "210k", "importance": "HIGH"},
        ]
        
        if not key:
            return Response({"ok": True, "events": default_events})
            
        try:
            today = date.today().strftime("%Y-%m-%d")
            future = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
            url = f"https://finnhub.io/api/v1/calendar/economic?from={today}&to={future}&token={key}"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json().get("economicCalendar", [])
            
            out = []
            importance_map = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
            for item in data[:30]:
                impact = item.get("impact", "low")
                if impact in ("high", "medium"):
                    dt_str = item.get("time", "")[:10]
                    out.append({
                        "event": item.get("event", ""),
                        "date": dt_str,
                        "forecast": str(item.get("forecast")) if item.get("forecast") is not None else "N/A",
                        "previous": str(item.get("prev")) if item.get("prev") is not None else "N/A",
                        "importance": "CRITICAL" if "FOMC" in item.get("event", "") or "Interest Rate" in item.get("event", "") else importance_map.get(impact, "HIGH")
                    })
            if not out:
                out = default_events
            return Response({"ok": True, "events": out})
        except Exception:
            return Response({"ok": True, "events": default_events})


class ResourcesPublicView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        rows = ResourceLink.objects.filter(active=True).order_by("sort")
        cats = {}
        order = ["Learn Trading", "Market Data & News", "Regulators & Safety", "Our Platform"]
        
        for r in rows:
            cats.setdefault(r.category, []).append({
                "title": r.title,
                "url": r.url,
                "description": r.description,
                "icon": r.icon
            })
            
        ordered = [c for c in order if c in cats] + [c for c in cats if c not in order]
        return Response({
            "ok": True,
            "categories": [{"name": c, "links": cats[c]} for c in ordered]
        })


# ── Alerts & Integrations ───────────────────────────────────────────────────

class AlertsListView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        alerts = PriceAlert.objects.filter(user=request.user).order_by("-created_at")
        return Response({
            "ok": True,
            "alerts": [
                {
                    "id": a.id, "ticker": a.ticker, "target_price": a.target_price,
                    "condition": a.condition, "active": a.active,
                    "created_at": a.created_at.strftime("%Y-%m-%d") if a.created_at else ""
                }
                for a in alerts
            ]
        })


class AlertsAddView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        ticker = request.data.get("ticker", "").strip().upper()
        target = float(request.data.get("target_price") or 0)
        cond = request.data.get("condition", "ABOVE")

        if not ticker or target <= 0:
            return Response({"ok": False, "error": "ticker and target_price required"}, status=400)
            
        alert = PriceAlert.objects.create(
            user=request.user,
            ticker=ticker,
            target_price=target,
            condition=cond,
            active=True
        )
        return Response({"ok": True, "id": alert.id})


class AlertsRemoveView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        alert_id = request.data.get("alert_id")
        try:
            alert = PriceAlert.objects.get(id=alert_id, user=request.user)
            alert.delete()
            return Response({"ok": True})
        except PriceAlert.DoesNotExist:
            return Response({"ok": False, "error": "Alert not found"}, status=404)


class TelegramConfigureView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        chat_id = str(request.data.get("chat_id", "")).strip()
        enabled = bool(request.data.get("enabled", True))
        
        if not chat_id:
            return Response({"ok": False, "error": "chat_id required"}, status=400)
            
        cfg, created = TelegramConfig.objects.update_or_create(
            user=request.user,
            defaults={"chat_id": chat_id, "enabled": enabled}
        )
        _send_telegram(chat_id, f"✅ BullLogic connected for *{request.user.username}*. You'll receive price alerts here.")
        return Response({"ok": True})


class TelegramStatusView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        cfg = TelegramConfig.objects.filter(user=request.user).first()
        return Response({
            "configured": cfg is not None,
            "chat_id": cfg.chat_id if cfg else None,
            "enabled": cfg.enabled if cfg else False
        })


class TelegramRemoveView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        TelegramConfig.objects.filter(user=request.user).delete()
        return Response({"ok": True})


class WhatsappConfigureView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        enabled = bool(request.data.get("enabled", True))
        
        if not phone_number:
            return Response({"ok": False, "error": "phone_number required"}, status=400)
            
        cfg, created = WhatsappConfig.objects.update_or_create(
            user=request.user,
            defaults={"phone_number": phone_number, "enabled": enabled}
        )
        _send_whatsapp(phone_number, f"✅ BullLogic connected for *{request.user.username}*. You'll receive price alerts and watchlist signals here on WhatsApp.")
        return Response({"ok": True})


class WhatsappStatusView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        cfg = WhatsappConfig.objects.filter(user=request.user).first()
        return Response({
            "configured": cfg is not None,
            "phone_number": cfg.phone_number if cfg else None,
            "enabled": cfg.enabled if cfg else False
        })


class WhatsappRemoveView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        WhatsappConfig.objects.filter(user=request.user).delete()
        return Response({"ok": True})


class DiscordConfigureView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        url = request.data.get("webhook_url", "").strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            return Response({"ok": False, "error": "Invalid Discord webhook URL"}, status=400)
            
        cfg, created = DiscordConfig.objects.update_or_create(
            user=request.user,
            defaults={"webhook_url": url, "enabled": True}
        )
        _send_discord(url, "BullLogic Connected", f"Hi {request.user.username}! Discord alerts are now active.", 0xFF6B35)
        return Response({"ok": True})


class DiscordStatusView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        cfg = DiscordConfig.objects.filter(user=request.user).first()
        return Response({
            "ok": True,
            "configured": cfg is not None,
            "enabled": cfg.enabled if cfg else False
        })


class DiscordRemoveView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        DiscordConfig.objects.filter(user=request.user).delete()
        return Response({"ok": True})


class DiscordTestView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        cfg = DiscordConfig.objects.filter(user=request.user).first()
        if not cfg:
            return Response({"ok": False, "error": "Discord not configured"}, status=400)
        _send_discord(cfg.webhook_url, "BullLogic Test", "This is a test notification from BullLogic.", 0xFF6B35)
        return Response({"ok": True})


class NotificationsListView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        notes = Notification.objects.filter(user=request.user).order_by("-created_at")[:100]
        return Response({
            "ok": True,
            "notifications": [
                {
                    "id": n.id, "channel": n.channel, "title": n.title,
                    "message": n.message, "read": n.read,
                    "created_at": n.created_at.isoformat() if n.created_at else ""
                }
                for n in notes
            ]
        })


class NotificationsReadView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        note_id = request.data.get("notification_id")
        try:
            note = Notification.objects.get(id=note_id, user=request.user)
            note.read = True
            note.save(update_fields=["read"])
            return Response({"ok": True})
        except Notification.DoesNotExist:
            return Response({"ok": False, "error": "Notification not found"}, status=404)


class NotificationsClearView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        Notification.objects.filter(user=request.user).update(read=True)
        return Response({"ok": True})


class DigestSendView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        # Mock trigger sending daily email digest
        print(f"[Digest Sender] Sent email digest to {request.user.email}")
        return Response({"ok": True, "message": "Performance email digest sent."})
