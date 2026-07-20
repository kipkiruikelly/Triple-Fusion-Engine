from flask import Blueprint, send_from_directory
import os

react_bp = Blueprint("react_bp", __name__)

@react_bp.route("/", defaults={"path": ""})
@react_bp.route("/<path:path>")
def serve_react_app(path):
    dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if path != "" and os.path.exists(os.path.join(dist, path)):
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")

def register_react_routes(app):
    app.register_blueprint(react_bp)