import os
import sys
import time
import glob
import json
from pathlib import Path
from datetime import date, datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication

_PARENT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from users.models import PredictionHistory, PredictionAccuracy, PortfolioPosition, FREE_DAILY_LIMIT


class PredictionView(APIView):
    """POST /api/predict — run ML prediction for a ticker."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        ticker = (request.data.get('ticker') or '').strip().upper()
        interval = request.data.get('interval', '1d')

        if not ticker:
            return Response({'ok': False, 'error': 'ticker is required.'}, status=400)

        # Check daily limit for free users
        user = request.user
        today = date.today()
        if not user.is_plus:
            if user.last_prediction_date != today:
                user.predictions_today = 0
                user.last_prediction_date = today
            if user.predictions_today >= FREE_DAILY_LIMIT:
                return Response({
                    'ok': False,
                    'error': f'Daily prediction limit reached ({FREE_DAILY_LIMIT}/day on free plan). Upgrade to Pro for unlimited predictions.'
                }, status=429)

        try:
            from predictor import run_prediction
            result = run_prediction(ticker, interval)

            # Save to prediction history
            PredictionHistory.objects.create(
                user=user,
                ticker=ticker,
                interval=interval,
                current_price=result.get('current_price', 0),
                lr_pred=result.get('lr_pred', 0),
                rf_pred=result.get('rf_pred', 0),
                direction=result.get('direction', 'HOLD'),
                confidence=result.get('confidence', 0),
            )

            # Increment counter
            user.predictions_today = (user.predictions_today or 0) + 1
            user.last_prediction_date = today
            user.save(update_fields=['predictions_today', 'last_prediction_date'])

            return Response({'ok': True, **result})

        except Exception as exc:
            return Response({'ok': False, 'error': f'Prediction failed: {str(exc)}'}, status=500)


class PredictionHistoryView(APIView):
    """GET /api/predict/history — get user's prediction history."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        limit = min(int(request.query_params.get('limit', 20)), 100)
        history = PredictionHistory.objects.filter(user=request.user).order_by('-predicted_at')[:limit]
        return Response({
            'ok': True,
            'history': [
                {
                    'id': p.id,
                    'ticker': p.ticker,
                    'interval': p.interval,
                    'current_price': p.current_price,
                    'direction': p.direction,
                    'confidence': p.confidence,
                    'predicted_at': p.predicted_at.isoformat() if p.predicted_at else None,
                }
                for p in history
            ]
        })


class PredictionAccuracyView(APIView):
    """GET /api/accuracy — get prediction accuracy track records."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        accuracies = PredictionAccuracy.objects.filter(prediction__user=request.user).order_by('-checked_at')
        total = accuracies.count()
        if total == 0:
            return Response({
                "ok": True,
                "count": 0,
                "direction_accuracy": None,
                "avg_pct_error": None,
                "recent": []
            })
            
        dir_ok = accuracies.filter(direction_ok=True).count()
        err_sum = sum(a.pct_error for a in accuracies if a.pct_error is not None)
        avg_err = err_sum / total if total > 0 else 0
        
        recent = []
        for acc in accuracies[:20]:
            recent.append({
                "ticker": acc.prediction.ticker,
                "date": acc.prediction.predicted_at.strftime("%Y-%m-%d") if acc.prediction.predicted_at else "",
                "predicted": round(acc.prediction.lr_pred, 2),
                "actual": round(acc.actual_price, 2) if acc.actual_price else None,
                "dir_ok": acc.direction_ok,
                "pct_err": round(acc.pct_error, 2) if acc.pct_error else None,
            })
            
        return Response({
            "ok": True,
            "count": total,
            "direction_accuracy": round(dir_ok / total * 100, 1),
            "avg_pct_error": round(avg_err, 2),
            "recent": recent
        })


class PipelineStatsView(APIView):
    """GET /api/pipeline/stats — get pipeline training stats."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        # Scan saved models dir
        models_dir = os.path.join(_PARENT_DIR, "Saved Models")
        data_dir = os.path.join(_PARENT_DIR, "Data")
        n_models = len(glob.glob(os.path.join(models_dir, "lr_model_*.pkl")))

        metrics_path = os.path.join(data_dir, "model_metrics.json")
        avg_auc = None
        if os.path.exists(metrics_path):
            try:
                with open(metrics_path) as f:
                    m = json.load(f)
                results = m.get("results", [])
                aucs = [r["xgb_auc"] for r in results if r.get("xgb_auc") and r["xgb_auc"] > 0]
                avg_auc = round(sum(aucs) / len(aucs), 3) if aucs else None
            except Exception:
                pass

        bt_path = os.path.join(data_dir, "backtest_summary.json")
        bt_return, bt_sharpe = None, None
        if os.path.exists(bt_path):
            try:
                with open(bt_path) as f:
                    bt = json.load(f)
                metrics = bt.get("metrics", {})
                bt_return = metrics.get("total_return")
                bt_sharpe = metrics.get("sharpe")
            except Exception:
                pass

        total_acc = PredictionAccuracy.objects.count()
        dir_ok = PredictionAccuracy.objects.filter(direction_ok=True).count()
        direction_acc = round(dir_ok / total_acc * 100, 1) if total_acc >= 5 else None

        open_positions = PortfolioPosition.objects.filter(user=request.user, status="open").count()
        total_positions = PortfolioPosition.objects.filter(user=request.user).count()
        total_preds = PredictionHistory.objects.filter(user=request.user).count()

        return Response({
            "ok": True,
            "research": {"n_models": n_models, "avg_auc": avg_auc, "tickers": 10, "timeframes": 7},
            "backtest": {"total_return": bt_return, "sharpe": bt_sharpe},
            "paper": {"open": open_positions, "total": total_positions,
                      "direction_acc": direction_acc, "checked": total_acc},
            "live": {"total_predictions": total_preds},
        })


