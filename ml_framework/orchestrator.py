import os
import sys
import importlib
import pandas as pd
from typing import Dict, Any, List
from ml_framework.config_parser import PipelineConfig
from ml_framework.connectors.base_connector import CONNECTORS
from ml_framework.features.base_builder import FEATURE_BUILDERS
from ml_framework.trainers.base_trainer import MODEL_TRAINERS
from ml_framework.predictors.serving_predictor import ServingPredictor

class PipelineOrchestrator:
    """The central engine coordinating configuration-driven modular pipeline executions."""
    
    def __init__(self, config_path: str):
        if config_path.endswith(".yaml") or config_path.endswith(".yml"):
            self.config = PipelineConfig.from_yaml(config_path)
        else:
            self.config = PipelineConfig.from_json_fallback(config_path)
        self.plugins = self._scan_and_load_plugins()

    def _scan_and_load_plugins(self) -> Dict[str, Any]:
        """Scan a root plugins/ directory and import modules dynamically via importlib."""
        loaded_plugins = {}
        plugins_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
        if not os.path.exists(plugins_dir):
            return loaded_plugins

        sys.path.insert(0, plugins_dir)
        for category in ["connectors", "features", "models", "predictors"]:
            cat_dir = os.path.join(plugins_dir, category)
            if not os.path.exists(cat_dir):
                continue
            for fname in os.listdir(cat_dir):
                if fname.endswith(".py") and not fname.startswith("__"):
                    module_name = fname[:-3]
                    try:
                        # Dynamically load the plugin module
                        mod = importlib.import_module(f"{category}.{module_name}")
                        # Auto-register if registration hook exists
                        if hasattr(mod, "register_plugin"):
                            mod.register_plugin(self)
                        loaded_plugins[f"{category}.{module_name}"] = mod
                    except Exception as e:
                        print(f"Failed to load plugin {category}.{module_name}: {e}")
        return loaded_plugins

    def run_ingestion(self, symbol: str, interval: str) -> pd.DataFrame:
        """Execute the ingestion and feature engineering pipeline phases."""
        # 1. Fetch raw data
        conn_cls = CONNECTORS.get(self.config.connector_name)
        if not conn_cls:
            raise ValueError(f"No connector registered with name: {self.config.connector_name}")
        connector = conn_cls()
        df = connector.fetch_data(symbol, interval, **self.config.connector_params)
        
        # 2. Build features sequentially
        for builder_name in self.config.features:
            builder_cls = FEATURE_BUILDERS.get(builder_name)
            if builder_cls:
                builder = builder_cls()
                df = builder.build_features(df, **self.config.feature_params)
        return df

    def run_training(self, df: pd.DataFrame, features: List[str], target_col: str) -> Dict[str, Any]:
        """Train models using the prepared datasets."""
        results = {}
        for trainer_name, params in self.config.model_params.items():
            # Check model registry mapping category
            if trainer_name in ["linear_regression", "random_forest"]:
                trainer_cls = MODEL_TRAINERS.get("sklearn")
                model_type = trainer_name
            else:
                trainer_cls = MODEL_TRAINERS.get("boosting")
                model_type = trainer_name
                
            if trainer_cls:
                trainer = trainer_cls()
                res = trainer.train(df, features, target_col, model_type=model_type, hyperparams=params)
                results[trainer_name] = res["model"]
        return results

    def run_prediction(self, df: pd.DataFrame, features: List[str], models: Dict[str, Any]) -> Dict[str, Any]:
        """Generate direction, targets, and confidence levels using serving predictors."""
        predictor = ServingPredictor()
        return predictor.predict(df, features, models)
