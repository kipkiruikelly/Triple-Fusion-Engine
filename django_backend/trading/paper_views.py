import json
import numpy as np
from datetime import datetime
from django.db.models import Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication

from users.models import PaperTrade, PaperEquitySnapshot, AppSetting, User

SIM_CURRENCY = "KES"
MIN_TRADES = 10
BUILTIN_STRATEGIES = ("ml_ensemble", "alpha_rules")

DEFAULT_CONFIG = {
    "starting_balance": 1000000.0,
    "risk_pct": 1.0,
    "max_positions": 5,
    "max_class_exposure_pct": 40.0,
    "daily_loss_breaker_pct": 5.0,
    "spread_bps": 5.0,
    "commission_bps": 10.0,
    "stop_atr_mult": 1.5,
    "target_atr_mult": 2.5,
    "max_hold_hours": 240,
    "min_confidence": 55.0,
    "alpha_entry_threshold": 0.5,
    "alpha_rank_weight": 0.5,
    "pyth_wide_conf_pct": 0.30,
    "tickers": ["QQQ", "SPY", "DIA", "AAPL", "MSFT", "TSLA", "NVDA", "GOOGL", "AMZN", "META", "BTC", "ETH"],
}


def load_config():
    try:
        row = AppSetting.objects.filter(key="paper_config").first()
        if row:
            return json.loads(row.value)
    except Exception:
        pass
    return DEFAULT_CONFIG


def compute_metrics(closed_pnls, equity_series, min_trades=MIN_TRADES):
    n = len(closed_pnls)
    out = {"trades": n, "min_trades": min_trades, "sufficient": n >= min_trades}
    if not out["sufficient"]:
        return out

    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    out["win_rate_pct"] = round(len(wins) / n * 100, 1)
    out["profit_factor"] = round(gross_w / gross_l, 3) if gross_l > 0 else None
    out["avg_win"] = round(gross_w / len(wins), 2) if wins else 0.0
    out["avg_loss"] = round(-gross_l / len(losses), 2) if losses else 0.0
    out["net_pnl"] = round(sum(closed_pnls), 2)

    eq = np.asarray([e for e in equity_series if e and e > 0], dtype=float)
    if len(eq) >= 3:
        rets = np.diff(eq) / eq[:-1]
        sd = rets.std(ddof=1)
        out["total_return_pct"] = round((eq[-1] / eq[0] - 1) * 100, 2)
        out["sharpe"] = round(float(rets.mean() / sd * np.sqrt(252)), 3) if sd > 0 else None
        downside = rets[rets < 0]
        dsd = downside.std(ddof=1) if len(downside) > 1 else 0.0
        out["sortino"] = round(float(rets.mean() / dsd * np.sqrt(252)), 3) if dsd > 0 else None
        peak = np.maximum.accumulate(eq)
        out["max_drawdown_pct"] = round(float(((eq - peak) / peak).min() * 100), 2)
    else:
        out["total_return_pct"] = out["sharpe"] = out["sortino"] = None
        out["max_drawdown_pct"] = None
    return out


