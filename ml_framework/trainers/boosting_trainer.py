from typing import Dict, Any, List
import pandas as pd
from ml_framework.base import BaseModelTrainer

class BoostingModelTrainer(BaseModelTrainer):
    """Modular model trainer wrapping XGBoost and LightGBM algorithms."""
    
    def train(self, df: pd.DataFrame, features: List[str], target_col: str, **kwargs) -> Dict[str, Any]:
        model_type = kwargs.get("model_type", "xgboost")
        hyperparams = kwargs.get("hyperparams", {})
        
        # Prepare arrays
        X = df[features].values
        y = df[target_col].values
        
        if model_type == "xgboost":
            import xgboost as xgb
            model = xgb.XGBRegressor(**hyperparams)
        elif model_type == "lightgbm":
            import lightgbm as lgb
            model = lgb.LGBMRegressor(**hyperparams)
        else:
            raise ValueError(f"Unknown boosting model type specified: {model_type}")
            
        model.fit(X, y)
        
        return {
            "model": model,
            "metrics": {}
        }
