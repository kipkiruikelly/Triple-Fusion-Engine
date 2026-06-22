"""
mt5_trading.py
MT5 algorithmic trading engine for MarketPredict.

Two modes:
  - LIVE: Connects to MetaTrader 5 via Wine/mt5linux rpyc bridge.
           Requires Wine with Python + MetaTrader5 package (wine-devel >= 10.12).
  - PAPER: Simulates trades against live yfinance data. No MT5 needed.
           Paper mode is the default when MT5 is unavailable.

Strategy (both modes):
  - RSI(14) reversal from extreme zones
  - MACD(12,26,9) histogram momentum flip
  - EMA(20) trend filter
  - ATR(14) dynamic SL/TP (SL=1.5×ATR, TP=3×ATR, 2:1 R:R)
  - 1% account risk per trade (configurable)
  - Max 3 open positions, 5% daily loss circuit-breaker
"""

import time
import threading
import logging
from collections import deque
from datetime import datetime, date

import numpy as np
import pandas as pd

# Try live MT5 bridge; fall back to paper mode
try:
    from mt5linux import MetaTrader5 as _MT5
    MT5_BACKEND = "mt5linux"
except ImportError:
    try:
        import MetaTrader5 as _MT5
        MT5_BACKEND = "native"
    except ImportError:
        _MT5 = None
        MT5_BACKEND = "paper"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("mt5_trading")

MAX_LOG_ENTRIES  = 200
MAX_POSITIONS    = 3
DAILY_LOSS_LIMIT = 0.05
PAPER_BALANCE    = 10_000.0   # virtual account balance


# ── Pure-Python indicator helpers ────────────────────────────────────────────

def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def _calc_macd(closes: np.ndarray, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    s = pd.Series(closes)
    ema_fast    = s.ewm(span=fast,   adjust=False).mean()
    ema_slow    = s.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(hist.iloc[-1])


def _calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return float(closes[-1]) * 0.001
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    )
    return float(tr[-period:].mean())


def _signal_from_arrays(closes, highs, lows):
    """Core signal logic shared between live and paper modes."""
    rsi             = _calc_rsi(closes)
    prev_rsi        = _calc_rsi(closes[:-1])
    macd, sig, hist = _calc_macd(closes)
    _, _, prev_hist = _calc_macd(closes[:-1])
    atr             = _calc_atr(highs, lows, closes)
    price           = float(closes[-1])

    buy_score = sell_score = 0

    if prev_rsi < 30 and rsi >= 30:
        buy_score += 1
    elif rsi < 35:
        buy_score += 1

    if prev_rsi > 70 and rsi <= 70:
        sell_score += 1
    elif rsi > 65:
        sell_score += 1

    if prev_hist < 0 and hist >= 0:
        buy_score += 2
    elif hist > 0 and hist > prev_hist:
        buy_score += 1

    if prev_hist > 0 and hist <= 0:
        sell_score += 2
    elif hist < 0 and hist < prev_hist:
        sell_score += 1

    ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
    if price > ema20:
        buy_score += 1
    else:
        sell_score += 1

    action = "HOLD"
    score  = 0
    if buy_score >= 3 and buy_score > sell_score:
        action, score = "BUY", buy_score
    elif sell_score >= 3 and sell_score > buy_score:
        action, score = "SELL", sell_score

    return {
        "action" : action,
        "score"  : score,
        "reason" : f"RSI={rsi:.1f} MACD_hist={hist:.5f} ATR={atr:.5f}",
        "rsi"    : round(rsi, 2),
        "macd"   : round(hist, 6),
        "atr"    : round(atr, 6),
        "price"  : round(price, 5),
    }


# ── Paper trading engine ─────────────────────────────────────────────────────

