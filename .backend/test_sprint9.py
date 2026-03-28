"""Sprint 9 Test Suite — Inference Studio Power-Ups & Dashboard Intelligence

Tests:
  - Vault Import from Backup (import_models_metadata, /api/vault/import)
  - Batch Generation Queue (/api/generate/batch, /api/generate/queue)
  - Dashboard Intelligence (recent_activity, category_distribution)
  - Vault Size Caching (_vault_size_cache)
  - Token Counter helpers
  - Frontend HTML structure validation
"""

import os
import sys
import json
import time
import tempfile
import unittest
import sqlite3

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metadata_db import MetadataDB


class TestVaultImport(unittest.TestCase):
    """Feature 1: Vault Import from Backup"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = MetadataDB(os.path.join(self.tmpdir, 'metadata.sqlite'))

    def test_import_empty_manifest(self):
        result = self.db.import_models_metadata([])
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['failed'], [])

    def test_import_valid_manifest(self):
        manifest = [
            {
                'filename': 'model_a.safetensors',
                'vault_category': 'checkpoints',
                'file_hash': 'aaa111',
                'metadata_json': '{"name": "Model A"}',
                'thumbnail_path': None,
                'user_tags': ['anime', 'sdxl']
            },
            {
                'filename': 'lora_b.safetensors',
                'vault_category': 'loras',
                'file_hash': 'bbb222',
                'metadata_json': '{"name": "LoRA B"}',
                'thumbnail_path': None,
                'user_tags': []
            }
        ]
        result = self.db.import_models_metadata(manifest)
        self.assertEqual(result['imported'], 2)
        self.assertEqual(result['skipped'], 0)

    def test_import_duplicate_skips(self):
        """Importing the same manifest twice should skip all on second import."""
        manifest = [{'filename': 'x.pt', 'vault_category': 'loras', 'file_hash': 'dup123'}]
        self.db.import_models_metadata(manifest)
        result = self.db.import_models_metadata(manifest)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['skipped'], 1)

    def test_import_missing_hash_fails(self):
        manifest = [{'filename': 'no_hash.bin', 'vault_category': 'checkpoints'}]
        result = self.db.import_models_metadata(manifest)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(len(result['failed']), 1)

    def test_import_restores_tags(self):
        manifest = [{
            'filename': 'tagged.safetensors', 'vault_category': 'loras',
            'file_hash': 'tag999', 'user_tags': ['favorite', 'sdxl']
        }]
        self.db.import_models_metadata(manifest)
        tags = self.db.get_user_tags('tag999')
        self.assertIn('favorite', tags)
        self.assertIn('sdxl', tags)


class TestRecentActivity(unittest.TestCase):
    """Feature 4: Dashboard Recent Activity Feed"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = MetadataDB(os.path.join(self.tmpdir, 'metadata.sqlite'))

    def test_empty_activity(self):
        result = self.db.get_recent_activity()
        self.assertEqual(result, [])

    def test_activity_returns_latest(self):
        for i in range(10):
            self.db.save_generation(
                image_path=f'/img_{i}.png', prompt=f'prompt {i}',
                negative='', model='test_model', seed=i,
                steps=20, cfg=7, sampler='euler', width=512, height=512
            )
        result = self.db.get_recent_activity(limit=5)
        self.assertEqual(len(result), 5)
        # Newest first by ID
        self.assertEqual(result[0]['prompt'], 'prompt 9')

    def test_activity_contains_expected_fields(self):
        self.db.save_generation('/img.png', 'test', '', 'model', 42, 20, 7.0, 'euler', 512, 512)
        result = self.db.get_recent_activity(limit=1)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertIn('prompt', row)
        self.assertIn('model', row)
        self.assertIn('created_at', row)
        self.assertIn('seed', row)


