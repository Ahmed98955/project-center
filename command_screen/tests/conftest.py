import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT.parent / "projects_station_part1" / "projects_station"

_TMP = tempfile.mkdtemp(prefix="cs_test_")
_STATION_TMP = tempfile.mkdtemp(prefix="ps_stat_")
os.environ["CS_DATA_DIR"] = _TMP
os.environ["PS_DATA_DIR"] = _STATION_TMP
os.environ["CS_POLL_SECONDS"] = "0.5"
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

# load the station app under an alias so both "app" packages can coexist
_spec = importlib.util.spec_from_file_location(
    "ps_app", STATION / "app" / "__init__.py", submodule_search_locations=[str(STATION / "app")])
ps_app = importlib.util.module_from_spec(_spec)
sys.modules["ps_app"] = ps_app
_spec.loader.exec_module(ps_app)
import ps_app.geo  # noqa: E402
import ps_app.seed  # noqa: E402
from ps_app.main import app as station_app  # noqa: E402

PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="session", autouse=True)
def station_server():
    ps_app.seed.ensure_database(reset=True)
    cfg = uvicorn.Config(station_app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture()
def client():
    # clean command db
    conn = db.connect()
    db.init_schema(conn)
    for tbl in ("tickets", "sync_state", "reference", "directives", "alert_events", "command_log"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute("DELETE FROM settings WHERE key='station_url'")
    db.set_setting(conn, "station_url", BASE)
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "Admin@2026"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture()
def station():
    c = httpx.Client(base_url=BASE, timeout=15)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "Admin@2026"})
    assert r.status_code == 200, r.text
    yield c
    c.close()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(_STATION_TMP, ignore_errors=True)
