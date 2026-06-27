"""
backtester.py
Historical backtesting engine for BullLogic.

Generates ML + ICT signals on historical bars, simulates trades
with ATR-based SL/TP, and returns detailed performance metrics.

No look-ahead bias: signal at bar i → entry at bar i+1 open.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import os

from predictor import build_features, _load_models, YF_SYMBOL_MAP

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")


# ── Signal generation ─────────────────────────────────────────────────────────

def _generate_signals(df: pd.DataFrame, lr, rf, scaler, feat_cols) -> np.ndarray:
    """
    Batch-predict signals for every bar.
    Returns numpy array of "BUY", "SELL", or "HOLD" strings.

    Entry logic:
      BUY  — LR predicts up, RF predicts positive return,
              price in discount zone (PD_Position < 0.45), above 200 SMA
      SELL — LR predicts down, RF predicts negative return,
              price in premium zone (PD_Position > 0.55), below 200 SMA
    """
    close   = df["Close"].values
    X       = scaler.transform(df[feat_cols].values)
    lr_pred = lr.predict(X)
    rf_ret  = rf.predict(X)

    lr_up = lr_pred > close
    rf_up = rf_ret  > 0

    pd_pos    = df["PD_Position"].values
    above_200 = df["Above_200SMA"].values > 0.5

    signals = np.full(len(df), "HOLD", dtype=object)
    signals[lr_up  & rf_up  & (pd_pos < 0.45) & above_200]  = "BUY"
    signals[~lr_up & ~rf_up & (pd_pos > 0.55) & ~above_200] = "SELL"
    return signals


# ── Trade simulation ──────────────────────────────────────────────────────────

def _simulate(df: pd.DataFrame, signals: np.ndarray,
              initial_capital: float, risk_pct: float) -> tuple:
    """
    Walk-forward trade simulation.
    Enter at next bar open, exit when SL or TP is hit (checked via High/Low).
    """
    opens  = df["Open"].values.astype(float)
    highs  = df["High"].values.astype(float)
    lows   = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    atrs   = df["ATR_14"].values.astype(float)
    dates  = [str(d.date()) for d in df.index]

    capital  = float(initial_capital)
    position = None
    trades   = []
    equity   = [{"date": dates[0], "equity": round(capital, 2)}]

    for i in range(1, len(df)):
        # ── 1. Check open position against today's OHLC ──────────────────────
        if position is not None and i > position["bar"]:
            action = position["action"]
            sl, tp = position["sl"], position["tp"]

            exited = False
            if action == "BUY":
                if lows[i] <= sl:
                    exit_p, outcome = sl, "loss"
                    exited = True
                elif highs[i] >= tp:
                    exit_p, outcome = tp, "win"
                    exited = True
            else:
                if highs[i] >= sl:
                    exit_p, outcome = sl, "loss"
                    exited = True
                elif lows[i] <= tp:
                    exit_p, outcome = tp, "win"
                    exited = True

            if exited:
                sl_dist = abs(position["entry"] - sl)
                shares  = (capital * risk_pct / 100) / sl_dist if sl_dist > 0 else 0
                pnl     = ((exit_p - position["entry"]) * shares if action == "BUY"
                           else (position["entry"] - exit_p) * shares)
                capital += pnl
                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date":  dates[i],
                    "action":     action,
                    "entry":      round(position["entry"], 4),
                    "exit":       round(exit_p, 4),
                    "sl":         round(sl, 4),
                    "tp":         round(tp, 4),
                    "result":     outcome,
                    "pnl":        round(pnl, 2),
                })
                position = None

        # ── 2. Enter new position if signal fired on previous bar ─────────────
        if position is None:
            sig = signals[i - 1]
            if sig in ("BUY", "SELL"):
                atr   = float(atrs[i - 1])
                entry = float(opens[i])
                if sig == "BUY":
                    sl = round(entry - 1.5 * atr, 4)
                    tp = round(entry + 3.0 * atr, 4)
                else:
                    sl = round(entry + 1.5 * atr, 4)
                    tp = round(entry - 3.0 * atr, 4)
                position = {
                    "action":     sig,
                    "entry":      entry,
                    "entry_date": dates[i],
                    "bar":        i,
                    "sl":         sl,
                    "tp":         tp,
                }

        equity.append({"date": dates[i], "equity": round(capital, 2)})

    # Close any remaining open position at last bar close
    if position is not None:
        exit_p  = float(closes[-1])
        action  = position["action"]
        sl_dist = abs(position["entry"] - position["sl"])
        shares  = (capital * risk_pct / 100) / sl_dist if sl_dist > 0 else 0
        pnl     = ((exit_p - position["entry"]) * shares if action == "BUY"
                   else (position["entry"] - exit_p) * shares)
        capital += pnl
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date":  dates[-1],
            "action":     action,
            "entry":      round(position["entry"], 4),
            "exit":       round(exit_p, 4),
            "sl":         round(position["sl"], 4),
            "tp":         round(position["tp"], 4),
            "result":     "open",
            "pnl":        round(pnl, 2),
        })
        equity[-1]["equity"] = round(capital, 2)

    return trades, equity


# ── Performance metrics ───────────────────────────────────────────────────────

def _max_drawdown(equity_curve: list) -> float:
    peak, max_dd = equity_curve[0]["equity"], 0.0
    for p in equity_curve:
        eq = p["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _sharpe(equity_curve: list) -> float:
    eqs  = [p["equity"] for p in equity_curve]
    rets = [(eqs[i] - eqs[i-1]) / eqs[i-1] for i in range(1, len(eqs)) if eqs[i-1] > 0]
    if len(rets) < 2:
        return 0.0
    mu  = sum(rets) / len(rets)
    var = sum((r - mu)**2 for r in rets) / (len(rets) - 1)
    std = var**0.5
    return round(mu / std * (252**0.5), 2) if std > 0 else 0.0


def _monthly_returns(equity_curve: list) -> dict:
    """Return {YYYY-MM: pct_change} from the equity curve."""
    monthly = {}
    for p in equity_curve:
        ym = p["date"][:7]
        monthly[ym] = p["equity"]
    months = sorted(monthly)
    result = {}
    for i in range(1, len(months)):
        prev = monthly[months[i-1]]
        curr = monthly[months[i]]
        if prev > 0:
            result[months[i]] = round((curr - prev) / prev * 100, 2)
    return result


def _bh_curve(df: pd.DataFrame, initial_capital: float) -> list:
    """Buy-and-hold equity curve (buy first close, hold to end)."""
    closes = df["Close"].values.astype(float)
    dates  = [str(d.date()) for d in df.index]
    base   = closes[0]
    return [
        {"date": dates[i], "equity": round(initial_capital * closes[i] / base, 2)}
        for i in range(len(closes))
    ]


# ── Public entry point ────────────────────────────────────────────────────────

def run_backtest(ticker: str, interval: str = "1d",
                 period: str = "2y",
                 initial_capital: float = 10_000,
                 risk_pct: float = 1.0) -> dict:
    """
    Run a full historical backtest.

    Args:
        ticker:          Equity symbol (e.g. "AAPL")
        interval:        "1d" or "1h"
        period:          yfinance period string: "6mo", "1y", "2y"
        initial_capital: Starting cash in USD
        risk_pct:        Percent of capital risked per trade (1 = 1%)

    Returns:
        Full result dict ready to JSON-serialize.
    """
    ticker = ticker.upper()

    # ── Fetch data ────────────────────────────────────────────────────────────
    yf_sym = YF_SYMBOL_MAP.get(ticker, ticker.replace(".", "-"))
    raw = yf.download(yf_sym, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if raw.empty or len(raw) < 60:
        raise ValueError(f"Not enough data for '{ticker}' — try a longer period or different ticker.")

    # ── Feature engineering ───────────────────────────────────────────────────
    df = build_features(raw.copy(), interval)
    if df.empty or len(df) < 30:
        raise ValueError("Feature engineering produced insufficient rows.")

    # ── Load models ───────────────────────────────────────────────────────────
    lr, rf, scaler, feat_cols = _load_models(ticker, interval)

    # ── Signals + simulation ──────────────────────────────────────────────────
    signals       = _generate_signals(df, lr, rf, scaler, feat_cols)
    trades, equity = _simulate(df, signals, initial_capital, risk_pct)

    # ── Metrics ───────────────────────────────────────────────────────────────
    closed = [t for t in trades if t["result"] != "open"]
    wins   = [t for t in closed if t["result"] == "win"]
    losses = [t for t in closed if t["result"] == "loss"]
    pnls   = [t["pnl"] for t in closed]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    win_rate     = len(wins) / len(closed) * 100 if closed else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if wins else 0.0)
    avg_win      = gross_profit / len(wins)   if wins   else 0.0
    avg_loss     = gross_loss   / len(losses) if losses else 0.0
    expectancy   = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    total_return = (equity[-1]["equity"] - initial_capital) / initial_capital * 100
    bh_return    = (float(df["Close"].iloc[-1]) - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0]) * 100

    metrics = {
        "total_return":   round(total_return, 2),
        "bh_return":      round(bh_return, 2),
        "alpha":          round(total_return - bh_return, 2),
        "win_rate":       round(win_rate, 1),
        "total_trades":   len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "gross_profit":   round(gross_profit, 2),
        "gross_loss":     round(gross_loss, 2),
        "profit_factor":  min(profit_factor, 99.0),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "expectancy":     round(expectancy, 2),
        "max_drawdown":   _max_drawdown(equity),
        "sharpe":         _sharpe(equity),
        "final_equity":   round(equity[-1]["equity"], 2),
    }

    return {
        "ticker":          ticker,
        "interval":        interval,
        "period":          period,
        "start":           equity[0]["date"],
        "end":             equity[-1]["date"],
        "bars":            len(df),
        "initial_capital": initial_capital,
        "risk_pct":        risk_pct,
        "metrics":         metrics,
        "trades":          trades[-200:],
        "equity_curve":    equity,
        "bh_curve":        _bh_curve(df, initial_capital),
        "monthly_returns": _monthly_returns(equity),
    }
