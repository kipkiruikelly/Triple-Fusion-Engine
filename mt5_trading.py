"""
mt5_trading.py
MT5 algorithmic trading engine for MarketPredict.

Connects to MetaTrader 5 via Wine on Linux using the mt5linux bridge.
Implements a multi-signal scalping strategy:
  - RSI(14) reversal from extreme zones
  - MACD(12,26,9) histogram momentum
  - ATR(14) for dynamic SL/TP sizing
  - 2:1 minimum risk-reward ratio
  - 1% account risk per trade (configurable)

Requires: MT5 running in Wine with the PythonMT5Bridge EA loaded.
"""

import time
import threading
import logging
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd

# Try mt5linux (Linux/Wine bridge) first, then native MetaTrader5 (Windows)
try:
    from mt5linux import MetaTrader5 as _MT5
    MT5_BACKEND = "mt5linux"
except ImportError:
    try:
        import MetaTrader5 as _MT5
        MT5_BACKEND = "native"
    except ImportError:
        _MT5 = None
        MT5_BACKEND = "unavailable"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("mt5_trading")

MAX_LOG_ENTRIES  = 200
MAX_POSITIONS    = 3
DAILY_LOSS_LIMIT = 0.05   # stop trading if daily drawdown exceeds 5 %


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
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_macd(closes: np.ndarray, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    s = pd.Series(closes)
    ema_fast   = s.ewm(span=fast,   adjust=False).mean()
    ema_slow   = s.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
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


class MT5Trader:
    def __init__(self):
        self.mt5         = _MT5
        self.backend     = MT5_BACKEND
        self.connected   = False
        self.trading     = False
        self._thread     = None
        self._lock       = threading.Lock()
        self.trade_log   = deque(maxlen=MAX_LOG_ENTRIES)
        self.account     = {}
        self.status_msg  = "Disconnected"
        self.equity_open = None   # equity at session start for daily loss check
        self.last_signal = {}

    # ── Connection ──────────────────────────────────────────────────────────

    def connect(self, account: int, password: str, server: str,
                host: str = "localhost", port: int = 18812) -> dict:
        if self.mt5 is None:
            return {"ok": False, "error": "MT5 package not installed. Run: pip install mt5linux"}

        try:
            if self.backend == "mt5linux":
                mt5 = self.mt5(host=host, port=port)
            else:
                mt5 = self.mt5

            if not mt5.initialize():
                return {"ok": False, "error": f"MT5 initialize() failed: {mt5.last_error()}"}

            if not mt5.login(account, password=password, server=server):
                mt5.shutdown()
                return {"ok": False, "error": f"Login failed: {mt5.last_error()}"}

            info = mt5.account_info()
            if info is None:
                mt5.shutdown()
                return {"ok": False, "error": "Could not fetch account info"}

            self._mt5_instance = mt5
            self.connected  = True
            self.account    = {
                "login"    : info.login,
                "name"     : info.name,
                "server"   : info.server,
                "currency" : info.currency,
                "balance"  : round(info.balance, 2),
                "equity"   : round(info.equity, 2),
                "margin"   : round(info.margin, 2),
                "free_margin": round(info.margin_free, 2),
                "leverage" : info.leverage,
            }
            self.equity_open = info.equity
            self.status_msg  = f"Connected — {info.name} ({info.server})"
            self._log("INFO", f"Connected to {info.server} as {info.name}, balance {info.currency} {info.balance:,.2f}")
            return {"ok": True, "account": self.account}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self.stop_trading()
        if self.connected:
            try:
                self._mt5_instance.shutdown()
            except Exception:
                pass
        self.connected  = False
        self.status_msg = "Disconnected"
        self._log("INFO", "Disconnected from MT5")

    def refresh_account(self):
        if not self.connected:
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

    # ── Signal generation ───────────────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe, n: int = 100) -> pd.DataFrame | None:
        try:
            rates = self._mt5_instance.copy_rates_from_pos(symbol, timeframe, 0, n)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df
        except Exception as e:
            log.warning(f"get_bars error: {e}")
            return None

    def generate_signal(self, symbol: str, timeframe) -> dict:
        mt5 = self._mt5_instance
        df  = self.get_bars(symbol, timeframe, n=120)
        if df is None or len(df) < 60:
            return {"action": "HOLD", "reason": "Insufficient data", "score": 0}

        closes = df["close"].values
        highs  = df["high"].values
        lows   = df["low"].values

        rsi              = _calc_rsi(closes)
        prev_rsi         = _calc_rsi(closes[:-1])
        macd, sig, hist  = _calc_macd(closes)
        _, _, prev_hist  = _calc_macd(closes[:-1])
        atr              = _calc_atr(highs, lows, closes)
        current_price    = float(closes[-1])

        # Score signals: each condition adds 1 point
        buy_score = sell_score = 0

        # RSI reversal from oversold
        if prev_rsi < 30 and rsi >= 30:
            buy_score += 1
        elif rsi < 35:
            buy_score += 1

        # RSI reversal from overbought
        if prev_rsi > 70 and rsi <= 70:
            sell_score += 1
        elif rsi > 65:
            sell_score += 1

        # MACD histogram momentum flip
        if prev_hist < 0 and hist >= 0:
            buy_score += 2   # strong flip signal
        elif hist > 0 and hist > prev_hist:
            buy_score += 1

        if prev_hist > 0 and hist <= 0:
            sell_score += 2
        elif hist < 0 and hist < prev_hist:
            sell_score += 1

        # Price vs short-term EMA
        ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
        if current_price > ema20:
            buy_score += 1
        else:
            sell_score += 1

        action = "HOLD"
        score  = 0
        reason = f"RSI={rsi:.1f} MACD_hist={hist:.5f} ATR={atr:.5f}"

        if buy_score >= 3 and buy_score > sell_score:
            action = "BUY"
            score  = buy_score
        elif sell_score >= 3 and sell_score > buy_score:
            action = "SELL"
            score  = sell_score

        signal = {
            "action" : action,
            "score"  : score,
            "reason" : reason,
            "rsi"    : round(rsi, 2),
            "macd"   : round(hist, 6),
            "atr"    : round(atr, 6),
            "price"  : round(current_price, 5),
        }
        self.last_signal = signal
        return signal

    # ── Order execution ─────────────────────────────────────────────────────

    def _count_positions(self, symbol: str) -> int:
        try:
            positions = self._mt5_instance.positions_get(symbol=symbol)
            return len(positions) if positions else 0
        except Exception:
            return 0

    def _calc_lot(self, symbol: str, risk_pct: float, sl_points: float) -> float:
        """Risk-based lot size: risk_pct% of balance / (SL in account currency)."""
        try:
            balance  = self.account.get("balance", 1000)
            risk_amt = balance * (risk_pct / 100.0)
            info     = self._mt5_instance.symbol_info(symbol)
            if info is None:
                return info.volume_min
            tick_value = info.trade_tick_value
            tick_size  = info.trade_tick_size
            if tick_size == 0 or tick_value == 0:
                return info.volume_min
            sl_money   = (sl_points / tick_size) * tick_value
            if sl_money <= 0:
                return info.volume_min
            lot = risk_amt / sl_money
            lot = max(info.volume_min, min(info.volume_max, round(lot / info.volume_step) * info.volume_step))
            return round(lot, 2)
        except Exception:
            return 0.01

    def place_order(self, symbol: str, action: str, risk_pct: float, atr: float) -> dict:
        mt5     = self._mt5_instance
        sl_dist = atr * 1.5          # SL = 1.5× ATR
        tp_dist = atr * 3.0          # TP = 3.0× ATR  (2:1 R:R)

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

        lot = self._calc_lot(symbol, risk_pct, sl_dist)

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
            "time"   : datetime.now().strftime("%H:%M:%S"),
            "action" : action,
            "symbol" : symbol,
            "lot"    : lot,
            "price"  : price,
            "sl"     : sl,
            "tp"     : tp,
            "ticket" : result.order,
        }
        self._log("TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}")
        return {"ok": True, "trade": trade}

    def close_all(self, symbol: str) -> int:
        """Close all open positions for the symbol. Returns number closed."""
        mt5        = self._mt5_instance
        positions  = mt5.positions_get(symbol=symbol) or []
        closed     = 0
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
                self._log("CLOSE", f"Closed ticket {pos.ticket} {symbol}")
        return closed

    # ── Trading loop ────────────────────────────────────────────────────────

    def _trading_loop(self, symbol: str, timeframe, risk_pct: float, interval: int):
        mt5 = self._mt5_instance
        # Map string timeframe to MT5 constant
        tf_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
        }
        tf = tf_map.get(timeframe, mt5.TIMEFRAME_M5)

        self._log("INFO", f"Trading started — {symbol} {timeframe} risk={risk_pct}% interval={interval}s")

        while self.trading:
            try:
                self.refresh_account()

                # Daily loss guard
                if self.equity_open and self.account.get("equity"):
                    drawdown = (self.equity_open - self.account["equity"]) / self.equity_open
                    if drawdown >= DAILY_LOSS_LIMIT:
                        self._log("WARN", f"Daily loss limit hit ({drawdown*100:.1f}%). Trading halted.")
                        self.trading = False
                        self.status_msg = f"Halted — daily loss limit ({DAILY_LOSS_LIMIT*100:.0f}%) reached"
                        break

                # Max positions guard
                if self._count_positions(symbol) >= MAX_POSITIONS:
                    self._log("INFO", f"Max positions ({MAX_POSITIONS}) reached, skipping")
                    time.sleep(interval)
                    continue

                signal = self.generate_signal(symbol, tf)
                self._log("SIGNAL", f"{signal['action']} score={signal['score']} {signal['reason']}")

                if signal["action"] in ("BUY", "SELL"):
                    result = self.place_order(symbol, signal["action"], risk_pct, signal["atr"])
                    if not result["ok"]:
                        self._log("ERROR", result["error"])

            except Exception as e:
                self._log("ERROR", f"Loop error: {e}")

            time.sleep(interval)

        self._log("INFO", "Trading loop stopped")

    def start_trading(self, symbol: str, timeframe: str = "M5",
                      risk_pct: float = 1.0, interval: int = 60) -> dict:
        if not self.connected:
            return {"ok": False, "error": "Not connected to MT5"}
        if self.trading:
            return {"ok": False, "error": "Already trading"}

        self.trading    = True
        self.status_msg = f"Trading {symbol} on {timeframe}"
        self._thread    = threading.Thread(
            target=self._trading_loop,
            args=(symbol, timeframe, risk_pct, interval),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True}

    def stop_trading(self) -> dict:
        if not self.trading:
            return {"ok": False, "error": "Not currently trading"}
        self.trading    = False
        self.status_msg = "Connected — trading stopped"
        if self._thread:
            self._thread.join(timeout=5)
        return {"ok": True}

    # ── Status & log ────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
        with self._lock:
            self.trade_log.appendleft(entry)
        log.info(f"[{level}] {msg}")

    def get_status(self) -> dict:
        self.refresh_account()
        return {
            "connected"   : self.connected,
            "trading"     : self.trading,
            "backend"     : self.backend,
            "status_msg"  : self.status_msg,
            "account"     : self.account,
            "last_signal" : self.last_signal,
            "log"         : list(self.trade_log)[:50],
        }


# Global singleton used by app.py
trader = MT5Trader()
