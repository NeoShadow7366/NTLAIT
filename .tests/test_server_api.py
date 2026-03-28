import urllib.request
import urllib.parse
import json
import unittest
from test_base import BaseQATestCase

class TestServerAPI(BaseQATestCase):
    
    def test_get_server_status(self):
        """Verify the /api/server_status endpoint returns 200 and basic metrics."""
        req = urllib.request.Request(f"{self.base_url}/api/server_status")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode('utf-8'))
            self.assertIn("unpopulated_models", data)
            self.assertIn("active_downloads", data)
            self.assertIn("is_syncing", data)

    def test_get_models_empty(self):
        """Verify the /api/models endpoint returns an empty array initially."""
        req = urllib.request.Request(f"{self.base_url}/api/models?limit=10&offset=0")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode('utf-8'))
            self.assertEqual(data["status"], "success")
            self.assertEqual(len(data["models"]), 0)
            self.assertEqual(data["total"], 0)

    def test_recipes_empty(self):
        """Verify the /api/recipes endpoint returns 200."""
        req = urllib.request.Request(f"{self.base_url}/api/recipes")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode('utf-8'))
            self.assertEqual(data["status"], "success")
            self.assertIsInstance(data["recipes"], list)

    def test_post_settings(self):
        """Verify the /api/settings POST endpoint updates user json seamlessly."""
        req = urllib.request.Request(f"{self.base_url}/api/settings", method="POST", data=b'{"theme": "light"}', headers={'Content-Type': 'application/json', 'Content-Length': '18'})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)

    def test_post_gallery_save(self):
        """Verify saving to gallery natively injects into sqlite DB via the Server HTTP routing."""
        payload = json.dumps({"image_path": "test.png", "prompt": "test"}).encode('utf-8')
        req = urllib.request.Request(f"{self.base_url}/api/gallery/save", method="POST", data=payload, headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        with urllib.request.urlopen(req) as response:
             self.assertEqual(response.status, 200)

    def test_post_vault_tag_add(self):
        """Verify tagging a model via POST routes cleanly."""
        payload = json.dumps({"file_hash": "mock", "tag": "test_tag"}).encode('utf-8')
        req = urllib.request.Request(f"{self.base_url}/api/vault/tag/add", method="POST", data=payload, headers={'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        with urllib.request.urlopen(req) as response:
             self.assertEqual(response.status, 200)

    def test_missing_api_endpoint_returns_json_404(self):
        """Verify that fetching an unknown /api/ route returns a graceful 404 JSON, not HTML."""
        req = urllib.request.Request(f"{self.base_url}/api/does_not_exist_at_all")
        try:
            with urllib.request.urlopen(req) as response:
                self.fail("Should have thrown 404 HTTP Error")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            data = json.loads(e.read().decode('utf-8'))
            self.assertIn("error", data)

if __name__ == '__main__':
    unittest.main()
