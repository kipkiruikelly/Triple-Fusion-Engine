#!/usr/bin/env python3
"""
backtest.py
Walk-forward backtest for the Stock Market Price Prediction System.

Tests the same ML+Technical signal fusion used by the live trading engine
against historical daily OHLCV data. No lookahead bias — signals are generated
using only data available up to and including the signal bar.

Entry  : next trading day's open
Exit   : SL (1.5×ATR) / TP (3.0×ATR) hit intraday, or force-close after 5 bars
Risk   : 1% of equity per trade (ATR position sizing)
Guards : 5% daily loss circuit-breaker, max 3 concurrent positions

Usage:
    python backtest.py                                        # QQQ, 2022–2024
    python backtest.py --ticker QQQ --start 2022-01-01 --end 2024-12-31
    python backtest.py --signal tech --no-plot
    python backtest.py --risk 2.0 --save-trades trades.csv --save-chart chart.png

Signal modes:
    fused  (default) — ML (LR+RF) fused with Technical (RSI/MACD/EMA)
    ml               — ML only
    tech             — Technical only

Author: Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
"""

import os
import sys
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import yfinance as yf
import ta

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

WARMUP_BARS      = 100   # minimum bars of history before first signal
MAX_HOLD         = 5     # force-close after this many bars
SL_ATR_MULT      = 1.5
TP_ATR_MULT      = 3.0
MAX_POSITIONS    = 3
DAILY_LOSS_LIMIT = 0.05  # halt new entries if equity drops 5% intraday


# ── Model loading ─────────────────────────────────────────────────────────────

def _load_models(ticker="QQQ"):
    paths = {
        "lr"    : os.path.join(MODELS_DIR, f"lr_model_{ticker}.pkl"),
        "rf"    : os.path.join(MODELS_DIR, f"rf_model_{ticker}.pkl"),
        "scaler": os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}.pkl"),
        "cols"  : os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}.pkl"),
    }
    missing = [k for k, v in paths.items() if not os.path.exists(v)]
    if missing:
        print(f"ERROR: Model files missing for {ticker}: {missing}")
        print("Run 'python data_pipeline.py && python model_training.py' first.")
        sys.exit(1)
    return (joblib.load(paths["lr"]), joblib.load(paths["rf"]),
            joblib.load(paths["scaler"]), joblib.load(paths["cols"]))


# ── Feature engineering (mirrors predictor.build_features) ───────────────────

def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["SMA_7"]  = ta.trend.sma_indicator(df["Close"], window=7)
    df["SMA_21"] = ta.trend.sma_indicator(df["Close"], window=21)
    df["EMA_12"] = ta.trend.ema_indicator(df["Close"], window=12)
    df["EMA_26"] = ta.trend.ema_indicator(df["Close"], window=26)
    df["RSI_14"] = ta.momentum.rsi(df["Close"], window=14)

    macd_obj = ta.trend.MACD(df["Close"], window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]        = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"]   = macd_obj.macd_diff()

    bb_obj = ta.volatility.BollingerBands(df["Close"], window=20, window_dev=2)
    df["BB_Upper"] = bb_obj.bollinger_hband()
    df["BB_Lower"] = bb_obj.bollinger_lband()
    df["BB_Mid"]   = bb_obj.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = df["Close"].pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = df["Close"].shift(lag)
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    hi = df["High"].values
    lo = df["Low"].values
    cl = df["Close"].values
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    df["ATR_14"] = np.nan
    if len(tr) >= 14:
        df.iloc[14:, df.columns.get_loc("ATR_14")] = (
            pd.Series(tr).rolling(14).mean().iloc[13:].values
        )

    df.dropna(inplace=True)
    return df


# ── Indicator helpers (mirrors mt5_trading helpers) ───────────────────────────

def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    d     = np.diff(closes[-(period + 1):])
    gains = np.where(d > 0, d, 0.0)
    loss  = np.where(d < 0, -d, 0.0)
    ag, al = gains.mean(), loss.mean()
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def _macd_hist(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig:
        return 0.0, 0.0
    s = pd.Series(closes)
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    h = m - m.ewm(span=sig, adjust=False).mean()
    prev = float(h.iloc[-2]) if len(h) >= 2 else 0.0
    return float(h.iloc[-1]), prev


def _atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return float(closes[-1]) * 0.01
    tr = np.maximum(highs[1:] - lows[1:],
         np.maximum(np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])))
    return float(tr[-period:].mean())


