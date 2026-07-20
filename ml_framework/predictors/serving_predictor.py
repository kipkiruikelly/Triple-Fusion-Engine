import numpy as np
import pandas as pd
from typing import Dict, Any, List
from ml_framework.base import BasePredictor

class ServingPredictor(BasePredictor):
    """Modular predictor managing models inference routing and post-processing filters."""
    
    def predict(self, df: pd.DataFrame, features: List[str], models: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        lr_model = models.get("linear_regression")
        rf_model = models.get("random_forest")
        scaler = models.get("scaler")
        
        if df.empty or lr_model is None or rf_model is None or scaler is None:
            return {"direction": "HOLD", "entry_price": 0.0, "stop_price": 0.0, "target_price": 0.0, "confidence": 0.5}
            
        current_price = float(df["Close"].iloc[-1])
        latest_row = df[features].tail(1)
        X_scaled = scaler.transform(latest_row.values)
        
        # Linear Regression prediction
        pred_lr = float(lr_model.predict(X_scaled)[0])
        
        # Random Forest prediction (usually returns returns %)
        pred_rf = float(rf_model.predict(X_scaled)[0])
        
        # Average prediction metrics
        avg_ret_pct = pred_rf
        predicted_close = current_price * (1 + avg_ret_pct / 100)
        
        # Direction calculations
        direction = "HOLD"
        if avg_ret_pct > 0.1:
            direction = "BUY"
        elif avg_ret_pct < -0.1:
            direction = "SELL"
            
        latest_atr = float(df["ATR_14"].iloc[-1]) if "ATR_14" in df.columns else (current_price * 0.01)
        if latest_atr <= 0:
            latest_atr = current_price * 0.01
            
        # Sizing target boundaries
        if direction == "BUY":
            sl = current_price - 1.5 * latest_atr
            tp = current_price + 3.0 * latest_atr
        elif direction == "SELL":
            sl = current_price + 1.5 * latest_atr
            tp = current_price - 3.0 * latest_atr
        else:
            sl = current_price
            tp = current_price
            
        # Mock confidence evaluation
        confidence = 0.5 + min(abs(avg_ret_pct) / 10, 0.45)
        
        return {
            "direction": direction,
            "entry_price": current_price,
            "stop_price": sl,
            "target_price": tp,
            "confidence": confidence,
            "lr_pred": pred_lr,
            "rf_pred": predicted_close
        }
