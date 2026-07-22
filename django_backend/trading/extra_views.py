"""trading/extra_views.py — All missing API endpoints for the dashboard.

Covers:
  - /api/notifications, /api/notifications/read, /api/notifications/clear
  - /api/manual-paper/account, /api/manual-paper/order, /api/manual-paper/cancel
  - /api/watchlist/add, /api/watchlist/remove
  - /api/screener
  - /api/journal
  - /api/forgot-password, /api/reset-password, /api/verify-email
  - /api/content/<page_id>
"""

import random
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # Bypass CSRF checks for APIs

import sys
from pathlib import Path
_PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import mt5_trading as _mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    _mt5 = None

from users.models import (
    Notification, TradeJournal, WatchlistItem, PaperTrade, TickerConfig
)


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _auth():
    return {
        'permission_classes': [IsAuthenticated],
        'authentication_classes': [SessionAuthentication],
    }


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        notifs = Notification.objects.filter(user=request.user).order_by('-created_at')[:30]
        data = []
        for n in notifs:
            data.append({
                'id': n.id,
                'type': n.type,
                'title': n.title,
                'body': n.body,
                'read': n.read,
                'link': n.link,
                'created_at': n.created_at.strftime('%b %d, %H:%M') if n.created_at else '',
            })
        unread = sum(1 for n in data if not n['read'])
        return Response({'ok': True, 'notifications': data, 'unread': unread})


class NotificationsReadView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        notif_id = request.data.get('id')
        if notif_id:
            Notification.objects.filter(user=request.user, id=notif_id).update(read=True)
        else:
            Notification.objects.filter(user=request.user).update(read=True)
        return Response({'ok': True})


class NotificationsClearView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        Notification.objects.filter(user=request.user).update(read=True)
        return Response({'ok': True})


# ── Manual Paper Trading ──────────────────────────────────────────────────────

