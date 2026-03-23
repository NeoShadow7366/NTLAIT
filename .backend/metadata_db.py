import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class MetadataDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
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
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create an index for fast lookups
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON models(file_hash)')
        
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

if __name__ == "__main__":
    db_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".backend", "metadata.sqlite")
    MetadataDB(db_file)