def strategy_report(strategy, cfg, user_id=None):
    closed = PaperTrade.objects.filter(strategy=strategy, status="closed", user_id=user_id).order_by("exit_time")
    snaps = PaperEquitySnapshot.objects.filter(strategy=strategy, user_id=user_id).order_by("taken_at")

    daily = {}
    for s in snaps:
        daily[s.taken_at.date().isoformat()] = s.equity
    eq_series = [cfg["starting_balance"]] + list(daily.values())

    pnls = [t.pnl for t in closed if t.pnl is not None]
    metrics = compute_metrics(pnls, eq_series)

    open_pos = PaperTrade.objects.filter(strategy=strategy, status="open", user_id=user_id)
    exposure_notional = sum(p.qty * p.entry_price for p in open_pos)
    
    total_closed_pnl = sum(pnls)
    eq_now = cfg["starting_balance"] + total_closed_pnl
    turnover = sum(abs(t.qty * t.entry_price) for t in closed)

    by_class, by_model = {}, {}
    for t in closed:
        for key, bucket in ((t.asset_class, by_class), (t.model or "?", by_model)):
            b = bucket.setdefault(key, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            b["trades"] += 1
            b["net_pnl"] = round(b["net_pnl"] + (t.pnl or 0.0), 2)
            if (t.pnl or 0) > 0:
                b["wins"] += 1
    for bucket in (by_class, by_model):
        for b in bucket.values():
            b["win_rate_pct"] = (round(b["wins"] / b["trades"] * 100, 1)
                                 if b["trades"] >= MIN_TRADES else None)

    return {
        "strategy": strategy,
        "enabled": True,  # default to enabled
        "equity": round(eq_now, 2),
        "starting_balance": cfg["starting_balance"],
        "currency": SIM_CURRENCY,
        "open_positions": open_pos.count(),
        "exposure_pct": round(exposure_notional / eq_now * 100, 2) if eq_now > 0 else 0.0,
        "turnover": round(turnover, 2),
        "metrics": metrics,
        "by_asset_class": by_class,
        "by_model": by_model,
        "equity_curve": [{"date": d, "equity": round(v, 2)}
                         for d, v in sorted(daily.items())],
    }


def _trade_json(t):
    return {
        "id": t.id,
        "strategy": t.strategy,
        "model": t.model,
        "ticker": t.ticker,
        "asset_class": t.asset_class,
        "side": t.side,
        "qty": t.qty,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "entry_price": t.entry_price,
        "entry_mkt": t.entry_mkt,
        "price_source": t.price_source,
        "stop": t.stop_price,
        "target": t.target_price,
        "confidence": t.confidence,
        "rationale": t.rationale,
        "commission": t.commission,
        "status": t.status,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "exit_price": t.exit_price,
        "exit_reason": t.exit_reason,
        "pnl": t.pnl,
        "simulated": True,
    }


class PaperSummaryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        cfg = load_config()
        started_row = AppSetting.objects.filter(key="paper_trading_started_at").first()
        started = started_row.value if started_row else None
        enabled_row = AppSetting.objects.filter(key="paper_trading_enabled").first()
        enabled = (enabled_row.value == "1") if enabled_row else True

        return Response({
            "ok": True,
            "simulated": True,
            "currency": SIM_CURRENCY,
            "enabled": enabled,
            "started_at": started,
            "min_trades": MIN_TRADES,
            "assumptions": {
                "spread_bps": cfg["spread_bps"],
                "commission_bps": cfg["commission_bps"],
                "note": ("Fills are simulated: entries and exits cross a "
                         "configurable spread/slippage estimate and pay a "
                         "commission per side. Simulated performance does "
                         "not guarantee real results."),
            },
            "strategies": [strategy_report(s, cfg) for s in BUILTIN_STRATEGIES],
        })


class PaperTradesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        q = PaperTrade.objects.filter(status="closed", user_id__isnull=True)
        strategy = request.query_params.get("strategy", "")
        ticker = request.query_params.get("ticker", "").upper().strip()

        if strategy in BUILTIN_STRATEGIES:
            q = q.filter(strategy=strategy)
        if ticker:
            q = q.filter(ticker=ticker)

        page = max(1, int(request.query_params.get("page", 1) or 1))
        per = 50
        offset = (page - 1) * per
        rows = q.order_by("-exit_time")[offset:offset + per]

        return Response({
            "ok": True,
            "simulated": True,
            "page": page,
            "total": q.count(),
            "trades": [_trade_json(t) for t in rows]
        })


class PaperOptInView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        request.user.paper_trading_opted_in = True
        request.user.save(update_fields=["paper_trading_opted_in"])
        return Response({"ok": True, "opted_in": True})


class PaperOptOutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        request.user.paper_trading_opted_in = False
        request.user.save(update_fields=["paper_trading_opted_in"])
        return Response({"ok": True, "opted_in": False})


class PaperMyPortfolioView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        cfg = load_config()
        return Response({
            "ok": True,
            "simulated": True,
            "currency": SIM_CURRENCY,
            "opted_in": bool(request.user.paper_trading_opted_in),
            "min_trades": MIN_TRADES,
            "strategies": [strategy_report(s, cfg, user_id=request.user.id) for s in BUILTIN_STRATEGIES],
        })


class TraderLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 10)), 100)
        cfg = load_config()
        users = User.objects.filter(paper_trading_opted_in=True)
        rows = []
        for u in users:
            for strategy in BUILTIN_STRATEGIES:
                report = strategy_report(strategy, cfg, user_id=u.id)
                m = report["metrics"]
                if not m["sufficient"]:
                    continue
                rows.append({
                    "username": u.username,
                    "strategy": strategy,
                    "sharpe": m["sharpe"],
                    "return_pct": m["total_return_pct"],
                    "win_rate": m["win_rate_pct"],
                    "trades": m["trades"],
                    "equity": report["equity"],
                })
        rows.sort(key=lambda r: (r["sharpe"] if r["sharpe"] is not None else float("-inf"), r["return_pct"] or 0), reverse=True)
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        return Response({
            "ok": True,
            "leaderboard": rows[:limit],
            "min_trades": MIN_TRADES,
            "total_ranked": len(rows)
        })
