import os
import sys
import pandas as pd
import ta as _ta
import yfinance as yf
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

_PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from core.utils import SCREENER_TICKERS, _SECTOR_ETFS
from market_data import get_history


class ScannerVolumeView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        results = []

        def _chk(t):
            try:
                hist, _ = get_history(t, period="30d", interval="1d")
                if len(hist) < 10:
                    return
                avg_vol = float(hist["Volume"].iloc[:-1].mean())
                today = float(hist["Volume"].iloc[-1])
                ratio = today / avg_vol if avg_vol > 0 else 1.0
                price = float(hist["Close"].iloc[-1])
                chg = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100)
                results.append({
                    "ticker": t,
                    "price": round(price, 2),
                    "volume": int(today),
                    "avg_volume": int(avg_vol),
                    "volume_ratio": round(ratio, 2),
                    "pct_change": round(chg, 2)
                })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_chk, SCREENER_TICKERS))
            
        results.sort(key=lambda x: x["volume_ratio"], reverse=True)
        return Response({"ok": True, "rows": results})


class ScannerSqueezeView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        results = []

        def _chk(t):
            try:
                info = yf.Ticker(t).info
                sf = (info.get("shortPercentOfFloat") or 0) * 100
                sr = info.get("shortRatio") or 0
                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                hist, _ = get_history(t, period="30d", interval="1d")
                
                rsi_val = None
                if len(hist) >= 14:
                    rsi_val = round(float(_ta.momentum.rsi(hist["Close"], window=14).iloc[-1]), 1)
                
                mom = 0.0
                if len(hist) >= 5:
                    mom = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-5] - 1) * 100), 2)
                
                results.append({
                    "ticker": t,
                    "price": round(float(price), 2),
                    "short_float_pct": round(float(sf), 1),
                    "days_to_cover": round(float(sr), 1),
                    "rsi": rsi_val,
                    "momentum_5d": mom,
                    "squeeze_score": round(float(sf) * 0.5 + max(0, mom) * 0.5, 1),
                })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(_chk, SCREENER_TICKERS))
            
        results.sort(key=lambda x: x["squeeze_score"], reverse=True)
        return Response({"ok": True, "rows": results})


class ScannerSectorView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        results = []

        def _chk(item):
            sector, etf = item
            try:
                hist, _ = get_history(etf, period="5d", interval="1d")
                if len(hist) < 2:
                    return
                d1 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100), 2)
                d5 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100), 2)
                results.append({
                    "sector": sector,
                    "etf": etf,
                    "price": round(float(hist["Close"].iloc[-1]), 2),
                    "d1": d1,
                    "d5": d5,
                    "volume": int(hist["Volume"].iloc[-1])
                })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_chk, _SECTOR_ETFS.items()))
            
        results.sort(key=lambda x: x["d1"], reverse=True)
        return Response({"ok": True, "sectors": results})