# ── Signal generators ─────────────────────────────────────────────────────────

def _tech_signal(lookback: pd.DataFrame) -> dict:
    closes = lookback["Close"].values.astype(float)
    highs  = lookback["High"].values.astype(float)
    lows   = lookback["Low"].values.astype(float)

    rsi      = _rsi(closes)
    prev_rsi = _rsi(closes[:-1])
    hist, ph = _macd_hist(closes)
    atr_val  = _atr(highs, lows, closes)
    price    = float(closes[-1])
    ema20    = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])

    buy = sell = 0
    if prev_rsi < 30 and rsi >= 30:    buy  += 1
    elif rsi < 35:                      buy  += 1
    if prev_rsi > 70 and rsi <= 70:    sell += 1
    elif rsi > 65:                     sell += 1
    if ph < 0 and hist >= 0:           buy  += 2
    elif hist > 0 and hist > ph:       buy  += 1
    if ph > 0 and hist <= 0:           sell += 2
    elif hist < 0 and hist < ph:       sell += 1
    if price > ema20:                   buy  += 1
    else:                               sell += 1

    if buy >= 3 and buy > sell:    action, score = "BUY",  buy
    elif sell >= 3 and sell > buy: action, score = "SELL", sell
    else:                          action, score = "HOLD", 0
    return {"action": action, "score": score, "atr": atr_val}


def _ml_signal(lookback: pd.DataFrame, lr, rf, scaler, feat_cols) -> dict:
    close = float(lookback["Close"].iloc[-1])
    atr   = float(lookback["ATR_14"].iloc[-1]) if "ATR_14" in lookback.columns else close * 0.01
    X       = scaler.transform(lookback[feat_cols].iloc[-1:].values)
    lr_pred = float(lr.predict(X)[0])
    rf_ret  = float(rf.predict(X)[0])

    if lr_pred > close and rf_ret > 0:   action = "BUY"
    elif lr_pred < close and rf_ret < 0: action = "SELL"
    else:                                 action = "HOLD"
    return {"action": action, "atr": atr}


def _fuse(ml: dict, tech: dict) -> dict:
    ma, ta_ = ml["action"], tech["action"]
    atr     = ml.get("atr", tech.get("atr", 0))
    if ma == "HOLD":           return {"action": "HOLD", "score": 0, "atr": atr}
    if ma == ta_:              return {"action": ma, "score": tech["score"] + 2, "atr": atr}
    if ta_ == "HOLD":          return {"action": ma, "score": 2, "atr": atr}
    return {"action": "HOLD", "score": 0, "atr": atr}


# ── Position ──────────────────────────────────────────────────────────────────

