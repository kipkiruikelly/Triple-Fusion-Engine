"""
wsgi.py
Production entry point — serves the Flask app with waitress instead of
the Flask/Werkzeug development server (no interactive debugger, no
reloader, safe for long-running/background use).

Usage:
    python wsgi.py

Host/port default to loopback-only; override via HOST/PORT env vars.
"""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    # The SSE live-price stream holds one thread per connected client
    # indefinitely, so waitress's default 4 threads starve under a couple
    # of open tabs. Keep the pool comfortably larger.
    threads = int(os.environ.get("WEB_THREADS", "24"))
    serve(app, host=host, port=port, threads=threads, channel_timeout=300)
