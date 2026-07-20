import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

from users.models import PortfolioPosition


class PortfolioPositionsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        positions = PortfolioPosition.objects.filter(user=request.user).order_by("-opened_at")
        open_tickers = list({p.ticker for p in positions if p.status == "open"})
        
        live_prices = {}
        if open_tickers:
            def _px(t):
                try:
                    return t, float(yf.Ticker(t).fast_info.last_price or 0)
                except Exception:
                    return t, 0.0
            with ThreadPoolExecutor(max_workers=min(len(open_tickers), 6)) as ex:
                live_prices = dict(ex.map(_px, open_tickers))

        rows = []
        for p in positions:
            ep, qty = p.entry_price, p.quantity
            if p.status == "open":
                lp = live_prices.get(p.ticker, ep)
            else:
                lp = p.exit_price or ep
            
            pnl = (lp - ep) * qty if p.side.lower() == "long" else (ep - lp) * qty
            pnl_pct = (pnl / (ep * qty) * 100) if ep * qty else 0
            
            rows.append({
                "id": p.id,
                "ticker": p.ticker,
                "side": p.side,
                "entry_price": ep,
                "quantity": qty,
                "live_price": round(lp, 4),
                "exit_price": p.exit_price,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "status": p.status,
                "opened_at": p.opened_at.strftime("%Y-%m-%d") if p.opened_at else "",
                "closed_at": p.closed_at.strftime("%Y-%m-%d") if p.closed_at else None,
                "note": p.note or "",
            })
        return Response({"ok": True, "positions": rows})


class PortfolioOpenView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        ticker = request.data.get("ticker", "").upper().strip()
        side = request.data.get("side", "long").lower()
        entry_price = request.data.get("entry_price")
        quantity = request.data.get("quantity")
        note = request.data.get("note", "")[:200]

        if not ticker or entry_price is None or quantity is None:
            return Response({"ok": False, "error": "ticker, entry_price, quantity required"}, status=400)
        if side not in ("long", "short"):
            return Response({"ok": False, "error": "side must be long or short"}, status=400)
        
        try:
            entry_price = float(entry_price)
            quantity = float(quantity)
        except (TypeError, ValueError):
            return Response({"ok": False, "error": "entry_price and quantity must be numbers"}, status=400)

        pos = PortfolioPosition.objects.create(
            user=request.user,
            ticker=ticker,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            note=note
        )
        return Response({"ok": True, "id": pos.id}, status=201)


class PortfolioCloseView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        pos_id = request.data.get("position_id")
        exit_price = request.data.get("exit_price")
        
        try:
            pos = PortfolioPosition.objects.get(id=pos_id, user=request.user, status="open")
        except PortfolioPosition.DoesNotExist:
            return Response({"ok": False, "error": "Position not found"}, status=404)

        if exit_price is None:
            return Response({"ok": False, "error": "exit_price required"}, status=400)

        pos.exit_price = float(exit_price)
        pos.status = "closed"
        pos.closed_at = datetime.utcnow()
        pos.save()
        return Response({"ok": True})


class PortfolioDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        pos_id = request.data.get("position_id")
        try:
            pos = PortfolioPosition.objects.get(id=pos_id, user=request.user)
        except PortfolioPosition.DoesNotExist:
            return Response({"ok": False, "error": "Position not found"}, status=404)

        pos.delete()
        return Response({"ok": True})


class RiskCalculateView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        try:
            account = float(request.data.get("account", 10000))
            risk_pct = float(request.data.get("risk_pct", 1.0))
            entry = float(request.data.get("entry", 100))
            stop_loss = float(request.data.get("stop_loss", 95))
            target = float(request.data.get("target", 110))
        except (TypeError, ValueError):
            return Response({"ok": False, "error": "All parameters must be valid numbers"}, status=400)

        if entry <= 0 or stop_loss <= 0:
            return Response({"ok": False, "error": "Invalid prices"}, status=400)

        risk_amount = account * risk_pct / 100
        risk_per_sh = abs(entry - stop_loss)
        if risk_per_sh == 0:
            return Response({"ok": False, "error": "Entry and stop loss cannot be equal"}, status=400)

        shares = risk_amount / risk_per_sh
        position_val = shares * entry
        rr_ratio = abs(target - entry) / risk_per_sh if risk_per_sh else 0
        potential_pnl = (target - entry) * shares
        win_rate_est = 0.55
        kelly_fraction = win_rate_est - (1 - win_rate_est) / rr_ratio if rr_ratio > 0 else 0
        kelly_shares = max(0, account * kelly_fraction / entry)

        return Response({
            "ok": True,
            "shares": round(shares, 4),
            "position_val": round(position_val, 2),
            "risk_amount": round(risk_amount, 2),
            "risk_per_sh": round(risk_per_sh, 4),
            "rr_ratio": round(rr_ratio, 2),
            "potential_pnl": round(potential_pnl, 2),
            "kelly_shares": round(kelly_shares, 4),
            "kelly_pct": round(kelly_fraction * 100, 2),
        })
