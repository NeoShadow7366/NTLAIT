import os
import json
import math
import logging
import time
import threading
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class EmbeddingEngine:
    """Semantic search and embedding generation engine.
    
    Optimization: Pre-parsed embedding vectors are cached in memory to avoid
    re-deserializing JSON on every search query. The cache auto-invalidates
    when new embeddings are generated.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._model = None
        self._db = None
        # In-memory embedding cache: list of (file_hash, vector_list) tuples
        self._embedding_cache = None
        self._cache_lock = threading.Lock()
        
    @property
    def model(self):
        if self._model is None:
            logging.info("Loading sentence-transformers model (all-MiniLM-L6-v2) - this takes ~80MB...")
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
        return self._model

    def embed_text(self, text: str):
        return self.model.encode(text).tolist()

    def _invalidate_cache(self):
        """Mark the embedding cache as stale so next search re-loads."""
        with self._cache_lock:
            self._embedding_cache = None

    def _ensure_cache(self):
        """Load and parse all embeddings from DB into memory if not cached.
        P5-4 fix: Single lock acquisition prevents TOCTOU race where two threads
        could both see None and both start loading."""
        if self._embedding_cache is not None:
            return  # Fast path without lock (read is atomic for None check)
        with self._cache_lock:
            if self._embedding_cache is not None:
                return  # Another thread beat us to it
            db = self._get_db()
            raw = db.get_all_embeddings()
            parsed = []
            for emb in raw:
                try:
                    vec = json.loads(emb['vector_json'])
                    parsed.append((emb['file_hash'], vec))
                except Exception:
                    continue
            self._embedding_cache = parsed
            logging.info(f"Embedding cache loaded: {len(parsed)} vectors in memory.")

    def _get_db(self):
        """Lazily create and cache a MetadataDB instance."""
        if self._db is None:
            from metadata_db import MetadataDB
            self._db = MetadataDB(self.db_path)
        return self._db

    def generate_missing_embeddings(self):
        db = self._get_db()
        unembedded = db.get_models_unembedded()
        
        if not unembedded:
            return 0
            
        logging.info(f"Found {len(unembedded)} models missing embeddings. Processing...")
        processed = 0
        for model in unembedded:
            try:
                parts = [model['filename'], model['vault_category']]
                metadata = {}
                if model.get('metadata_json'):
                    metadata = json.loads(model['metadata_json'])
                
                if 'baseModel' in metadata:
                    parts.append(metadata['baseModel'])
                if 'tags' in metadata:
                    parts.extend(metadata['tags'])
                
                user_tags = db.get_user_tags(model['file_hash'])
                parts.extend(user_tags)
                
                text_to_embed = " ".join([str(p) for p in parts if p]).replace("_", " ").lower()
                vector = self.embed_text(text_to_embed)
                
                db.save_embedding(model['file_hash'], json.dumps(vector))
                processed += 1
            except Exception as e:
                logging.error(f"Error embedding {model['filename']}: {e}")
        
        # Invalidate the search cache so new embeddings are picked up
        if processed > 0:
            self._invalidate_cache()
                
        return processed

    def search(self, query: str, top_k: int = 20):
        """Semantic search using cached, pre-parsed embedding vectors.
        
        Performance: With cache, this avoids re-parsing N JSON strings per query.
        For 1000 models, this saves ~1000 json.loads() calls per keystroke.
        """
        query_vector = self.embed_text(query)
        self._ensure_cache()
        
        if not self._embedding_cache:
            return []

        # Pre-compute query norm once
        q_norm = math.sqrt(sum(a * a for a in query_vector))
        if q_norm == 0:
            return []
            
        results = []
        for file_hash, vec in self._embedding_cache:
            # Inline cosine similarity for performance
            dot = sum(a * b for a, b in zip(query_vector, vec))
            v_norm = math.sqrt(sum(b * b for b in vec))
            if v_norm == 0:
                continue
            score = dot / (q_norm * v_norm)
            results.append((score, file_hash))
                
        results.sort(reverse=True, key=lambda x: x[0])
        return results[:top_k]

if __name__ == "__main__":
    db_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".backend", "metadata.sqlite")
    engine = EmbeddingEngine(db_file)
    while True:
        try:
            processed = engine.generate_missing_embeddings()
            if processed > 0:
                logging.info(f"Embedded {processed} models in background run.")
        except Exception as e:
            logging.error(f"Embedding Engine Error: {e}")
        time.sleep(60)  # Run every minute
