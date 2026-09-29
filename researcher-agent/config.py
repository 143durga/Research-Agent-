import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024  # 25MB default
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf"}

    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
    EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")

    # Simple local API-key gate for the JSON API (optional; if unset, API is open on localhost).
    APP_API_KEY = os.environ.get("APP_API_KEY", "")

    RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))

    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_UPLOAD_EXTENSIONS
