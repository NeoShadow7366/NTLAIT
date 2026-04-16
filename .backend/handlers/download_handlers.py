"""Download domain handlers — download, retry, clear, delete model.

Mixin class providing download-related HTTP handler methods.
Composed into AIWebServer via multiple inheritance.
"""
import os
import sys
import json
import uuid
import subprocess
import logging


class DownloadHandlersMixin:
    """Download domain handlers for the AIWebServer class.

    Handles:
        POST /api/download       → handle_download
        POST /api/download/retry → handle_retry_download
        GET  /api/downloads      → handle_get_downloads
        POST /api/downloads/clear → handle_clear_downloads
        POST /api/delete_model   → handle_delete_model
        POST /api/open_folder    → handle_open_folder
        POST /api/import         → handle_import_file
        GET  /api/import/status  → handle_import_status
        GET  /api/import/jobs    → handle_import_jobs
    """

    def handle_download(self, data):
        url = data.get("url")
        filename = data.get("filename")
        model_name = data.get("model_name")
        dest_folder = data.get("dest_folder")
        api_key = data.get("api_key")

        if not all([url, filename, model_name, dest_folder]):
            self.send_json_response({"status": "error", "message": "Missing download parameters"}, 400)
            return

        job_id = str(uuid.uuid4())
        downloader_script = os.path.join(self.root_dir, ".backend", "download_engine.py")
        python_exe = sys.executable

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)

        cmd = [
            python_exe, downloader_script,
            "--job_id", job_id,
            "--url", url,
            "--dest_folder", dest_folder,
            "--filename", filename,
            "--model_name", model_name,
            "--root_dir", self.root_dir
        ]
        if api_key:
            cmd.extend(["--api_key", api_key])

        proc = subprocess.Popen(cmd, **kwargs)

        # S2-3: Track download PID for cleanup on shutdown
        try:
            from server import AIWebServer
            if hasattr(AIWebServer, 'running_processes') and hasattr(AIWebServer.running_processes, 'register'):
                AIWebServer.running_processes.register(f"download_{job_id}", proc)
        except Exception:
            pass  # Registry not available — non-critical

        self.send_json_response({"status": "success", "job_id": job_id})

    def handle_retry_download(self, data):
        job_id = data.get("job_id")
        api_key = data.get("api_key")

        if not job_id:
            self.send_json_response({"status": "error", "message": "Missing job_id"}, 400)
            return

        cache_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
        if not os.path.exists(cache_file):
            self.send_json_response({"status": "error", "message": "No download history found"}, 404)
            return

        try:
            with open(cache_file, "r") as f:
                jobs = json.load(f)

            job = jobs.get(job_id)
            if not job:
                self.send_json_response({"status": "error", "message": "Job not found"}, 404)
                return

            url = job.get("url")
            dest_folder = job.get("dest_folder")
            filename = job.get("filename")
            model_name = job.get("model_name")

            if not all([url, dest_folder, filename, model_name]):
                self.send_json_response({"status": "error", "message": "Incomplete job metadata for retry"}, 400)
                return

            self.handle_download({
                "url": url,
                "filename": filename,
                "model_name": model_name,
                "dest_folder": dest_folder,
                "api_key": api_key
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_get_downloads(self):
        cache_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
        if not os.path.exists(cache_file):
            self.send_json_response({})
            return
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            self.send_json_response(data)
        except Exception:
            self.send_json_response({})

    def handle_clear_downloads(self):
        cache_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                self.send_json_response({"status": "success", "message": "Download history cleared"})
            except Exception as e:
                self.send_json_response({"status": "error", "message": str(e)}, 500)
        else:
            self.send_json_response({"status": "success", "message": "Already empty"})

    def handle_delete_model(self, data):
        from server import _get_db
        filename = data.get("filename")
        category = data.get("category")
        if not filename or not category:
            self.send_json_response({"status": "error", "message": "Missing filename or category"}, 400)
            return

        # S2-12: Path traversal guard
        if ".." in filename or ".." in category:
            self.send_json_response({"status": "error", "message": "Invalid path"}, 403)
            return

        vault_base = os.path.abspath(os.path.join(self.root_dir, "Global_Vault"))
        filepath = os.path.abspath(os.path.join(vault_base, category, filename))
        if not filepath.startswith(vault_base):
            self.send_json_response({"status": "error", "message": "Path escapes vault"}, 403)
            return

        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                db = _get_db()
                # P3-3 fix: Use get_model_by_filename → remove_model_by_id for cascade cleanup
                # (embeddings + user_tags), instead of remove_model_by_filename which leaves orphans
                model = db.get_model_by_filename(filename)
                if model:
                    db.remove_model_by_id(model["id"])
                    # P3-3: Also clean orphaned thumbnail
                    file_hash = model.get("file_hash")
                    if file_hash:
                        thumb_dir = os.path.join(self.root_dir, ".backend", "cache", "thumbnails")
                        for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                            tp = os.path.join(thumb_dir, f"{file_hash}.{ext}")
                            if os.path.exists(tp):
                                try:
                                    os.remove(tp)
                                except OSError:
                                    pass
                    # Invalidate embedding cache
                    try:
                        engine = self._get_embedding_engine()
                        engine._invalidate_cache()
                    except Exception:
                        pass
                else:
                    db.remove_model_by_filename(filename, vault_category=category)
                self.send_json_response({"status": "success", "message": "Model deleted"})
            except Exception as e:
                self.send_json_response({"status": "error", "message": str(e)}, 500)
        else:
            self.send_json_response({"status": "error", "message": "File not found"}, 404)

    def handle_open_folder(self, data):
        category = data.get("category")
        if not category:
            self.send_json_response({"status": "error", "message": "Missing category"}, 400)
            return

        # S2-11: Path traversal guard
        if ".." in category:
            self.send_json_response({"status": "error", "message": "Invalid path"}, 403)
            return

        vault_base = os.path.abspath(os.path.join(self.root_dir, "Global_Vault"))
        folder_path = os.path.abspath(os.path.join(vault_base, category))
        if not folder_path.startswith(vault_base):
            self.send_json_response({"status": "error", "message": "Path escapes vault"}, 403)
            return

        os.makedirs(folder_path, exist_ok=True)

        try:
            if os.name == 'nt':
                subprocess.Popen(['explorer', folder_path])
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, folder_path])
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_import_file(self, data):
        src_path = data.get("path")
        category = data.get("category", "")
        if not src_path:
            self.send_json_response({"status": "error", "message": "Missing path"}, 400)
            return
        try:
            from import_engine import start_import
            from server import _get_settings
            api_key = _get_settings().get("civitai_api_key", "")
            start_import(src_path, category, self.root_dir, api_key)
            self.send_json_response({"status": "success", "message": "Import started in background."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_import_status(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        import_id = qs.get("id", [None])[0]
        if not import_id:
            self.send_json_response({"status": "error", "message": "Missing id"}, 400)
            return
        try:
            from import_engine import get_import_status
            result = get_import_status(import_id)
            if not result:
                self.send_json_response({"status": "error", "message": "Job not found"}, 404)
            else:
                self.send_json_response(result)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_import_jobs(self):
        try:
            from import_engine import list_import_jobs
            self.send_json_response(list_import_jobs())
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)
