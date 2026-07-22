#!/usr/bin/env python
"""
mt5_execution_daemon.py

A lightweight TCP Socket Daemon that runs on a Windows execution host.
Receives JSON trade signals from remote clients (e.g., Linux web servers)
and executes them locally using the MetaTrader 5 (MT5) python package.

API Structure:
  Request (JSON):
    {
      "action": "BUY" | "SELL" | "STATUS" | "CLOSE",
      "symbol": "EURUSD",
      "volume": 0.1,
      "sl": 1.0921,
      "tp": 1.1142,
      "ticket": 123456 (for CLOSE actions)
    }
  Response (JSON):
    {
      "ok": true | false,
      "ticket": 123456,
      "error": "Error description"
    }

Usage:
  python mt5_execution_daemon.py --port 8765
  python mt5_execution_daemon.py --test
"""

import sys
import json
import socket
import argparse
import threading

MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    pass


class MT5ExecutionDaemon:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None

    def initialize_mt5(self) -> bool:
        if not MT5_AVAILABLE:
            print("[WARN] MetaTrader 5 python package is not installed on this host.")
            return False
        if not mt5.initialize():
            print(f"[ERROR] MT5 initialization failed: {mt5.last_error()}")
            return False
        print("[INFO] MetaTrader 5 terminal initialized successfully.")
        return True

    def handle_request(self, request_data: dict) -> dict:
        action = request_data.get("action", "STATUS").upper()
        symbol = request_data.get("symbol", "EURUSD").upper()

        if action == "STATUS":
            if not MT5_AVAILABLE:
                return {"ok": False, "error": "MT5 library missing on daemon host."}
            terminal_info = mt5.terminal_info()
            if not terminal_info:
                return {"ok": False, "error": "MT5 terminal not running or unreachable."}
            return {
                "ok": True, 
                "connected": True, 
                "name": terminal_info.company, 
                "build": terminal_info.build
            }

        if not MT5_AVAILABLE:
            # Paper execution simulation fallback
            import random
            ticket = random.randint(5000000, 9000000)
            print(f"[PAPER SIMULATION] Simulating {action} for {symbol} | Vol: {request_data.get('volume')} | Ticket: {ticket}")
            return {"ok": True, "ticket": ticket, "simulated": True}

        if action in ("BUY", "SELL"):
            volume = float(request_data.get("volume", 0.01))
            sl = float(request_data.get("sl", 0.0))
            tp = float(request_data.get("tp", 0.0))

            price = mt5.symbol_info_tick(symbol).ask if action == "BUY" else mt5.symbol_info_tick(symbol).bid
            order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 1010,
                "comment": "BullLogic Remote Signal Daemon",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }

            result = mt5.order_send(request)
            if result is None:
                return {"ok": False, "error": "Order send returned None."}
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {"ok": False, "error": f"Execution failed: {result.comment} (Code: {result.retcode})"}
            
            return {"ok": True, "ticket": result.order, "price": result.price}

        if action == "CLOSE":
            ticket = int(request_data.get("ticket", 0))
            if not ticket:
                return {"ok": False, "error": "Ticket ID required for close action."}
            
            # Retrieve position
            positions = mt5.positions_get(ticket=ticket)
            if not positions or len(positions) == 0:
                return {"ok": False, "error": f"Position ticket {ticket} not found."}
            
            pos = positions[0]
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            close_price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": close_type,
                "position": ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 1010,
                "comment": "BullLogic Close Remote Position",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {"ok": False, "error": f"Close order failed: {result.comment}"}
            
            return {"ok": True, "ticket": ticket, "message": "Position closed successfully."}

        return {"ok": False, "error": f"Unsupported daemon action: {action}"}

    def client_thread(self, client_socket: socket.socket):
        try:
            data = client_socket.recv(4096)
            if not data:
                return
            
            request = json.loads(data.decode("utf-8"))
            response = self.handle_request(request)
            client_socket.sendall(json.dumps(response).encode("utf-8"))
        except Exception as e:
            err_resp = {"ok": False, "error": f"Daemon connection handler error: {str(e)}"}
            try:
                client_socket.sendall(json.dumps(err_resp).encode("utf-8"))
            except Exception:
                pass
        finally:
            client_socket.close()

    def start(self):
        self.initialize_mt5()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)
        self.running = True
        print(f"[START] Socket execution daemon listening on {self.host}:{self.port}...")

        try:
            while self.running:
                client, addr = self.socket.accept()
                t = threading.Thread(target=self.client_thread, args=(client,))
                t.daemon = True
                t.start()
        except KeyboardInterrupt:
            print("[INFO] Shutting down socket server...")
        finally:
            self.running = False
            self.socket.close()
            if MT5_AVAILABLE:
                mt5.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        daemon = MT5ExecutionDaemon()
        test_payload = {"action": "STATUS", "symbol": "EURUSD"}
        result = daemon.handle_request(test_payload)
        print("=== DAEMON TEST RUN RESULT ===")
        print(json.dumps(result, indent=2))
        sys.exit(0)

    daemon = MT5ExecutionDaemon(port=args.port)
    daemon.start()