class _Pos:
    __slots__ = ("action", "entry", "sl", "tp", "shares", "entry_bar")

    def __init__(self, action, entry, sl, tp, shares, entry_bar):
        self.action    = action
        self.entry     = entry
        self.sl        = sl
        self.tp        = tp
        self.shares    = shares
        self.entry_bar = entry_bar

    def try_close(self, high, low, close, bar):
        """Returns (exit_price, reason) if the position should close, else None."""
        if self.action == "BUY":
            sl_hit = low  <= self.sl
            tp_hit = high >= self.tp
        else:
            sl_hit = high >= self.sl
            tp_hit = low  <= self.tp

        if sl_hit and tp_hit:  # both hit same bar — assume SL (conservative)
            return self.sl, "SL"
        if sl_hit:
            return self.sl, "SL"
        if tp_hit:
            return self.tp, "TP"
        if bar - self.entry_bar >= MAX_HOLD:
            return close, "TIMEOUT"
        return None


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_backtest(ticker, start, end, initial, risk_pct, mode, commission, verbose=True):
    lr = rf = scaler = feat_cols = None
    if mode in ("ml", "fused"):
        if verbose:
            print(f"Loading {ticker} models…")
        lr, rf, scaler, feat_cols = _load_models(ticker)

    if verbose:
        print(f"Downloading {ticker} data…")
    buf_start = (pd.Timestamp(start) - pd.DateOffset(months=8)).strftime("%Y-%m-%d")
    raw = yf.download(ticker, start=buf_start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty or len(raw) < WARMUP_BARS + 10:
        print("ERROR: Not enough data. Try an earlier start date.")
        sys.exit(1)

    df   = _build_features(raw)
    test = df[df.index >= start].copy()
    if test.empty:
        print(f"ERROR: No data in {start} – {end}")
        sys.exit(1)

    if verbose:
        print(f"Test window : {test.index[0].date()} → {test.index[-1].date()} "
              f"({len(test)} trading days)\n")

    equity    = initial
    peak_eq   = initial
    max_dd    = 0.0
    open_pos  = []
    closed    = []
    equity_ts = []

    for i in range(len(test)):
        row       = test.iloc[i]
        date_today = test.index[i]
        day_start  = equity

        high  = float(row["High"])
        low   = float(row["Low"])
        close = float(row["Close"])

        # ── 1. Check exits for open positions ─────────────────────────────────
        still_open = []
        for pos in open_pos:
            result = pos.try_close(high, low, close, i)
            if result is not None:
                exit_p, reason = result
                gross  = pos.shares * ((exit_p - pos.entry) if pos.action == "BUY"
                                       else (pos.entry - exit_p))
                comm   = pos.shares * (pos.entry + exit_p) * commission
                pnl    = gross - comm
                equity += pnl
                entry_date = test.index[pos.entry_bar].date() if pos.entry_bar < len(test) else date_today.date()
                closed.append({
                    "entry_date"  : entry_date,
                    "exit_date"   : date_today.date(),
                    "action"      : pos.action,
                    "entry_price" : round(pos.entry, 4),
                    "exit_price"  : round(exit_p, 4),
                    "reason"      : reason,
                    "pnl$"        : round(pnl, 2),
                    "equity_after": round(equity, 2),
                })
            else:
                still_open.append(pos)
        open_pos = still_open

        # ── 2. Record equity and drawdown ──────────────────────────────────────
        equity_ts.append(round(equity, 2))
        peak_eq = max(peak_eq, equity)
        dd      = (peak_eq - equity) / peak_eq if peak_eq > 0 else 0.0
        max_dd  = max(max_dd, dd)

        # ── 3. Guards: daily loss limit, max positions, last bar ───────────────
        daily_loss = (day_start - equity) / day_start if day_start > 0 else 0
        if daily_loss >= DAILY_LOSS_LIMIT or len(open_pos) >= MAX_POSITIONS or i + 1 >= len(test):
            continue

        # ── 4. Generate signal (using data up to today only) ──────────────────
        full_i   = df.index.get_loc(date_today)
        lookback = df.iloc[max(0, full_i - 199): full_i + 1]
        if len(lookback) < WARMUP_BARS:
            continue

        if mode == "tech":
            sig = _tech_signal(lookback)
        elif mode == "ml":
            sig = _ml_signal(lookback, lr, rf, scaler, feat_cols)
        else:
            ml_  = _ml_signal(lookback, lr, rf, scaler, feat_cols)
            tec_ = _tech_signal(lookback)
            sig  = _fuse(ml_, tec_)

        if sig["action"] not in ("BUY", "SELL"):
            continue

        # ── 5. Size and open position (entry at next bar's open) ───────────────
        action  = sig["action"]
        atr_val = sig.get("atr", close * 0.01)
        sl_dist = atr_val * SL_ATR_MULT
        tp_dist = atr_val * TP_ATR_MULT
        if sl_dist <= 0:
            continue

        entry = float(test.iloc[i + 1]["Open"])
        sl    = (entry - sl_dist) if action == "BUY" else (entry + sl_dist)
        tp    = (entry + tp_dist) if action == "BUY" else (entry - tp_dist)

        risk_amt = equity * (risk_pct / 100.0)
        shares   = risk_amt / sl_dist
        shares   = min(shares, equity / entry) if entry > 0 else shares  # cap at full equity

        open_pos.append(_Pos(action, entry, sl, tp, shares, i + 1))

    # ── Force-close any remaining positions at end of test period ─────────────
    if open_pos:
        last_close = float(test.iloc[-1]["Close"])
        last_date  = test.index[-1].date()
        for pos in open_pos:
            gross  = pos.shares * ((last_close - pos.entry) if pos.action == "BUY"
                                   else (pos.entry - last_close))
            comm   = pos.shares * (pos.entry + last_close) * commission
            pnl    = gross - comm
            equity += pnl
            entry_date = test.index[pos.entry_bar].date() if pos.entry_bar < len(test) else last_date
            closed.append({
                "entry_date"  : entry_date,
                "exit_date"   : last_date,
                "action"      : pos.action,
                "entry_price" : round(pos.entry, 4),
                "exit_price"  : round(last_close, 4),
                "reason"      : "END",
                "pnl$"        : round(pnl, 2),
                "equity_after": round(equity, 2),
            })

    # ── Metrics ───────────────────────────────────────────────────────────────
    eq_series  = pd.Series(equity_ts, index=test.index[:len(equity_ts)])
    n          = len(closed)
    wins       = [t for t in closed if t["pnl$"] > 0]
    losses     = [t for t in closed if t["pnl$"] <= 0]
    gross_win  = sum(t["pnl$"] for t in wins)
    gross_loss = abs(sum(t["pnl$"] for t in losses))
    pf         = gross_win / gross_loss if gross_loss > 0 else float("inf")

    daily_rets = eq_series.pct_change().dropna()
    sharpe     = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)
                  if daily_rets.std() > 0 else 0.0)

    bh_start = float(test.iloc[0]["Close"])
    bh_end   = float(test.iloc[-1]["Close"])
    bh_ret   = (bh_end - bh_start) / bh_start * 100

    metrics = {
        "ticker"       : ticker.upper(),
        "mode"         : mode,
        "start"        : test.index[0].date(),
        "end"          : test.index[-1].date(),
        "days"         : len(test),
        "initial"      : round(initial, 2),
        "final"        : round(equity, 2),
        "total_ret"    : round((equity - initial) / initial * 100, 2),
        "bh_ret"       : round(bh_ret, 2),
        "sharpe"       : round(sharpe, 3),
        "max_dd"       : round(max_dd * 100, 2),
        "n_trades"     : n,
        "win_rate"     : round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_win$"     : round(np.mean([t["pnl$"] for t in wins]),   2) if wins   else 0.0,
        "avg_loss$"    : round(np.mean([t["pnl$"] for t in losses]), 2) if losses else 0.0,
        "profit_factor": round(pf, 2),
        "sl_exits"     : sum(1 for t in closed if t["reason"] == "SL"),
        "tp_exits"     : sum(1 for t in closed if t["reason"] == "TP"),
        "timeout_exits": sum(1 for t in closed if t["reason"] in ("TIMEOUT", "END")),
    }
    return closed, eq_series, metrics


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(m, trades):
    sep = "═" * 62
    print(f"\n{sep}")
    print(f"  BACKTEST  ·  {m['ticker']}  ·  {m['mode'].upper()} signals")
    print(sep)
    print(f"  Period          {m['start']}  →  {m['end']}  ({m['days']} days)")
    print(f"  Initial         ${m['initial']:>12,.2f}")
    print(f"  Final Equity    ${m['final']:>12,.2f}")
    print(f"  Strategy Return {m['total_ret']:>+11.2f}%")
    print(f"  Buy & Hold      {m['bh_ret']:>+11.2f}%")
    print(f"  Alpha           {m['total_ret'] - m['bh_ret']:>+11.2f}%")
    print(f"  Sharpe Ratio    {m['sharpe']:>12.3f}")
    print(f"  Max Drawdown    {m['max_dd']:>11.2f}%")
    print()
    print(f"  Trades          {m['n_trades']:>12}")
    print(f"  Win Rate        {m['win_rate']:>11.1f}%")
    print(f"  Avg Win         ${m['avg_win$']:>11,.2f}")
    print(f"  Avg Loss        ${m['avg_loss$']:>11,.2f}")
    print(f"  Profit Factor   {m['profit_factor']:>12.2f}")
    print()
    print(f"  SL exits        {m['sl_exits']:>12}")
    print(f"  TP exits        {m['tp_exits']:>12}")
    print(f"  Timeout exits   {m['timeout_exits']:>12}")
    print(sep)

    if trades:
        last = trades[-15:]
        print(f"\nMost recent {len(last)} trades:")
        print(f"  {'Exit Date':>12}  {'Act':4}  {'Entry':>8}  {'Exit':>8}  {'Why':>7}  {'P&L $':>9}")
        print("  " + "─" * 56)
        for t in last:
            print(f"  {str(t['exit_date']):>12}  {t['action']:4}  "
                  f"{t['entry_price']:>8.3f}  {t['exit_price']:>8.3f}  "
                  f"{t['reason']:>7}  {t['pnl$']:>+9.2f}")
    print()


