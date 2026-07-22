#!/usr/bin/env python3
"""
paper_trader.py
Daily paper-trade signal logger, builds a live, auditable track record.

Uses the same triple-fusion signal as backtest.py.
All positions and P&L are persisted to Data/paper_trades.db.

Usage (run once per day, e.g. via cron at market close):
    python paper_trader.py --scan            # scan all tickers for new signals
    python paper_trader.py --close           # mark SL/TP/timeout on open positions
    python paper_trader.py --scan --close    # typical daily run
    python paper_trader.py --report          # print live performance summary

Cron example (weekdays at 4:30 PM ET):
    30 16 * * 1-5 cd /path/to/project && python paper_trader.py --scan --close
"""

import os
import sys
import sqlite3
import argparse
import smtplib
import warnings
warnings.filterwarnings("ignore")

# Windows consoles default to cp1252, which can't print the report's
# box-drawing characters.
if sys.stdout and getattr(sys.stdout, "encoding", "") and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "Data", "paper_trades.db")
APP_DB     = os.path.join(BASE_DIR, "instance", "users.db")
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

MAIL_USER  = os.environ.get("MAIL_USER", "")
MAIL_PASS  = os.environ.get("MAIL_PASSWORD", "")
MAIL_FROM  = os.environ.get("MAIL_FROM", "BullLogic Signals <noreply@bulllogic.ai>")

INITIAL_EQUITY = 10_000.0
RISK_PCT       = 1.0          # risk 1% of equity per trade
SL_ATR_MULT    = 1.5
TP_ATR_MULT    = 2.5
MAX_HOLD_DAYS  = 10
MAX_POSITIONS  = 3
COMMISSION     = 0.001        # 0.1% per side

SCAN_TICKERS = [
    "QQQ", "SPY", "DIA", "AAPL", "MSFT", "TSLA",
    "NVDA", "GOOGL", "AMZN", "META", "ADBE",
]

YF_SYMBOL_MAP = {
    "NDX": "^NDX", "SPX": "^GSPC", "DJI": "^DJI",
    "BTC": "BTC-USD", "ETH": "ETH-USD",
}


