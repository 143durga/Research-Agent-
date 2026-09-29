import logging
import os
from flask import Flask, jsonify, render_template, request

from config import Config
from db.database import run_migrations


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Never log secrets: filter out anything that looks like an API key value.
    class _RedactSecrets(logging.Filter):
        SENSITIVE_SUBSTRINGS = ("api_key", "apikey", "authorization", "x-api-key")

        def filter(self, record):
            msg = str(record.getMessage()).lower()
            if any(s in msg for s in self.SENSITIVE_SUBSTRINGS) and ("sk-" in msg or "key=" in msg):
                record.msg = "[redacted log message containing a potential secret]"
                record.args = ()
            return True

    logging.getLogger().addFilter(_RedactSecrets())

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    with app.app_context():
        run_migrations()

    from routes.pages import pages
    from routes.api import api
    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    def _wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify({"error": "Not found."}), 404
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(405)
    def bad_method(e):
        if _wants_json():
            return jsonify({"error": "Method not allowed."}), 405
        return render_template("error.html", code=405, message="Method not allowed."), 405

    @app.errorhandler(413)
    def too_large(e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify({"error": f"File too large. The maximum upload size is {mb} MB."}), 413

    @app.errorhandler(500)
    def server_error(e):
        logging.exception("Unhandled server error")
        if _wants_json():
            return jsonify({"error": "Unexpected server error."}), 500
        return render_template("error.html", code=500, message="Something went wrong on the server."), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Bind to localhost by default: this app has no login. Set HOST=0.0.0.0 only behind your own auth/firewall.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=app.config["DEBUG"])
