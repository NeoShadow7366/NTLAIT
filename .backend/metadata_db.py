import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class MetadataDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        if self.db_path != ':memory:':
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Enable WAL mode for concurrent read/write safety
        cursor.execute('PRAGMA journal_mode=WAL')
        
        # Create Models Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            vault_category TEXT NOT NULL,
            file_hash TEXT UNIQUE,
            metadata_json TEXT,
            thumbnail_path TEXT,
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_available INTEGER DEFAULT 0,
            latest_version_id INTEGER
        )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON models(file_hash)')
        
        # Backward compatibility for existing databases
        try:
            cursor.execute("ALTER TABLE models ADD COLUMN update_available INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE models ADD COLUMN latest_version_id INTEGER")
        except sqlite3.OperationalError: pass

        # Generations table — My Creations gallery
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT,
            prompt TEXT,
            negative TEXT,
            model TEXT,
            seed INTEGER,
            steps INTEGER,
            cfg REAL,
            sampler TEXT,
            width INTEGER,
            height INTEGER,
            rating INTEGER DEFAULT 0,
            tags TEXT,
            extra_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT UNIQUE,
            vector_json TEXT,
            last_embedded TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT,
            tag TEXT,
            UNIQUE(file_hash, tag)
        )
        ''')

        # Prompt Library table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            prompt TEXT,
            negative TEXT,
            model TEXT,
            tags TEXT,
            extra_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()
        logging.info(f"Database initialized at {self.db_path}")

    def insert_or_update_model(self, filename: str, vault_category: str, file_hash: str, metadata_json: str = None, thumbnail_path: str = None):
        """Inserts a newly crawled model into the dictionary, or updates its metadata if it exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO models (filename, vault_category, file_hash, metadata_json, thumbnail_path, last_scanned)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(file_hash) DO UPDATE SET
            filename=excluded.filename,
            vault_category=excluded.vault_category,
            metadata_json=COALESCE(excluded.metadata_json, models.metadata_json),
            thumbnail_path=COALESCE(excluded.thumbnail_path, models.thumbnail_path),
            last_scanned=CURRENT_TIMESTAMP
        ''', (filename, vault_category, file_hash, metadata_json, thumbnail_path))
        
        conn.commit()
        conn.close()
        
    def get_model_by_hash(self, file_hash: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE file_hash = ?', (file_hash,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_filenames(self):
        """Returns a set of all tracked filenames to allow fast skips during crawling."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM models')
        rows = cursor.fetchall()
        conn.close()
        return set(row[0] for row in rows)

    def get_unpopulated_models(self):
        """Returns models where metadata_json is strictly NULL."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE metadata_json IS NULL')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
        
    def update_model_metadata(self, file_hash: str, metadata_json: str, thumbnail_path: str = None):
        """Updates a specific model with JSON metadata and an optional thumbnail path."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        UPDATE models 
        SET metadata_json = ?, thumbnail_path = ?, last_scanned = CURRENT_TIMESTAMP
        WHERE file_hash = ?
        ''', (metadata_json, thumbnail_path, file_hash))
        
        conn.commit()
        conn.close()

    def save_generation(self, image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO generations (image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json))
        rowid = cursor.lastrowid
        conn.commit()
        conn.close()
        return rowid

    def list_generations(self, sort='newest', limit=100, offset=0):
        order = 'created_at ASC' if sort == 'oldest' else ('rating DESC' if sort == 'top_rated' else 'created_at DESC')
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM generations ORDER BY {order} LIMIT ? OFFSET ?', (limit, offset))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_generation(self, gen_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute('DELETE FROM generations WHERE id = ?', (gen_id,))
        conn.commit()
        conn.close()

    def rate_generation(self, gen_id, rating):
        conn = sqlite3.connect(self.db_path)
        conn.execute('UPDATE generations SET rating=? WHERE id=?', (rating, gen_id))
        conn.commit()
        conn.close()

    def save_embedding(self, file_hash: str, vector_json: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO embeddings (file_hash, vector_json, last_embedded)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(file_hash) DO UPDATE SET
            vector_json=excluded.vector_json,
            last_embedded=CURRENT_TIMESTAMP
        ''', (file_hash, vector_json))
        conn.commit()
        conn.close()

    def get_all_embeddings(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT file_hash, vector_json FROM embeddings')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_user_tag(self, file_hash: str, tag: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO user_tags (file_hash, tag) VALUES (?, ?)', (file_hash, tag))
        conn.commit()
        conn.close()

    def remove_user_tag(self, file_hash: str, tag: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_tags WHERE file_hash = ? AND tag = ?', (file_hash, tag))
        conn.commit()
        conn.close()

    def get_user_tags(self, file_hash: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = lambda cursor, row: row[0]
        cursor = conn.cursor()
        cursor.execute('SELECT tag FROM user_tags WHERE file_hash = ?', (file_hash,))
        tags = cursor.fetchall()
        conn.close()
        return tags

    def get_all_user_tags(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = lambda cursor, row: row[0]
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT tag FROM user_tags ORDER BY tag')
        tags = cursor.fetchall()
        conn.close()
        return tags
        
    def get_models_unembedded(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.* 
            FROM models m 
            LEFT JOIN embeddings e ON m.file_hash = e.file_hash 
            WHERE e.file_hash IS NULL
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_models_for_update_check(self):
        """Returns all models that have CIVITAI metadata to check for updates."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT file_hash, metadata_json FROM models WHERE metadata_json IS NOT NULL")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def set_model_update_status(self, file_hash: str, update_available: int, latest_version_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE models 
            SET update_available = ?, latest_version_id = ?
            WHERE file_hash = ?
        ''', (update_available, latest_version_id, file_hash))
        conn.commit()
        conn.close()

    # ── Prompt Library ──────────────────────────────────────────────

    def save_prompt(self, title: str, prompt: str = "", negative: str = "", model: str = "", tags: str = "", extra_json: str = None) -> int:
        """Saves a favorite prompt to the library. Returns the new row ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO prompts (title, prompt, negative, model, tags, extra_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, prompt, negative, model, tags, extra_json))
        rowid = cursor.lastrowid
        conn.commit()
        conn.close()
        return rowid

    def list_prompts(self, search: str = None, limit: int = 100) -> list:
        """Returns saved prompts, optionally filtered by title/content substring."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if search:
            like = f"%{search}%"
            cursor.execute(
                'SELECT * FROM prompts WHERE title LIKE ? OR prompt LIKE ? ORDER BY id DESC LIMIT ?',
                (like, like, limit)
            )
        else:
            cursor.execute('SELECT * FROM prompts ORDER BY id DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_prompt(self, prompt_id: int) -> None:
        """Deletes a saved prompt by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
        conn.commit()
        conn.close()

    # ── Bulk Vault Operations ───────────────────────────────────────

    def remove_models_by_filenames(self, filenames: list) -> int:
        """Batch-delete models by filename within a single transaction. Returns count deleted."""
        if not filenames:
            return 0
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        deleted = 0
        try:
            for fn in filenames:
                cursor.execute('DELETE FROM models WHERE filename = ?', (fn,))
                deleted += cursor.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return deleted

    def remove_model_by_filename(self, filename: str) -> None:
        """Removes a single model entry by filename."""
        conn = sqlite3.connect(self.db_path)
        conn.execute('DELETE FROM models WHERE filename = ?', (filename,))
        conn.commit()
        conn.close()

    # ── Vault Export ────────────────────────────────────────────────

    def export_models_metadata(self, filenames: list) -> list:
        """Returns full metadata dicts for a list of filenames, for portable backup manifests."""
        if not filenames:
            return []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        results = []
        for fn in filenames:
            cursor.execute('SELECT * FROM models WHERE filename = ?', (fn,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d['user_tags'] = self.get_user_tags(d.get('file_hash', ''))
                results.append(d)
        conn.close()
        return results

    # ── Dashboard Analytics ─────────────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        """Returns aggregate statistics for the dashboard analytics widget."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM models')
        total_models = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM generations')
        total_generations = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM prompts')
        prompts_saved = cursor.fetchone()[0]

        conn.close()
        return {
            'total_models': total_models,
            'total_generations': total_generations,
            'prompts_saved': prompts_saved
        }

    # ── Vault Import (Sprint 9) ──────────────────────────────────────

    def import_models_metadata(self, manifest: list) -> dict:
        """Imports model metadata from a vault_manifest.json export.
        Upserts by file_hash: existing entries are updated, new entries are inserted.
        Returns {imported: int, skipped: int, failed: list}."""
        imported = 0
        skipped = 0
        failed = []
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            for entry in manifest:
                filename = entry.get('filename')
                vault_category = entry.get('vault_category', '')
                file_hash = entry.get('file_hash')
                metadata_json = entry.get('metadata_json')
                thumbnail_path = entry.get('thumbnail_path')

                if not filename or not file_hash:
                    failed.append({'filename': filename or '(unknown)', 'reason': 'Missing filename or file_hash'})
                    continue

                # Check if already exists
                cursor.execute('SELECT id FROM models WHERE file_hash = ?', (file_hash,))
                existing = cursor.fetchone()
                if existing:
                    skipped += 1
                    continue

                cursor.execute('''
                INSERT INTO models (filename, vault_category, file_hash, metadata_json, thumbnail_path, last_scanned)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(file_hash) DO UPDATE SET
                    filename=excluded.filename,
                    vault_category=excluded.vault_category,
                    metadata_json=COALESCE(excluded.metadata_json, models.metadata_json),
                    thumbnail_path=COALESCE(excluded.thumbnail_path, models.thumbnail_path),
                    last_scanned=CURRENT_TIMESTAMP
                ''', (filename, vault_category, file_hash, metadata_json, thumbnail_path))
                imported += 1

                # Restore user tags if present
                user_tags = entry.get('user_tags', [])
                for tag in user_tags:
                    cursor.execute('INSERT OR IGNORE INTO user_tags (file_hash, tag) VALUES (?, ?)', (file_hash, tag))

            conn.commit()
        except Exception as e:
            conn.rollback()
            failed.append({'filename': '(batch)', 'reason': str(e)})
        finally:
            conn.close()
        return {'imported': imported, 'skipped': skipped, 'failed': failed}

    # ── Recent Activity (Sprint 9) ─────────────────────────────────

    def get_recent_activity(self, limit: int = 5) -> list:
        """Returns the most recent generations for the dashboard activity feed."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, prompt, model, created_at, seed, width, height
            FROM generations
            ORDER BY id DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Vault Category Distribution (Sprint 9) ─────────────────────

    def get_vault_category_distribution(self) -> dict:
        """Returns {category: count} for all models, grouped by vault_category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT vault_category, COUNT(*) FROM models GROUP BY vault_category ORDER BY COUNT(*) DESC')
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}

    # ── Gallery Tags (Sprint 10) ───────────────────────────────────

    def get_gallery_tags(self) -> list:
        """Returns distinct tags across all generations that have non-null tags."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT tags FROM generations WHERE tags IS NOT NULL AND tags != ""')
        rows = cursor.fetchall()
        conn.close()
        # Tags are comma-separated strings; split, deduplicate, and sort
        all_tags = set()
        for row in rows:
            for tag in row[0].split(','):
                tag = tag.strip()
                if tag:
                    all_tags.add(tag)
        return sorted(all_tags)

    def list_generations_by_tag(self, tag: str, limit: int = 100, offset: int = 0) -> list:
        """Returns generations filtered by a tag substring match."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        like = f"%{tag}%"
        cursor.execute(
            'SELECT * FROM generations WHERE tags LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?',
            (like, limit, offset)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    db_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".backend", "metadata.sqlite")
    MetadataDB(db_file)