class ManualPaperAccountView(APIView):
    """GET /api/manual-paper/account — paper trading account summary."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        open_trades = PaperTrade.objects.filter(
            user=request.user, status='open'
        ).order_by('-created_at')

        positions = []
        total_pnl = 0.0
        for t in open_trades:
            import market_data
            try:
                quote = market_data.get_quote(t.ticker)
                current_price = float(quote.get('price')) if (quote and quote.get('price')) else t.entry_price
            except Exception:
                current_price = t.entry_price
            
            if t.side == 'LONG':
                pnl = (current_price - t.entry_price) * t.qty
            else:
                pnl = (t.entry_price - current_price) * t.qty
            total_pnl += pnl
            positions.append({
                'id': t.id,
                'ticker': t.ticker,
                'side': t.side,
                'qty': t.qty,
                'entry_price': t.entry_price,
                'current_price': current_price,
                'pnl': round(pnl, 2),
                'status': t.status,
                'opened_at': t.entry_time.isoformat() if t.entry_time else '',
            })

        closed = PaperTrade.objects.filter(user=request.user, status='closed')
        realized_pnl = sum(t.pnl for t in closed if t.pnl is not None)
        balance = 10000.0 + realized_pnl  # starting balance $10k

        return Response({
            'ok': True,
            'account': {
                'balance': round(balance, 2),
                'equity': round(balance + total_pnl, 2),
                'unrealized_pnl': round(total_pnl, 2),
                'realized_pnl': round(realized_pnl, 2),
                'open_positions': len(positions),
            },
            'positions': positions,
        })


class ManualPaperOrderView(APIView):
    """POST /api/manual-paper/order — place a paper or live trade depending on user state."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        ticker = (request.data.get('ticker') or '').upper().strip()
        side   = (request.data.get('side') or 'LONG').upper()
        if side in ('BUY', 'LONG'):
            side = 'LONG'
        elif side in ('SELL', 'SHORT'):
            side = 'SHORT'

        qty    = float(request.data.get('qty') or request.data.get('quantity') or 1)
        order_type = (request.data.get('order_type') or 'market').upper()
        target_price = request.data.get('target_price') or request.data.get('price')
        if target_price is not None:
            target_price = float(target_price)

        if not ticker:
            return Response({'ok': False, 'error': 'ticker is required.'}, status=400)
        
        # Check user status
        if not request.user.paper_trading_opted_in:
            # LIVE TRADING (Requires Pro plan + connected MT5)
            if not request.user.is_pro:
                return Response({'ok': False, 'error': 'Live trading requires a Pro plan.'}, status=403)
            if not MT5_AVAILABLE or not _mt5 or not hasattr(_mt5, 'trader'):
                return Response({'ok': False, 'error': 'MT5 execution engine not available.'}, status=503)
            
            if not _mt5.trader.connected:
                _mt5.trader._auto_connect_live()
            if not _mt5.trader.connected:
                return Response({'ok': False, 'error': 'Not connected to MT5. Please check MT5 settings in admin panel.'}, status=400)
            
            try:
                risk_pct = float(request.data.get('risk_pct') or 1.0)
                atr = float(request.data.get('atr') or 0.1)
                
                result = _mt5.trader.place_order(
                    ticker, 
                    'BUY' if side == 'LONG' else 'SELL', 
                    risk_pct, 
                    atr, 
                    order_type_str=order_type, 
                    target_price=target_price
                )
                if result.get('ok'):
                    _mt5.trader.refresh_account()
                return Response(result)
            except Exception as exc:
                return Response({'ok': False, 'error': str(exc)}, status=400)
        else:
            # PAPER TRADING
            # Get real-time price using market_data to make the paper trade realistic
            import sys
            from pathlib import Path
            _PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
            if _PARENT_DIR not in sys.path:
                sys.path.insert(0, _PARENT_DIR)
            import market_data
            
            try:
                quote = market_data.get_quote(ticker)
                price = float(quote.get('price')) if quote and quote.get('price') else 100.0
            except Exception:
                price = 100.0
                
            # If limit/stop price is specified, use it for execution
            exec_price = target_price if (target_price and order_type != 'MARKET') else price

            trade = PaperTrade.objects.create(
                user=request.user,
                strategy='manual',
                ticker=ticker,
                asset_class='equity' if not any(c in ticker for c in ['-', '=X', '^']) else 'crypto' if '-' in ticker else 'forex',
                side=side,
                qty=qty,
                entry_time=datetime.utcnow(),
                entry_price=exec_price,
                entry_mkt=price,
                stop_price=exec_price * 0.95,
                target_price=exec_price * 1.10,
                max_hold_hours=72,
                status='open',
            )
            return Response({
                'ok': True,
                'trade': {
                    'id': trade.id,
                    'ticker': trade.ticker,
                    'side': trade.side,
                    'qty': trade.qty,
                    'entry_price': trade.entry_price,
                    'status': trade.status,
                }
            }, status=201)


