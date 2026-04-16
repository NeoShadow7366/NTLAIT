import os
import sys
import hashlib
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from metadata_db import MetadataDB, MODEL_EXTENSIONS

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


class VaultCrawler:
    """Multi-path model indexer with cancellable discovery and hashing.
    
    Supports two scan modes:
      1. Discovery scan — fast filename-only indexing (no SHA-256 hash)
      2. Hash scan — full SHA-256 computation for CivitAI metadata lookup
    
    Both modes are cancellable via the cancel_event threading.Event.
    External paths are read from installed packages' extra_model_paths.yaml files.
    """

    def __init__(self, root_dir: str, db: 'MetadataDB' = None):
        self.root_dir = os.path.abspath(root_dir)
        self.vault_dir = os.path.join(self.root_dir, "Global_Vault")
        self.packages_dir = os.path.join(self.root_dir, "packages")
        self.db_path = os.path.join(self.root_dir, ".backend", "metadata.sqlite")
        self.db = db or MetadataDB(self.db_path)
        
        # Extensions we care about tracking (shared constant)
        self.valid_extensions = MODEL_EXTENSIONS
        
        # Cancellation support
        self.cancel_event = threading.Event()
        
        # Progress tracking (read by SSE emitter)
        self.scan_progress = {
            "active": False,
            "phase": "",         # "discovery" | "hashing"
            "current": 0,
            "total": 0,
            "percent": 0,        # P5-2: pre-computed % so frontend doesn't divide-by-zero
            "current_file": "",
            "source": "",
        }

    def _calculate_hash(self, file_path: str) -> str:
        """SHA-256 hash in 4MB chunks. Returns None on error or cancellation."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096 * 1024), b""):
                    if self.cancel_event.is_set():
                        return None
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logging.error(f"Failed to hash {file_path}: {e}")
            return None

    def _is_model_file(self, filename: str) -> bool:
        """Check if a file has a recognized model extension."""
        return any(filename.lower().endswith(ext) for ext in self.valid_extensions)

    # ══════════════════════════════════════════════════════
    #  EXTERNAL PATH DISCOVERY
    # ══════════════════════════════════════════════════════

    def get_external_paths(self) -> list:
        """Read extra_model_paths.yaml from all installed packages.
        Returns list of dicts: [{name, base_path, categories: {key: subdir}}]
        """
        from handlers.package_handlers import PackageHandlersMixin
        
        external = []
        if not os.path.exists(self.packages_dir):
            return external
            
        for pkg_id in os.listdir(self.packages_dir):
            yaml_path = os.path.join(self.packages_dir, pkg_id, "app", "extra_model_paths.yaml")
            if not os.path.exists(yaml_path):
                continue
            try:
                sections = PackageHandlersMixin._parse_yaml_simple(yaml_path)
                for section_name, entries in sections.items():
                    base = entries.get("base_path", "")
                    if not base or not os.path.exists(base):
                        continue
                    categories = {k: v for k, v in entries.items() if k != "base_path"}
                    external.append({
                        "name": section_name,
                        "base_path": base,
                        "categories": categories,
                        "source_tag": f"external:{section_name}"
                    })
            except Exception as e:
                logging.warning(f"Failed to parse {yaml_path}: {e}")
        
        return external

    # ══════════════════════════════════════════════════════
    #  DISCOVERY SCAN (fast, no hashing)
    # ══════════════════════════════════════════════════════

    def discover_vault(self):
        """Fast discovery of Global_Vault models (existing behavior + source_path)."""
        logging.info(f"Starting Vault Crawl in {self.vault_dir}")
        if not os.path.exists(self.vault_dir):
            logging.warning("Vault directory missing; nothing to crawl.")
            return

        # C-2 fix: Use (filename, category) tuples to prevent cross-category collisions
        tracked_pairs = self.db.get_filenames_by_source('Global_Vault')
        files_to_hash = []
        
        for root, _, files in os.walk(self.vault_dir):
            if self.cancel_event.is_set():
                return
            for file in files:
                if self._is_model_file(file):
                    rel_path = os.path.relpath(os.path.join(root, file), self.vault_dir)
                    category = rel_path.split(os.sep)[0] if os.sep in rel_path else "misc"
                    if (file, category) not in tracked_pairs:
                        files_to_hash.append((root, file))
        
        if not files_to_hash:
            logging.info("Vault Crawl Complete — no new files.")
            # Still prune stale records even when no new files found
            self.prune_stale_models()
            return
        
        logging.info(f"Found {len(files_to_hash)} new files to index.")
        
        # Hash and register (original behavior for Global_Vault)
        # P5-6: use dict-literal form — keyword args to dict.update() are not supported
        self.scan_progress.update({"active": True, "phase": "hashing", "total": len(files_to_hash), "current": 0, "percent": 0, "source": "Global_Vault", "current_file": ""})
        hash_results = []
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for root, file in files_to_hash:
                futures.append(executor.submit(self._hash_single_vault_file, root, file))
            
            for future in futures:
                if self.cancel_event.is_set():
                    break
                try:
                    result = future.result()
                    if result:
                        hash_results.append(result)
                except Exception as e:
                    logging.error(f"Hash worker failed: {e}")
                self.scan_progress["current"] += 1
                total = self.scan_progress["total"]
                self.scan_progress["percent"] = int(self.scan_progress["current"] / total * 100) if total else 100
        
        # Sequential DB writes
        for filename, category, file_hash in hash_results:
            try:
                self.db.insert_or_update_model(
                    filename=filename,
                    vault_category=category,
                    file_hash=file_hash,
                    source_path="Global_Vault"
                )
                logging.info(f"Registered {filename} [{file_hash[:8]}] in database.")
            except Exception as e:
                logging.error(f"Failed to register {filename}: {e}")

        self._update_vault_size_cache()
        self.scan_progress["active"] = False
        logging.info(f"Vault Crawl Complete. Indexed {len(hash_results)} new files.")
        
        # C-1 fix: Clean up DB records for files that no longer exist on disk
        self.prune_stale_models()

    def _hash_single_vault_file(self, root: str, filename: str):
        """Hash a single vault file. Returns (filename, category, hash) or None."""
        if self.cancel_event.is_set():
            return None
        file_path = os.path.join(root, filename)
        if os.path.exists(os.path.join(root, ".manager_ignore")):
            return None
        rel_path = os.path.relpath(file_path, self.vault_dir)
        category = rel_path.split(os.sep)[0] if os.sep in rel_path else "misc"
        
        self.scan_progress["current_file"] = filename
        file_hash = self._calculate_hash(file_path)
        if file_hash:
            return (filename, category, file_hash)
        return None

    # ══════════════════════════════════════════════════════
    #  EXTERNAL LIBRARY DISCOVERY (fast, no hashing)
    # ══════════════════════════════════════════════════════

    def discover_external(self, source_name: str = None):
        """Discover models from external paths (extra_model_paths.yaml).
        If source_name is given, only scan that specific source.
        No hashing — just registers filenames for fast browsing.
        """
        self.cancel_event.clear()
        external_paths = self.get_external_paths()
        
        if source_name:
            external_paths = [p for p in external_paths if p["name"] == source_name]
        
        if not external_paths:
            logging.info("No external paths configured or found.")
            return {"discovered": 0}

        total_discovered = 0
        
        for ext in external_paths:
            if self.cancel_event.is_set():
                break
                
            source_tag = ext["source_tag"]
            base = ext["base_path"]
            logging.info(f"Scanning external source: {ext['name']} at {base}")
            
            # P5-6: use dict-literal form
            self.scan_progress.update({
                "active": True, "phase": "discovery", "current": 0, "total": 0,
                "percent": 0, "source": ext["name"], "current_file": ""
            })

            # Walk each category subdirectory
            for cat_key, subdir in ext["categories"].items():
                if self.cancel_event.is_set():
                    break
                    
                full_path = os.path.join(base, subdir)
                if not os.path.exists(full_path):
                    continue
                
                # Map common ComfyUI category names to vault categories
                vault_cat = self._map_category(cat_key)
                
                for root, _, files in os.walk(full_path):
                    if self.cancel_event.is_set():
                        break
                    for file in files:
                        if self.cancel_event.is_set():
                            break
                        if not self._is_model_file(file):
                            continue
                        
                        self.scan_progress["current_file"] = file
                        self.scan_progress["current"] += 1
                        
                        try:
                            self.db.insert_discovered_model(
                                filename=file,
                                vault_category=vault_cat,
                                source_path=source_tag
                            )
                            total_discovered += 1
                        except Exception as e:
                            logging.error(f"Failed to register {file}: {e}")
        
        self.scan_progress["active"] = False
        logging.info(f"External Discovery Complete. Found {total_discovered} new models.")
        return {"discovered": total_discovered}

    @staticmethod
    def _map_category(key: str) -> str:
        """Map extra_model_paths.yaml keys to vault_category names."""
        mapping = {
            "checkpoints": "checkpoints",
            "loras": "loras",
            "vae": "vaes",
            "controlnet": "controlnet",
            "unet": "unet",
            "clip": "clip",
            "embeddings": "embeddings",
            "upscale_models": "upscalers",
            "hypernetworks": "hypernetworks",
        }
        return mapping.get(key.lower(), key.lower())

    # ══════════════════════════════════════════════════════
    #  HASH SCAN (slow, cancellable)
    # ══════════════════════════════════════════════════════

    def hash_library(self, source_path: str = None):
        """Hash all unhashed models. Cancellable via cancel_event.
        If source_path is given, only hash models from that source.
        """
        self.cancel_event.clear()
        unhashed = self.db.get_unhashed_models(source_path)
        
        if not unhashed:
            logging.info("No unhashed models to process.")
            return {"hashed": 0, "cancelled": False}
        
        logging.info(f"Starting hash scan for {len(unhashed)} models...")
        # P5-6: use dict-literal form
        self.scan_progress.update({
            "active": True, "phase": "hashing", "current": 0, "total": len(unhashed),
            "percent": 0, "source": source_path or "all", "current_file": ""
        })
        
        hashed_count = 0
        external_paths = self.get_external_paths()
        
        for model in unhashed:
            if self.cancel_event.is_set():
                logging.info(f"Hash scan cancelled after {hashed_count}/{len(unhashed)} models.")
                break
            
            filename = model["filename"]
            source = model["source_path"]
            category = model["vault_category"]
            
            self.scan_progress["current"] += 1
            self.scan_progress["current_file"] = filename
            total = self.scan_progress["total"]
            self.scan_progress["percent"] = int(self.scan_progress["current"] / total * 100) if total else 100
            
            # Resolve full file path
            file_path = self._resolve_file_path(filename, source, category, external_paths)
            if not file_path or not os.path.exists(file_path):
                logging.warning(f"Cannot locate {filename} from {source}")
                continue
            
            logging.info(f"Hashing: {filename}...")
            file_hash = self._calculate_hash(file_path)
            
            if file_hash and not self.cancel_event.is_set():
                try:
                    self.db.update_model_hash(model["id"], file_hash)
                    hashed_count += 1
                    logging.info(f"Hashed {filename} [{file_hash[:8]}]")
                except Exception as e:
                    logging.error(f"Failed to update hash for {filename}: {e}")
        
        self.scan_progress["active"] = False
        cancelled = self.cancel_event.is_set()
        logging.info(f"Hash scan complete. Hashed {hashed_count} models. Cancelled: {cancelled}")
        return {"hashed": hashed_count, "cancelled": cancelled}

    def hash_single_model(self, model_id: int) -> dict:
        """Hash a single model by its database ID.
        P5-3 fix: Updates scan_progress so frontend polling reflects active state."""
        # P2-1 fix: Use proper MetadataDB API instead of raw cursor access
        model = self.db.get_model_by_id(model_id)
        if not model:
            return {"status": "error", "message": "Model not found"}

        if model.get("file_hash"):
            return {"status": "already_hashed", "hash": model["file_hash"]}

        external_paths = self.get_external_paths()
        file_path = self._resolve_file_path(
            model["filename"], model["source_path"],
            model["vault_category"], external_paths
        )

        if not file_path or not os.path.exists(file_path):
            return {"status": "error", "message": f"File not found: {model['filename']}"}

        # P5-3: Mark scan as active so frontend progress poll sees it running
        self.scan_progress.update({
            "active": True, "phase": "hashing", "current": 0, "total": 1,
            "percent": 0, "source": model.get("source_path", "unknown"),
            "current_file": model["filename"]
        })
        try:
            file_hash = self._calculate_hash(file_path)
            if not file_hash:
                return {"status": "error", "message": "Hash computation failed"}
            self.db.update_model_hash(model_id, file_hash)
            self.scan_progress.update({"current": 1, "percent": 100})
            return {"status": "success", "hash": file_hash}
        finally:
            self.scan_progress["active"] = False

    def _resolve_file_path(self, filename: str, source_path: str,
                           category: str, external_paths: list) -> str:
        """Resolve the full filesystem path for a model given its source info."""
        if source_path == "Global_Vault":
            return os.path.join(self.vault_dir, category, filename)
        
        # External source: external:{section_name}
        if source_path.startswith("external:"):
            section_name = source_path.split(":", 1)[1]
            for ext in external_paths:
                if ext["name"] == section_name:
                    # Search in category subdirectories
                    for cat_key, subdir in ext["categories"].items():
                        mapped = self._map_category(cat_key)
                        if mapped == category or cat_key == category:
                            candidate = os.path.join(ext["base_path"], subdir, filename)
                            if os.path.exists(candidate):
                                return candidate
                    # Fallback: search all subdirs
                    for cat_key, subdir in ext["categories"].items():
                        candidate = os.path.join(ext["base_path"], subdir, filename)
                        if os.path.exists(candidate):
                            return candidate
        return None

    # ══════════════════════════════════════════════════════
    #  CANCELLATION
    # ══════════════════════════════════════════════════════

    def cancel_scan(self):
        """Signal the current scan/hash operation to stop safely."""
        self.cancel_event.set()
        logging.info("Scan cancellation requested.")

    # ══════════════════════════════════════════════════════
    #  STALE MODEL PRUNING (C-1 fix)
    # ══════════════════════════════════════════════════════

    def prune_stale_models(self):
        """Remove DB records for Global_Vault models whose files no longer exist on disk.
        
        Uses Option A: full removal including metadata, embeddings, and user_tags.
        Only prunes models with source_path='Global_Vault' — external sources are not touched.
        """
        if not os.path.exists(self.vault_dir):
            return
        
        models = self.db.get_vault_models_for_pruning('Global_Vault')
        if not models:
            return
        
        pruned_count = 0
        for model in models:
            if self.cancel_event.is_set():
                break
            
            filename = model["filename"]
            category = model["vault_category"]
            expected_path = os.path.join(self.vault_dir, category, filename)
            
            # Also check recursively in case file is in a subdirectory
            if not os.path.exists(expected_path):
                # Double-check: walk the category dir for nested files
                cat_dir = os.path.join(self.vault_dir, category)
                found = False
                if os.path.isdir(cat_dir):
                    for root, _, files in os.walk(cat_dir):
                        if filename in files:
                            found = True
                            break
                
                if not found:
                    try:
                        # P2-7: Also clean up orphaned thumbnail files
                        file_hash = model.get("file_hash")
                        if file_hash:
                            thumb_dir = os.path.join(self.root_dir, ".backend", "cache", "thumbnails")
                            if os.path.isdir(thumb_dir):
                                for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                                    thumb_path = os.path.join(thumb_dir, f"{file_hash}.{ext}")
                                    if os.path.exists(thumb_path):
                                        try:
                                            os.remove(thumb_path)
                                            logging.info(f"Removed orphaned thumbnail: {file_hash}.{ext}")
                                        except OSError:
                                            pass
                        self.db.remove_model_by_id(model["id"])
                        pruned_count += 1
                        logging.info(f"Pruned stale model: {filename} (category: {category})")
                    except Exception as e:
                        logging.error(f"Failed to prune {filename}: {e}")
        
        if pruned_count > 0:
            logging.info(f"Pruned {pruned_count} stale model record(s) from database.")
            # P2-6: Invalidate embedding cache after pruning
            self._invalidate_embedding_cache()

    # ══════════════════════════════════════════════════════
    #  UTILITIES
    # ══════════════════════════════════════════════════════

    def _invalidate_embedding_cache(self):
        """P2-6: Signal the EmbeddingEngine to discard its in-memory cache.
        Called after pruning or deletion so stale vectors don't appear in search."""
        try:
            server_mod = sys.modules.get('server', None)
            if server_mod and hasattr(server_mod, '_embedding_engine'):
                server_mod._embedding_engine._invalidate_cache()
                logging.info("Embedding cache invalidated after model changes.")
        except Exception:
            pass  # Non-critical

    def _update_vault_size_cache(self):
        """Update the shared vault size cache for the dashboard."""
        try:
            vault_size = 0
            for root, _, files in os.walk(self.vault_dir):
                for f in files:
                    try:
                        vault_size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            server_mod = sys.modules.get('server', None)
            if server_mod and hasattr(server_mod, '_vault_size_cache'):
                server_mod._vault_size_cache.set(vault_size)
        except Exception:
            pass

    # Legacy entry point — used by server.py on boot
    def crawl(self):
        """Boot-time scan: index Global_Vault only (with hashing)."""
        self.cancel_event.clear()
        self.discover_vault()


if __name__ == "__main__":
    crawler = VaultCrawler(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    crawler.crawl()
