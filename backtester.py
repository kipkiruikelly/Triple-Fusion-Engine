"""
backtester.py  —  BullLogic historical backtesting engine

Option 6: true bar-by-bar replay of the live prediction pipeline.
At each bar we run the exact same inference the live app runs, then
enter the trade on the *next* bar's open (no look-ahead bias).

Signal fires when ML direction AND ICT bias both agree:
  BUY  — direction=="Up"   AND ict_bias=="Bullish"
  SELL — direction=="Down" AND ict_bias=="Bearish"

SL/TP exit: 1.5× ATR stop, 3× ATR target, checked via bar High/Low.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

from predictor import build_features, _load_models, YF_SYMBOL_MAP


# ── Bar-by-bar signal replay ───────────────────────────────────────────────────

def _replay_signal_at(row: pd.Series, close: float,
                      lr_pred: float, rf_ret: float,
                      recent_vol: float) -> tuple:
    """
    Replay the exact logic from run_prediction() for a single bar.
    Returns (signal, direction, confidence, ict_bias).
    """
    price_change = lr_pred - close
    direction    = "Up" if price_change > 0 else "Down"
    change_pct   = abs(price_change / close * 100)
    confidence   = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

    above_200   = int(row["Above_200SMA"]) == 1
    struct_bull = int(row["Structure_Bullish"]) == 1

    if above_200 and struct_bull:
        ict_bias = "Bullish"
    elif not above_200 and not struct_bull:
        ict_bias = "Bearish"
    else:
        ict_bias = "Neutral"

    # Signal fires when ML and ICT agree
    if direction == "Up"   and ict_bias == "Bullish":
        signal = "BUY"
    elif direction == "Down" and ict_bias == "Bearish":
        signal = "SELL"
    else:
        signal = "HOLD"

    return signal, direction, confidence, ict_bias


def _generate_signals(df: pd.DataFrame, lr, rf, scaler, feat_cols) -> np.ndarray:
    """
    Batch-predict then replay signal logic bar by bar.
    Equivalent to running run_prediction() at each historical bar.
    """
    closes   = df["Close"].values.astype(float)
    X_all    = scaler.transform(df[feat_cols].values)
    lr_preds = lr.predict(X_all)
    rf_rets  = rf.predict(X_all)
    daily_ret = df["Daily_Return"].values.astype(float)

    signals = np.full(len(df), "HOLD", dtype=object)

    for i in range(len(df)):
        recent_vol = float(np.std(daily_ret[max(0, i - 20):i + 1]))
        sig, _, _, _ = _replay_signal_at(
            row        = df.iloc[i],
            close      = closes[i],
            lr_pred    = float(lr_preds[i]),
            rf_ret     = float(rf_rets[i]),
            recent_vol = recent_vol,
        )
        signals[i] = sig

    return signals


# ── Trade simulation ───────────────────────────────────────────────────────────

def _simulate(df: pd.DataFrame, signals: np.ndarray,
              initial_capital: float, risk_pct: float) -> tuple:
    """
    Walk-forward trade simulation.
    Entry at next bar open; exit when SL or TP hit (checked via High/Low).
    Only one open position at a time.
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

        # ── 1. Check open position against current bar OHLC ──────────────────
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
            else:  # SELL
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
                    "confidence": position.get("confidence", 0),
                    "ict_bias":   position.get("ict_bias", ""),
                })
                position = None

        # ── 2. Enter new position on signal from previous bar ─────────────────
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


# ── Performance metrics ────────────────────────────────────────────────────────

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
    rets = [(eqs[i] - eqs[i - 1]) / eqs[i - 1]
            for i in range(1, len(eqs)) if eqs[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mu  = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    return round(mu / std * (252 ** 0.5), 2) if std > 0 else 0.0


def _monthly_returns(equity_curve: list) -> dict:
    monthly = {}
    for p in equity_curve:
        ym = p["date"][:7]
        monthly[ym] = p["equity"]
    months = sorted(monthly)
    result = {}
    for i in range(1, len(months)):
        prev = monthly[months[i - 1]]
        curr = monthly[months[i]]
        if prev > 0:
            result[months[i]] = round((curr - prev) / prev * 100, 2)
    return result


def _bh_curve(df: pd.DataFrame, initial_capital: float) -> list:
    closes = df["Close"].values.astype(float)
    dates  = [str(d.date()) for d in df.index]
    base   = closes[0]
    return [
        {"date": dates[i], "equity": round(initial_capital * closes[i] / base, 2)}
        for i in range(len(closes))
    ]


# ── Public entry point ─────────────────────────────────────────────────────────

def run_backtest(ticker: str, interval: str = "1d",
                 period: str = "2y",
                 initial_capital: float = 10_000,
                 risk_pct: float = 1.0) -> dict:
    """
    Run a full historical backtest using the live prediction pipeline
    replayed bar-by-bar over historical data.
    """
    ticker = ticker.upper()
    yf_sym = YF_SYMBOL_MAP.get(ticker, ticker.replace(".", "-"))

    raw = yf.download(yf_sym, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if raw.empty or len(raw) < 60:
        raise ValueError(
            f"Not enough data for '{ticker}' — try a longer period or a different ticker."
        )

    df = build_features(raw.copy(), interval)
    if df.empty or len(df) < 30:
        raise ValueError("Feature engineering produced insufficient rows.")

    lr, rf, scaler, feat_cols = _load_models(ticker, interval)

    signals        = _generate_signals(df, lr, rf, scaler, feat_cols)
    trades, equity = _simulate(df, signals, initial_capital, risk_pct)

    closed = [t for t in trades if t["result"] != "open"]
    wins   = [t for t in closed if t["result"] == "win"]
    losses = [t for t in closed if t["result"] == "loss"]

    gross_profit  = sum(t["pnl"] for t in wins)
    gross_loss    = abs(sum(t["pnl"] for t in losses))
    win_rate      = len(wins) / len(closed) * 100 if closed else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if wins else 0.0)
    avg_win       = gross_profit / len(wins)   if wins   else 0.0
    avg_loss      = gross_loss   / len(losses) if losses else 0.0
    expectancy    = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)
    total_return  = (equity[-1]["equity"] - initial_capital) / initial_capital * 100
    bh_return     = (float(df["Close"].iloc[-1]) - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0]) * 100

    # Signal frequency stats
    n_buy  = int(np.sum(signals == "BUY"))
    n_sell = int(np.sum(signals == "SELL"))

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
        "buy_signals":    n_buy,
        "sell_signals":   n_sell,
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
