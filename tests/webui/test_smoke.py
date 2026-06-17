import pytest
from fastapi.testclient import TestClient


@pytest.mark.smoke
def test_app_imports_and_has_routes():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/config/options").status_code == 200
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/analysis").status_code == 405
