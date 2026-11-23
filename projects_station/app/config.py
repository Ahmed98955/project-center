import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("PS_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.environ.get("PS_DB_PATH", DATA_DIR / "projects_station.db"))
SEED_DIR = BASE_DIR / "app" / "seed_data"

HOST = os.environ.get("PS_HOST", "127.0.0.1")
PORT = int(os.environ.get("PS_PORT", "8765"))

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
