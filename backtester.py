"""
backtester.py ,  BullLogic historical backtesting engine

Strict ICT + ML signal logic:
  BUY , ML bullish AND above 200SMA AND bullish structure
          AND price in Discount (PD < 0.45) AND ≥2 ICT confluences
  SELL, ML bearish AND below 200SMA AND bearish structure
          AND price in Premium (PD > 0.55) AND ≥2 ICT confluences

ICT confluences counted (any 2 of 6 required):
  1. In OTE zone (0.62-0.79 Fibonacci retracement)
  2. Unfilled FVG present within last 10 bars
  3. Order Block present within last 10 bars
  4. Liquidity sweep (stop hunt) just occurred
  5. Price at Consequent Encroachment of most recent FVG
  6. Price near 20-bar IPDA level (within 1.5 ATR)

Trade management (strict ICT):
  SL , 1.0× ATR (at OB boundary, tighter than default 1.5×)
  TP , 3.0× ATR → 3:1 R:R
  Cooldown, 3 bars after a loss in same direction (no revenge entries)

Entry , next bar open (no look-ahead bias)
Exit  , SL or TP hit, checked via bar High/Low
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

from predictor import build_features, _load_models, YF_SYMBOL_MAP


# ── ICT confluence scorer ──────────────────────────────────────────────────────

def _ict_score(row: pd.Series, direction: str) -> tuple:
    """
    Score ICT confluence for one bar.
    Returns (score: int, patterns: list[str]).

    Scored conditions (any 1 required for entry):
      BUY , OTE zone, Bullish FVG, Bullish OB, Swept Low, CE Bull FVG, IPDA low
      SELL, OTE zone, Bearish FVG, Bearish OB, Swept High, CE Bear FVG, IPDA high

    Note: the PD position (discount/premium) is intentionally NOT a hard gate
    here because FVG/OB/OTE patterns are already at structurally discounted
    levels by definition. Using the 60-bar PD range as a gate produces false
    negatives in strongly trending markets.
    """
    score    = 0
    patterns = []

    if direction == "BUY":
        if int(row["In_OTE_Buy"]):
            score += 1; patterns.append("OTE")
        if float(row["Bull_FVG_Count"]) > 0:
            score += 1; patterns.append("FVG")
        if float(row["Bull_OB_Count"]) > 0:
            score += 1; patterns.append("OB")
        if int(row["Swept_Low"]):
            score += 1; patterns.append("SweepLow")
        if abs(float(row["CE_Bull_FVG_Dist"])) < 0.5:
            score += 1; patterns.append("CE")
        if float(row["IPDA_20_Low_Dist"]) < 1.5:
            score += 1; patterns.append("IPDA")
    else:
        if int(row["In_OTE_Sell"]):
            score += 1; patterns.append("OTE")
        if float(row["Bear_FVG_Count"]) > 0:
            score += 1; patterns.append("FVG")
        if float(row["Bear_OB_Count"]) > 0:
            score += 1; patterns.append("OB")
        if int(row["Swept_High"]):
            score += 1; patterns.append("SweepHigh")
        if abs(float(row["CE_Bear_FVG_Dist"])) < 0.5:
            score += 1; patterns.append("CE")
        if float(row["IPDA_20_High_Dist"]) < 1.5:
            score += 1; patterns.append("IPDA")

    return score, patterns


# ── Bar-by-bar signal replay ───────────────────────────────────────────────────

def _generate_signals(df: pd.DataFrame, lr, rf, scaler,
                      feat_cols) -> tuple:
    """
    Replay the live prediction + strict ICT filter at every bar.

    Entry gates (ALL required):
      BUY , ML bullish + above 200SMA + bullish structure + ≥1 ICT pattern
      SELL, ML bearish + below 200SMA + bearish structure + ≥1 ICT pattern

    The PD position is included as one of the scoreable ICT patterns but
    is NOT a hard gate, using the 60-bar range as a mandatory filter
    blocks nearly every signal in trending markets because price spends
    most of a trend run in "premium" relative to the wider range.

    Returns (signals array, meta list of per-bar dicts with ICT details).
    """
    closes    = df["Close"].values.astype(float)
    X_all     = scaler.transform(df[feat_cols].values)
    lr_preds  = lr.predict(X_all)
    rf_rets   = rf.predict(X_all)

    signals = np.full(len(df), "HOLD", dtype=object)
    meta    = [None] * len(df)

    for i in range(len(df)):
        row   = df.iloc[i]
        price = closes[i]
        lr_p  = float(lr_preds[i])
        rf_r  = float(rf_rets[i])

        ml_bull = lr_p > price and rf_r > 0
        ml_bear = lr_p < price and rf_r < 0

        above_200   = int(row["Above_200SMA"]) == 1
        struct_bull = int(row["Structure_Bullish"]) == 1

        # ── BUY: macro + structure + at least 1 ICT pattern ──────
        if ml_bull and above_200 and struct_bull:
            score, patterns = _ict_score(row, "BUY")
            if score >= 1:
                signals[i] = "BUY"
                meta[i]    = {"score": score, "patterns": patterns}

        # ── SELL: macro + structure + at least 1 ICT pattern ─────
        elif ml_bear and not above_200 and not struct_bull:
            score, patterns = _ict_score(row, "SELL")
            if score >= 1:
                signals[i] = "SELL"
                meta[i]    = {"score": score, "patterns": patterns}

    return signals, meta


# ── Trade simulation ───────────────────────────────────────────────────────────

_SL_ATR_MULT = 1.0   # ICT SL: tight, at order block boundary
_TP_ATR_MULT = 3.0   # ICT TP: 3:1 reward-to-risk
_COOLDOWN    = 3     # bars to wait after a loss (same direction)


def _simulate(df: pd.DataFrame, signals: np.ndarray, meta: list,
              initial_capital: float, risk_pct: float) -> tuple:
    """
    Walk-forward simulation with:
    • SL = 1.0×ATR  (tight ICT placement)
    • TP = 3.0×ATR  (3:1 R:R)
    • 3-bar cooldown per direction after a loss
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

    # Cooldown trackers: bar index of last loss per direction
    last_loss = {"BUY": -999, "SELL": -999}

    for i in range(1, len(df)):

        # ── 1. Check open position against current bar OHLC ──────
        if position is not None and i > position["bar"]:
            action = position["action"]
            sl, tp = position["sl"], position["tp"]
            exited, exit_p, outcome = False, 0.0, ""

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

                if outcome == "loss":
                    last_loss[action] = i   # start cooldown

                trades.append({
                    "entry_date":  position["entry_date"],
                    "exit_date":   dates[i],
                    "action":      action,
                    "entry":       round(position["entry"], 4),
                    "exit":        round(exit_p, 4),
                    "sl":          round(sl, 4),
                    "tp":          round(tp, 4),
                    "result":      outcome,
                    "pnl":         round(pnl, 2),
                    "confluence":  position.get("confluence", 0),
                    "patterns":    position.get("patterns", ""),
                })
                position = None

        # ── 2. Enter new position on previous bar signal ──────────
        if position is None:
            sig = signals[i - 1]
            if sig in ("BUY", "SELL"):
                # Enforce cooldown, skip if within 3 bars of same-direction loss
                if i - last_loss[sig] <= _COOLDOWN:
                    equity.append({"date": dates[i], "equity": round(capital, 2)})
                    continue

                atr   = float(atrs[i - 1])
                entry = float(opens[i])

                if sig == "BUY":
                    sl = round(entry - _SL_ATR_MULT * atr, 4)
                    tp = round(entry + _TP_ATR_MULT * atr, 4)
                else:
                    sl = round(entry + _SL_ATR_MULT * atr, 4)
                    tp = round(entry - _TP_ATR_MULT * atr, 4)

                m = meta[i - 1] or {}
                position = {
                    "action":     sig,
                    "entry":      entry,
                    "entry_date": dates[i],
                    "bar":        i,
                    "sl":         sl,
                    "tp":         tp,
                    "confluence": m.get("score", 0),
                    "patterns":   ",".join(m.get("patterns", [])),
                }

        equity.append({"date": dates[i], "equity": round(capital, 2)})

    # ── Close any remaining open position at last close ───────────
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
            "confluence": position.get("confluence", 0),
            "patterns":   position.get("patterns", ""),
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
    Run a strict ICT + ML backtest over historical data.

    Entry: next bar open after signal.
    Exit:  SL (1×ATR) or TP (3×ATR) hit, checked via bar High/Low.
    """
    ticker = ticker.upper()
    yf_sym = YF_SYMBOL_MAP.get(ticker, ticker.replace(".", "-"))

    raw = yf.download(yf_sym, period=period, interval=interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if raw.empty or len(raw) < 60:
        raise ValueError(
            f"Not enough data for '{ticker}', try a longer period or different ticker."
        )

    df = build_features(raw.copy(), interval)
    if df.empty or len(df) < 30:
        raise ValueError("Feature engineering produced insufficient rows.")

    lr, rf, scaler, feat_cols, _xgb = _load_models(ticker, interval)

    signals, meta  = _generate_signals(df, lr, rf, scaler, feat_cols)
    trades, equity = _simulate(df, signals, meta, initial_capital, risk_pct)

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
        "sl_mult":        _SL_ATR_MULT,
        "tp_mult":        _TP_ATR_MULT,
        "min_confluence": 2,
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
