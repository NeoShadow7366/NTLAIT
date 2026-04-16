import sqlite3
import os
import json
import logging
import threading

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Shared constant: recognized model file extensions (used by crawler, import, handlers)
MODEL_EXTENSIONS = {".safetensors", ".pt", ".ckpt", ".bin", ".sft"}

class MetadataDB:
    """SQLite-backed metadata store with persistent connection.
    
    Uses a single persistent connection with check_same_thread=False (safe with
    WAL journal mode for concurrent reads). Write operations are serialized via
    a threading lock to prevent 'database is locked' errors.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection = None
        self._write_lock = threading.Lock()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Lazily create and cache a persistent SQLite connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10
            )
            self._connection.execute('PRAGMA journal_mode=WAL')
            self._connection.execute('PRAGMA busy_timeout=5000')
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        """Close the persistent connection. Call during shutdown or test teardown."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def _init_db(self):
        if self.db_path != ':memory:':
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = self._conn
        cursor = conn.cursor()
        
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
        # Multi-path scanning: track where each model physically lives
        try:
            cursor.execute("ALTER TABLE models ADD COLUMN source_path TEXT DEFAULT 'Global_Vault'")
        except sqlite3.OperationalError: pass
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source ON models(source_path)')

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

        # Favorites table — stores CivitAI model favorites (migrated from settings.json)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            model_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        logging.info(f"Database initialized at {self.db_path}")

    def get_models_paginated(self, limit: int = 1000, offset: int = 0) -> dict:
        """Returns paginated models with pre-joined user tags and parsed metadata.
        Returns {"models": [...], "total": int}."""
        conn = self._conn
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM models')
        total = cursor.fetchone()[0]

        cursor.execute('SELECT * FROM models ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset))
        rows = cursor.fetchall()

        # Bulk-fetch tags for this page in one query (chunked for SQLite param limit)
        hash_to_tags = {}
        if rows:
            hashes = [r["file_hash"] for r in rows if r["file_hash"]]
            if hashes:
                for i in range(0, len(hashes), 900):
                    chunk = hashes[i:i+900]
                    placeholders = ','.join('?' * len(chunk))
                    cursor.execute(f'SELECT file_hash, tag FROM user_tags WHERE file_hash IN ({placeholders})', chunk)
                    for h, tag in cursor.fetchall():
                        hash_to_tags.setdefault(h, []).append(tag)



        models = []
        for row in rows:
            d = dict(row)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except Exception:
                    d["metadata"] = {}
            else:
                d["metadata"] = {}
            d.pop("metadata_json", None)
            d["user_tags"] = hash_to_tags.get(d.get("file_hash"), [])
            models.append(d)

        return {"models": models, "total": total}

    def insert_or_update_model(self, filename: str, vault_category: str, file_hash: str,
                               metadata_json: str = None, thumbnail_path: str = None,
                               source_path: str = 'Global_Vault'):
        """Inserts a newly crawled model into the dictionary, or updates its metadata if it exists."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO models (filename, vault_category, file_hash, metadata_json, thumbnail_path, last_scanned, source_path)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(file_hash) DO UPDATE SET
                filename=excluded.filename,
                vault_category=excluded.vault_category,
                metadata_json=COALESCE(excluded.metadata_json, models.metadata_json),
                thumbnail_path=COALESCE(excluded.thumbnail_path, models.thumbnail_path),
                source_path=excluded.source_path,
                last_scanned=CURRENT_TIMESTAMP
            ''', (filename, vault_category, file_hash, metadata_json, thumbnail_path, source_path))
            
            conn.commit()

    def insert_discovered_model(self, filename: str, vault_category: str,
                                source_path: str, file_size: int = 0):
        """Fast discovery insert — registers a model WITHOUT hashing.
        Uses filename+source_path as the dedup key since hash is unknown."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            # Check if already known by filename+source
            cursor.execute(
                'SELECT id FROM models WHERE filename = ? AND source_path = ?',
                (filename, source_path))
            if cursor.fetchone():
                return  # Already discovered
            cursor.execute('''
            INSERT INTO models (filename, vault_category, file_hash, source_path, last_scanned)
            VALUES (?, ?, NULL, ?, CURRENT_TIMESTAMP)
            ''', (filename, vault_category, source_path))
            conn.commit()

    def get_unhashed_models(self, source_path: str = None) -> list:
        """Returns models where file_hash is NULL (discovered but not yet hashed)."""
        conn = self._conn
        cursor = conn.cursor()
        if source_path:
            cursor.execute('SELECT * FROM models WHERE file_hash IS NULL AND source_path = ?', (source_path,))
        else:
            cursor.execute('SELECT * FROM models WHERE file_hash IS NULL')
        return [dict(row) for row in cursor.fetchall()]

    def update_model_source(self, file_hash: str, new_source: str, new_category: str = None):
        """Update the source_path (and optionally category) after migration."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            if new_category:
                cursor.execute('UPDATE models SET source_path = ?, vault_category = ? WHERE file_hash = ?',
                               (new_source, new_category, file_hash))
            else:
                cursor.execute('UPDATE models SET source_path = ? WHERE file_hash = ?',
                               (new_source, file_hash))
            conn.commit()

        
    def get_model_by_hash(self, file_hash: str):
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE file_hash = ?', (file_hash,))
        row = cursor.fetchone()

        return dict(row) if row else None

    def get_model_by_filename(self, filename: str):
        """Look up a model by filename. Returns the first match or None."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE filename = ? LIMIT 1', (filename,))
        row = cursor.fetchone()

        return dict(row) if row else None

    def get_model_by_id(self, model_id: int):
        """Look up a model by its database ID. Returns dict or None."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE id = ?', (model_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_filenames(self):
        """Returns a set of all tracked filenames to allow fast skips during crawling."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM models')
        rows = cursor.fetchall()

        return set(row[0] for row in rows)

    def get_filenames_by_source(self, source_path: str = 'Global_Vault') -> set:
        """Returns a set of (filename, vault_category) tuples for a specific source.
        Used by the crawler to avoid filename collisions across categories."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute(
            'SELECT filename, vault_category FROM models WHERE source_path = ?',
            (source_path,))
        return set((row[0], row[1]) for row in cursor.fetchall())

    def get_vault_models_for_pruning(self, source_path: str = 'Global_Vault') -> list:
        """Returns id, filename, vault_category for all models from a given source.
        Used by VaultCrawler.prune_stale_models() to verify files still exist."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, filename, vault_category, file_hash FROM models WHERE source_path = ?',
            (source_path,))
        return [dict(row) for row in cursor.fetchall()]

    def get_unpopulated_models(self):
        """Returns models where metadata_json is strictly NULL."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE metadata_json IS NULL')
        rows = cursor.fetchall()

        return [dict(row) for row in rows]
        
    def update_model_metadata(self, file_hash: str, metadata_json: str, thumbnail_path: str = None):
        """Updates a specific model with JSON metadata and an optional thumbnail path."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE models 
            SET metadata_json = ?, thumbnail_path = ?, last_scanned = CURRENT_TIMESTAMP
            WHERE file_hash = ?
            ''', (metadata_json, thumbnail_path, file_hash))
            
            conn.commit()


    def save_generation(self, image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json=None):
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO generations (image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (image_path, prompt, negative, model, seed, steps, cfg, sampler, width, height, extra_json))
            rowid = cursor.lastrowid
            conn.commit()

            return rowid

    def list_generations(self, sort='newest', limit=100, offset=0):
        # S2-7: Explicit allowlist prevents SQL injection if new sort options are added
        _SORT_MAP = {
            'newest': 'created_at DESC',
            'oldest': 'created_at ASC',
            'top_rated': 'rating DESC'
        }
        order = _SORT_MAP.get(sort, 'created_at DESC')
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM generations ORDER BY {order} LIMIT ? OFFSET ?', (limit, offset))
        rows = cursor.fetchall()

        return [dict(r) for r in rows]

    def delete_generation(self, gen_id):
        with self._write_lock:
            conn = self._conn
            conn.execute('DELETE FROM generations WHERE id = ?', (gen_id,))
            conn.commit()


    def batch_delete_generations(self, gen_ids: list) -> int:
        """Delete multiple generations in a single SQL statement.
        Returns count of deleted rows."""
        if not gen_ids:
            return 0
        with self._write_lock:
            conn = self._conn
            placeholders = ','.join('?' for _ in gen_ids)
            cursor = conn.execute(f'DELETE FROM generations WHERE id IN ({placeholders})', gen_ids)
            deleted = cursor.rowcount
            conn.commit()

            return deleted

    def rate_generation(self, gen_id, rating):
        with self._write_lock:
            conn = self._conn
            conn.execute('UPDATE generations SET rating=? WHERE id=?', (rating, gen_id))
            conn.commit()


    def save_embedding(self, file_hash: str, vector_json: str):
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO embeddings (file_hash, vector_json, last_embedded)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_hash) DO UPDATE SET
                vector_json=excluded.vector_json,
                last_embedded=CURRENT_TIMESTAMP
            ''', (file_hash, vector_json))
            conn.commit()


    def get_all_embeddings(self):
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT file_hash, vector_json FROM embeddings')
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def add_user_tag(self, file_hash: str, tag: str):
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO user_tags (file_hash, tag) VALUES (?, ?)', (file_hash, tag))
            conn.commit()


    def remove_user_tag(self, file_hash: str, tag: str):
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_tags WHERE file_hash = ? AND tag = ?', (file_hash, tag))
            conn.commit()


    def get_user_tags(self, file_hash: str):
        # S2-2: Use a fresh cursor instead of mutating shared row_factory
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT tag FROM user_tags WHERE file_hash = ?', (file_hash,))
        return [row[0] for row in cursor.fetchall()]

    def get_all_user_tags(self):
        # S2-2: Use a fresh cursor instead of mutating shared row_factory
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT tag FROM user_tags ORDER BY tag')
        return [row[0] for row in cursor.fetchall()]
        
    def get_models_unembedded(self):
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.* 
            FROM models m 
            LEFT JOIN embeddings e ON m.file_hash = e.file_hash 
            WHERE e.file_hash IS NULL
        ''')
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def get_models_for_update_check(self):
        """Returns all models that have CIVITAI metadata to check for updates."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute("SELECT file_hash, metadata_json FROM models WHERE metadata_json IS NOT NULL")
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def set_model_update_status(self, file_hash: str, update_available: int, latest_version_id: int):
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE models 
                SET update_available = ?, latest_version_id = ?
                WHERE file_hash = ?
            ''', (update_available, latest_version_id, file_hash))
            conn.commit()


    # ── Prompt Library ──────────────────────────────────────────────

    def save_prompt(self, title: str, prompt: str = "", negative: str = "", model: str = "", tags: str = "", extra_json: str = None) -> int:
        """Saves a favorite prompt to the library. Returns the new row ID."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO prompts (title, prompt, negative, model, tags, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (title, prompt, negative, model, tags, extra_json))
            rowid = cursor.lastrowid
            conn.commit()

            return rowid

    def list_prompts(self, search: str = None, limit: int = 100) -> list:
        """Returns saved prompts, optionally filtered by title/content substring."""
        conn = self._conn
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

        return [dict(r) for r in rows]

    def delete_prompt(self, prompt_id: int) -> None:
        """Deletes a saved prompt by ID."""
        with self._write_lock:
            conn = self._conn
            conn.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
            conn.commit()


    # ── Bulk Vault Operations ───────────────────────────────────────

    def remove_models_by_filenames(self, filenames: list) -> int:
        """Batch-delete models by filename within a single transaction.
        P2-4 fix: Also cascade-deletes associated embeddings and user_tags.
        Returns count of models deleted."""
        if not filenames:
            return 0
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            deleted = 0
            try:
                for fn in filenames:
                    # Fetch hashes before deleting so we can cascade-clean
                    cursor.execute('SELECT file_hash FROM models WHERE filename = ?', (fn,))
                    hashes = [row[0] for row in cursor.fetchall() if row[0]]
                    cursor.execute('DELETE FROM models WHERE filename = ?', (fn,))
                    deleted += cursor.rowcount
                    # Cascade: clean up embeddings and user_tags
                    for fh in hashes:
                        cursor.execute('DELETE FROM embeddings WHERE file_hash = ?', (fh,))
                        cursor.execute('DELETE FROM user_tags WHERE file_hash = ?', (fh,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return deleted

    def remove_model_by_filename(self, filename: str, vault_category: str = None) -> None:
        """Removes a single model entry by filename.
        If vault_category is provided, only delete the matching (filename, category) row
        to prevent accidental cross-category deletions when filenames collide.
        P4-1 fix: Now cascade-deletes associated embeddings and user_tags."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            # Fetch hashes before deleting for cascade cleanup
            if vault_category:
                cursor.execute(
                    'SELECT file_hash FROM models WHERE filename = ? AND vault_category = ?',
                    (filename, vault_category))
            else:
                cursor.execute('SELECT file_hash FROM models WHERE filename = ?', (filename,))
            hashes = [row[0] for row in cursor.fetchall() if row[0]]
            # Delete the model rows
            if vault_category:
                cursor.execute(
                    'DELETE FROM models WHERE filename = ? AND vault_category = ?',
                    (filename, vault_category))
            else:
                cursor.execute('DELETE FROM models WHERE filename = ?', (filename,))
            # Cascade: clean up embeddings and user_tags
            for fh in hashes:
                cursor.execute('DELETE FROM embeddings WHERE file_hash = ?', (fh,))
                cursor.execute('DELETE FROM user_tags WHERE file_hash = ?', (fh,))
            conn.commit()

    def remove_model_by_id(self, model_id: int) -> None:
        """Removes a single model entry by its database ID.
        Also cleans up associated embeddings and user_tags."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            # Get the hash first for cascade cleanup
            cursor.execute('SELECT file_hash FROM models WHERE id = ?', (model_id,))
            row = cursor.fetchone()
            file_hash = row[0] if row else None
            # Delete the model
            cursor.execute('DELETE FROM models WHERE id = ?', (model_id,))
            # Cascade: clean up related embedding and user_tags
            if file_hash:
                cursor.execute('DELETE FROM embeddings WHERE file_hash = ?', (file_hash,))
                cursor.execute('DELETE FROM user_tags WHERE file_hash = ?', (file_hash,))
            conn.commit()

    def update_model_hash(self, model_id: int, file_hash: str) -> None:
        """Set the SHA-256 hash on an existing model row.
        Used by VaultCrawler.hash_library() instead of raw cursor access."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE models SET file_hash = ?, last_scanned = CURRENT_TIMESTAMP WHERE id = ?',
                (file_hash, model_id))
            conn.commit()


    # ── Vault Export ────────────────────────────────────────────────

    def export_models_metadata(self, filenames: list) -> list:
        """Returns full metadata dicts for a list of filenames, for portable backup manifests."""
        if not filenames:
            return []
        conn = self._conn
        cursor = conn.cursor()
        results = []
        for fn in filenames:
            cursor.execute('SELECT * FROM models WHERE filename = ?', (fn,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d['user_tags'] = self.get_user_tags(d.get('file_hash', ''))
                results.append(d)

        return results

    # ── Dashboard Analytics ─────────────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        """Returns aggregate statistics for the dashboard analytics widget."""
        conn = self._conn
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM models')
        total_models = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM generations')
        total_generations = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM prompts')
        prompts_saved = cursor.fetchone()[0]


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
        with self._write_lock:
            conn = self._conn
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
        return {'imported': imported, 'skipped': skipped, 'failed': failed}

    # ── Recent Activity (Sprint 9) ─────────────────────────────────

    def get_recent_activity(self, limit: int = 5) -> list:
        """Returns the most recent generations for the dashboard activity feed."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, prompt, model, created_at, seed, width, height
            FROM generations
            ORDER BY id DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()

        return [dict(r) for r in rows]

    # ── Vault Category Distribution (Sprint 9) ─────────────────────

    def get_vault_category_distribution(self) -> dict:
        """Returns {category: count} for all models, grouped by vault_category."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT vault_category, COUNT(*) FROM models GROUP BY vault_category ORDER BY COUNT(*) DESC')
        rows = cursor.fetchall()

        return {row[0]: row[1] for row in rows}

    # ── Gallery Tags (Sprint 10) ───────────────────────────────────

    def get_gallery_tags(self) -> list:
        """Returns distinct tags across all generations that have non-null tags."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT tags FROM generations WHERE tags IS NOT NULL AND tags != ""')
        rows = cursor.fetchall()

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
        conn = self._conn
        cursor = conn.cursor()
        like = f"%{tag}%"
        cursor.execute(
            'SELECT * FROM generations WHERE tags LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?',
            (like, limit, offset)
        )
        rows = cursor.fetchall()

        return [dict(r) for r in rows]

    # ── Favorites ────────────────────────────────────────────────
    def get_all_favorites(self) -> dict:
        """Returns {model_id: data_dict} for all favorites."""
        conn = self._conn
        cursor = conn.cursor()
        cursor.execute("SELECT model_id, data_json FROM favorites")
        result = {}
        for row in cursor.fetchall():
            try:
                result[row[0]] = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                result[row[0]] = {}

        return result

    def add_favorite(self, model_id: str, data_json: str):
        """Add or update a favorite model."""
        with self._write_lock:
            conn = self._conn
            conn.execute(
                "INSERT OR REPLACE INTO favorites (model_id, data_json) VALUES (?, ?)",
                (str(model_id), data_json)
            )
            conn.commit()


    def remove_favorite(self, model_id: str):
        """Remove a favorite model."""
        with self._write_lock:
            conn = self._conn
            conn.execute("DELETE FROM favorites WHERE model_id = ?", (str(model_id),))
            conn.commit()


    def bulk_import_favorites(self, favorites_dict: dict):
        """Import a dict of {model_id: data} into favorites table (one-time migration)."""
        with self._write_lock:
            conn = self._conn
            cursor = conn.cursor()
            for model_id, data in favorites_dict.items():
                data_str = json.dumps(data) if isinstance(data, dict) else str(data)
                cursor.execute(
                    "INSERT OR IGNORE INTO favorites (model_id, data_json) VALUES (?, ?)",
                    (str(model_id), data_str)
                )
            conn.commit()

            logging.info(f"Bulk imported {len(favorites_dict)} favorites into SQLite")


if __name__ == "__main__":
    db_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".backend", "metadata.sqlite")
    MetadataDB(db_file)

