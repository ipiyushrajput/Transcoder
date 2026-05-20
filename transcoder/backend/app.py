import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify
from flask_cors import CORS
from database import init_db

def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Logging setup
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            RotatingFileHandler("logs/transcoder.log", maxBytes=50 * 1024 * 1024, backupCount=10),
            logging.StreamHandler(),
        ],
    )

    # Initialize database
    db_ok = init_db()
    if not db_ok:
        logging.warning("Database unavailable — running without persistence")

    # Register blueprints
    from routes.vod_routes import vod_bp
    from routes.live_routes import live_bp
    from routes.common_routes import common_bp

    app.register_blueprint(vod_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(common_bp)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "transcoder-api"}), 200

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