class ManualPaperCancelView(APIView):
    """POST /api/manual-paper/cancel — close/cancel a paper or live trade."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        order_id = request.data.get('order_id')
        ticker = (request.data.get('ticker') or '').upper().strip()
        
        # Check user status
        if not request.user.paper_trading_opted_in:
            # LIVE CLOSE
            if not request.user.is_pro:
                return Response({'ok': False, 'error': 'MT5 connection requires a Pro plan.'}, status=403)
            if not MT5_AVAILABLE or not _mt5 or not hasattr(_mt5, 'trader'):
                return Response({'ok': False, 'error': 'MT5 module not available.'}, status=503)
            
            try:
                n = _mt5.trader.close_all(ticker)
                _mt5.trader.refresh_account()
                return Response({'ok': True, 'closed': n})
            except Exception as exc:
                return Response({'ok': False, 'error': str(exc)}, status=400)
        else:
            # PAPER CLOSE
            if not order_id:
                return Response({'ok': False, 'error': 'order_id is required.'}, status=400)
            try:
                trade = PaperTrade.objects.get(id=order_id, user=request.user, status='open')
            except PaperTrade.DoesNotExist:
                return Response({'ok': False, 'error': 'Order not found or already closed.'}, status=404)

            # Get current exit price
            import sys
            from pathlib import Path
            _PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
            if _PARENT_DIR not in sys.path:
                sys.path.insert(0, _PARENT_DIR)
            import market_data
            
            try:
                quote = market_data.get_quote(trade.ticker)
                exit_price = float(quote.get('price')) if quote and quote.get('price') else trade.entry_price
            except Exception:
                exit_price = trade.entry_price

            pnl = (exit_price - trade.entry_price) * trade.qty
            if trade.side == 'SHORT':
                pnl = -pnl

            trade.status = 'closed'
            trade.exit_time = datetime.utcnow()
            trade.exit_price = round(exit_price, 4)
            trade.pnl = round(pnl, 2)
            trade.exit_reason = 'manual'
            trade.save(update_fields=['status', 'exit_time', 'exit_price', 'pnl', 'exit_reason'])

            return Response({
                'ok': True,
                'pnl': trade.pnl,
                'exit_price': trade.exit_price
            })


# ── Watchlist add/remove ──────────────────────────────────────────────────────

class WatchlistAddView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        ticker = (request.data.get('ticker') or '').upper().strip()
        if not ticker:
            return Response({'ok': False, 'error': 'ticker is required.'}, status=400)
        item, created = WatchlistItem.objects.get_or_create(user=request.user, ticker=ticker)
        return Response({'ok': True, 'created': created, 'ticker': ticker})


class WatchlistRemoveView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        ticker = (request.data.get('ticker') or '').upper().strip()
        deleted, _ = WatchlistItem.objects.filter(user=request.user, ticker=ticker).delete()
        return Response({'ok': True, 'deleted': deleted > 0})


# ── Screener ──────────────────────────────────────────────────────────────────

import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from utils import SCREENER_TICKERS
from predictor import ml_signal


class ScreenerView(APIView):
    """GET /api/screener — return a list of real ML-derived stock screener results."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        interval = request.query_params.get("interval", "1d")
        if interval not in ("1d", "1h"):
            interval = "1d"
            
        tickers = request.query_params.getlist("tickers") or SCREENER_TICKERS

        def _scan(ticker):
            try:
                sig = ml_signal(ticker, interval)
                return {
                    "ticker":     ticker,
                    "action":     sig.get("action", "HOLD"),
                    "price":      sig.get("current_price", 0),
                    "ai_score":   sig.get("ai_score", 5),
                    "alpha_signals": sig.get("alpha_signals", []),
                    "lr_pred":    sig.get("lr_pred", 0),
                    "confidence": sig.get("confidence", 0),
                    "rsi":        sig.get("rsi", 50),
                    "macd_hist":  sig.get("macd_hist", 0),
                    "atr":        sig.get("atr", 0),
                }
            except Exception:
                return {
                    "ticker": ticker, "action": "HOLD", "price": 0, "ai_score": 5, "alpha_signals": [],
                    "lr_pred": 0, "confidence": 0, "rsi": 50, "macd_hist": 0, "atr": 0
                }

        with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as ex:
            rows = list(ex.map(_scan, tickers))
            
        rows.sort(key=lambda x: x["confidence"], reverse=True)
        return Response({"ok": True, "interval": interval, "rows": rows})


# ── Trade Journal ─────────────────────────────────────────────────────────────

class JournalView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        entries = TradeJournal.objects.filter(user=request.user).order_by('-created_at')[:50]
        data = [{
            'id': e.id,
            'ticker': e.ticker,
            'title': e.title,
            'body': e.body,
            'mood': e.mood,
            'tags': e.tags,
            'trade_type': e.trade_type,
            'created_at': e.created_at.isoformat() if e.created_at else '',
        } for e in entries]
        return Response({'ok': True, 'entries': data})

    def post(self, request):
        entry = TradeJournal.objects.create(
            user=request.user,
            ticker=(request.data.get('ticker') or '').upper() or None,
            title=request.data.get('title', 'Journal Entry'),
            body=request.data.get('body', ''),
            mood=request.data.get('mood'),
            tags=request.data.get('tags'),
            trade_type=request.data.get('trade_type'),
        )
        return Response({'ok': True, 'id': entry.id}, status=201)

    def delete(self, request):
        entry_id = request.data.get('id')
        if not entry_id:
            return Response({'ok': False, 'error': 'id is required'}, status=400)
        try:
            entry = TradeJournal.objects.get(id=entry_id, user=request.user)
            entry.delete()
            return Response({'ok': True})
        except TradeJournal.DoesNotExist:
            return Response({'ok': False, 'error': 'Entry not found'}, status=404)


