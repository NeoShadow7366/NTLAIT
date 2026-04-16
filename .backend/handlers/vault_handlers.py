"""Vault domain handlers — search, tags, export, import, health, repair, bulk delete.

Mixin class providing vault-related HTTP handler methods.
Composed into AIWebServer via multiple inheritance.
"""
import os
import sys
import json
import time
import shutil
import logging
import zipfile
import io


class VaultHandlersMixin:
    """Vault domain handlers for the AIWebServer class.

    Handles:
        GET  /api/vault/search     → handle_vault_search
        GET  /api/vault/tags       → handle_get_all_tags
        GET  /api/hf/search        → handle_hf_search
        POST /api/vault/tag/add    → handle_add_tag
        POST /api/vault/tag/remove → handle_remove_tag
        POST /api/vault/export     → handle_vault_export
        POST /api/vault/import     → handle_vault_import
        POST /api/vault/updates    → handle_vault_updates
        POST /api/vault/health_check → handle_vault_health_check
        POST /api/vault/repair     → handle_vault_repair
        POST /api/vault/import_scan → handle_import_scan
        POST /api/vault/bulk_delete → handle_vault_bulk_delete
        POST /api/import/external  → handle_import_external
        GET  /api/favorites        → handle_get_favorites
        POST /api/favorites/add    → handle_add_favorite
        POST /api/favorites/remove → handle_remove_favorite
    """

    def handle_vault_search(self):
        try:
            from server import _get_db
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            q = qs.get("query", [""])[0]
            limit = int(qs.get("limit", [50])[0])

            if not q:
                return self.send_api_models()

            logging.info(f"Performing semantic search for: {q}")

            db = _get_db()
            # L-2 fix: Singleton EmbeddingEngine to avoid reinstantiating 80MB model per request
            engine = self._get_embedding_engine()
            results = engine.search(q, top_k=limit)

            models = []
            for score, fhash in results:
                if score < 0.1:
                    continue
                m = db.get_model_by_hash(fhash)
                if m:
                    if m.get("metadata_json"):
                        try:
                            m["metadata"] = json.loads(m["metadata_json"])
                        except Exception:
                            m["metadata"] = {}
                    else:
                        m["metadata"] = {}
                    del m["metadata_json"]
                    m["user_tags"] = db.get_user_tags(fhash)
                    m["search_score"] = float(score)
                    models.append(m)

            self.send_json_response({"status": "success", "models": models})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_get_all_tags(self):
        try:
            from server import _get_db
            db = _get_db()
            tags = db.get_all_user_tags()
            self.send_json_response({"status": "success", "tags": tags})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_add_tag(self, data):
        hash_val = data.get("file_hash")
        tag = data.get("tag")
        # P3-2 fix: Frontend sends filename+category, resolve hash from DB
        if not hash_val and data.get("filename"):
            from server import _get_db as _gdb
            m = _gdb().get_model_by_filename(data["filename"])
            if m:
                hash_val = m.get("file_hash")
        if not hash_val or not tag:
            self.send_json_response({"status": "error", "message": "Missing hash or tag"}, 400)
            return
        try:
            from server import _get_db
            db = _get_db()
            db.add_user_tag(hash_val, tag.strip())
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_remove_tag(self, data):
        hash_val = data.get("file_hash")
        tag = data.get("tag")
        # P3-2 fix: Frontend sends filename+category, resolve hash from DB
        if not hash_val and data.get("filename"):
            from server import _get_db as _gdb
            m = _gdb().get_model_by_filename(data["filename"])
            if m:
                hash_val = m.get("file_hash")
        if not hash_val or not tag:
            self.send_json_response({"status": "error", "message": "Missing hash or tag"}, 400)
            return
        try:
            from server import _get_db
            db = _get_db()
            db.remove_user_tag(hash_val, tag.strip())
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_hf_search(self):
        from urllib.parse import urlparse, parse_qs
        from server import _get_settings
        qs = parse_qs(urlparse(self.path).query)
        query = qs.get("query", [""])[0]
        type_filter = qs.get("type", [""])[0]
        limit = int(qs.get("limit", [40])[0])
        offset = int(qs.get("offset", [0])[0])

        filter_tags = None
        if type_filter == "Text Encoder":
            if not query:
                query = "clip t5-xxl encoder"
            else:
                query += " clip t5 encoder"
        elif type_filter and type_filter not in ["Model", "Checkpoint"]:
            filter_tags = type_filter.lower()

        try:
            from hf_client import HFClient
            api_key = _get_settings().get("hf_api_key")
            client = HFClient(api_key=api_key)
            result = client.search_models(query=query, limit=limit, offset=offset, filter_tags=filter_tags)
            self.send_json_response({"status": "success", "items": result})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_updates(self, data):
        updater_script = os.path.join(self.root_dir, ".backend", "update_checker.py")
        python_exe = sys.executable
        try:
            import subprocess
            subprocess.Popen([python_exe, updater_script, "--root_dir", self.root_dir])
            self.send_json_response({"status": "success", "message": "Update check started in background."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_health_check(self, data):
        """Checks vault symlinks/junctions in installed packages for broken targets.
        H-2 fix: Reads manifest.json symlink maps instead of guessing by directory name."""
        from server import _get_db
        from symlink_manager import create_safe_directory_link
        broken_links = 0
        repaired_links = 0
        packages_dir = os.path.join(self.root_dir, "packages")
        vault_dir = os.path.join(self.root_dir, "Global_Vault")

        if not os.path.exists(packages_dir):
            self.send_json_response({"status": "success", "message": "No packages installed."})
            return

        for pkg_name in os.listdir(packages_dir):
            pkg_path = os.path.join(packages_dir, pkg_name)
            manifest_path = os.path.join(pkg_path, "manifest.json")
            if not os.path.isdir(pkg_path) or not os.path.exists(manifest_path):
                continue

            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            symlinks = manifest.get("model_symlinks", {})
            app_path = os.path.join(pkg_path, "app")

            for vault_src, app_target in symlinks.items():
                source_path = os.path.join(vault_dir, vault_src)
                target_path = os.path.join(app_path, app_target)

                # Check if the link/junction exists and its target is valid
                if os.path.exists(target_path) or os.path.islink(target_path):
                    try:
                        real_target = os.path.realpath(target_path)
                        if not os.path.exists(real_target):
                            broken_links += 1
                            # Attempt repair: re-create junction to vault
                            if os.path.exists(source_path):
                                try:
                                    if os.path.islink(target_path):
                                        os.unlink(target_path)
                                    else:
                                        os.rmdir(target_path)
                                    create_safe_directory_link(source_path, target_path)
                                    repaired_links += 1
                                    logging.info(f"Repaired broken link: {target_path} → {source_path}")
                                except Exception as e:
                                    logging.warning(f"Failed to repair {target_path}: {e}")
                    except Exception:
                        pass
                elif os.path.exists(source_path):
                    # Link is completely missing — recreate
                    try:
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        create_safe_directory_link(source_path, target_path)
                        repaired_links += 1
                        logging.info(f"Recreated missing link: {target_path} → {source_path}")
                    except Exception as e:
                        logging.warning(f"Failed to create {target_path}: {e}")

        self.send_json_response({
            "status": "success",
            "message": f"Found {broken_links} broken link(s). Repaired {repaired_links}."
        })

    def handle_vault_repair(self, data):
        """POST /api/vault/repair — re-fetch metadata + thumbnails for a model.
        Accepts file_hash directly, or falls back to filename-based lookup."""
        from server import _get_db
        file_hash = data.get("file_hash")
        filename = data.get("filename")

        db = _get_db()

        if not file_hash and filename:
            model = db.get_model_by_filename(filename)
            if model:
                file_hash = model.get("file_hash")

        if not file_hash:
            self.send_json_response({"status": "error", "message": "Missing file_hash and unable to resolve from filename"}, 400)
            return

        try:
            from civitai_client import CivitaiClient
            # C-3 fix: Use correct CivitaiClient constructor signature and method
            client = CivitaiClient(self.root_dir, db=db)
            success = client.repair_model_metadata(file_hash)
            if success:
                self.send_json_response({"status": "success", "message": f"Metadata refreshed for {file_hash[:12]}..."})
            else:
                self.send_json_response({"status": "error", "message": f"Could not fetch metadata for {file_hash[:12]}"}, 404)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_import_scan(self, data):
        try:
            from server import _get_db
            from import_engine import start_import
            from metadata_db import MODEL_EXTENSIONS
            vault_dir = os.path.join(self.root_dir, "Global_Vault")
            db = _get_db()
            known_filenames = db.get_all_filenames()
            count = 0
            api_key = data.get("api_key", "")
            for root, _, files in os.walk(vault_dir):
                for f in files:
                    # L-4 fix: Use shared MODEL_EXTENSIONS constant
                    if any(f.lower().endswith(ext) for ext in MODEL_EXTENSIONS):
                        if f not in known_filenames:
                            f_path = os.path.join(root, f)
                            category = os.path.basename(root)
                            start_import(f_path, category, self.root_dir, api_key)
                            count += 1
            self.send_json_response({"status": "success", "message": f"Queued {count} unmanaged files for background import.\nCheck terminal for process logs."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_export(self, data):
        """POST /api/vault/export — export models as metadata JSON or streaming zip."""
        from server import _get_db
        filenames = data.get("filenames", [])
        include_files = data.get("include_files", False)

        if not filenames:
            self.send_json_response({"status": "error", "message": "No filenames specified"}, 400)
            return

        try:
            db = _get_db()
            manifest = db.export_models_metadata(filenames)

            if not include_files:
                self.send_json_response({
                    "status": "success",
                    "manifest": manifest,
                    "export_type": "metadata_only"
                })
                return

            # S2-6: Stream ZIP via temp file instead of buffering entire archive in RAM.
            # This prevents OOM for large vault exports (e.g., 50GB of checkpoints).
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip', dir=os.path.join(self.root_dir, '.backend', 'cache'))
            try:
                os.close(tmp_fd)  # Close fd, zipfile will open by path
                with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                    zf.writestr('vault_manifest.json', json.dumps(manifest, indent=2, default=str))
                    for entry in manifest:
                        fn = entry.get('filename', '')
                        cat = entry.get('vault_category', '')
                        filepath = os.path.join(self.root_dir, 'Global_Vault', cat, fn)
                        if os.path.exists(filepath):
                            arcname = f"{cat}/{fn}"
                            zf.write(filepath, arcname)

                zip_size = os.path.getsize(tmp_path)
                ts = time.strftime('%Y%m%d_%H%M%S')
                filename = f"vault_export_{ts}.zip"

                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Content-Length', str(zip_size))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                # Stream from disk in 64KB chunks instead of loading entire ZIP into RAM
                _CHUNK = 64 * 1024
                with open(tmp_path, 'rb') as zf:
                    while True:
                        chunk = zf.read(_CHUNK)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            finally:
                # Always clean up temp file
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_import(self, data):
        """POST /api/vault/import — import models from a metadata manifest."""
        from server import _get_db
        manifest = data.get("manifest", [])
        if not manifest:
            self.send_json_response({"status": "error", "message": "Empty manifest"}, 400)
            return
        try:
            db = _get_db()
            result = db.import_models_metadata(manifest)
            # P4-2 fix: Unpack dict so frontend gets flat {imported:N, skipped:N}
            self.send_json_response({"status": "success", **result})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_bulk_delete(self, data):
        from server import _get_db
        models = data.get("models", [])
        if not models:
            self.send_json_response({"status": "error", "message": "No models specified"}, 400)
            return

        deleted_count = 0
        failed = []
        filenames_to_remove = []

        vault_base = os.path.abspath(os.path.join(self.root_dir, "Global_Vault"))

        for m in models:
            filename = m.get("filename")
            category = m.get("category")
            if not filename or not category:
                failed.append({"filename": filename, "reason": "Missing filename or category"})
                continue

            # S2-17: Path traversal guard — ensure resolved path stays within Global_Vault
            if ".." in filename or ".." in category:
                failed.append({"filename": filename, "reason": "Invalid path component"})
                continue
            filepath = os.path.join(self.root_dir, "Global_Vault", category, filename)
            if not os.path.abspath(filepath).startswith(vault_base):
                failed.append({"filename": filename, "reason": "Path traversal blocked"})
                continue

            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    filenames_to_remove.append(filename)
                    deleted_count += 1
                except Exception as e:
                    failed.append({"filename": filename, "reason": str(e)})
            else:
                failed.append({"filename": filename, "reason": "File not found"})

        # Batch remove DB entries
        if filenames_to_remove:
            try:
                db = _get_db()
                # P4-3: Collect file hashes before deletion for thumbnail cleanup
                hashes_to_clean = []
                for fn in filenames_to_remove:
                    model = db.get_model_by_filename(fn)
                    if model and model.get("file_hash"):
                        hashes_to_clean.append(model["file_hash"])
                db.remove_models_by_filenames(filenames_to_remove)
                # P4-3: Clean orphaned thumbnails
                thumb_dir = os.path.join(self.root_dir, ".backend", "cache", "thumbnails")
                for fh in hashes_to_clean:
                    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                        tp = os.path.join(thumb_dir, f"{fh}.{ext}")
                        if os.path.exists(tp):
                            try:
                                os.remove(tp)
                            except OSError:
                                pass
                # P2-6: Invalidate embedding cache so deleted models vanish from search
                try:
                    engine = self._get_embedding_engine()
                    engine._invalidate_cache()
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"DB cleanup after bulk delete failed: {e}")

        self.send_json_response({
            "status": "success",
            "deleted": deleted_count,
            "failed": failed
        })

    def handle_import_external(self, data):
        from symlink_manager import create_safe_directory_link
        target_path = data.get("path")
        if not target_path or not os.path.exists(target_path) or not os.path.isdir(target_path):
            self.send_json_response({"status": "error", "message": "Invalid directory provided"}, 400)
            return

        # S2-13: Validate the resolved path is a real directory (not a symlink to sensitive areas)
        resolved = os.path.realpath(target_path)
        if not os.path.isdir(resolved):
            self.send_json_response({"status": "error", "message": "Resolved path is not a directory"}, 400)
            return

        try:
            folder_name = os.path.basename(os.path.abspath(target_path)).replace(" ", "_")
            if not folder_name:
                folder_name = "External_Import"
            vault_dir = os.path.join(self.root_dir, "Global_Vault", f"External_{folder_name}")
            os.makedirs(vault_dir, exist_ok=True)
            try:
                create_safe_directory_link(resolved, os.path.join(vault_dir, "Models"))
                self.send_json_response({"status": "success"})
            except Exception as e:
                self.send_json_response({"status": "error", "message": str(e)}, 500)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_get_favorites(self):
        try:
            from server import _get_db
            db = _get_db()
            favs = db.get_all_favorites()
            self.send_json_response(favs)
        except Exception as e:
            logging.error(f"Failed to get favorites: {e}")
            self.send_json_response({})

    def handle_add_favorite(self, data):
        model_id = data.get("model_id")
        model_data = data.get("data", {})
        if not model_id:
            self.send_json_response({"error": "model_id required"}, 400)
            return
        try:
            from server import _get_db
            db = _get_db()
            db.add_favorite(str(model_id), json.dumps(model_data))
            self.send_json_response({"status": "ok"})
        except Exception as e:
            logging.error(f"Failed to add favorite: {e}")
            self.send_json_response({"error": str(e)}, 500)

    def handle_remove_favorite(self, data):
        model_id = data.get("model_id")
        if not model_id:
            self.send_json_response({"error": "model_id required"}, 400)
            return
        try:
            from server import _get_db
            db = _get_db()
            db.remove_favorite(str(model_id))
            self.send_json_response({"status": "ok"})
        except Exception as e:
            logging.error(f"Failed to remove favorite: {e}")
            self.send_json_response({"error": str(e)}, 500)

    # ══════════════════════════════════════════════════════
    #  MULTI-PATH SCANNING & MIGRATION
    # ══════════════════════════════════════════════════════

    def _get_crawler(self):
        """Get or create the shared VaultCrawler instance."""
        server_mod = sys.modules.get('server', None)
        if server_mod and hasattr(server_mod, '_vault_crawler'):
            return server_mod._vault_crawler
        # Fallback: create one
        from vault_crawler import VaultCrawler
        crawler = VaultCrawler(self.root_dir)
        if server_mod:
            server_mod._vault_crawler = crawler
        return crawler

    def _get_embedding_engine(self):
        """Get or create the shared EmbeddingEngine instance (L-2 fix).
        Avoids reinstantiating the 80MB sentence-transformer model per search request."""
        server_mod = sys.modules.get('server', None)
        if server_mod and hasattr(server_mod, '_embedding_engine'):
            return server_mod._embedding_engine
        from embedding_engine import EmbeddingEngine
        engine = EmbeddingEngine(self.db_path)
        if server_mod:
            server_mod._embedding_engine = engine
        return engine

    def handle_scan_external(self, data):
        """POST /api/vault/scan_external — Discover models from external paths.
        Body: {"source": "stability_matrix"} or {} for all sources."""
        import threading
        source = data.get("source")
        crawler = self._get_crawler()

        if crawler.scan_progress.get("active"):
            self.send_json_response({"status": "busy", "message": "A scan is already in progress."}, 409)
            return

        def _run():
            crawler.discover_external(source_name=source)
        
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.send_json_response({"status": "started", "source": source or "all"})

    def handle_hash_library(self, data):
        """POST /api/vault/hash_library — Hash all unhashed models.
        Body: {"source": "external:stability_matrix"} or {} for all."""
        import threading
        source = data.get("source")
        crawler = self._get_crawler()

        if crawler.scan_progress.get("active"):
            self.send_json_response({"status": "busy", "message": "A scan is already in progress."}, 409)
            return

        def _run():
            result = crawler.hash_library(source_path=source)
            logging.info(f"Hash library complete: {result}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.send_json_response({"status": "started", "source": source or "all"})

    def handle_hash_single(self, data):
        """POST /api/vault/hash_single — Hash one model by DB id.
        Body: {"model_id": 42}"""
        model_id = data.get("model_id")
        if not model_id:
            self.send_json_response({"error": "model_id required"}, 400)
            return
        
        crawler = self._get_crawler()
        result = crawler.hash_single_model(int(model_id))
        self.send_json_response(result)

    def handle_cancel_scan(self, data):
        """POST /api/vault/cancel_scan — Cancel the active scan/hash."""
        crawler = self._get_crawler()
        crawler.cancel_scan()
        self.send_json_response({"status": "cancelled"})

    def handle_scan_progress(self):
        """GET /api/vault/scan_progress — Returns current scan status."""
        crawler = self._get_crawler()
        self.send_json_response(crawler.scan_progress)

    def handle_external_sources(self):
        """GET /api/vault/external_sources — List available external model paths."""
        crawler = self._get_crawler()
        sources = crawler.get_external_paths()
        self.send_json_response({"sources": sources})

    def handle_migrate_models(self, data):
        """POST /api/vault/migrate — Move models from Global_Vault to external path.
        Body: {
            "filenames": ["model1.safetensors"],
            "destination_base": "I:\\StabilityMatrix-win-x64\\Data\\Models\\",
            "destination_subdir": "StableDiffusion/",
            "destination_source": "external:stability_matrix",
            "source_category": "checkpoints"
        }
        """
        import threading
        filenames = data.get("filenames", [])
        dest_base = data.get("destination_base", "")
        dest_subdir = data.get("destination_subdir", "")
        dest_source = data.get("destination_source", "")
        source_category = data.get("source_category", "")

        if not filenames or not dest_base:
            self.send_json_response({"error": "filenames and destination_base required"}, 400)
            return

        dest_dir = os.path.join(dest_base, dest_subdir) if dest_subdir else dest_base

        # Security: no traversal
        if ".." in dest_dir or ".." in dest_base:
            self.send_json_response({"error": "Invalid path"}, 403)
            return

        if not os.path.isdir(dest_dir):
            self.send_json_response({"error": f"Destination does not exist: {dest_dir}"}, 400)
            return

        def _migrate():
            from server import _get_db
            db = _get_db()
            results = []
            
            for fname in filenames:
                result = {"filename": fname, "status": "pending"}
                src_path = os.path.join(self.root_dir, "Global_Vault", source_category, fname)
                
                if not os.path.exists(src_path):
                    result["status"] = "error"
                    result["message"] = "Source file not found"
                    results.append(result)
                    continue

                dst_path = os.path.join(dest_dir, fname)
                
                # Handle duplicate filename at destination
                if os.path.exists(dst_path):
                    # Check if same file by size
                    if os.path.getsize(src_path) == os.path.getsize(dst_path):
                        # Same size — likely same file, skip copy but still update DB
                        logging.info(f"File {fname} already exists at destination (same size), skipping copy.")
                        try:
                            model = db.get_model_by_filename(fname)
                            if model and model.get("file_hash"):
                                db.update_model_source(model["file_hash"], dest_source,
                                                      self._map_vault_category(dest_subdir))
                            # Delete source
                            os.remove(src_path)
                            result["status"] = "migrated"
                            result["message"] = "Already at destination, source removed"
                        except Exception as e:
                            result["status"] = "error"
                            result["message"] = str(e)
                        results.append(result)
                        continue
                    else:
                        # Different file with same name — rename
                        base, ext = os.path.splitext(fname)
                        counter = 1
                        while os.path.exists(dst_path):
                            dst_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                            counter += 1
                        logging.info(f"Renamed to avoid conflict: {os.path.basename(dst_path)}")

                try:
                    # Copy
                    logging.info(f"Migrating {fname} → {dst_path}")
                    shutil.copy2(src_path, dst_path)
                    
                    # Verify by size (hash verification is expensive, size is sufficient for copy integrity)
                    src_size = os.path.getsize(src_path)
                    dst_size = os.path.getsize(dst_path)
                    
                    if src_size != dst_size:
                        result["status"] = "error"
                        result["message"] = "Size mismatch after copy — source NOT deleted"
                        # Clean up failed copy
                        try:
                            os.remove(dst_path)
                        except OSError:
                            pass
                        results.append(result)
                        continue
                    
                    # Update DB
                    model = db.get_model_by_filename(fname)
                    if model and model.get("file_hash"):
                        new_cat = self._map_vault_category(dest_subdir)
                        db.update_model_source(model["file_hash"], dest_source, new_cat)
                    
                    # Delete original only after verified copy
                    os.remove(src_path)
                    result["status"] = "migrated"
                    logging.info(f"Successfully migrated {fname}")
                    
                except Exception as e:
                    result["status"] = "error"
                    result["message"] = str(e)
                    logging.error(f"Migration failed for {fname}: {e}")
                
                results.append(result)

                # Emit SSE progress
                try:
                    server_mod = sys.modules.get('server', None)
                    if server_mod and hasattr(server_mod, '_sse_emit'):
                        server_mod._sse_emit({
                            "type": "migration_progress",
                            "filename": fname,
                            "status": result["status"],
                            "done": len(results),
                            "total": len(filenames)
                        })
                except Exception:
                    pass

            logging.info(f"Migration complete: {sum(1 for r in results if r['status'] == 'migrated')}/{len(results)} succeeded")

        t = threading.Thread(target=_migrate, daemon=True)
        t.start()
        self.send_json_response({"status": "started", "count": len(filenames)})

    @staticmethod
    def _map_vault_category(subdir: str) -> str:
        """Map a destination subdirectory name to a vault category."""
        subdir_clean = subdir.rstrip("/").rstrip("\\").lower()
        mapping = {
            "stablediffusion": "checkpoints",
            "lora": "loras",
            "vae": "vaes",
            "controlnet": "controlnet",
            "diffusionmodels": "unet",
            "textencoders": "clip",
            "embeddings": "embeddings",
        }
        return mapping.get(subdir_clean, subdir_clean)

