import unittest
import tempfile
import os
import shutil
import sys
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(os.path.dirname(current_dir), ".backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from vault_crawler import VaultCrawler
from metadata_db import MetadataDB

class TestVaultCrawler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.temp_dir, "Global_Vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        
        # Create categories
        self.ckpt_dir = os.path.join(self.vault_dir, "checkpoints")
        self.loras_dir = os.path.join(self.vault_dir, "loras")
        os.makedirs(self.ckpt_dir, exist_ok=True)
        os.makedirs(self.loras_dir, exist_ok=True)
        
        # Need to dynamically place the SQLite DB in our temp dir so we don't pollute the real one
        self.db_path = os.path.join(self.temp_dir, ".backend", "metadata.sqlite")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Override the crawler's initialization statically to force it to use temp_dir
        self.crawler = VaultCrawler(self.temp_dir)
        self.crawler.db_path = self.db_path
        self.crawler.db = MetadataDB(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_dummy_file(self, path, size_mb, content_char=b'0'):
        with open(path, 'wb') as f:
            f.write(content_char * (1024 * 1024 * size_mb))

    def test_concurrent_hashing(self):
        """Verify the ThreadPoolExecutor securely processes multiple large files without locking SQLite DB."""
        files_to_make = [
            (os.path.join(self.ckpt_dir, "model1.safetensors"), b'A'),
            (os.path.join(self.ckpt_dir, "model2.safetensors"), b'B'),
            (os.path.join(self.loras_dir, "lora1.safetensors"), b'C'),
            (os.path.join(self.loras_dir, "lora2.safetensors"), b'D'),
        ]
        
        for p, char in files_to_make:
             # Fast 1MB dummy binaries
            self._create_dummy_file(p, 1, char)
            
        # Run threaded crawler
        self.crawler.crawl()
        
        # Assert database natively updated concurrently
        db = MetadataDB(self.db_path)
        tracked = db.get_all_filenames()
        
        self.assertEqual(len(tracked), 4)
        self.assertIn("model1.safetensors", tracked)
        self.assertIn("lora2.safetensors", tracked)
        
        # Run it again to prove skipping works
        self.crawler.crawl()
        self.assertEqual(len(db.get_all_filenames()), 4)

    def test_manager_ignore_logic(self):
        """Verify the crawler respects .manager_ignore nested configs."""
        secure_dir = os.path.join(self.ckpt_dir, "hidden", ".manager_ignore")
        os.makedirs(os.path.dirname(secure_dir), exist_ok=True)
        with open(secure_dir, 'w') as f:
            f.write("")
            
        file_path = os.path.join(os.path.dirname(secure_dir), "secret.safetensors")
        self._create_dummy_file(file_path, 1, b'X')
        
        self.crawler.crawl()
        
        db = MetadataDB(self.db_path)
        tracked = db.get_all_filenames()
        self.assertNotIn("secret.safetensors", tracked)

if __name__ == '__main__':
    unittest.main()