# ── Static Content pages ──────────────────────────────────────────────────────

class ContentView(APIView):
    """GET /api/content/<page_id> — serve static page content."""
    permission_classes = [AllowAny]
    authentication_classes = []

    CONTENT = {
        'privacy': {
            'title': 'Privacy Policy',
            'content': (
                "Last updated: July 2026\n\n"
                "BullLogic ('we', 'us', or 'our') respects your privacy. This Privacy Policy explains how we collect, use, "
                "and protect your information when you use our platform.\n\n"
                "INFORMATION WE COLLECT\n"
                "We collect information you provide when registering, including your name, email address, and trading preferences. "
                "We also collect usage data, prediction history, and session activity to improve our service.\n\n"
                "HOW WE USE YOUR INFORMATION\n"
                "We use your data to deliver predictions, personalize your experience, send alerts you have opted into, "
                "and improve our machine learning models.\n\n"
                "DATA SECURITY\n"
                "We use industry-standard encryption and session authentication to protect your data. "
                "Passwords are hashed with PBKDF2-SHA256. We do not sell your data to third parties.\n\n"
                "CONTACT\n"
                "For privacy inquiries, contact: privacy@bulllogic.ai"
            ),
        },
        'terms': {
            'title': 'Terms of Service',
            'content': (
                "Last updated: July 2026\n\n"
                "By using BullLogic you agree to these Terms of Service.\n\n"
                "1. USE OF SERVICE\n"
                "BullLogic provides AI-powered market predictions for informational purposes only. "
                "Nothing on this platform constitutes financial advice.\n\n"
                "2. NO FINANCIAL ADVICE\n"
                "All predictions, signals, and analytics are generated by machine learning models and are NOT "
                "guaranteed to be accurate. Past performance does not indicate future results.\n\n"
                "3. ACCOUNTS\n"
                "You are responsible for maintaining the security of your account. "
                "You must be 18 years or older to use this service.\n\n"
                "4. PROHIBITED USES\n"
                "You may not use BullLogic to manipulate markets, distribute predictions commercially without authorization, "
                "or reverse-engineer our proprietary models.\n\n"
                "5. LIMITATION OF LIABILITY\n"
                "BullLogic is not liable for any financial losses resulting from use of this platform."
            ),
        },
        'disclosures': {
            'title': 'Risk Disclosures',
            'content': (
                "IMPORTANT RISK DISCLOSURE\n\n"
                "Trading financial instruments involves substantial risk of loss and is not suitable for all investors.\n\n"
                "AI PREDICTION LIMITATIONS\n"
                "Our machine learning models are trained on historical data. Markets are inherently unpredictable "
                "and no algorithm can guarantee profits. Model accuracy rates reflect backtested performance "
                "which may not reflect live trading outcomes.\n\n"
                "PAST PERFORMANCE\n"
                "Past accuracy of our predictions does not guarantee future results. "
                "All displayed win rates and performance metrics are historical.\n\n"
                "PAPER TRADING\n"
                "Paper trading results may differ significantly from live trading due to slippage, "
                "liquidity constraints, and market impact.\n\n"
                "REGULATORY\n"
                "BullLogic is not a registered investment advisor, broker-dealer, or financial institution. "
                "Always consult a qualified financial advisor before making investment decisions."
            ),
        },
        'data_sources': {
            'title': 'Data Sources',
            'content': (
                "Yahoo Finance (primary prices)\n"
                "Live quotes, historical daily and intraday candles for stocks, ETFs, crypto, forex, commodities, and indices. Used for model training, live predictions, charts, and the price sidebar. Data may be delayed by up to 15 minutes for some exchanges.\n\n"
                "Pyth Network (Hermes) (verification + failover)\n"
                "An oracle network aggregating prices from major exchanges and trading firms, delivered with a confidence interval. We cross-check displayed prices against Pyth and show a Verified badge when sources agree. If Yahoo is unavailable, Pyth prices take over with a clear source label. Equity feeds pause outside US market hours by design.\n\n"
                "Alpaca Markets (training data)\n"
                "High-resolution 1-minute historical bars used to train the short-timeframe models. Not used for live display.\n\n"
                "Microsoft Azure Blob Storage (infrastructure)\n"
                "Encrypted storage for trained model files. No personal data is stored there.\n\n"
                "Safaricom Daraja and Stripe (payments)\n"
                "Payment processing only. See the Privacy Policy for what payment data we retain.\n\n"
                "Disclaimer:\n"
                "Where sources disagree beyond tolerance we show both values rather than choosing silently. When all sources fail you see an honest 'last known price' banner with the timestamp, never a fabricated number."
            ),
        },
        'methodology': {
            'title': 'Methodology & Model Architecture',
            'content': (
                "1. What the models are\n"
                "For every supported asset we train an ensemble of three machine learning models: Linear Regression (finds straight-line relationships between indicators and future price), Random Forest (hundreds of decision trees voting together), and XGBoost (a gradient-boosted classifier focused on direction). Each model sees years of historical candles plus dozens of engineered features: moving averages, RSI, MACD, volatility measures, and market-structure signals inspired by ICT concepts.\n\n"
                "2. What data feeds them\n"
                "Training and live inference use Yahoo Finance data, with Alpaca supplying high-resolution 1-minute bars. Displayed prices are cross-checked in real time against the Pyth Network oracle, which aggregates prices from major exchanges and trading firms. When our two sources agree within 0.5 percent you see a Verified badge; when they disagree we show you both numbers instead of quietly picking one.\n\n"
                "3. What a prediction actually says\n"
                "A prediction gives you: a predicted price for the chosen timeframe, a direction (bullish or bearish), and a confidence score derived from how strongly the models agree. It is a statistical estimate based on patterns in past data. It is not knowledge of the future.\n\n"
                "4. How accuracy is graded\n"
                "Every prediction is graded automatically once its time horizon passes. We fetch what the market actually did and record whether the direction call was right and how far the price target missed in percent. Every user's predictions are graded, including the wrong ones. Aggregated results are public on the Track Record page. Models with fewer than 10 graded calls show 'insufficient data' because small samples mislead.\n\n"
                "5. The limits, honestly\n"
                "- Markets are moved by news, policy, and events that no historical pattern predicts.\n"
                "- A model that is 60 percent right on direction is still wrong 4 times out of 10.\n"
                "- Accuracy drifts as market conditions change. We monitor for drift and retrain, but there is always lag.\n"
                "- Short timeframes (minutes) are noisier and harder than daily horizons.\n"
                "- Backtested or historical accuracy never guarantees the next call.\n\n"
                "Bottom line:\n"
                "BullLogic is a research tool that helps you form a view faster. It is not financial advice, and no prediction should ever be your only reason to trade. Decide your risk before you decide your trade."
            ),
        },
        'risk_basics': {
            'title': 'Three Things Before Your First Prediction',
            'content': (
                "1. PREDICTIONS ARE PROBABILITIES, NOT PROMISES\n"
                "Even our best models are wrong regularly. Check the public track record for any model before "
                "trusting it, and treat every prediction as one input among many, never as a guarantee.\n\n"
                "2. DO NOT PUT EVERYTHING IN ONE TRADE\n"
                "Spreading money across different assets and keeping position sizes small means a single wrong "
                "call cannot wipe you out. Professionals rarely risk more than 1 to 2 percent of their capital on one idea.\n\n"
                "3. ONLY TRADE MONEY YOU CAN AFFORD TO LOSE\n"
                "Never trade rent, school fees, or emergency savings. If losing the money would change your life, "
                "it does not belong in the market. There will always be another trade tomorrow."
            ),
        },
        'faq': [
            {'question': 'How do BullLogic predictions work?', 'answer': 'We train machine learning models (Linear Regression, Random Forest, and XGBoost ensembles) on years of historical price data and technical indicators. When you request a prediction, the models analyze indicators like RSI and MACD to generate direction and confidence.'},
            {'question': 'How accurate are the predictions?', 'answer': 'It varies by asset and timeframe. Every prediction on the platform is automatically graded once its horizon passes. See live numbers on the Track Record page. No prediction is ever guaranteed.'},
            {'question': 'Is this financial advice?', 'answer': 'No. BullLogic is an information and analytics tool. Nothing on the platform constitutes a recommendation to buy or sell any asset. You are solely responsible for your trading decisions.'},
            {'question': 'What assets can I get predictions for?', 'answer': 'Over 50 instruments: major US stocks, ETFs (SPY, QQQ), crypto (BTC, ETH, SOL), forex pairs, and global indices.'},
            {'question': 'How many free predictions do I get?', 'answer': 'Free accounts get 5 predictions per day, resetting at midnight UTC. Pro accounts have no daily limits.'},
            {'question': 'How do I pay with M-Pesa?', 'answer': 'Go to Pricing, choose a plan, and enter your Safaricom number (07XX XXX XXX). You will receive an STK prompt on your phone to approve. Pro access activates instantly after confirmation.'},
        ],
    }

    def get(self, request, page_id):
        page_id = page_id.rstrip('/')
        content = self.CONTENT.get(page_id)
        if content is None:
            return Response({'ok': False, 'error': f'Page "{page_id}" not found.'}, status=404)
        return Response({'ok': True, 'data': content})

