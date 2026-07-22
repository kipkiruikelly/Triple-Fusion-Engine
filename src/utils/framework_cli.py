import argparse
import sys
import os
import joblib
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_framework.orchestrator import PipelineOrchestrator

def main():
    parser = argparse.ArgumentParser(description="BullLogic Modular ML Framework CLI")
    parser.add_argument("--config", type=str, default="pipeline_config.json", help="Path to config file")
    parser.add_argument("--mode", type=str, required=True, choices=["ingest", "train", "predict"], help="Pipeline phase to run")
    parser.add_argument("--symbol", type=str, default="SPY", help="Ticker symbol")
    parser.add_argument("--interval", type=str, default="1d", help="Timeframe interval")
    
    args = parser.parse_args()
    
    # 1. Instantiate the orchestrator
    print(f"Loading pipeline orchestrator with configuration: {args.config}")
    orchestrator = PipelineOrchestrator(args.config)
    
    if args.mode == "ingest":
        print(f"Running ingestion for {args.symbol} ({args.interval})...")
        df = orchestrator.run_ingestion(args.symbol, args.interval)
        print(f"Ingested {len(df)} rows. Columns: {list(df.columns)}")
        
    elif args.mode == "train":
        print(f"Running ingestion to prepare training data...")
        df = orchestrator.run_ingestion(args.symbol, args.interval)
        
        # Prepare targets
        df["Next_Close"] = df["Close"].shift(-1)
        df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
        df.dropna(inplace=True)
        
        # Gather features from config or defaults
        features = [
            "Close", "High", "Low", "Volume",
            "SMA_7", "SMA_21", "EMA_12", "EMA_26",
            "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
            "BB_Upper", "BB_Lower", "BB_Width",
            "Volume_SMA_10", "Daily_Return",
            "Above_200SMA", "Dist_200SMA",
            "Body_Ratio", "Displacement",
            "Dist_to_SH", "Dist_to_SL",
            "Structure_Bullish", "PD_Position",
            "Bull_FVG_Count", "Bear_FVG_Count",
            "Bull_OB_Count", "Bear_OB_Count",
        ]
        available_features = [f for f in features if f in df.columns]
        
        print("Training models...")
        trained_models = orchestrator.run_training(df, available_features, "Next_Return")
        
        # Save models to Saved Models/ for legacy compatibility
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Saved Models")
        os.makedirs(models_dir, exist_ok=True)
        
        # Scale features
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        scaler.fit(df[available_features].values)
        
        t = args.symbol.upper()
        joblib.dump(scaler, os.path.join(models_dir, f"scaler_sklearn_{t}.pkl"))
        joblib.dump(available_features, os.path.join(models_dir, f"feature_cols_sklearn_{t}.pkl"))
        
        for name, model in trained_models.items():
            model_file = f"{'lr' if 'linear' in name else 'rf'}_model_{t}.pkl"
            joblib.dump(model, os.path.join(models_dir, model_file))
            print(f"Saved model {name} -> Saved Models/{model_file}")
            
    elif args.mode == "predict":
        print(f"Ingesting latest candles for {args.symbol}...")
        df = orchestrator.run_ingestion(args.symbol, args.interval)
        
        # Load trained models from Saved Models/
        t = args.symbol.upper()
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Saved Models")
        
        try:
            lr = joblib.load(os.path.join(models_dir, f"lr_model_{t}.pkl"))
            rf = joblib.load(os.path.join(models_dir, f"rf_model_{t}.pkl"))
            scaler = joblib.load(os.path.join(models_dir, f"scaler_sklearn_{t}.pkl"))
            features = joblib.load(os.path.join(models_dir, f"feature_cols_sklearn_{t}.pkl"))
        except FileNotFoundError:
            print(f"Error: Models for {t} not found. Please train models first using: python framework_cli.py --mode train --symbol {t}")
            return
            
        models = {"linear_regression": lr, "random_forest": rf, "scaler": scaler}
        
        pred_res = orchestrator.run_prediction(df, features, models)
        print("\n=== Prediction Results ===")
        print(f"Direction:   {pred_res['direction']}")
        print(f"Entry Price: ${pred_res['entry_price']:.2f}")
        print(f"Stop Loss:   ${pred_res['stop_price']:.2f}")
        print(f"Take Profit: ${pred_res['target_price']:.2f}")
        print(f"Confidence:  {pred_res['confidence']*100:.1f}%")

if __name__ == "__main__":
    main()
