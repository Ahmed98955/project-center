import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("CS_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("CS_DB_PATH", DATA_DIR / "command_screen.db"))
UPLOAD_DIR = DATA_DIR / "uploads"

HOST = os.environ.get("CS_HOST", "127.0.0.1")
PORT = int(os.environ.get("CS_PORT", "8766"))
POLL_SECONDS = float(os.environ.get("CS_POLL_SECONDS", "2"))
DEFAULT_STATION_URL = os.environ.get("CS_STATION_URL", "http://127.0.0.1:8765")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
