import os
import tempfile
import sqlite3
import unittest
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_path = os.path.join(PROJECT_ROOT, ".backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from metadata_db import MetadataDB

class TestMetadataDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_metadata.sqlite")
        self.db = MetadataDB(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        os.rmdir(self.temp_dir)

    def test_initialization(self):
        """Ensure tables are created upon initialization."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        self.assertIn("models", tables)
        self.assertIn("generations", tables)
        self.assertIn("user_tags", tables)
        self.assertIn("embeddings", tables)

    def test_upsert_model(self):
        """Verify inserting and updating a model hash works cleanly."""
        self.db.insert_or_update_model(filename="test_model.safetensors", vault_category="checkpoints", file_hash="mock_hash123", metadata_json="{}")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM models WHERE file_hash = ?", ("mock_hash123",))
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row["filename"], "test_model.safetensors")
        self.assertEqual(row["vault_category"], "checkpoints")

    def test_save_generation(self):
        """Verify the generations gallery table functions correctly."""
        row_id = self.db.save_generation(
            image_path="test.png",
            prompt="A beautiful test",
            negative="",
            model="SD 1.5",
            seed=42,
            steps=20,
            cfg=7.0,
            sampler="Euler a",
            width=512,
            height=512
        )
        self.assertIsInstance(row_id, int)
        
        gens = self.db.list_generations()
        self.assertEqual(len(gens), 1)
        self.assertEqual(gens[0]["prompt"], "A beautiful test")

if __name__ == '__main__':
    unittest.main()
