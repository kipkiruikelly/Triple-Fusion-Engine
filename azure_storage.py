"""
azure_storage.py
Azure Blob Storage integration for BullLogic model artifacts.

Container : trained-models
Auth      : AZURE_STORAGE_CONNECTION_STRING env var

Uploads/downloads every *.pkl file in Saved Models/ that belongs to
a given ticker (handles both old 4-file and professional multi-TF layouts).
"""

import os
import glob
import logging

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
CONTAINER  = "trained-models"

logger = logging.getLogger(__name__)


def _client():
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not set.")
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(conn_str)


def _ticker_files(ticker: str) -> list[str]:
    """Return all local .pkl files that belong to this ticker."""
    T = ticker.upper()
    patterns = [
        os.path.join(MODELS_DIR, f"*_{T}.pkl"),
        os.path.join(MODELS_DIR, f"*_{T}_*.pkl"),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    return sorted(set(files))


def upload_models_to_azure(ticker: str) -> dict:
    """Upload all model files for ticker to Azure. Returns {blob_name: ok/error}."""
    ticker  = ticker.upper()
    results = {}
    try:
        client    = _client()
        container = client.get_container_client(CONTAINER)
        try:
            container.create_container()
        except Exception:
            pass

        files = _ticker_files(ticker)
        if not files:
            logger.warning("No local model files found for %s.", ticker)
            return {"warning": f"no files for {ticker}"}

        for fpath in files:
            fname = os.path.basename(fpath)
            try:
                with open(fpath, "rb") as f:
                    container.upload_blob(fname, f, overwrite=True)
                results[fname] = "ok"
                logger.info("Uploaded %s to Azure.", fname)
            except Exception as e:
                results[fname] = str(e)
                logger.error("Failed to upload %s: %s", fname, e)
    except Exception as e:
        logger.error("Azure upload failed: %s", e)
        results["error"] = str(e)
    return results


def download_models_from_azure(ticker: str) -> dict:
    """Download all ticker model files from Azure to Saved Models/."""
    ticker  = ticker.upper()
    results = {}
    try:
        client    = _client()
        container = client.get_container_client(CONTAINER)
        os.makedirs(MODELS_DIR, exist_ok=True)

        blobs = [b.name for b in container.list_blobs()
                 if f"_{ticker}.pkl" in b.name or f"_{ticker}_" in b.name]

        if not blobs:
            results["warning"] = f"no blobs for {ticker}"
            return results

        for fname in blobs:
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
                logger.error("Failed to download %s: %s", fname, e)
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
