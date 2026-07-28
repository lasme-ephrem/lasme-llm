from fastapi.testclient import TestClient
from unittest.mock import patch

from chat.server.main import app


def test_artifact_preview_is_short_lived_and_sandbox_ready() -> None:
    html = (
        "<!doctype html><html><body>"
        "<button onclick=\"this.textContent='ok'\">Tester</button>"
        "</body></html>"
    )
    with patch("chat.server.main.is_direct_local_request", return_value=True), TestClient(app) as client:
        created = client.post("/api/artifact-previews", json={"content": html})
        assert created.status_code == 200
        payload = created.json()
        assert payload["url"].startswith("/api/artifact-previews/")
        assert payload["expires_in"] == 900

        preview = client.get(payload["url"])
        assert preview.status_code == 200
        assert preview.text == html
        assert preview.headers["cache-control"] == "no-store"
        assert preview.headers["x-frame-options"] == "SAMEORIGIN"
        policy = preview.headers["content-security-policy"]
        assert "script-src 'unsafe-inline'" in policy
        assert "connect-src 'none'" in policy
        assert "form-action 'none'" in policy


def test_artifact_preview_rejects_invalid_or_oversized_content() -> None:
    with patch("chat.server.main.is_direct_local_request", return_value=True), TestClient(app) as client:
        missing = client.get("/api/artifact-previews/not-valid")
        assert missing.status_code == 404

        oversized = client.post(
            "/api/artifact-previews",
            json={"content": "x" * 500_001},
        )
        assert oversized.status_code == 422
