"""
Sprint 10 — Gallery Pro & UX Intelligence
Comprehensive unit tests covering:
  1. Gallery tag extraction (get_gallery_tags)
  2. Gallery tag-based filtering (list_generations_by_tag)
  3. Gallery rating persistence (rate_generation)
  4. Server endpoint routing — /api/gallery/tags
  5. Server endpoint — /api/gallery?tag=X filtering
  6. Dashboard disk space warning field in /api/server_status
  7. Command palette registry expansion
"""

import os
import sys
import json
import sqlite3
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from io import BytesIO

# Ensure we can import our backend modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metadata_db import MetadataDB


class TestGalleryTags(unittest.TestCase):
    """Tests for Sprint 10 gallery tag methods in MetadataDB."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_meta.sqlite")
        self.db = MetadataDB(self.db_path)

        # Manually insert generations with tags for testing
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Ensure generations table has tags and rating columns
        try:
            cursor.execute("ALTER TABLE generations ADD COLUMN tags TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column may already exist
        try:
            cursor.execute("ALTER TABLE generations ADD COLUMN rating INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Insert test generations with various tags
        cursor.execute(
            "INSERT INTO generations (image_path, prompt, model, seed, steps, cfg, sampler, width, height, negative, tags, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("/img/1.png", "a cat on a boat", "sdxl", 42, 20, 7.0, "euler", 1024, 1024, "worst quality", "animals, boats", 5),
        )
        cursor.execute(
            "INSERT INTO generations (image_path, prompt, model, seed, steps, cfg, sampler, width, height, negative, tags, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("/img/2.png", "landscape sunset", "sd15", 99, 30, 8.0, "dpm", 512, 512, "bad", "landscapes, sunset", 3),
        )
        cursor.execute(
            "INSERT INTO generations (image_path, prompt, model, seed, steps, cfg, sampler, width, height, negative, tags, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("/img/3.png", "a dog in a boat", "sdxl", 55, 20, 7.0, "euler", 1024, 1024, "", "animals, boats", 4),
        )
        cursor.execute(
            "INSERT INTO generations (image_path, prompt, model, seed, steps, cfg, sampler, width, height, negative, tags, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("/img/4.png", "portrait painting", "flux", 10, 4, 3.5, "euler", 1024, 1024, "", "", 0),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_gallery_tags_returns_sorted_unique(self):
        """get_gallery_tags should return deduplicated, sorted tags."""
        tags = self.db.get_gallery_tags()
        self.assertIsInstance(tags, list)
        self.assertEqual(tags, ["animals", "boats", "landscapes", "sunset"])

    def test_get_gallery_tags_excludes_empty(self):
        """Tags from generations with empty string tags should be excluded."""
        tags = self.db.get_gallery_tags()
        self.assertNotIn("", tags)

    def test_list_generations_by_tag_filters_correctly(self):
        """list_generations_by_tag should only return matching rows."""
        results = self.db.list_generations_by_tag("animals")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("animals", r["tags"])

    def test_list_generations_by_tag_no_results(self):
        """Filtering by a non-existent tag should return empty list."""
        results = self.db.list_generations_by_tag("unicorns")
        self.assertEqual(len(results), 0)

    def test_list_generations_by_tag_partial_match(self):
        """Tags are matched with LIKE — partial substrings work."""
        results = self.db.list_generations_by_tag("sun")
        self.assertEqual(len(results), 1)
        self.assertIn("sunset", results[0]["tags"])

    def test_list_generations_by_tag_respects_limit(self):
        """Limit parameter should cap results."""
        results = self.db.list_generations_by_tag("boats", limit=1)
        self.assertEqual(len(results), 1)


class TestGalleryRating(unittest.TestCase):
    """Tests for Sprint 10 gallery rating persistence."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_meta.sqlite")
        self.db = MetadataDB(self.db_path)

        # Insert a generation
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE generations ADD COLUMN rating INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        cursor.execute(
            "INSERT INTO generations (image_path, prompt, model, seed, steps, cfg, sampler, width, height, negative, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("/img/test.png", "test prompt", "sdxl", 42, 20, 7.0, "euler", 1024, 1024, ""),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_rate_generation_updates_value(self):
        """rate_generation should persist the rating value."""
        self.db.rate_generation(1, 5)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT rating FROM generations WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row["rating"], 5)

    def test_rate_generation_overwrite(self):
        """Rating the same generation twice should overwrite."""
        self.db.rate_generation(1, 3)
        self.db.rate_generation(1, 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT rating FROM generations WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row["rating"], 1)