class AiAnalyzeView(APIView):
    """POST /api/ai/analyze/<ticker> — generate text market commentary."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request, ticker):
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not deepseek_key and not anthropic_key:
            return Response({
                "ok": False,
                "error": "AI analyst not configured (no provider API key set)."
            }, status=503)

        interval = request.data.get("interval", "1d")
        cur_price = request.data.get("current_price", 0)
        lr_pred = request.data.get("lr_pred", 0)
        direction = request.data.get("direction", "-")
        confidence = request.data.get("confidence", 0)
        rsi = request.data.get("rsi", 50)
        macd_signal = request.data.get("macd_signal", "-")
        ict_bias = request.data.get("ict_bias", "-")
        pd_zone = request.data.get("pd_zone", "-")

        prompt = (
            f"You are a premier quantitative institutional research analyst. "
            f"Generate a highly professional, structured, and actionable market analysis report for {ticker.upper()} "
            f"using the following model inputs:\n\n"
            f"- Timeframe: {interval}\n"
            f"- Current Market Price: ${cur_price}\n"
            f"- Machine Learning Target Price: ${lr_pred}\n"
            f"- Projected Direction: {direction} (Confidence Level: {confidence}%)\n"
            f"- RSI(14): {rsi}\n"
            f"- MACD Setup: {macd_signal}\n"
            f"- ICT Order Flow Bias: {ict_bias}\n"
            f"- Premium/Discount (PD) Zone: {pd_zone}\n\n"
            f"Structure the output exactly using these professional headers and clean markdown spacing:\n\n"
            f"✦ **EXECUTIVE SUMMARY & MOMENTUM OUTLOOK**\n"
            f"[Provide a sophisticated analysis of short-term momentum and price direction probabilities. Assess if technical indicators like RSI and MACD confirm or diverge from the ML model's projection. Use institutional phrasing like 'neutral posture', 'bullish validation', or 'low-conviction deviation' rather than retail slang.]\n\n"
            f"✦ **KEY RESISTANCE & SUPPORT LEVELS**\n"
            f"[Detail clear resistance and support levels. Define specific price triggers that invalidate the directional thesis or confirm a breakout. Relate these to the PD Zone if specified.]\n\n"
            f"✦ **RISK EXPOSURE & VALIDATION METRICS**\n"
            f"[Outline the primary technical failure points and market dynamics that would invalidate the model's predictive edge. Include timeframe-based validation guidelines.]\n\n"
            f"✦ **TACTICAL EXECUTION STRATEGY**\n"
            f"[Specify precise, institutional entry conditions, target levels, and stop-loss gates. Do not use colloquial advice; write as a systematic asset management execution plan.]\n\n"
            f"Write in a direct, objective, and authoritative tone. Avoid introductory remarks, disclaimers, or conversational filler."
        )

        deepseek_err = None
        if deepseek_key:
            try:
                import openai as _openai
                client = _openai.OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
                response = client.chat.completions.create(
                    model="deepseek-chat", max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )
                return Response({
                    "ok": True, 
                    "analysis": response.choices[0].message.content,
                    "provider": "deepseek"
                })
            except Exception as e:
                deepseek_err = str(e)
                if not anthropic_key:
                    return Response({"ok": False, "error": deepseek_err}, status=500)

        try:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return Response({
                "ok": True, 
                "analysis": response.content[0].text,
                "provider": "anthropic"
            })
        except Exception as e:
            err = str(e)
            if deepseek_err:
                err = f"deepseek: {deepseek_err}; anthropic: {err}"
            return Response({"ok": False, "error": err}, status=500)


class ModelMetricsView(APIView):
    """GET /api/model-metrics — load trained model metrics from file."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        path = os.path.join(BASE_DIR, "Data", "model_metrics.json")
        if not os.path.exists(path):
            return Response({
                "ok": False,
                "error": "No metrics file found. Run train_professional.py first."
            }, status=404)
        try:
            with open(path) as f:
                data = json.load(f)
            return Response({"ok": True, **data})
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=500)


