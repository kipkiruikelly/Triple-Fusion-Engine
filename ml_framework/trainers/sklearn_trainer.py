from typing import Dict, Any, List
import pandas as pd
from ml_framework.base import BaseModelTrainer
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor

class SklearnModelTrainer(BaseModelTrainer):
    """Modular model trainer wrapping standard Scikit-Learn algorithms."""
    
    def train(self, df: pd.DataFrame, features: List[str], target_col: str, **kwargs) -> Dict[str, Any]:
        model_type = kwargs.get("model_type", "linear_regression")
        hyperparams = kwargs.get("hyperparams", {})
        
        # Prepare arrays
        X = df[features].values
        y = df[target_col].values
        
        if model_type == "linear_regression":
            model = LinearRegression(**hyperparams)
        elif model_type == "random_forest":
            model = RandomForestRegressor(**hyperparams)
        else:
            raise ValueError(f"Unknown Scikit-Learn model type specified: {model_type}")
            
        model.fit(X, y)
        
        # Calculate training score metrics
        score = model.score(X, y)
        
        return {
            "model": model,
            "metrics": {
                "r2_score": float(score)
            }
        }
