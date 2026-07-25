import unittest

from fastapi.testclient import TestClient

from chat.server.main import app
from core.config import settings


class RemoteAPISecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous_token = settings.access_token
        self.previous_remote_coding = settings.allow_remote_coding
        settings.access_token = "test-secret-token"
        settings.allow_remote_coding = False
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        settings.access_token = self.previous_token
        settings.allow_remote_coding = self.previous_remote_coding

    def test_remote_api_requires_token(self):
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/sessions",
            headers={"X-Lasme-Token": "test-secret-token"},
        )
        self.assertEqual(response.status_code, 200)

    def test_remote_coding_api_stays_disabled_with_valid_token(self):
        response = self.client.get(
            "/api/coding/tree",
            headers={"X-Lasme-Token": "test-secret-token"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