class ResearchView(APIView):
    """GET /api/research/<ticker> — run deep research for a ticker."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request, ticker):
        ticker = ticker.upper().strip()
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor

        def _price():
            try:
                fi = yf.Ticker(ticker).fast_info
                return {"price": round(float(fi.last_price or 0), 2),
                        "prev":  round(float(fi.previous_close or 0), 2)}
            except Exception:
                return {}

        def _info():
            try:
                i = yf.Ticker(ticker).info
                return {
                    "name":           i.get("longName", ticker),
                    "sector":         i.get("sector", "-"),
                    "industry":       i.get("industry", "-"),
                    "market_cap":     i.get("marketCap"),
                    "pe":             round(float(i.get("trailingPE") or 0), 2) if i.get("trailingPE") else None,
                    "eps":            round(float(i.get("trailingEps") or 0), 2) if i.get("trailingEps") else None,
                    "52w_high":       round(float(i.get("fiftyTwoWeekHigh") or 0), 2) if i.get("fiftyTwoWeekHigh") else None,
                    "52w_low":        round(float(i.get("fiftyTwoWeekLow") or 0), 2) if i.get("fiftyTwoWeekLow") else None,
                    "avg_volume":     i.get("averageVolume"),
                    "beta":           round(float(i.get("beta") or 0), 2) if i.get("beta") else None,
                    "div_yield":      round(float((i.get("dividendYield") or 0) * 100), 2) if i.get("dividendYield") else None,
                    "target_mean":    round(float(i.get("targetMeanPrice") or 0), 2) if i.get("targetMeanPrice") else None,
                    "recommendation": i.get("recommendationKey", "-"),
                    "analyst_count":  i.get("numberOfAnalystOpinions", 0),
                    "short_float":    round(float((i.get("shortPercentOfFloat") or 0) * 100), 2) if i.get("shortPercentOfFloat") else None,
                    "description":    (i.get("longBusinessSummary") or "")[:400],
                }
            except Exception:
                return {}

        def _news():
            try:
                raw = yf.Ticker(ticker).news or []
                items = []
                for n in raw[:5]:
                    ct    = n.get("content", {})
                    title = ct.get("title") or n.get("title", "")
                    link  = ct.get("canonicalUrl", {}).get("url") or n.get("link", "")
                    items.append({"title": title, "link": link})
                return items
            except Exception:
                return []

        def _prediction():
            try:
                from predictor import run_prediction
                res = run_prediction(ticker, "1d")
                return {
                    "direction":  res.get("direction"),
                    "confidence": res.get("confidence"),
                    "lr_pred":    res.get("lr_pred"),
                    "action":     res.get("action"),
                    "rsi":        res.get("rsi"),
                    "macd":       res.get("macd_signal"),
                    "ict_bias":   res.get("ict_bias"),
                    "current_price": res.get("current_price"),
                }
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=4) as ex:
            fp = ex.submit(_price)
            fi = ex.submit(_info)
            fn = ex.submit(_news)
            fd = ex.submit(_prediction)
            price_d = fp.result()
            info_d  = fi.result()
            news_d  = fn.result()
            pred_d  = fd.result()

        return Response({
            "ok": True,
            "ticker": ticker,
            "data": {
                "price": price_d, 
                "info": info_d,
                "news": news_d,  
                "prediction": pred_d
            }
        })


class FeatureImportanceView(APIView):
    """GET /api/feature-importance/<ticker> — load feature importance for a model."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request, ticker):
        try:
            import joblib
            ticker = ticker.upper().strip()
            interval = request.query_params.get("interval", "1d")
            if interval not in ("1d", "1h"):
                interval = "1d"
            
            BASE_DIR = Path(__file__).resolve().parent.parent.parent
            models_dir = os.path.join(BASE_DIR, "Saved Models")
            suffix = "" if interval == "1d" else f"_{interval}"
            rf_path = os.path.join(models_dir, f"rf_model_{ticker}{suffix}.pkl")
            feat_path = os.path.join(models_dir, f"feature_cols_sklearn_{ticker}{suffix}.pkl")
            
            if not os.path.exists(rf_path):
                return Response({
                    "ok": False, 
                    "error": f"No {interval} model found for {ticker}."
                })
                
            rf = joblib.load(rf_path)
            feat = joblib.load(feat_path)
            pairs = sorted(zip(feat, rf.feature_importances_.tolist()), key=lambda x: x[1], reverse=True)[:15]
            
            return Response({
                "ok": True,
                "ticker": ticker,
                "interval": interval,
                "features": [{"name": n, "importance": round(v, 4)} for n, v in pairs]
            })
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=500)