class PaperAccount:
    """Virtual account for paper trading."""

    def __init__(self, balance: float = PAPER_BALANCE):
        self.balance      = balance
        self.equity       = balance
        self.positions    = []   # list of dicts
        self.ticket_seq   = 1000
        self.day          = date.today()

    def open_position(self, symbol, action, lot, price, sl, tp):
        ticket = self.ticket_seq
        self.ticket_seq += 1
        self.positions.append({
            "ticket": ticket,
            "symbol": symbol,
            "action": action,
            "lot"   : lot,
            "price" : price,
            "sl"    : sl,
            "tp"    : tp,
            "pnl"   : 0.0,
        })
        return ticket

    def update_equity(self, current_prices: dict):
        """Recalculate equity based on current prices; auto-close if SL/TP hit."""
        closed = []
        pnl_total = 0.0
        for pos in self.positions:
            sym   = pos["symbol"]
            cprice = current_prices.get(sym, pos["price"])
            if pos["action"] == "BUY":
                pnl = (cprice - pos["price"]) * pos["lot"] * 1000
                if cprice <= pos["sl"] or cprice >= pos["tp"]:
                    closed.append((pos, pnl))
                    continue
            else:
                pnl = (pos["price"] - cprice) * pos["lot"] * 1000
                if cprice >= pos["sl"] or cprice <= pos["tp"]:
                    closed.append((pos, pnl))
                    continue
            pos["pnl"] = round(pnl, 2)
            pnl_total += pnl

        for pos, pnl in closed:
            self.positions.remove(pos)
            self.balance += pnl

        self.equity = self.balance + pnl_total
        return [p["ticket"] for p, _ in closed]

    def close_all(self, symbol):
        remaining = [p for p in self.positions if p["symbol"] != symbol]
        closed    = len(self.positions) - len(remaining)
        self.positions = remaining
        return closed

    def info(self):
        return {
            "login"      : 0,
            "name"       : "Paper Account",
            "server"     : "Paper Trading",
            "currency"   : "USD",
            "balance"    : round(self.balance, 2),
            "equity"     : round(self.equity, 2),
            "margin"     : 0.0,
            "free_margin": round(self.equity, 2),
            "leverage"   : 100,
        }


# ── Main trader class ────────────────────────────────────────────────────────