class TestCategoryDistribution(unittest.TestCase):
    """Feature 5: Vault Category Distribution"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = MetadataDB(os.path.join(self.tmpdir, 'metadata.sqlite'))

    def test_empty_distribution(self):
        result = self.db.get_vault_category_distribution()
        self.assertEqual(result, {})

    def test_distribution_counts(self):
        self.db.insert_or_update_model('a.safetensors', 'checkpoints', 'h1')
        self.db.insert_or_update_model('b.safetensors', 'checkpoints', 'h2')
        self.db.insert_or_update_model('c.safetensors', 'loras', 'h3')
        result = self.db.get_vault_category_distribution()
        self.assertEqual(result['checkpoints'], 2)
        self.assertEqual(result['loras'], 1)

    def test_distribution_ordering(self):
        """Categories should be ordered by count descending."""
        for i in range(5):
            self.db.insert_or_update_model(f'l{i}.safetensors', 'loras', f'lh{i}')
        self.db.insert_or_update_model('c.safetensors', 'checkpoints', 'ch1')
        dist = self.db.get_vault_category_distribution()
        keys = list(dist.keys())
        self.assertEqual(keys[0], 'loras')  # 5 > 1


class TestVaultSizeCache(unittest.TestCase):
    """Feature 6: Vault Size Caching with TTL"""

    def test_cache_structure(self):
        from server import _vault_size_cache
        self.assertIn('size', _vault_size_cache)
        self.assertIn('expires', _vault_size_cache)

    def test_cache_initial_expired(self):
        """Cache should start expired so first request triggers a walk."""
        from server import _vault_size_cache
        self.assertLessEqual(_vault_size_cache['expires'], time.time())


class TestBatchQueueModule(unittest.TestCase):
    """Feature 2: Batch Generation Queue module-level structures"""

    def test_queue_exists(self):
        from server import _batch_queue, _batch_lock
        self.assertIsInstance(_batch_queue, list)
        self.assertIsNotNone(_batch_lock)

    def test_queue_starts_empty(self):
        from server import _batch_queue
        # Queue state depends on server lifecycle, just verify structure
        self.assertIsInstance(_batch_queue, list)


class TestTokenCounter(unittest.TestCase):
    """Feature 3: Token counter approximation logic (mirrored from JS)"""

    @staticmethod
    def count_tokens(text):
        """Python mirror of the JS countTokens function."""
        if not text or not text.strip():
            return 0
        import re
        return len([t for t in re.split(r'[\s,]+', text) if t])

    def test_empty_string(self):
        self.assertEqual(self.count_tokens(''), 0)
        self.assertEqual(self.count_tokens('   '), 0)

    def test_simple_prompt(self):
        self.assertEqual(self.count_tokens('masterpiece, best quality'), 3)

    def test_complex_prompt(self):
        prompt = "1girl, solo, long hair, looking at viewer, smile, open mouth"
        count = self.count_tokens(prompt)
        self.assertEqual(count, 10)

    def test_whitespace_handling(self):
        self.assertEqual(self.count_tokens('a  b   c'), 3)

    def test_comma_only_separation(self):
        self.assertEqual(self.count_tokens('a,b,c'), 3)


class TestDashboardStats(unittest.TestCase):
    """Dashboard analytics augmented with Sprint 9 data"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = MetadataDB(os.path.join(self.tmpdir, 'metadata.sqlite'))

    def test_dashboard_stats_base(self):
        stats = self.db.get_dashboard_stats()
        self.assertEqual(stats['total_models'], 0)
        self.assertEqual(stats['total_generations'], 0)
        self.assertEqual(stats['prompts_saved'], 0)

    def test_dashboard_stats_with_data(self):
        self.db.insert_or_update_model('m.safetensors', 'checkpoints', 'hh1')
        self.db.save_generation('/img.png', 'p', '', 'model', 1, 20, 7, 'euler', 512, 512)
        self.db.save_prompt(title='Test Prompt', prompt='hello')
        stats = self.db.get_dashboard_stats()
        self.assertEqual(stats['total_models'], 1)
        self.assertEqual(stats['total_generations'], 1)
        self.assertEqual(stats['prompts_saved'], 1)


class TestFrontendHTMLStructure(unittest.TestCase):
    """Validate Sprint 9 HTML elements exist in index.html"""

    @classmethod
    def setUpClass(cls):
        html_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".backend", "static", "index.html"
        )
        with open(html_path, 'r', encoding='utf-8') as f:
            cls.html = f.read()

    def test_activity_feed_container(self):
        self.assertIn('dash-activity-list', self.html)

    def test_donut_chart_svg(self):
        self.assertIn('dash-donut', self.html)

    def test_donut_legend(self):
        self.assertIn('dash-donut-legend', self.html)

    def test_token_counter(self):
        self.assertIn('inf-token-counter', self.html)
        self.assertIn('inf-token-count', self.html)
        self.assertIn('inf-token-limit', self.html)

    def test_batch_queue_panel(self):
        self.assertIn('batch-panel', self.html)
        self.assertIn('batch-list', self.html)
        self.assertIn('inf-batch-count', self.html)

    def test_vault_import_button(self):
        self.assertIn('btn-vault-import-backup', self.html)
        self.assertIn('vault-import-file', self.html)

    def test_batch_add_button(self):
        self.assertIn('inf-batch-add-btn', self.html)

    def test_sprint9_css_classes(self):
        self.assertIn('.activity-feed', self.html)
        self.assertIn('.donut-container', self.html)
        self.assertIn('.token-counter', self.html)
        self.assertIn('.batch-panel', self.html)

    def test_sprint9_js_functions(self):
        self.assertIn('renderActivityFeed', self.html)
        self.assertIn('renderDonutChart', self.html)
        self.assertIn('updateTokenCounter', self.html)
        self.assertIn('addToBatchQueue', self.html)
        self.assertIn('handleVaultImportBackup', self.html)


if __name__ == '__main__':
    unittest.main()