# ── Database ──────────────────────────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT    NOT NULL,
            action       TEXT    NOT NULL,
            entry_date   TEXT    NOT NULL,
            entry_price  REAL    NOT NULL,
            sl           REAL    NOT NULL,
            tp           REAL    NOT NULL,
            atr          REAL    NOT NULL,
            shares       REAL    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'open',
            exit_date    TEXT,
            exit_price   REAL,
            exit_reason  TEXT,
            pnl          REAL
        );
        CREATE TABLE IF NOT EXISTS paper_equity (
            date    TEXT PRIMARY KEY,
            equity  REAL NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def _current_equity(conn):
    row = conn.execute("SELECT equity FROM paper_equity ORDER BY date DESC LIMIT 1").fetchone()
    return row["equity"] if row else INITIAL_EQUITY


def _open_positions(conn):
    return conn.execute(
        "SELECT * FROM paper_positions WHERE status='open' ORDER BY entry_date"
    ).fetchall()


# ── Signal (mirrors backtest._ict_signal + _ml_signal + _fuse) ───────────────

def _fetch_ohlcv(ticker: str) -> pd.DataFrame:
    yf_sym = YF_SYMBOL_MAP.get(ticker, ticker)
    # 18mo so the VIX 252-day percentile and 200SMA have real history
    df = yf.download(yf_sym, period="18mo", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Full production feature set, same pipeline the models were trained on.

    Delegates to predictor.build_features (TA + ICT + VIX/sector/earnings aux)
    so live paper trades never diverge from the trained feature space.
    """
    from predictor import build_features, _fetch_aux
    aux = _fetch_aux(ticker, "1d")
    return build_features(df.copy(), "1d", ticker, aux)


def _ict_bias_score(row: pd.Series, closes: np.ndarray) -> dict:
    ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1])
    price = float(row["Close"])
    st_bull = price > ema20 > ema50
    st_bear = price < ema20 < ema50

    above_200 = float(row["Above_200SMA"])
    struct_b  = float(row["Structure_Bullish"])
    bull_conds = int(above_200 >= 0.5) + int(struct_b >= 0.5) + int(st_bull)
    bear_conds = int(above_200 < 0.5)  + int(struct_b < 0.5)  + int(st_bear)

    pd_pos   = float(row["PD_Position"])
    bull_ob  = float(row["Bull_OB_Count"])
    bear_ob  = float(row["Bear_OB_Count"])
    bull_fvg = float(row["Bull_FVG_Count"])
    bear_fvg = float(row["Bear_FVG_Count"])
    swept_l  = float(row["Swept_Low"])
    swept_h  = float(row["Swept_High"])
    disp     = float(row["Displacement"])
    close_v  = float(row["Close"])
    open_v   = float(row.get("Open", close_v))

    buy = sell = 0
    if pd_pos < 0.40:   buy  += 3
    elif pd_pos < 0.50: buy  += 1
    if pd_pos > 0.60:   sell += 3
    elif pd_pos > 0.50: sell += 1
    if bull_ob > 0:  buy  += 2
    if bear_ob > 0:  sell += 2
    if bull_fvg > 0: buy  += 1
    if bear_fvg > 0: sell += 1
    if swept_l > 0:  buy  += 2
    if swept_h > 0:  sell += 2
    if disp > 0 and close_v > open_v: buy  += 1
    if disp > 0 and close_v < open_v: sell += 1

    return {
        "bullish_bias": bull_conds >= 2,
        "bearish_bias": bear_conds >= 2,
        "buy_score":    buy,
        "sell_score":   sell,
        "atr":          float(row["ATR_14"]),
    }


def _ml_vote(ticker: str, df: pd.DataFrame) -> str:
    """Return BUY / SELL / HOLD from LR+RF+XGB ensemble, or HOLD if no model."""
    import joblib
    suffix = ""
    paths = {
        "lr":   os.path.join(MODELS_DIR, f"lr_model_{ticker}{suffix}.pkl"),
        "rf":   os.path.join(MODELS_DIR, f"rf_model_{ticker}{suffix}.pkl"),
        "sc":   os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}{suffix}.pkl"),
        "feat": os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}{suffix}.pkl"),
        "xgb":  os.path.join(MODELS_DIR, f"xgb_model_{ticker}{suffix}.pkl"),
    }
    if not all(os.path.exists(p) for k, p in paths.items() if k != "xgb"):
        return "HOLD"
    try:
        lr   = joblib.load(paths["lr"])
        rf   = joblib.load(paths["rf"])
        sc   = joblib.load(paths["sc"])
        feat = joblib.load(paths["feat"])
        missing = [f for f in feat if f not in df.columns]
        if missing:
            print(f"  [ml] {ticker}: {len(missing)} trained features not built "
                  f"({', '.join(missing[:4])}...), ML vote disabled")
            return "HOLD"
        X    = sc.transform(df[feat].iloc[-1:].values)
        cur  = float(df["Close"].iloc[-1])
        lr_up = float(lr.predict(X)[0]) > cur
        rf_up = float(rf.predict(X)[0]) > 0

        xgb_up = None
        if os.path.exists(paths["xgb"]):
            xgb = joblib.load(paths["xgb"])
            xgb_up = float(xgb.predict_proba(X)[0][1]) > 0.5

        votes_up = sum(v is True  for v in [lr_up, rf_up, xgb_up])
        votes_dn = sum(v is False for v in [lr_up, rf_up, xgb_up])
        if votes_up >= 2:   return "BUY"
        if votes_dn >= 2:   return "SELL"
        return "HOLD"
    except Exception as e:
        print(f"  [ml] {ticker}: model inference failed ({type(e).__name__}: {e}), ML vote disabled")
        return "HOLD"


def _fuse_signal(ict: dict, ml_action: str) -> str:
    for side in ("BUY", "SELL"):
        bias_ok  = ict["bullish_bias"] if side == "BUY" else ict["bearish_bias"]
        ict_raw  = ict["buy_score"]    if side == "BUY" else ict["sell_score"]
        if not bias_ok or ict_raw < 3:
            continue
        ml_pts = 2 if ml_action == side else (0 if ml_action == "HOLD" else -1)
        if ict_raw + ml_pts >= 5:
            return side
    return "HOLD"


# ── Email alerts ─────────────────────────────────────────────────────────────

def _pro_emails():
    """Return list of (email,) for Pro users with alerts enabled."""
    if not os.path.exists(APP_DB):
        return []
    try:
        conn = sqlite3.connect(APP_DB)
        rows = conn.execute(
            "SELECT email FROM user WHERE plan='pro' AND alerts_enabled=1"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _send_signal_email(signals: list):
    """Email Pro subscribers with today's signals."""
    if not MAIL_USER or not MAIL_PASS or not signals:
        return
    recipients = _pro_emails()
    if not recipients:
        return

    today_str = date.today().strftime("%B %d, %Y")
    rows_html = ""
    rows_txt  = ""
    for s in signals:
        color    = "#00C076" if s["action"] == "BUY" else "#FF4D4D"
        rows_html += (
            f"<tr>"
            f"<td style='padding:10px 14px;font-weight:700'>{s['ticker']}</td>"
            f"<td style='padding:10px 14px;color:{color};font-weight:700'>{s['action']}</td>"
            f"<td style='padding:10px 14px'>${s['entry']:.2f}</td>"
            f"<td style='padding:10px 14px;color:#FF4D4D'>${s['sl']:.2f}</td>"
            f"<td style='padding:10px 14px;color:#00C076'>${s['tp']:.2f}</td>"
            f"</tr>"
        )
        rows_txt += f"  {s['action']:<5} {s['ticker']:<6} entry=${s['entry']:.2f}  SL=${s['sl']:.2f}  TP=${s['tp']:.2f}\n"

    html = f"""
<html><body style="font-family:Inter,Arial,sans-serif;background:#0F1217;color:#E2E8F0;margin:0;padding:24px">
<div style="max-width:560px;margin:0 auto">
  <div style="font-size:18pt;font-weight:800;color:#fff;margin-bottom:6px">
    Bull<span style="color:#FF6B35">Logic</span>, Daily Signal Alert
  </div>
  <div style="color:#7A8499;font-size:10pt;margin-bottom:24px">{today_str}</div>
  <div style="background:#1A1F2E;border:1px solid #2A3150;border-radius:10px;overflow:hidden;margin-bottom:20px">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:1px solid #2A3150;color:#7A8499;font-size:9pt">
          <th style="padding:10px 14px;text-align:left">Ticker</th>
          <th style="padding:10px 14px;text-align:left">Signal</th>
          <th style="padding:10px 14px;text-align:left">Entry</th>
          <th style="padding:10px 14px;text-align:left">Stop Loss</th>
          <th style="padding:10px 14px;text-align:left">Take Profit</th>
        </tr>
      </thead>
      <tbody style="font-size:10pt">
        {rows_html}
      </tbody>
    </table>
  </div>
  <div style="font-size:8.5pt;color:#7A8499;line-height:1.6">
    Signals generated by the triple-fusion engine (ICT + XGBoost + LR/RF).
    This is not financial advice. Past performance does not guarantee future results.<br><br>
    Manage your alert preferences at your <a href="https://kali.tail3ceaef.ts.net/profile" style="color:#FF6B35">profile page</a>.
  </div>
</div>
</body></html>"""

    text = f"BullLogic Daily Signal Alert, {today_str}\n\n{rows_txt}\nNot financial advice.\n"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BullLogic: {len(signals)} signal{'s' if len(signals) != 1 else ''}, {today_str}"
    msg["From"]    = MAIL_FROM
    msg["To"]      = MAIL_USER
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    sent = 0
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(MAIL_USER, MAIL_PASS)
            for recipient in recipients:
                msg.replace_header("To", recipient)
                server.sendmail(MAIL_USER, recipient, msg.as_string())
                sent += 1
        print(f"  [alerts] Sent signal email to {sent} Pro subscriber(s).")
    except Exception as e:
        print(f"  [alerts] Email failed: {e}")


# ── Scan ──────────────────────────────────────────────────────────────────────

def scan(conn, tickers):
    equity   = _current_equity(conn)
    open_pos = _open_positions(conn)
    open_syms = {r["ticker"] for r in open_pos}
    today    = date.today().isoformat()
    new_signals = []

    if len(open_pos) >= MAX_POSITIONS:
        print(f"  [scan] Max positions ({MAX_POSITIONS}) open, skipping scan.")
        return

    for ticker in tickers:
        if ticker in open_syms:
            continue
        try:
            df = _fetch_ohlcv(ticker)
            if df.empty or len(df) < 120:
                print(f"  [scan] {ticker}: insufficient data ({len(df)} rows), skipped")
                continue
            df = _features(df, ticker)
            if df.empty:
                print(f"  [scan] {ticker}: feature build produced no rows, skipped")
                continue
            row    = df.iloc[-1]
            closes = df["Close"].values
            ict    = _ict_bias_score(row, closes)
            ml     = _ml_vote(ticker, df)
            action = _fuse_signal(ict, ml)
            if action not in ("BUY", "SELL"):
                continue

            atr      = ict["atr"]
            entry    = float(row["Close"])
            sl       = (entry - atr * SL_ATR_MULT) if action == "BUY" else (entry + atr * SL_ATR_MULT)
            tp       = (entry + atr * TP_ATR_MULT) if action == "BUY" else (entry - atr * TP_ATR_MULT)
            risk_amt = equity * (RISK_PCT / 100)
            shares   = risk_amt / (atr * SL_ATR_MULT)

            conn.execute("""
                INSERT INTO paper_positions
                  (ticker, action, entry_date, entry_price, sl, tp, atr, shares)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticker, action, today, entry, sl, tp, atr, shares))
            conn.commit()
            print(f"  [scan] {action} {ticker}  entry={entry:.2f}  SL={sl:.2f}  TP={tp:.2f}")
            new_signals.append({"ticker": ticker, "action": action,
                                 "entry": entry, "sl": sl, "tp": tp})
        except Exception as e:
            print(f"  [scan] {ticker} error: {e}")

    _snapshot_equity(conn)
    if new_signals:
        _send_signal_email(new_signals)


# ── Close ─────────────────────────────────────────────────────────────────────

def close_positions(conn):
    today    = date.today().isoformat()
    open_pos = _open_positions(conn)
    if not open_pos:
        print("  [close] No open positions.")
        return

    for pos in open_pos:
        ticker = pos["ticker"]
        try:
            df = _fetch_ohlcv(ticker)
            if df.empty:
                continue
            high  = float(df["High"].iloc[-1])
            low   = float(df["Low"].iloc[-1])
            close = float(df["Close"].iloc[-1])

            entry_date  = date.fromisoformat(pos["entry_date"])
            days_held   = (date.today() - entry_date).days
            action      = pos["action"]
            sl, tp      = pos["sl"], pos["tp"]

            reason = exit_price = None
            if action == "BUY":
                if low <= sl:    reason, exit_price = "SL", sl
                elif high >= tp: reason, exit_price = "TP", tp
            else:
                if high >= sl:   reason, exit_price = "SL", sl
                elif low <= tp:  reason, exit_price = "TP", tp
            if reason is None and days_held >= MAX_HOLD_DAYS:
                reason, exit_price = "TIMEOUT", close
            if reason is None:
                continue

            gross = pos["shares"] * ((exit_price - pos["entry_price"]) if action == "BUY"
                                     else (pos["entry_price"] - exit_price))
            comm  = pos["shares"] * (pos["entry_price"] + exit_price) * COMMISSION
            pnl   = gross - comm

            conn.execute("""
                UPDATE paper_positions
                SET status='closed', exit_date=?, exit_price=?, exit_reason=?, pnl=?
                WHERE id=?
            """, (today, exit_price, reason, round(pnl, 4), pos["id"]))
            conn.commit()
            print(f"  [close] {reason} {action} {ticker}  pnl={pnl:+.2f}")
        except Exception as e:
            print(f"  [close] {ticker} error: {e}")

    _snapshot_equity(conn)


def _snapshot_equity(conn):
    today  = date.today().isoformat()
    last_e = _current_equity(conn)
    closed = conn.execute(
        "SELECT SUM(pnl) as s FROM paper_positions WHERE status='closed' AND exit_date=?",
        (today,)
    ).fetchone()
    day_pnl = float(closed["s"] or 0.0)
    new_eq  = last_e + day_pnl
    conn.execute("INSERT OR REPLACE INTO paper_equity (date, equity) VALUES (?,?)",
                 (today, round(new_eq, 4)))
    conn.commit()


# ── Report ────────────────────────────────────────────────────────────────────

def report(conn):
    closed = conn.execute(
        "SELECT * FROM paper_positions WHERE status='closed' ORDER BY exit_date"
    ).fetchall()
    open_p = _open_positions(conn)
    equity = _current_equity(conn)

    print(f"\n{'═'*60}")
    print("  PAPER TRADING LIVE PERFORMANCE")
    print(f"{'═'*60}")
    print(f"  Equity          ${equity:>12,.2f}  (started ${INITIAL_EQUITY:,.2f})")
    total_ret = (equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    print(f"  Total Return    {total_ret:>+11.2f}%")

    if closed:
        n = len(closed)
        wins   = [r for r in closed if (r["pnl"] or 0) > 0]
        losses = [r for r in closed if (r["pnl"] or 0) <= 0]
        gross_w = sum(r["pnl"] for r in wins)
        gross_l = abs(sum(r["pnl"] for r in losses))
        pf      = gross_w / gross_l if gross_l > 0 else float("inf")
        wr      = len(wins) / n * 100

        eq_rows = conn.execute("SELECT date, equity FROM paper_equity ORDER BY date").fetchall()
        if len(eq_rows) > 1:
            eq_s = pd.Series(
                [r["equity"] for r in eq_rows],
                index=pd.to_datetime([r["date"] for r in eq_rows])
            )
            dr    = eq_s.pct_change().dropna()
            sharpe = float(dr.mean() / dr.std() * np.sqrt(252)) if dr.std() > 0 else 0.0
            dside  = dr[dr < 0]
            sortino= float(dr.mean() / dside.std() * np.sqrt(252)) if len(dside) > 1 and dside.std() > 0 else 0.0
            peak   = eq_s.cummax()
            max_dd = float(((eq_s - peak) / peak).min() * 100)
        else:
            sharpe = sortino = max_dd = 0.0

        print(f"  Closed Trades   {n:>12}")
        print(f"  Win Rate        {wr:>11.1f}%")
        print(f"  Profit Factor   {pf:>12.2f}")
        print(f"  Sharpe Ratio    {sharpe:>12.3f}")
        print(f"  Sortino Ratio   {sortino:>12.3f}")
        print(f"  Max Drawdown    {max_dd:>11.2f}%")
        print()
        print(f"  {'Ticker':<8} {'Date':>12} {'Act':4} {'Entry':>8} {'Exit':>8} {'Why':>7} {'PnL $':>9}")
        print("  " + "─" * 56)
        for r in closed[-15:]:
            print(f"  {r['ticker']:<8} {r['exit_date']:>12} {r['action']:4}"
                  f" {r['entry_price']:>8.2f} {r['exit_price']:>8.2f}"
                  f" {r['exit_reason']:>7} {r['pnl']:>+9.2f}")
    else:
        print("  No closed trades yet.")

    if open_p:
        print(f"\n  Open Positions ({len(open_p)}):")
        for r in open_p:
            print(f"    {r['action']} {r['ticker']}  entry={r['entry_price']:.2f}"
                  f"  SL={r['sl']:.2f}  TP={r['tp']:.2f}  since {r['entry_date']}")
    print(f"{'═'*60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan",     action="store_true", help="Scan tickers for new signals")
    ap.add_argument("--close",    action="store_true", help="Close SL/TP/timeout positions")
    ap.add_argument("--report",   action="store_true", help="Print performance summary")
    ap.add_argument("--tickers",  nargs="+", default=SCAN_TICKERS, help="Tickers to scan")
    args = ap.parse_args()

    if not any([args.scan, args.close, args.report]):
        ap.print_help()
        sys.exit(0)

    init_db()
    conn = _get_conn()

    if args.close:
        print("Checking open positions for exits…")
        close_positions(conn)
    if args.scan:
        print(f"Scanning {len(args.tickers)} tickers for signals…")
        scan(conn, args.tickers)
    if args.report or args.scan or args.close:
        report(conn)

    conn.close()


if __name__ == "__main__":
    main()