# ── Password reset / verify email (implementations) ───────────────────────────

import secrets
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from users.models import User, PasswordResetToken

@method_decorator(csrf_exempt, name='dispatch')
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            return Response({'ok': False, 'error': 'Email is required.'}, status=400)
        
        user = User.objects.filter(email__iexact=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(hours=1)
            
            PasswordResetToken.objects.create(
                user=user,
                token=token,
                expires_at=expires_at,
                used=False
            )
            
            reset_url = f"http://localhost:5001/reset-password?token={token}"
            send_mail(
                subject="Reset Your BullLogic Password",
                message=f"Hello,\n\nPlease reset your password using the link below:\n\n{reset_url}\n\nThis link will expire in 1 hour.",
                from_email="noreply@bulllogic.ai",
                recipient_list=[user.email],
                fail_silently=True
            )
            
        return Response({'ok': True, 'message': 'If that email is registered, you will receive a reset link shortly.'})


@method_decorator(csrf_exempt, name='dispatch')
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        token = request.data.get('token', '')
        password = request.data.get('password', '')
        if not token or not password:
            return Response({'ok': False, 'error': 'token and password are required.'}, status=400)
        
        if len(password) < 8:
            return Response({'ok': False, 'error': 'Password must be at least 8 characters long.'}, status=400)

        reset_token = PasswordResetToken.objects.filter(token=token, used=False).first()
        if not reset_token:
            return Response({'ok': False, 'error': 'Invalid or already used token.'}, status=400)
            
        if reset_token.expires_at < datetime.utcnow():
            return Response({'ok': False, 'error': 'Token has expired.'}, status=400)
            
        user = reset_token.user
        user.set_password(password)
        user.session_token = secrets.token_hex(20)
        user.save()
        
        reset_token.used = True
        reset_token.save(update_fields=['used'])
        
        return Response({'ok': True, 'message': 'Password reset successfully. Please log in.'})


@method_decorator(csrf_exempt, name='dispatch')
class VerifyEmailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        token = request.data.get('token', '')
        if not token:
            return Response({'ok': False, 'error': 'token is required.'}, status=400)
            
        signer = TimestampSigner()
        try:
            username = signer.unsign(token, max_age=86400)
            user = User.objects.get(username=username)
            user.email_verified = True
            user.save(update_fields=['email_verified'])
            return Response({'ok': True, 'message': 'Email verified successfully!'})
        except SignatureExpired:
            return Response({'ok': False, 'error': 'Verification link has expired.'}, status=400)
        except (BadSignature, User.DoesNotExist):
            return Response({'ok': False, 'error': 'Invalid verification link.'}, status=400)

# ── Simulated Payments / Upgrade APIs ────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class StripeCheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        tier = (request.data.get('tier') or '').strip().lower()
        billing_mode = (request.data.get('billing_mode') or 'monthly').strip().lower()
        if tier not in ('free', 'plus', 'pro', 'enterprise'):
            return Response({'ok': False, 'error': f'Invalid tier "{tier}"'}, status=400)

        user = request.user
        user.plan = tier
        user.save(update_fields=['plan'])

        from users.models import Payment
        amount = 0.0
        if tier == 'plus':
            amount = 8.0 if billing_mode == 'annual' else 12.0
        elif tier == 'pro':
            amount = 19.0 if billing_mode == 'annual' else 29.0
            
        Payment.objects.create(
            user=user,
            provider='stripe',
            plan=billing_mode,
            tier=tier,
            amount=amount,
            currency='USD',
            status='paid',
            completed_at=datetime.utcnow()
        )

        return Response({
            'ok': True,
            'message': f'Success! Upgraded to {tier.capitalize()} plan.',
            'plan': tier
        })


@method_decorator(csrf_exempt, name='dispatch')
class MpesaPayView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request):
        import mpesa
        phone = (request.data.get('phone') or '').strip().replace(" ", "").replace("-", "")
        tier = (request.data.get('tier') or '').strip().lower()
        billing_mode = (request.data.get('billing_mode') or 'monthly').strip().lower()
        
        if not phone:
            return Response({'ok': False, 'error': 'Phone number is required'}, status=400)
        if tier not in ('plus', 'pro', 'enterprise'):
            return Response({'ok': False, 'error': f'Invalid tier "{tier}"'}, status=400)

        # Format phone to 254XXXXXXXXX
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not phone.startswith("254") or len(phone) != 12 or not phone.isdigit():
            return Response({'ok': False, 'error': 'Enter a valid Safaricom number (07XXXXXXXX).'}, status=400)

        # Determine amount
        if tier == 'plus':
            amount = mpesa.PLUS_ANNUAL_KES if billing_mode == "annual" else mpesa.PLUS_MONTHLY_KES
        else:
            amount = mpesa.PRO_ANNUAL_KES if billing_mode == "annual" else mpesa.PRO_MONTHLY_KES
            
        days = 365 if billing_mode == "annual" else 30
        desc = f"BullLogic {tier.capitalize()} {'1 yr' if billing_mode == 'annual' else '30 days'}"

        if not mpesa.MPESA_OK:
            # Fallback for dev if credentials are not configured
            user = request.user
            user.plan = tier
            user.save(update_fields=['plan'])
            return Response({
                'ok': True,
                'message': f'Sandbox Mode: Upgrade to {tier.capitalize()} is complete!',
                'plan': tier
            })

        try:
            resp = mpesa.stk_push(phone, amount, f"BullLogic{tier.capitalize()[:4]}", desc)
        except Exception as e:
            return Response({'ok': False, 'error': str(e)}, status=500)

        if resp.get("ResponseCode") != "0":
            return Response({'ok': False, 'error': resp.get("ResponseDescription", "STK push failed")}, status=400)

        checkout_id = resp["CheckoutRequestID"]
        
        # Save payment log
        from users.models import Payment
        Payment.objects.create(
            user=request.user,
            provider='mpesa',
            plan=billing_mode,
            tier=tier,
            amount=float(amount),
            currency='KES',
            days=days,
            phone=phone,
            reference=checkout_id,
            status='pending'
        )

        return Response({
            'ok': True,
            'message': f'STK push initiated on {phone}. Upgrade to {tier.capitalize()} will complete once payment is approved!',
            'checkout_request_id': checkout_id
        })


@method_decorator(csrf_exempt, name='dispatch')
class MpesaCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        import mpesa
        from users.models import Payment
        data = request.data or {}
        try:
            body = data["Body"]["stkCallback"]
            code = body.get("ResultCode", -1)
            chk_id = body.get("CheckoutRequestID", "")
            payment = Payment.objects.filter(reference=chk_id, provider='mpesa').first()
            if payment:
                if code == 0:
                    receipt = None
                    for item in (body.get("CallbackMetadata") or {}).get("Item", []):
                        if item.get("Name") == "MpesaReceiptNumber":
                            receipt = str(item.get("Value", ""))[:40]
                    
                    if payment.status != 'paid':
                        payment.status = 'paid'
                        payment.receipt = receipt
                        payment.completed_at = datetime.utcnow()
                        payment.save(update_fields=['status', 'receipt', 'completed_at'])
                        
                        user = payment.user
                        if user:
                            user.plan = payment.tier
                            user.save(update_fields=['plan'])
                elif payment.status == 'pending':
                    payment.status = 'cancelled' if code == 1032 else 'failed'
                    payment.completed_at = datetime.utcnow()
                    payment.save(update_fields=['status', 'completed_at'])
        except Exception:
            pass
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