class MT5Trader:

    def __init__(self):
        self.mt5           = _MT5
        self.backend       = MT5_BACKEND
        self.connected     = False
        self.trading       = False
        self._thread       = None
        self._lock         = threading.Lock()
        self.trade_log     = deque(maxlen=MAX_LOG_ENTRIES)
        self.account       = {}
        self.status_msg    = "Disconnected"
        self.equity_open   = None
        self.last_signal   = {}
        self._mt5_instance = None
        self._paper        = None   # PaperAccount, set when in paper mode

    @property
    def is_paper(self):
        return self._paper is not None

    # ── Connection ───────────────────────────────────────────────────────────

    def connect(self, account_num: int, password: str, server: str,
                host: str = "localhost", port: int = 18812) -> dict:

        # Paper mode: when account_num == 0 or no MT5 available
        if account_num == 0 or self.backend == "paper":
            self._paper      = PaperAccount()
            self.connected   = True
            self.account     = self._paper.info()
            self.equity_open = self._paper.balance
            self.status_msg  = "Connected (Paper Trading)"
            self._log("INFO", "Paper trading mode activated — $10,000 virtual balance")
            return {"ok": True, "account": self.account, "mode": "paper"}

        # Live MT5 bridge
        if self.mt5 is None:
            return {"ok": False, "error": (
                "MT5 bridge unavailable. Either use paper mode (account=0) or "
                "install wine-devel >= 10.12 to fix the ucrtbase.dll.crealf issue."
            )}

        try:
            mt5 = self.mt5(host=host, port=port) if self.backend == "mt5linux" else self.mt5

            if not mt5.initialize():
                return {"ok": False, "error": f"MT5 initialize() failed: {mt5.last_error()}"}

            if not mt5.login(account_num, password=password, server=server):
                mt5.shutdown()
                return {"ok": False, "error": f"Login failed: {mt5.last_error()}"}

            info = mt5.account_info()
            if info is None:
                mt5.shutdown()
                return {"ok": False, "error": "Could not fetch account info"}

            self._mt5_instance = mt5
            self._paper        = None
            self.connected     = True
            self.account       = {
                "login"      : info.login,
                "name"       : info.name,
                "server"     : info.server,
                "currency"   : info.currency,
                "balance"    : round(info.balance, 2),
                "equity"     : round(info.equity, 2),
                "margin"     : round(info.margin, 2),
                "free_margin": round(info.margin_free, 2),
                "leverage"   : info.leverage,
            }
            self.equity_open = info.equity
            self.status_msg  = f"Connected (Live) — {info.name} @ {info.server}"
            self._log("INFO", f"Connected to {info.server} as {info.name}")
            return {"ok": True, "account": self.account, "mode": "live"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self.stop_trading()
        if self.connected and self._mt5_instance:
            try:
                self._mt5_instance.shutdown()
            except Exception:
                pass
        self.connected     = False
        self._paper        = None
        self._mt5_instance = None
        self.status_msg    = "Disconnected"
        self._log("INFO", "Disconnected")

    def refresh_account(self):
        if not self.connected:
            return
        if self.is_paper:
            self.account = self._paper.info()
            return
        try:
            info = self._mt5_instance.account_info()
            if info:
                self.account.update({
                    "balance"     : round(info.balance, 2),
                    "equity"      : round(info.equity, 2),
                    "margin"      : round(info.margin, 2),
                    "free_margin" : round(info.margin_free, 2),
                })
        except Exception:
            pass

    # ── Signal generation ────────────────────────────────────────────────────

    def _get_bars_paper(self, symbol: str, n: int = 120) -> pd.DataFrame | None:
        """Fetch OHLCV bars from yfinance for paper mode."""
        try:
            import yfinance as yf
            yf_sym = symbol.replace(".", "-")
            df = yf.download(yf_sym, period="60d", interval="5m",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty or len(df) < 60:
                df = yf.download(yf_sym, period="1y", auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
            return df.tail(n) if not df.empty else None
        except Exception as e:
            log.warning(f"yfinance error: {e}")
            return None

    def generate_signal(self, symbol: str, timeframe=None) -> dict:
        if self.is_paper:
            df = self._get_bars_paper(symbol)
            if df is None or len(df) < 60:
                return {"action": "HOLD", "reason": "Insufficient data", "score": 0,
                        "rsi": 50, "macd": 0, "atr": 0, "price": 0}
            closes = df["Close"].values.astype(float)
            highs  = df["High"].values.astype(float)
            lows   = df["Low"].values.astype(float)
        else:
            df = self.get_bars_live(symbol, timeframe, n=120)
            if df is None or len(df) < 60:
                return {"action": "HOLD", "reason": "Insufficient data", "score": 0,
                        "rsi": 50, "macd": 0, "atr": 0, "price": 0}
            closes = df["close"].values.astype(float)
            highs  = df["high"].values.astype(float)
            lows   = df["low"].values.astype(float)

        signal = _signal_from_arrays(closes, highs, lows)
        self.last_signal = signal
        return signal

    def get_bars_live(self, symbol: str, timeframe, n: int = 100) -> pd.DataFrame | None:
        try:
            rates = self._mt5_instance.copy_rates_from_pos(symbol, timeframe, 0, n)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df
        except Exception as e:
            log.warning(f"get_bars_live error: {e}")
            return None

    # ── Order execution ──────────────────────────────────────────────────────

    def _count_positions(self, symbol: str) -> int:
        if self.is_paper:
            return sum(1 for p in self._paper.positions if p["symbol"] == symbol)
        try:
            positions = self._mt5_instance.positions_get(symbol=symbol)
            return len(positions) if positions else 0
        except Exception:
            return 0

    def _calc_lot(self, risk_pct: float, sl_points: float, price: float) -> float:
        balance  = self.account.get("balance", PAPER_BALANCE)
        risk_amt = balance * (risk_pct / 100.0)
        if sl_points <= 0 or price <= 0:
            return 0.01
        sl_pct = sl_points / price
        if sl_pct <= 0:
            return 0.01
        lot = risk_amt / (sl_pct * price * 1000)
        return round(max(0.01, min(lot, 10.0)), 2)

    def place_order(self, symbol: str, action: str, risk_pct: float, atr: float) -> dict:
        sl_dist = atr * 1.5
        tp_dist = atr * 3.0

        if self.is_paper:
            df = self._get_bars_paper(symbol, n=5)
            price = float(df["Close"].iloc[-1]) if df is not None else 0
            if price <= 0:
                return {"ok": False, "error": "Cannot get current price"}
            if action == "BUY":
                sl = round(price - sl_dist, 5)
                tp = round(price + tp_dist, 5)
            else:
                sl = round(price + sl_dist, 5)
                tp = round(price - tp_dist, 5)
            lot    = self._calc_lot(risk_pct, sl_dist, price)
            ticket = self._paper.open_position(symbol, action, lot, price, sl, tp)
            trade  = {
                "time"  : datetime.now().strftime("%H:%M:%S"),
                "action": action,
                "symbol": symbol,
                "lot"   : lot,
                "price" : price,
                "sl"    : sl,
                "tp"    : tp,
                "ticket": ticket,
            }
            self._log("PAPER TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}")
            return {"ok": True, "trade": trade}

        # Live MT5 order
        mt5  = self._mt5_instance
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"ok": False, "error": "No tick data"}

        if action == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = round(price - sl_dist, 5)
            tp         = round(price + tp_dist, 5)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = round(price + sl_dist, 5)
            tp         = round(price - tp_dist, 5)

        lot = self._calc_lot(risk_pct, sl_dist, price)
        request = {
            "action"       : mt5.TRADE_ACTION_DEAL,
            "symbol"       : symbol,
            "volume"       : lot,
            "type"         : order_type,
            "price"        : price,
            "sl"           : sl,
            "tp"           : tp,
            "deviation"    : 20,
            "magic"        : 20250622,
            "comment"      : "MarketPredict algo",
            "type_time"    : mt5.ORDER_TIME_GTC,
            "type_filling" : mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "None"
            return {"ok": False, "error": f"Order rejected: {err}"}

        trade = {
            "time"  : datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "symbol": symbol,
            "lot"   : lot,
            "price" : price,
            "sl"    : sl,
            "tp"    : tp,
            "ticket": result.order,
        }
        self._log("TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}")
        return {"ok": True, "trade": trade}

    def close_all(self, symbol: str) -> int:
        if self.is_paper:
            return self._paper.close_all(symbol)
        mt5       = self._mt5_instance
        positions = mt5.positions_get(symbol=symbol) or []
        closed    = 0
        for pos in positions:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                continue
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price      = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            req = {
                "action"       : mt5.TRADE_ACTION_DEAL,
                "symbol"       : symbol,
                "volume"       : pos.volume,
                "type"         : close_type,
                "position"     : pos.ticket,
                "price"        : price,
                "deviation"    : 20,
                "magic"        : 20250622,
                "comment"      : "MarketPredict close",
                "type_time"    : mt5.ORDER_TIME_GTC,
                "type_filling" : mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
                self._log("CLOSE", f"Closed ticket {pos.ticket}")
        return closed

    # ── Trading loop ─────────────────────────────────────────────────────────

    def _trading_loop(self, symbol: str, timeframe, risk_pct: float, interval: int):
        tf_map = {}
        if not self.is_paper and self._mt5_instance:
            mt5 = self._mt5_instance
            tf_map = {
                "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            }
        tf = tf_map.get(timeframe, None)

        mode = "Paper" if self.is_paper else "Live"
        self._log("INFO", f"{mode} trading started — {symbol} {timeframe} risk={risk_pct}% interval={interval}s")

        while self.trading:
            try:
                self.refresh_account()

                # Daily loss guard
                eq = self.account.get("equity", 0)
                if self.equity_open and eq and self.equity_open > 0:
                    drawdown = (self.equity_open - eq) / self.equity_open
                    if drawdown >= DAILY_LOSS_LIMIT:
                        self._log("WARN", f"Daily loss limit hit ({drawdown*100:.1f}%). Trading halted.")
                        self.trading    = False
                        self.status_msg = f"Halted — {DAILY_LOSS_LIMIT*100:.0f}% daily loss limit"
                        break

                # Max positions guard
                if self._count_positions(symbol) >= MAX_POSITIONS:
                    self._log("INFO", f"Max positions ({MAX_POSITIONS}) held, waiting")
                    time.sleep(interval)
                    continue

                signal = self.generate_signal(symbol, tf)
                self._log("SIGNAL", f"{signal['action']} score={signal['score']} {signal['reason']}")

                if signal["action"] in ("BUY", "SELL"):
                    result = self.place_order(symbol, signal["action"], risk_pct, signal["atr"])
                    if not result["ok"]:
                        self._log("ERROR", result["error"])

                # Paper: update equity based on current prices
                if self.is_paper and self._paper.positions:
                    df = self._get_bars_paper(symbol, n=3)
                    if df is not None:
                        cur = float(df["Close"].iloc[-1])
                        closed_tickets = self._paper.update_equity({symbol: cur})
                        for t in closed_tickets:
                            self._log("PAPER CLOSE", f"Ticket {t} auto-closed (SL/TP hit)")

            except Exception as e:
                self._log("ERROR", f"Loop error: {e}")

            time.sleep(interval)

        self._log("INFO", "Trading loop stopped")

    def start_trading(self, symbol: str, timeframe: str = "M5",
                      risk_pct: float = 1.0, interval: int = 60) -> dict:
        if not self.connected:
            return {"ok": False, "error": "Not connected. Use account=0 for paper mode."}
        if self.trading:
            return {"ok": False, "error": "Already trading"}
        self.trading    = True
        mode = "Paper" if self.is_paper else "Live"
        self.status_msg = f"{mode} Trading — {symbol} {timeframe}"
        self._thread = threading.Thread(
            target=self._trading_loop,
            args=(symbol, timeframe, risk_pct, interval),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "mode": mode.lower()}

    def stop_trading(self) -> dict:
        if not self.trading:
            return {"ok": False, "error": "Not currently trading"}
        self.trading = False
        mode = "Paper" if self.is_paper else "Live"
        self.status_msg = f"{mode} — trading stopped"
        if self._thread:
            self._thread.join(timeout=5)
        return {"ok": True}

    # ── Status & log ─────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
        with self._lock:
            self.trade_log.appendleft(entry)
        log.info(f"[{level}] {msg}")

    def get_status(self) -> dict:
        self.refresh_account()
        positions = []
        if self.is_paper:
            positions = self._paper.positions
        return {
            "connected"   : self.connected,
            "trading"     : self.trading,
            "backend"     : self.backend,
            "mode"        : "paper" if self.is_paper else "live",
            "status_msg"  : self.status_msg,
            "account"     : self.account,
            "last_signal" : self.last_signal,
            "positions"   : positions,
            "log"         : list(self.trade_log)[:50],
        }


# Global singleton
trader = MT5Trader()