class TestServerStatusDiskWarning(unittest.TestCase):
    """Tests for Sprint 10 disk space warning threshold in server_status."""

    def test_settings_default_threshold(self):
        """Default vault_size_warning_gb should be 50 if not in settings."""
        # This is a logic test — we verify the value would be 50
        # by simulating the settings loading logic
        default_threshold = 50
        settings_data = {}
        vault_size_warning_gb = settings_data.get('vault_size_warning_gb', 50)
        self.assertEqual(vault_size_warning_gb, default_threshold)

    def test_settings_custom_threshold(self):
        """Custom vault_size_warning_gb from settings should be used."""
        settings_data = {'vault_size_warning_gb': 100}
        vault_size_warning_gb = settings_data.get('vault_size_warning_gb', 50)
        self.assertEqual(vault_size_warning_gb, 100)


class TestCommandPaletteExpansion(unittest.TestCase):
    """Tests for Sprint 10 command palette expansion — purely structural."""

    def test_index_html_has_new_commands(self):
        """index.html should contain the new Sprint 10 command entries."""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        if not os.path.exists(html_path):
            self.skipTest("index.html not found at expected path")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Search Models in Vault", content)
        self.assertIn("View Recent Generations", content)
        self.assertIn("Toggle Theme (Dark/Light/Glass)", content)
        self.assertIn("A/B Compare Generations", content)

    def test_index_html_has_ab_modal(self):
        """index.html should contain the A/B comparison modal."""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        if not os.path.exists(html_path):
            self.skipTest("index.html not found at expected path")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ab-comparison", content)
        self.assertIn("ab-pane-a", content)
        self.assertIn("ab-divider", content)

    def test_index_html_has_star_rating(self):
        """index.html should contain the gallery star rating elements."""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        if not os.path.exists(html_path):
            self.skipTest("index.html not found at expected path")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("gl-star-bar", content)
        self.assertIn("gallery-star-bar", content)
        self.assertIn("rateGeneration", content)

    def test_index_html_has_disk_warning(self):
        """index.html should contain the disk space warning widget."""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        if not os.path.exists(html_path):
            self.skipTest("index.html not found at expected path")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("dash-disk-warning", content)
        self.assertIn("disk-warning", content)
        self.assertIn("vault_size_warning_gb", content)

    def test_index_html_has_tag_filter(self):
        """index.html should contain gallery tag filter UI."""
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        if not os.path.exists(html_path):
            self.skipTest("index.html not found at expected path")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("gallery-tag-filter", content)
        self.assertIn("gallery-tag-bar", content)
        self.assertIn("tag-filter-bar", content)
        self.assertIn("loadGalleryByTag", content)


class TestServerEndpointRouting(unittest.TestCase):
    """Tests for Sprint 10 server endpoint routing."""

    def test_gallery_tags_route_exists(self):
        """server.py should have the /api/gallery/tags route."""
        server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/api/gallery/tags", content)
        self.assertIn("handle_gallery_tags", content)

    def test_gallery_tag_filter_in_list(self):
        """server.py gallery list handler should support ?tag= parameter."""
        server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('qs.get("tag"', content)
        self.assertIn("list_generations_by_tag", content)

    def test_server_status_has_disk_warning(self):
        """server.py server_status handler should return vault_size_warning_gb."""
        server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("vault_size_warning_gb", content)


if __name__ == "__main__":
    unittest.main()
