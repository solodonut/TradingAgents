import pytest


@pytest.mark.smoke
def test_app_imports_and_has_routes():
    from api.main import app

    paths = {r.path for r in app.routes}
    assert "/api/config/options" in paths
    assert "/api/history" in paths
    assert "/api/analysis" in paths