class TrackRecordView(APIView):
    """GET /api/track-record — returns general stats and tickers performance stats."""
    permission_classes = [AllowAny]

    def get(self, request):
        days = request.query_params.get("days", "90")
        try:
            days = int(days)
        except ValueError:
            days = 90
            
        days = 30 if days <= 30 else 90
        
        since = datetime.utcnow() - timedelta(days=days)
        MIN_SAMPLES = 10
        
        accs = PredictionAccuracy.objects.filter(
            direction_ok__isnull=False,
            prediction__predicted_at__gte=since
        ).select_related('prediction')
        
        groups = {}
        for acc in accs:
            pred = acc.prediction
            key = (pred.ticker, pred.interval or '1d')
            if key not in groups:
                groups[key] = {'n': 0, 'ok': 0, 'errors': []}
            groups[key]['n'] += 1
            if acc.direction_ok:
                groups[key]['ok'] += 1
            if acc.pct_error is not None:
                groups[key]['errors'].append(acc.pct_error)
                
        per = []
        tot_n = 0
        tot_ok = 0
        
        for (ticker, ivl), info in groups.items():
            n = info['n']
            ok = info['ok']
            tot_n += n
            tot_ok += ok
            
            avg_err = (sum(info['errors']) / len(info['errors'])) if info['errors'] else None
            
            per.append({
                "ticker": ticker,
                "interval": ivl,
                "n": n,
                "direction_accuracy": round((ok / n) * 100, 1) if n >= MIN_SAMPLES else None,
                "avg_pct_error": round(avg_err, 2) if avg_err is not None and n >= MIN_SAMPLES else None,
                "sufficient": n >= MIN_SAMPLES
            })
            
        per.sort(key=lambda r: -r["n"])
        
        overall = round((tot_ok / tot_n) * 100, 1) if tot_n >= MIN_SAMPLES else None
        
        return Response({
            "ok": True,
            "days": days,
            "total_graded": tot_n,
            "overall_direction_accuracy": overall,
            "min_samples": MIN_SAMPLES,
            "per_model": per
        })


_app_start_time = time.time()

class HealthView(APIView):
    """GET /api/health — Liveness probe for containers and monitoring."""
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            from predictor import _ML_AVAILABLE
            ml_ok = _ML_AVAILABLE
        except Exception:
            ml_ok = True

        return Response({
            "status": "ok",
            "service": "bull-logic-django",
            "uptime_seconds": round(time.time() - _app_start_time, 1),
            "ml_available": ml_ok,
        })


class SignalView(APIView):
    """POST /api/signal — Return a compact trading signal for MT5/automation."""
    permission_classes = [AllowAny]

    def post(self, request):
        ticker = (request.data.get("ticker") or "").strip().upper()
        interval = request.data.get("interval", "1d")

        if not ticker:
            return Response({"error": "ticker is required"}, status=400)

        try:
            from predictor import ml_signal
            result = ml_signal(ticker, interval)
            return Response(result)
        except Exception as e:
            return Response({"action": "HOLD", "error": str(e)}, status=500)

