"""
azure_storage.py
Azure Blob Storage integration for BullLogic model artifacts.

Container: trained-models
Auth: AZURE_STORAGE_CONNECTION_STRING env var
Files per ticker: lr_model_{T}.pkl, rf_model_{T}.pkl,
                  scaler_sklearn_{T}.pkl, feature_cols_sklearn_{T}.pkl
"""

import os
import logging

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
CONTAINER  = "trained-models"

logger = logging.getLogger(__name__)

_MODEL_FILES = [
    "lr_model_{ticker}.pkl",
    "rf_model_{ticker}.pkl",
    "scaler_sklearn_{ticker}.pkl",
    "feature_cols_sklearn_{ticker}.pkl",
]


def _client():
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not set.")
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(conn_str)


def upload_models_to_azure(ticker: str) -> dict:
    """Upload 4 model files for ticker to Azure. Returns {blob_name: ok/error}."""
    ticker  = ticker.upper()
    results = {}
    try:
        client = _client()
        container = client.get_container_client(CONTAINER)
        try:
            container.create_container()
        except Exception:
            pass

        for template in _MODEL_FILES:
            fname = template.format(ticker=ticker)
            fpath = os.path.join(MODELS_DIR, fname)
            if not os.path.exists(fpath):
                results[fname] = "not found locally"
                continue
            try:
                with open(fpath, "rb") as f:
                    container.upload_blob(fname, f, overwrite=True)
                results[fname] = "ok"
                logger.info("Uploaded %s to Azure.", fname)
            except Exception as e:
                results[fname] = str(e)
    except Exception as e:
        logger.error("Azure upload failed: %s", e)
        results["error"] = str(e)
    return results


def download_models_from_azure(ticker: str) -> dict:
    """Download ticker models from Azure to Saved Models/. Returns {blob_name: ok/error}."""
    ticker  = ticker.upper()
    results = {}
    try:
        client    = _client()
        container = client.get_container_client(CONTAINER)
        os.makedirs(MODELS_DIR, exist_ok=True)

        for template in _MODEL_FILES:
            fname = template.format(ticker=ticker)
            fpath = os.path.join(MODELS_DIR, fname)
            if os.path.exists(fpath):
                results[fname] = "already exists"
                continue
            try:
                blob = container.get_blob_client(fname)
                with open(fpath, "wb") as f:
                    f.write(blob.download_blob().readall())
                results[fname] = "ok"
                logger.info("Downloaded %s from Azure.", fname)
            except Exception as e:
                results[fname] = str(e)
    except Exception as e:
        logger.error("Azure download failed: %s", e)
        results["error"] = str(e)
    return results


def list_models_in_azure() -> list:
    """List all blobs in the trained-models container."""
    try:
        client    = _client()
        container = client.get_container_client(CONTAINER)
        return [b.name for b in container.list_blobs()]
    except Exception as e:
        logger.error("Azure list failed: %s", e)
        return []


def azure_enabled() -> bool:
    """Return True if Azure connection string is configured."""
    return bool(os.environ.get("AZURE_STORAGE_CONNECTION_STRING"))
