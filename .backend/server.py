import os
import sys
import sqlite3
import json
import logging
import subprocess
import signal
import time
import uuid
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ── Sprint 9: Vault Size Cache (60s TTL) ─────────────────────────
_vault_size_cache = {"size": 0, "expires": 0}

# ── Sprint 9: In-Memory Batch Generation Queue ──────────────────
_batch_queue = []  # list of {id, status, payload, result, error}
_batch_lock = threading.Lock()
_batch_worker_running = False

class AIWebServer(BaseHTTPRequestHandler):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(root_dir, ".backend", "metadata.sqlite")
    static_dir = os.path.join(root_dir, ".backend", "static")
    running_processes = {}  # PID tracking for launched packages

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # API Endpoints
        if path == "/api/models":
            self.send_api_models()
        elif path == "/api/packages":
            self.send_api_packages()
        elif path == "/api/recipes":
            self.send_api_recipes()
        elif path == "/api/downloads":
            self.handle_get_downloads()
        elif path == "/api/comfy_image":
            self.handle_comfy_image()
        elif path == "/api/comfy_upload":
            self.handle_comfy_upload()
        elif path == "/api/stop":
            self.handle_stop()
        elif path == "/api/import/status":
            self.handle_import_status()
        elif path == "/api/import/jobs":
            self.handle_import_jobs()
        elif path == "/api/gallery":
            self.handle_gallery_list()
        elif path == "/api/vault/search":
            self.handle_vault_search()
        elif path == "/api/vault/tags":
            self.handle_get_all_tags()
        elif path == "/api/hf/search":
            self.handle_hf_search()
        elif path == "/api/extensions":
            self.handle_get_extensions()
        elif path == "/api/extensions/status":
            self.handle_extension_status()
        elif path == "/api/settings":
            self.handle_get_settings()
        elif path == "/api/server_status":
            self.handle_server_status()
        elif path == "/api/logs":
            self.handle_get_logs()
        elif path == "/api/prompts":
            self.handle_list_prompts()
        elif path == "/api/generate/queue":
            self.handle_batch_queue_status()
        elif path == "/api/gallery/tags":
            self.handle_gallery_tags()
        else:
            self.serve_static_files(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # These endpoints read their own body - must be handled BEFORE the generic JSON read below
        if path == "/api/comfy_upload":
            self.handle_comfy_upload()
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        
        try:
            data = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.warning(f"Failed to parse POST body as JSON: {e}")
            data = {}

        if path == "/api/install":
            self.handle_install(data)
        elif path == "/api/launch":
            self.handle_launch(data)
        elif path == "/api/repair_dependency":
            self.handle_repair_dependency(data)
        elif path == "/api/stop":
            self.handle_stop(data)
        elif path == "/api/uninstall":
            self.handle_uninstall(data)
        elif path == "/api/download":
            self.handle_download(data)
        elif path == "/api/download/retry":
            self.handle_retry_download(data)
        elif path == "/api/downloads/clear":
            self.handle_clear_downloads()
        elif path == "/api/delete_model":
            self.handle_delete_model(data)
        elif path == "/api/open_folder":
            self.handle_open_folder(data)
        elif path == "/api/import":
            self.handle_import_file(data)
        elif path == "/api/gallery/save":
            self.handle_gallery_save(data)
        elif path == "/api/gallery/delete":
            self.handle_gallery_delete(data)
        elif path == "/api/gallery/rate":
            self.handle_gallery_rate(data)
        elif path == "/api/vault/tag/add":
            self.handle_add_tag(data)
        elif path == "/api/vault/tag/remove":
            self.handle_remove_tag(data)
        elif path == "/api/recipes/build":
            self.handle_build_recipe(data)
        elif path == "/api/extensions/install":
            self.handle_install_extension(data)
        elif path == "/api/extensions/remove":
            self.handle_remove_extension(data)
        elif path == "/api/extensions/cancel":
            self.handle_cancel_extension(data)
        elif path == "/api/vault/export":
            self.handle_vault_export(data)
        elif path == "/api/vault/import":
            self.handle_vault_import(data)
        elif path == "/api/vault/updates":
            self.handle_vault_updates(data)
        elif path == "/api/vault/health_check":
            self.handle_vault_health_check(data)
        elif path == "/api/vault/import_scan":
            self.handle_import_scan(data)
        elif path == "/api/vault/bulk_delete":
            self.handle_vault_bulk_delete(data)
        elif path == "/api/generate/batch":
            self.handle_batch_generate(data)
        elif path == "/api/prompts/save":
            self.handle_save_prompt(data)
        elif path == "/api/prompts/delete":
            self.handle_delete_prompt(data)
        elif path == "/api/settings":
            self.handle_save_settings(data)
        elif path == "/api/system/update":
            self.handle_system_update(data)
        elif path == "/api/comfy_proxy":
            self.handle_comfy_proxy(data)
        elif path == "/api/a1111_proxy":
            self.handle_a1111_proxy(data)
        elif path == "/api/forge_proxy":
            self.handle_forge_proxy(data)
        elif path == "/api/fooocus_proxy":
            self.handle_fooocus_proxy(data)
        else:
            self.send_json_response({"error": f"Endpoint {path} not found"}, 404)

    def serve_static_files(self, path):
        # Default to index.html
        if path == "/":
            path = "/index.html"
            
        # Security: Prevent directory traversal
        if ".." in path:
            self.send_error(403, "Forbidden")
            return
            
        # Check if they are requesting a thumbnail
        if path.startswith("/.backend/cache/thumbnails/"):
            filepath = os.path.join(self.root_dir, path.lstrip("/"))
        else:
            filepath = os.path.join(self.static_dir, path.lstrip("/"))
            
        if not os.path.exists(filepath):
            if path.startswith("/api/"):
                self.send_json_response({"error": "Endpoint not found"}, 404)
            else:
                self.send_error(404, "File Not Found")
            return
            
        # Basic MIME types mapping
        ext = filepath.split(".")[-1].lower()
        content_type = "text/plain"
        if ext == "html": content_type = "text/html"
        elif ext == "css": content_type = "text/css"
        elif ext == "js": content_type = "application/javascript"
        elif ext in ["jpg", "jpeg"]: content_type = "image/jpeg"
        elif ext == "png": content_type = "image/png"
        elif ext == "json": content_type = "application/json"
        elif ext == "webp": content_type = "image/webp"
        
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Server Error: {str(e)}")

    def send_api_models(self):
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            
            limit = int(qs.get('limit', [1000])[0])
            offset = int(qs.get('offset', [0])[0])

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Count total
            cursor.execute('SELECT COUNT(*) FROM models')
            total = cursor.fetchone()[0]
            
            # Fetch slice
            cursor.execute('SELECT * FROM models ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset))
            rows = cursor.fetchall()
            conn.close()
            
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(self.db_path)
            
            # Format rows
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
                del d["metadata_json"]
                d["user_tags"] = db.get_user_tags(d["file_hash"])
                models.append(d)
                
            self.send_json_response({
                "status": "success", 
                "models": models,
                "total": total,
                "limit": limit,
                "offset": offset
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def send_api_packages(self):
        packages_dir = os.path.join(self.root_dir, "packages")
        packages = []
        if os.path.exists(packages_dir):
            for d in os.listdir(packages_dir):
                app_path = os.path.join(packages_dir, d)
                if os.path.isdir(app_path):
                    manifest_path = os.path.join(app_path, "manifest.json")
                    pkg_info = {"id": d, "name": d.capitalize()}
                    
                    if os.path.exists(manifest_path):
                        try:
                            with open(manifest_path, 'r', encoding='utf-8') as f:
                                manifest = json.load(f)
                                pkg_info["name"] = manifest.get("name", d.capitalize())
                        except (json.JSONDecodeError, OSError) as e:
                            logging.warning(f"Failed to read manifest for {d}: {e}")
                    packages.append(pkg_info)
                    
        self.send_json_response({"status": "success", "packages": packages})

    def send_api_recipes(self):
        recipes_dir = os.path.join(self.root_dir, ".backend", "recipes")
        recipes = []
        if os.path.exists(recipes_dir):
            for file in os.listdir(recipes_dir):
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(recipes_dir, file), 'r', encoding='utf-8') as f:
                            recipe = json.load(f)
                            recipes.append({
                                "id": file,
                                "app_id": recipe.get("app_id"),
                                "name": recipe.get("name", file),
                                "repository": recipe.get("repository", "")
                            })
                    except Exception as e:
                        logging.error(f"Error reading recipe {file}: {e}")
                        
        self.send_json_response({"status": "success", "recipes": recipes})

    def handle_build_recipe(self, data):
        app_id = data.get("app_id")
        name = data.get("name")
        repository = data.get("repository")
        launch = data.get("launch")
        pip_packages = data.get("pip_packages", [])
        symlink_targets = data.get("symlink_targets", [])
        platform_flags = data.get("platform_flags", "")
        requirements_file = data.get("requirements_file", "requirements.txt")

        if not app_id or not name:
            self.send_json_response({"status": "error", "message": "Missing app_id or name"}, 400)
            return

        recipe_id = f"{app_id}_recipe.json"
        recipe_path = os.path.join(self.root_dir, ".backend", "recipes", recipe_id)

        recipe = {
            "app_id": app_id,
            "name": name,
            "repository": repository,
            "launch": launch,
            "pip_packages": pip_packages,
            "symlink_targets": symlink_targets,
            "platform_flags": platform_flags,
            "requirements_file": requirements_file
        }

        try:
            os.makedirs(os.path.dirname(recipe_path), exist_ok=True)
            with open(recipe_path, 'w', encoding='utf-8') as f:
                json.dump(recipe, f, indent=4)
            self.send_json_response({"status": "success", "recipe_id": recipe_id, "message": f"Recipe {recipe_id} created successfully."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_install(self, data):
        recipe_id = data.get("recipe_id")
        if not recipe_id:
            self.send_json_response({"status": "error", "message": "Missing recipe_id"}, 400)
            return
            
        recipe_path = os.path.join(self.root_dir, ".backend", "recipes", recipe_id)
        if not os.path.exists(recipe_path):
            self.send_json_response({"status": "error", "message": "Recipe not found"}, 404)
            return

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        
        logging.info(f"Triggering background installation for {recipe_id}")
        
        # Spawn isolated installation process
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)
            
        subprocess.Popen([sys.executable, installer_script, recipe_path], **kwargs)
        
        self.send_json_response({"status": "success", "message": "Installation started in background"})

    def handle_launch(self, data):
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        package_path = os.path.join(self.root_dir, "packages", package_id)
        manifest_path = os.path.join(package_path, "manifest.json")
        app_path = os.path.join(package_path, "app")
        
        # PRE-FLIGHT 1: Recover missing manifest
        if not os.path.exists(manifest_path) and os.path.exists(app_path):
            recipe_path = os.path.join(self.root_dir, ".backend", "recipes", f"{package_id}.json")
            if os.path.exists(recipe_path):
                import shutil
                shutil.copy2(recipe_path, manifest_path)
                logging.info(f"Pre-flight: Auto-recovered manifest.json for {package_id}")

        if not os.path.exists(manifest_path) or not os.path.exists(app_path):
             self.send_json_response({"status": "error", "message": "Package improperly installed"}, 404)
             return

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            self.send_json_response({"status": "error", "message": f"Could not read manifest: {str(e)}"}, 500)
            return

        launch_cmd = manifest.get("launch_command")
        if not launch_cmd:
            self.send_json_response({"status": "error", "message": "No launch_command found in manifest"}, 400)
            return

        # PRE-FLIGHT 2: Symlinks verification
        try:
            import sys
            if self.root_dir not in sys.path:
                sys.path.append(self.root_dir)
            if os.path.join(self.root_dir, ".backend") not in sys.path:
                sys.path.append(os.path.join(self.root_dir, ".backend"))
            from symlink_manager import create_safe_directory_link
            symlinks = manifest.get("model_symlinks", {})
            vault_dir = os.path.join(self.root_dir, "Global_Vault")
            for vault_src, app_target in symlinks.items():
                source_path = os.path.join(vault_dir, vault_src)
                target_path = os.path.join(app_path, app_target)
                if not os.path.exists(target_path):
                    os.makedirs(source_path, exist_ok=True)
                    create_safe_directory_link(source_path, target_path)
                    logging.info(f"Pre-flight: Recreated missing symlink for {app_target}")
        except Exception as e:
            logging.error(f"Pre-flight symlink check failed: {e}")

        # Determine python executable location
        if os.name == 'nt':
            python_exe = os.path.join(package_path, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(package_path, "env", "bin", "python")
            
        # PRE-FLIGHT 3: Executable environment verification
        if not os.path.exists(python_exe):
            self.send_json_response({
                "status": "error", 
                "message": "Isolated python environment not found. Please repair the installation."
            }, 404)
            return

        logging.info(f"Launching {package_id}...")
        
        # Pipe output to a runtime log file for web-terminal tailing
        log_path = os.path.join(package_path, "runtime.log")
        log_file = open(log_path, 'w', encoding='utf-8')
            
        # Combine command, e.g. python_exe main.py
        full_command = [python_exe] + launch_cmd.split(" ")
        
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)
            
        p = subprocess.Popen(full_command, cwd=app_path, stdout=log_file, stderr=subprocess.STDOUT, **kwargs)
        AIWebServer.running_processes[package_id] = p
        
        self.send_json_response({"status": "success", "message": "Package starting..."})

    def handle_repair_dependency(self, data):
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return
            
        package_path = os.path.join(self.root_dir, "packages", package_id)
        if os.name == 'nt':
            python_exe = os.path.join(package_path, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(package_path, "env", "bin", "python")
            
        req_path = os.path.join(package_path, "app", "requirements.txt")
        if not os.path.exists(python_exe):
            self.send_json_response({"status": "error", "message": "Python env not found"}, 404)
            return
            
        logging.info(f"Auto-repairing dependencies for {package_id}...")
        try:
            cmd = [python_exe, "-m", "pip", "install"]
            if os.path.exists(req_path):
                cmd.extend(["-r", "requirements.txt"])
            else:
                self.send_json_response({"status": "error", "message": "requirements.txt not found"}, 404)
                return
                
            kwargs = {}
            if os.name == 'nt':
                kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)
                
            subprocess.Popen(cmd, cwd=os.path.join(package_path, "app"), **kwargs)
            self.send_json_response({"status": "success", "message": "Repair started..."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": f"Repair failed: {str(e)}"}, 500)

    def handle_stop(self, data=None):
        if hasattr(self, 'path') and getattr(self, 'command', '') == 'GET':
            # Handle GET requests if applicable (using query string)
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            package_id = qs.get("package_id", [""])[0]
        else:
            package_id = data.get("package_id") if data else None
            
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        p = AIWebServer.running_processes.get(package_id)
        if not p:
            self.send_json_response({"status": "error", "message": "Package not running or not tracked"}, 404)
            return

        logging.info(f"Terminating package {package_id} (PID: {p.pid})...")
        try:
            if os.name == 'nt':
                # Force kill the process tree on Windows
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], check=False)
            else:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill() # SIGKILL
        except Exception as e:
            logging.error(f"Error stopping package {package_id}: {e}")
            self.send_json_response({"status": "error", "message": str(e)}, 500)
            return
            
        del AIWebServer.running_processes[package_id]
        self.send_json_response({"status": "success", "message": "Package stopped successfully"})

    def handle_uninstall(self, data):
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        
        logging.info(f"Triggering background uninstallation for {package_id}")
        
        # We can run uninstall inline optionally, but for UX safety we stick to subprocess
        # Python script expects recipe.json natively.
        # Let's import installer_engine directly for faster deletion without background overhead.
        try:
            sys.path.append(os.path.join(self.root_dir, ".backend"))
            from installer_engine import RecipeInstaller
            installer = RecipeInstaller(self.root_dir)
            success = installer.uninstall(package_id)
            if success:
                self.send_json_response({"status": "success", "message": "Package uninstalled successfully"})
            else:
                self.send_json_response({"status": "error", "message": "Failed to uninstall package"}, 500)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_get_extensions(self):
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            package_id = qs.get("package_id", [""])[0]
            
            if not package_id:
                self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
                return
                
            # For now, extensions only apply strictly to ComfyUI (or similar structure)
            target_dir = os.path.join(self.root_dir, "packages", package_id, "custom_nodes")
            extensions = []
            
            if os.path.exists(target_dir):
                for folder in os.listdir(target_dir):
                    ext_path = os.path.join(target_dir, folder)
                    if os.path.isdir(ext_path) and not folder.startswith("__"):
                        extensions.append({"name": folder, "path": ext_path})
            
            self.send_json_response({"status": "success", "extensions": extensions})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_install_extension(self, data):
        package_id = data.get("package_id")
        repo_url = data.get("repo_url")
        
        if not package_id or not repo_url:
            self.send_json_response({"status": "error", "message": "Missing package_id or repo_url"}, 400)
            return
            
        target_dir = os.path.join(self.root_dir, "packages", package_id, "custom_nodes")
        os.makedirs(target_dir, exist_ok=True)
        
        import uuid
        import threading
        job_id = str(uuid.uuid4())[:8]
        
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from installer_engine import ExtensionCloneTracker
            tracker = ExtensionCloneTracker(self.root_dir)
            
            logging.info(f"Starting tracked clone of {repo_url} (job: {job_id})")
            t = threading.Thread(
                target=tracker.clone_with_progress,
                args=(repo_url, target_dir, job_id),
                daemon=True
            )
            t.start()
            self.send_json_response({"status": "success", "job_id": job_id, "message": "Extension clone started with progress tracking."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_extension_status(self):
        """GET /api/extensions/status?job_id=X — poll real-time clone progress."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        job_id = qs.get("job_id", [""])[0]
        if not job_id:
            self.send_json_response({"status": "error", "message": "Missing job_id"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from installer_engine import ExtensionCloneTracker
            tracker = ExtensionCloneTracker(self.root_dir)
            job = tracker.get_job_status(job_id)
            if not job:
                self.send_json_response({"status": "error", "message": "Job not found"}, 404)
            else:
                self.send_json_response(job)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_cancel_extension(self, data):
        """POST /api/extensions/cancel — kill a running extension clone."""
        job_id = data.get("job_id")
        if not job_id:
            self.send_json_response({"status": "error", "message": "Missing job_id"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from installer_engine import ExtensionCloneTracker
            tracker = ExtensionCloneTracker(self.root_dir)
            success = tracker.cancel_job(job_id)
            if success:
                self.send_json_response({"status": "success", "message": "Clone cancelled."})
            else:
                self.send_json_response({"status": "error", "message": "Could not cancel (no PID or already finished)."}, 400)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_remove_extension(self, data):
        package_id = data.get("package_id")
        ext_name = data.get("ext_name")
        
        if not package_id or not ext_name:
            self.send_json_response({"status": "error", "message": "Missing package_id or ext_name"}, 400)
            return
            
        target_path = os.path.join(self.root_dir, "packages", package_id, "custom_nodes", ext_name)
        if not os.path.exists(target_path):
            self.send_json_response({"status": "error", "message": "Extension not found"}, 404)
            return
            
        import shutil
        try:
            shutil.rmtree(target_path)
            self.send_json_response({"status": "success", "message": "Extension removed."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_updates(self, data):
        updater_script = os.path.join(self.root_dir, ".backend", "update_checker.py")
        python_exe = sys.executable
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
        
        try:
            subprocess.Popen([python_exe, updater_script], **kwargs)
            self.send_json_response({"status": "success", "message": "Update check started in background."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_vault_health_check(self, data):
        # A lightweight immediate check of the vault packages symlinks and missing thumbnails
        broken_links = 0
        packages_dir = os.path.join(self.root_dir, "packages")
        
        if os.path.exists(packages_dir):
            for d in os.listdir(packages_dir):
                pkg_models = os.path.join(packages_dir, d, "models")
                if os.path.exists(pkg_models):
                    for src_dir, dirs, files in os.walk(pkg_models):
                        for f in files:
                            p = os.path.join(src_dir, f)
                            if os.path.islink(p) and not os.path.exists(os.readlink(p)):
                                try:
                                    os.unlink(p)
                                    broken_links += 1
                                except: pass
                                
        self.send_json_response({"status": "success", "message": f"Repaired {broken_links} broken symlinks in packages."})

    def handle_get_settings(self):
        settings_path = os.path.join(self.root_dir, ".backend", "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json_response(data)
                return
            except (json.JSONDecodeError, OSError) as e:
                logging.warning(f"Failed to read settings.json, returning defaults: {e}")
        self.send_json_response({"theme": "dark", "civitai_api_key": "", "auto_updates": True})

    def handle_save_settings(self, data):
        settings_path = os.path.join(self.root_dir, ".backend", "settings.json")
        try:
            # Merge with existing settings to avoid data loss from partial saves
            existing = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    existing = {}
            existing.update(data)
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=4)
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_system_update(self, data):
        updater_script = os.path.join(self.root_dir, ".backend", "updater.py")
        if not os.path.exists(updater_script):
            self.send_json_response({"status": "error", "message": "Updater script not found!"}, 404)
            return
            
        python_exe = sys.executable
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
        
        try:
            subprocess.Popen([python_exe, updater_script, "--pid", str(os.getpid())], **kwargs)
            self.send_json_response({"status": "success", "message": "Applying System Update. The server may restart..."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_get_logs(self):
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            package_id = qs.get("package_id", [""])[0]
            if not package_id:
                self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
                return
            
            log_path = os.path.join(self.root_dir, "packages", package_id, "runtime.log")
            if not os.path.exists(log_path):
                self.send_json_response({"status": "success", "logs": "--- No active execution environment. Logs empty. ---"})
                return
            
            # Read last 150 lines safely
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            tail = "".join(lines[-150:])
            
            self.send_json_response({"status": "success", "logs": tail})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_download(self, data):
        url = data.get("url")
        filename = data.get("filename")
        model_name = data.get("model_name")
        dest_folder = data.get("dest_folder")
        api_key = data.get("api_key")

        if not all([url, filename, model_name, dest_folder]):
            self.send_json_response({"status": "error", "message": "Missing download parameters"}, 400)
            return
            
        import uuid
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

        subprocess.Popen(cmd, **kwargs)
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
                
            # Trigger same logic as handle_download but reuse job params
            # We use handle_download's logic directly to spawn a NEW job_id or same?
            # User likely wants to "retry" the same slot, but my system uses UUIDs per launch.
            # I will spawn a new job but the UI will probably just show a new entry.
            # Actually, let's just re-launch handle_download with the old params.
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
        filename = data.get("filename")
        category = data.get("category")
        if not filename or not category:
            self.send_json_response({"status": "error", "message": "Missing filename or category"}, 400)
            return
            
        filepath = os.path.join(self.root_dir, "Global_Vault", category, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                # Cleanup DB natively using metadata_db
                from metadata_db import MetadataDB
                db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
                db.remove_model_by_filename(filename)
                self.send_json_response({"status": "success", "message": "Model deleted"})
            except Exception as e:
                self.send_json_response({"status": "error", "message": str(e)}, 500)
        else:
            self.send_json_response({"status": "error", "message": "File not found"}, 404)

    def handle_import_file(self, data):
        src_path = data.get("path")
        category = data.get("category", "")
        api_key = data.get("api_key", "")
        if not src_path or not os.path.exists(src_path):
            self.send_json_response({"status": "error", "message": "File not found"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from import_engine import start_import
            import_id = start_import(src_path, category, self.root_dir, api_key)
            self.send_json_response({"status": "queued", "import_id": import_id})
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
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
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
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from import_engine import list_import_jobs
            self.send_json_response(list_import_jobs())
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_gallery_list(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        sort = qs.get("sort", ["newest"])[0]
        tag = qs.get("tag", [""])[0]
        try:
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            if tag:
                rows = db.list_generations_by_tag(tag)
            else:
                rows = db.list_generations(sort=sort)
            self.send_json_response({"status": "success", "generations": rows})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_gallery_tags(self):
        """GET /api/gallery/tags — returns unique tags from all generations."""
        try:
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            tags = db.get_gallery_tags()
            self.send_json_response({"status": "success", "tags": tags})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_gallery_save(self, data):
        try:
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            row_id = db.save_generation(
                image_path=data.get("image_path"),
                prompt=data.get("prompt", ""),
                negative=data.get("negative", ""),
                model=data.get("model", ""),
                seed=data.get("seed"),
                steps=data.get("steps"),
                cfg=data.get("cfg"),
                sampler=data.get("sampler", ""),
                width=data.get("width"),
                height=data.get("height"),
                extra_json=json.dumps(data.get("extra", {}))
            )
            self.send_json_response({"status": "success", "id": row_id})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_gallery_delete(self, data):
        gen_id = data.get("id")
        if not gen_id:
            self.send_json_response({"status": "error", "message": "Missing id"}, 400)
            return
        try:
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            db.delete_generation(gen_id)
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_gallery_rate(self, data):
        gen_id = data.get("id")
        rating = data.get("rating", 0)
        if not gen_id:
            self.send_json_response({"status": "error", "message": "Missing id"}, 400)
            return
        try:
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            db.rate_generation(gen_id, rating)
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_open_folder(self, data):
        category = data.get("category")
        if not category:
            self.send_json_response({"status": "error", "message": "Missing category"}, 400)
            return
            
        folder_path = os.path.normpath(os.path.join(self.root_dir, "Global_Vault", category))
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

    def handle_comfy_proxy(self, data):
        endpoint = data.get("endpoint")
        if not endpoint:
            self.send_json_response({"error": "No endpoint specified"}, 400)
            return
            
        payload = data.get("payload")
        if endpoint == "/api/generate" and payload:
            from proxy_translators import build_comfy_workflow
            try:
                payload = build_comfy_workflow(payload)
                endpoint = "/prompt"
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return

        import urllib.request
        url = f"http://127.0.0.1:8188{endpoint}"
        
        try:
            if payload:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            else:
                req = urllib.request.Request(url)
            
            with urllib.request.urlopen(req, timeout=30) as res:
                content = res.read().decode('utf-8')
                self.send_json_response(json.loads(content))
        except Exception as e:
            err_msg = str(e)
            if "Connection refused" in err_msg or "WinError 10061" in err_msg or "RemoteDisconnected" in err_msg:
                p = AIWebServer.running_processes.get("comfyui")
                if p and p.poll() is not None:
                    # Process died quietly. Parse logs.
                    log_path = os.path.join(self.root_dir, "packages", "comfyui", "runtime.log")
                    missing_mod = None
                    if os.path.exists(log_path):
                        try:
                            with open(log_path, 'r', encoding='utf-8') as f:
                                lines = f.readlines()[-50:]
                            for line in lines:
                                if "ModuleNotFoundError" in line or "ImportError" in line:
                                    missing_mod = line.strip()
                                    break
                        except Exception:
                            pass
                    
                    if missing_mod:
                        self.send_json_response({
                            "error": "engine_crashed", 
                            "message": f"Engine crashed. {missing_mod}",
                            "missing_module": missing_mod,
                            "repair_available": True
                        }, 500)
                        return
            self.send_json_response({"error": err_msg}, 500)

    def handle_comfy_image(self):
        # proxy raw image bytes from comfyUI
        import urllib.request
        from urllib.parse import urlparse
        
        parsed = urlparse(self.path)
        qs = parsed.query
        url = f"http://127.0.0.1:8188/view?{qs}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as res:
                img_data = res.read()
                
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(img_data)
        except Exception as e:
            self.send_error(500, str(e))

    def handle_comfy_upload(self):
        import urllib.request
        try:
            length = int(self.headers['Content-Length'])
            boundary = self.headers['Content-Type'].split('boundary=')[1].encode()
            body = self.rfile.read(length)
            
            url = f"http://127.0.0.1:8188/upload/image"
            req = urllib.request.Request(url, data=body, headers={'Content-Type': self.headers['Content-Type']})
            with urllib.request.urlopen(req, timeout=30) as res:
                self.send_json_response(json.loads(res.read().decode('utf-8')))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_a1111_proxy(self, data):
        payload = data.get("payload")
        endpoint = data.get("endpoint", "/sdapi/v1/txt2img")
        
        if endpoint == "/api/generate" and payload:
            import sys, os
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from proxy_translators import build_a1111_payload
            try:
                payload = build_a1111_payload(payload)
                endpoint = "/sdapi/v1/img2img" if "init_images" in payload else "/sdapi/v1/txt2img"
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return
                
        import urllib.request
        url = f"http://127.0.0.1:7860{endpoint}"
        try:
            if payload:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as res:
                content = res.read().decode('utf-8')
                self.send_json_response(json.loads(content))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_forge_proxy(self, data):
        payload = data.get("payload")
        endpoint = data.get("endpoint", "/sdapi/v1/txt2img")
        
        if endpoint == "/api/generate" and payload:
            import sys, os
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from proxy_translators import build_a1111_payload
            try:
                payload = build_a1111_payload(payload)
                endpoint = "/sdapi/v1/img2img" if "init_images" in payload else "/sdapi/v1/txt2img"
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return
                
        import urllib.request
        url = f"http://127.0.0.1:7861{endpoint}"
        try:
            if payload:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as res:
                content = res.read().decode('utf-8')
                self.send_json_response(json.loads(content))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_fooocus_proxy(self, data):
        payload = data.get("payload")
        endpoint = data.get("endpoint", "/v1/generation/text-to-image")
        
        if endpoint == "/api/generate" and payload:
            import sys, os
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from proxy_translators import build_fooocus_payload
            try:
                payload = build_fooocus_payload(payload)
                endpoint = "/v1/generation/text-to-image"
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return
                
        import urllib.request
        url = f"http://127.0.0.1:8888{endpoint}"
        try:
            if payload:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as res:
                content = res.read().decode('utf-8')
                self.send_json_response(json.loads(content))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_stop(self):
        import subprocess
        import os
        import json
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            package_id = post_data.get("package_id")
            
            if package_id in AIWebServer.running_processes:
                p = AIWebServer.running_processes[package_id]
                if os.name == 'nt':
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
                else:
                    p.terminate()
                del AIWebServer.running_processes[package_id]
                self.send_json_response({"status": "success"})
            else:
                self.send_json_response({"status": "not_running", "message": "Package algorithm not strictly mapped in server."})
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))



    def handle_vault_search(self):
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            q = qs.get("query", [""])[0]
            limit = int(qs.get("limit", [50])[0])
            
            if not q:
                return self.send_api_models()
                
            logging.info(f"Performing semantic search for: {q}")
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(self.db_path)
            from embedding_engine import EmbeddingEngine
            engine = EmbeddingEngine(self.db_path)
            results = engine.search(q, top_k=limit)
            
            models = []
            for score, fhash in results:
                # Need similarity threshold to exclude bad matches
                if score < 0.1: continue
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
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(self.db_path)
            tags = db.get_all_user_tags()
            self.send_json_response({"status": "success", "tags": tags})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_add_tag(self, data):
        hash_val = data.get("file_hash")
        tag = data.get("tag")
        if not hash_val or not tag:
            self.send_json_response({"status": "error", "message": "Missing hash or tag"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(self.db_path)
            db.add_user_tag(hash_val, tag.strip())
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_remove_tag(self, data):
        hash_val = data.get("file_hash")
        tag = data.get("tag")
        if not hash_val or not tag:
            self.send_json_response({"status": "error", "message": "Missing hash or tag"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(self.db_path)
            db.remove_user_tag(hash_val, tag.strip())
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_hf_search(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        query = qs.get("query", [""])[0]
        type_filter = qs.get("type", [""])[0]
        limit = int(qs.get("limit", [40])[0])
        
        # Augment query for Text Encoder searches
        if type_filter == "Text Encoder":
            if not query:
                query = "clip t5-xxl encoder"
            else:
                query += " clip t5 encoder"
        
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from hf_client import HFClient
            settings_path = os.path.join(self.root_dir, ".backend", "settings.json")
            api_key = None
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    s = json.load(f)
                    api_key = s.get("hf_api_key")
            
            client = HFClient(api_key=api_key)
            result = client.search_models(query=query, limit=limit)
            self.send_json_response({"status": "success", "items": result})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_import_scan(self, data):
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            from import_engine import start_import
            
            vault_dir = os.path.join(self.root_dir, "Global_Vault")
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            
            known_filenames = {r['filename'] for r in db.list_models(limit=99999)}
            
            count = 0
            api_key = data.get("api_key", "")
            
            for root, _, files in os.walk(vault_dir):
                for f in files:
                    if any(f.lower().endswith(x) for x in ['.safetensors', '.ckpt', '.pt', '.bin']):
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
        filenames = data.get("filenames", [])
        include_files = data.get("include_files", False)

        if not filenames:
            self.send_json_response({"status": "error", "message": "No filenames specified"}, 400)
            return

        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            manifest = db.export_models_metadata(filenames)

            if not include_files:
                # Metadata-only export — return JSON
                self.send_json_response({
                    "status": "success",
                    "manifest": manifest,
                    "export_type": "metadata_only"
                })
                return

            # Streaming zip export with model files + manifest
            import zipfile
            import io
            import time as _time

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                # Write metadata manifest
                zf.writestr('vault_manifest.json', json.dumps(manifest, indent=2, default=str))

                # Write model files
                for entry in manifest:
                    fn = entry.get('filename', '')
                    cat = entry.get('vault_category', '')
                    filepath = os.path.join(self.root_dir, 'Global_Vault', cat, fn)
                    if os.path.exists(filepath):
                        arcname = f"{cat}/{fn}"
                        zf.write(filepath, arcname)

            zip_bytes = buf.getvalue()
            ts = _time.strftime('%Y%m%d_%H%M%S')
            filename = f"vault_export_{ts}.zip"

            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Length', str(len(zip_bytes)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(zip_bytes)

        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_server_status(self):
        global _vault_size_cache
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            
            unpopulated = len(db.get_unpopulated_models())

            # Dashboard analytics stats
            stats = db.get_dashboard_stats()
            
            downloads_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
            active_downloads = 0
            recent_downloads = []
            if os.path.exists(downloads_file):
                with open(downloads_file, 'r') as f:
                    jobs = json.load(f)
                    active_downloads = sum(1 for j in jobs.values() if j.get("status") not in ["completed", "failed", "error"])
                    # Sprint 9: Recent completed downloads for activity feed
                    completed = [{"id": k, **v} for k, v in jobs.items() if v.get("status") == "completed"]
                    completed.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
                    recent_downloads = completed[:5]
            
            # LAN sharing status
            settings_path = os.path.join(self.root_dir, ".backend", "settings.json")
            lan_sharing = False
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, 'r') as f:
                        lan_sharing = json.load(f).get("lan_sharing", False)
                except (json.JSONDecodeError, OSError):
                    pass

            lan_ip = ""
            if lan_sharing:
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    lan_ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    lan_ip = "unknown"

            # Sprint 9: Vault size with 60-second cache TTL
            now = time.time()
            if now >= _vault_size_cache["expires"]:
                vault_dir = os.path.join(self.root_dir, "Global_Vault")
                vault_size_bytes = 0
                if os.path.exists(vault_dir):
                    for root, dirs, files in os.walk(vault_dir):
                        for f in files:
                            try:
                                vault_size_bytes += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
                _vault_size_cache["size"] = vault_size_bytes
                _vault_size_cache["expires"] = now + 60
            vault_size_bytes = _vault_size_cache["size"]

            # Installed / running packages
            packages_dir = os.path.join(self.root_dir, "packages")
            installed_packages = 0
            if os.path.exists(packages_dir):
                installed_packages = sum(1 for d in os.listdir(packages_dir) if os.path.isdir(os.path.join(packages_dir, d)))
            running_packages = len(AIWebServer.running_processes)

            # Sprint 9: Recent activity + category distribution
            recent_generations = db.get_recent_activity(limit=5)
            category_distribution = db.get_vault_category_distribution()

            # Sprint 10: Disk space warning threshold
            vault_size_warning_gb = 50  # default
            settings_data = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, 'r') as f:
                        settings_data = json.load(f)
                    vault_size_warning_gb = settings_data.get('vault_size_warning_gb', 50)
                except (json.JSONDecodeError, OSError):
                    pass

            self.send_json_response({
                "unpopulated_models": unpopulated,
                "active_downloads": active_downloads,
                "is_syncing": (unpopulated > 0 or active_downloads > 0),
                "lan_sharing": lan_sharing,
                "lan_ip": lan_ip,
                # Sprint 8: Dashboard analytics
                "total_models": stats.get('total_models', 0),
                "total_generations": stats.get('total_generations', 0),
                "prompts_saved": stats.get('prompts_saved', 0),
                "vault_size_bytes": vault_size_bytes,
                "installed_packages": installed_packages,
                "running_packages": running_packages,
                # Sprint 9: Dashboard intelligence
                "recent_generations": recent_generations,
                "recent_downloads": recent_downloads,
                "category_distribution": category_distribution,
                # Sprint 10: Disk space warning
                "vault_size_warning_gb": vault_size_warning_gb
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Sprint 9: Vault Import Handler ──────────────────────────────

    def handle_vault_import(self, data):
        """POST /api/vault/import — restore model metadata from exported manifest."""
        manifest = data.get("manifest", [])
        if not manifest:
            self.send_json_response({"status": "error", "message": "No manifest data provided"}, 400)
            return

        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            result = db.import_models_metadata(manifest)
            self.send_json_response({
                "status": "success",
                "imported": result["imported"],
                "skipped": result["skipped"],
                "failed": result["failed"],
                "message": f"Imported {result['imported']} models, skipped {result['skipped']} duplicates."
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Sprint 9: Batch Generation Queue ────────────────────────────

    def handle_batch_generate(self, data):
        """POST /api/generate/batch — add one or more payloads to the batch queue."""
        global _batch_worker_running
        payloads = data.get("payloads", [])
        if not payloads:
            # Single payload shorthand
            payload = data.get("payload")
            if payload:
                payloads = [payload]

        if not payloads:
            self.send_json_response({"status": "error", "message": "No payloads provided"}, 400)
            return

        job_ids = []
        with _batch_lock:
            for p in payloads:
                job_id = str(uuid.uuid4())[:8]
                _batch_queue.append({
                    "id": job_id,
                    "status": "pending",
                    "payload": p,
                    "result": None,
                    "error": None,
                    "created_at": time.time()
                })
                job_ids.append(job_id)

        # Start worker thread if not running
        if not _batch_worker_running:
            t = threading.Thread(target=self._batch_worker, daemon=True)
            t.start()

        self.send_json_response({
            "status": "success",
            "job_ids": job_ids,
            "queue_length": len(_batch_queue),
            "message": f"Added {len(job_ids)} job(s) to batch queue."
        })

    def handle_batch_queue_status(self):
        """GET /api/generate/queue — returns current batch queue state."""
        with _batch_lock:
            queue_snapshot = [
                {
                    "id": j["id"],
                    "status": j["status"],
                    "prompt": (j.get("payload") or {}).get("prompt", "")[:80],
                    "result": j.get("result"),
                    "error": j.get("error"),
                    "created_at": j.get("created_at", 0)
                }
                for j in _batch_queue
            ]
        self.send_json_response({"status": "success", "queue": queue_snapshot})

    @staticmethod
    def _batch_worker():
        """Background worker that processes batch generation queue sequentially."""
        global _batch_worker_running
        _batch_worker_running = True
        logging.info("Batch generation worker started.")

        while True:
            job = None
            with _batch_lock:
                for j in _batch_queue:
                    if j["status"] == "pending":
                        j["status"] = "running"
                        job = j
                        break

            if not job:
                _batch_worker_running = False
                logging.info("Batch generation worker finished — queue empty.")
                break

            try:
                import urllib.request
                # Determine backend from payload
                backend = job["payload"].get("backend", "comfyui")
                proxy_map = {
                    "comfyui": "http://127.0.0.1:8188",
                    "a1111": "http://127.0.0.1:7860",
                    "forge": "http://127.0.0.1:7861",
                    "fooocus": "http://127.0.0.1:8888"
                }
                base_url = proxy_map.get(backend, "http://127.0.0.1:8188")

                # Build translated payload
                root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                sys.path.insert(0, os.path.join(root_dir, ".backend"))

                if backend == "comfyui":
                    from proxy_translators import build_comfy_workflow
                    translated = build_comfy_workflow(job["payload"])
                    endpoint = "/prompt"
                elif backend in ("a1111", "forge"):
                    from proxy_translators import build_a1111_payload
                    translated = build_a1111_payload(job["payload"])
                    endpoint = "/sdapi/v1/img2img" if "init_images" in translated else "/sdapi/v1/txt2img"
                elif backend == "fooocus":
                    from proxy_translators import build_fooocus_payload
                    translated = build_fooocus_payload(job["payload"])
                    endpoint = "/v1/generation/text-to-image"
                else:
                    translated = job["payload"]
                    endpoint = "/prompt"

                url = f"{base_url}{endpoint}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(translated).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=300) as res:
                    content = json.loads(res.read().decode('utf-8'))

                with _batch_lock:
                    job["status"] = "done"
                    job["result"] = content
                logging.info(f"Batch job {job['id']} completed.")

            except Exception as e:
                with _batch_lock:
                    job["status"] = "failed"
                    job["error"] = str(e)
                logging.error(f"Batch job {job['id']} failed: {e}")

    # ── Prompt Library Handlers ─────────────────────────────────────


    def handle_list_prompts(self):
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            search = qs.get("search", [None])[0]
            limit = int(qs.get("limit", [100])[0])
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            prompts = db.list_prompts(search=search, limit=limit)
            self.send_json_response({"status": "success", "prompts": prompts})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_save_prompt(self, data):
        title = data.get("title", "").strip()
        if not title:
            self.send_json_response({"status": "error", "message": "Title is required"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            row_id = db.save_prompt(
                title=title,
                prompt=data.get("prompt", ""),
                negative=data.get("negative", ""),
                model=data.get("model", ""),
                tags=data.get("tags", ""),
                extra_json=json.dumps(data.get("extra", {})) if data.get("extra") else None
            )
            self.send_json_response({"status": "success", "id": row_id})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_delete_prompt(self, data):
        prompt_id = data.get("id")
        if not prompt_id:
            self.send_json_response({"status": "error", "message": "Missing id"}, 400)
            return
        try:
            sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
            from metadata_db import MetadataDB
            db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
            db.delete_prompt(prompt_id)
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Bulk Vault Operations Handler ──────────────────────────────

    def handle_vault_bulk_delete(self, data):
        models = data.get("models", [])
        if not models:
            self.send_json_response({"status": "error", "message": "No models specified"}, 400)
            return

        deleted_count = 0
        failed = []
        filenames_to_remove = []

        for m in models:
            filename = m.get("filename")
            category = m.get("category")
            if not filename or not category:
                failed.append({"filename": filename, "reason": "Missing filename or category"})
                continue
            filepath = os.path.join(self.root_dir, "Global_Vault", category, filename)
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
                sys.path.insert(0, os.path.join(self.root_dir, ".backend"))
                from metadata_db import MetadataDB
                db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
                db.remove_models_by_filenames(filenames_to_remove)
            except Exception as e:
                logging.error(f"DB cleanup after bulk delete failed: {e}")

        self.send_json_response({
            "status": "success",
            "deleted": deleted_count,
            "failed": failed
        })


def start_background_scanners():
    import threading
    import os
    
    def _run_scanners():
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # 1. Run the ultra-fast Vault Crawler
            from vault_crawler import VaultCrawler
            crawler = VaultCrawler(root_dir)
            crawler.crawl()
            
            # 2. Run the Rate-Limited CivitAI Client
            from civitai_client import CivitaiClient
            civitai = CivitaiClient(root_dir)
            civitai.process_unpopulated_models()
        except Exception as e:
            logging.error(f"Background Scanners failed: {e}")

    t = threading.Thread(target=_run_scanners, daemon=True)
    t.start()
    logging.info("Spawned async backend scanners...")

def run_server(port=8080):
    # Check settings for LAN sharing
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_path = os.path.join(root_dir, ".backend", "settings.json")
    lan_sharing = False
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                lan_sharing = json.load(f).get("lan_sharing", False)
        except (json.JSONDecodeError, OSError):
            pass

    host = '0.0.0.0' if lan_sharing else ''
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, AIWebServer)

    if lan_sharing:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
            logging.info(f"LAN sharing enabled — accessible at http://{lan_ip}:{port}")
        except Exception:
            logging.info(f"LAN sharing enabled — accessible at http://0.0.0.0:{port}")
    
    logging.info(f"Starting lightweight Web Server on http://localhost:{port}")
    start_background_scanners()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Server stopped.")

if __name__ == "__main__":
    run_server()
