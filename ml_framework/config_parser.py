import os
import json
from typing import Dict, Any

class PipelineConfig:
    """Class to parse and validate ML framework configuration parameters."""
    
    def __init__(self, config_dict: Dict[str, Any]):
        self.raw = config_dict
        self.connector_name = config_dict.get("connector", "yfinance")
        self.connector_params = config_dict.get("connector_params", {})
        
        self.features = config_dict.get("features", [])
        self.feature_params = config_dict.get("feature_params", {})
        
        self.models = config_dict.get("models", ["linear_regression", "random_forest"])
        self.model_params = config_dict.get("model_params", {})
        
        self.serving = config_dict.get("serving", {})
        self.evaluation = config_dict.get("evaluation", {})

    @classmethod
    def from_yaml(cls, yaml_path: str):
        """Parse configuration parameters from a YAML file."""
        try:
            import yaml
            with open(yaml_path, "r") as f:
                data = yaml.safe_load(f)
            return cls(data or {})
        except ImportError:
            # Fallback to simple custom parser if PyYAML is not installed
            return cls.from_json_fallback(yaml_path.replace(".yaml", ".json"))

    @classmethod
    def from_json(cls, json_path: str):
        """Parse configuration parameters from a JSON file."""
        with open(json_path, "r") as f:
            data = json.load(f)
        return cls(data or {})

    @classmethod
    def from_json_fallback(cls, json_path: str):
        """Attempts to fallback to JSON format config file reading."""
        if os.path.exists(json_path):
            return cls.from_json(json_path)
        # Default mock fallback values
        return cls({
            "connector": "yfinance",
            "features": ["technical_analysis", "ict_indicators"],
            "models": ["linear_regression", "random_forest", "xgboost"],
            "model_params": {
                "random_forest": {"n_estimators": 100, "max_depth": 10},
                "xgboost": {"n_estimators": 100, "max_depth": 5}
            }
        })
