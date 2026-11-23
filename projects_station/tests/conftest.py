import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="ps_test_")
os.environ["PS_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    seed.ensure_database(reset=True)
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "Admin@2026"})
        assert r.status_code == 200, r.text
        yield c


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