# ── Chart ─────────────────────────────────────────────────────────────────────

def plot_results(ticker, eq_series, raw_df, trades, metrics, show=True, save_path=None):
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("matplotlib not installed — pip install matplotlib")
        return

    fig, axes = plt.subplots(3, 1, figsize=(14, 10))
    fig.suptitle(
        f"{ticker}  ·  {metrics['mode'].upper()} signals  ·  "
        f"{metrics['start']} → {metrics['end']}",
        fontsize=13, fontweight="bold"
    )

    # Panel 1: equity curve vs buy-and-hold
    ax1 = axes[0]
    bh  = raw_df["Close"].reindex(eq_series.index).ffill()
    bh_norm = bh / bh.iloc[0] * eq_series.iloc[0]
    ax1.plot(eq_series.index, eq_series, label="Strategy",    color="steelblue",  lw=1.5)
    ax1.plot(bh_norm.index,   bh_norm,   label="Buy & Hold",  color="darkorange", lw=1.5, ls="--")
    ax1.set_ylabel("Portfolio ($)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.25)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # Panel 2: price with BUY ▲ / SELL ▼ entry markers
    ax2 = axes[1]
    price = raw_df["Close"].reindex(eq_series.index).ffill()
    ax2.plot(price.index, price, color="gray", lw=1)
    for t in trades:
        d = pd.Timestamp(t["entry_date"])
        p = t["entry_price"]
        if d in price.index or d in eq_series.index:
            color  = "green" if t["action"] == "BUY" else "red"
            marker = "^"     if t["action"] == "BUY" else "v"
            ax2.scatter(d, p, color=color, marker=marker, s=45, zorder=5, alpha=0.8)
    ax2.set_ylabel("Price ($)")
    ax2.grid(True, alpha=0.25)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # Panel 3: rolling drawdown
    ax3 = axes[2]
    roll_peak = eq_series.cummax()
    drawdown  = (eq_series - roll_peak) / roll_peak * 100
    ax3.fill_between(drawdown.index, drawdown, 0, color="crimson", alpha=0.35)
    ax3.plot(drawdown.index, drawdown, color="crimson", lw=0.8)
    ax3.set_ylabel("Drawdown (%)")
    ax3.grid(True, alpha=0.25)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Chart saved → {save_path}")
    if show:
        plt.show()
    plt.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--ticker",      default="QQQ",        metavar="SYM",
                   help="Ticker symbol (default: QQQ)")
    p.add_argument("--start",       default="2022-01-01", metavar="DATE",
                   help="Test start date (default: 2022-01-01)")
    p.add_argument("--end",         default="2024-12-31", metavar="DATE",
                   help="Test end date   (default: 2024-12-31)")
    p.add_argument("--initial",     default=10_000.0, type=float,
                   help="Starting balance (default: 10000)")
    p.add_argument("--risk",        default=1.0,      type=float,
                   help="Risk %% per trade (default: 1.0)")
    p.add_argument("--signal",      default="fused",  choices=["fused", "ml", "tech"],
                   help="Signal mode (default: fused)")
    p.add_argument("--commission",  default=0.001,    type=float,
                   help="Commission per side as fraction (default: 0.001 = 0.1%%)")
    p.add_argument("--no-plot",     action="store_true",
                   help="Skip the chart")
    p.add_argument("--save-trades", metavar="CSV",
                   help="Save trade log to a CSV file")
    p.add_argument("--save-chart",  metavar="PNG",
                   help="Save chart to a PNG file")
    args = p.parse_args()

    trades, eq_series, metrics = run_backtest(
        ticker     = args.ticker.upper(),
        start      = args.start,
        end        = args.end,
        initial    = args.initial,
        risk_pct   = args.risk,
        mode       = args.signal,
        commission = args.commission,
        verbose    = True,
    )

    print_report(metrics, trades)

    if args.save_trades and trades:
        pd.DataFrame(trades).to_csv(args.save_trades, index=False)
        print(f"Trade log saved → {args.save_trades}")

    if not args.no_plot or args.save_chart:
        buf = (pd.Timestamp(args.start) - pd.DateOffset(months=8)).strftime("%Y-%m-%d")
        raw = yf.download(args.ticker.upper(), start=buf, end=args.end,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        plot_results(
            args.ticker.upper(), eq_series, raw, trades, metrics,
            show      = not args.no_plot,
            save_path = args.save_chart,
        )


if __name__ == "__main__":
    main()
