from flask import Blueprint, send_from_directory
import os

react_bp = Blueprint("react_bp", __name__)

@react_bp.route("/app", defaults={"path": ""})
@react_bp.route("/app/<path:path>")
def serve_react_app(path):
    dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if not os.path.exists(dist):
        return "React frontend build not found. Run `npm run build` in frontend/", 404
    if path != "" and os.path.exists(os.path.join(dist, path)):
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")

def register_react_routes(app):
    dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.exists(dist):
        app.register_blueprint(react_bp)