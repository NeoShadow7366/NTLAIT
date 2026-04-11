"""Package domain handlers — install, launch, stop, repair, extensions, recipes.

Mixin class providing package lifecycle HTTP handler methods.
Composed into AIWebServer via multiple inheritance.
"""
import os
import sys
import json
import time
import shutil
import uuid
import subprocess
import threading
import datetime
import logging


class PackageHandlersMixin:
    """Package domain handlers for the AIWebServer class.

    Handles:
        GET  /api/models          → send_api_models
        GET  /api/packages        → send_api_packages
        GET  /api/recipes         → send_api_recipes
        GET  /api/install/status  → handle_install_status
        POST /api/recipes/build   → handle_build_recipe
        POST /api/install         → handle_install
        POST /api/launch          → handle_launch
        POST /api/stop            → handle_stop
        POST /api/restart         → handle_restart
        POST /api/uninstall       → handle_uninstall
        POST /api/repair/dependency → handle_repair_dependency
        POST /api/repair/install  → handle_repair_install
        GET  /api/extensions      → handle_get_extensions
        POST /api/extensions/install → handle_install_extension
        GET  /api/extensions/status → handle_extension_status
        POST /api/extensions/cancel → handle_cancel_extension
        POST /api/extensions/remove → handle_remove_extension
        GET  /api/prompts         → handle_list_prompts
        POST /api/prompts/save    → handle_save_prompt
        POST /api/prompts/delete  → handle_delete_prompt
        GET  /api/ollama/status   → handle_ollama_status
        POST /api/ollama/enhance  → handle_ollama_enhance
    """

    def send_api_models(self):
        try:
            from server import _get_db
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            limit = int(qs.get('limit', [1000])[0])
            offset = int(qs.get('offset', [0])[0])
            db = _get_db()
            result = db.get_models_paginated(limit=limit, offset=offset)
            self.send_json_response({
                "status": "success",
                "models": result["models"],
                "total": result["total"],
                "limit": limit,
                "offset": offset
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Disk size cache (non-blocking) ─────────────────────────────
    _disk_size_cache = {}
    _disk_size_thread = None

    @classmethod
    def _compute_dir_size_mb(cls, path: str) -> float:
        """Calculate total size of a directory in MB. Returns 0 on error."""
        total = 0
        try:
            for dirpath, _dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except OSError:
            pass
        return round(total / (1024 * 1024), 1)

    @classmethod
    def _refresh_disk_sizes(cls, packages_dir: str):
        """Background worker: refresh disk sizes for all installed packages."""
        def _worker():
            try:
                if not os.path.exists(packages_dir):
                    return
                for d in os.listdir(packages_dir):
                    app_path = os.path.join(packages_dir, d)
                    if os.path.isdir(app_path):
                        cls._disk_size_cache[d] = cls._compute_dir_size_mb(app_path)
            except Exception:
                pass
            finally:
                cls._disk_size_thread = None

        if cls._disk_size_thread is None or not cls._disk_size_thread.is_alive():
            cls._disk_size_thread = threading.Thread(target=_worker, daemon=True)
            cls._disk_size_thread.start()

    def send_api_packages(self):
        from server import AIWebServer
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
                                pkg_info["installed_version"] = manifest.get("installed_version")
                                pkg_info["installed_at"] = manifest.get("installed_at")
                                pkg_info["port"] = manifest.get("port")
                        except (json.JSONDecodeError, OSError) as e:
                            logging.warning(f"Failed to read manifest for {d}: {e}")

                    # Add running status via thread-safe ProcessRegistry
                    pkg_info["is_running"] = AIWebServer.running_processes.is_running(d)
                    # Disk usage from cache (non-blocking)
                    pkg_info["disk_size_mb"] = AIWebServer._disk_size_cache.get(d)
                    packages.append(pkg_info)

        # Trigger background refresh of disk sizes
        AIWebServer._refresh_disk_sizes(packages_dir)
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
                                "repository": recipe.get("repository", ""),
                                "description": recipe.get("description", "")
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

    def handle_install_status(self):
        """Serve the install_jobs.json file so the frontend can poll progress."""
        jobs_file = os.path.join(self.root_dir, ".backend", "cache", "install_jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
            else:
                jobs = {}
            self.send_json_response({"status": "success", "jobs": jobs})
        except (json.JSONDecodeError, OSError):
            self.send_json_response({"status": "success", "jobs": {}})

    def handle_install(self, data):
        from server import AIWebServer
        recipe_id = data.get("recipe_id")
        if not recipe_id:
            self.send_json_response({"status": "error", "message": "Missing recipe_id"}, 400)
            return

        recipe_path = os.path.join(self.root_dir, ".backend", "recipes", recipe_id)
        if not os.path.exists(recipe_path):
            self.send_json_response({"status": "error", "message": "Recipe not found"}, 404)
            return

        try:
            with open(recipe_path, 'r', encoding='utf-8') as f:
                recipe_data = json.load(f)
            app_id = recipe_data.get("app_id", recipe_id)
        except Exception:
            app_id = recipe_id

        # Guard: Reject duplicate installs (thread-safe check)
        if AIWebServer.running_installs.is_running(app_id):
            self.send_json_response({
                "status": "error",
                "message": f"{app_id} is already being installed. Please wait for it to finish."
            }, 409)
            return

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        logging.info(f"Triggering background installation for {recipe_id}")

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

        proc = subprocess.Popen([sys.executable, installer_script, recipe_path], **kwargs)
        AIWebServer.running_installs.register(app_id, proc)
        self.send_json_response({"status": "success", "message": "Installation started in background"})

    def handle_launch(self, data):
        from server import AIWebServer
        from symlink_manager import create_safe_directory_link
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        # Guard: Prevent double-launch
        if AIWebServer.running_processes.is_running(package_id):
            port = AIWebServer.running_processes.get_port(package_id) or 7860
            url = f"http://127.0.0.1:{port}"
            self.send_json_response({"status": "success", "message": "Package already running.", "url": url, "already_running": True})
            return

        package_path = os.path.join(self.root_dir, "packages", package_id)
        manifest_path = os.path.join(package_path, "manifest.json")
        app_path = os.path.join(package_path, "app")

        # PRE-FLIGHT 1: Recover missing manifest
        if not os.path.exists(manifest_path) and os.path.exists(app_path):
            recipe_path = os.path.join(self.root_dir, ".backend", "recipes", f"{package_id}.json")
            if os.path.exists(recipe_path):
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

        # PRE-FLIGHT 2: Verify the launch script exists
        launch_script = launch_cmd.split(" ")[0]
        launch_script_path = os.path.join(app_path, launch_script)
        if not os.path.exists(launch_script_path):
            logging.error(f"Launch script not found: {launch_script_path}")
            self.send_json_response({
                "status": "error",
                "message": f"Source code is missing or corrupted ({launch_script} not found). Use Repair to re-download.",
                "needs_repair": True
            }, 404)
            return

        # PRE-FLIGHT 3: Symlinks verification
        try:
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

        # PRE-FLIGHT 4: Git safe.directory (prevents 'dubious ownership' on cloned repos)
        if os.path.isdir(os.path.join(app_path, ".git")):
            try:
                subprocess.run(
                    ["git", "config", "--global", "--add", "safe.directory",
                     app_path.replace("\\", "/")],
                    timeout=10, capture_output=True
                )
            except Exception:
                pass  # Non-critical
        # Determine python executable location
        if os.name == 'nt':
            python_exe = os.path.join(package_path, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(package_path, "env", "bin", "python")

        # PRE-FLIGHT 4: Executable environment verification
        if not os.path.exists(python_exe):
            self.send_json_response({
                "status": "error",
                "message": "Isolated python environment not found. Please repair the installation."
            }, 404)
            return

        logging.info(f"Launching {package_id}...")

        # Pipe output to a runtime log file (append mode preserves history)
        log_path = os.path.join(package_path, "runtime.log")
        try:
            log_file = open(log_path, 'a', encoding='utf-8')
            log_file.write(f"\n{'='*60}\n")
            log_file.write(f"  Session started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"{'='*60}\n\n")
            log_file.flush()
        except OSError as e:
            logging.error(f"Failed to open log file for {package_id}: {e}")
            self.send_json_response({"status": "error", "message": f"Cannot open log file: {e}"}, 500)
            return

        full_command = [python_exe] + launch_cmd.split(" ")

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

        p = subprocess.Popen(full_command, cwd=app_path, stdout=log_file, stderr=subprocess.STDOUT, **kwargs)

        _fallback_ports = {"comfyui": 8188, "forge": 7860, "auto1111": 7861, "fooocus": 8888}
        port = manifest.get("port", _fallback_ports.get(package_id, 7860))

        AIWebServer.running_processes.register(package_id, p, log_file=log_file, port=port)
        url = f"http://127.0.0.1:{port}"
        self.send_json_response({"status": "success", "message": "Package starting...", "url": url, "port": port})

    def handle_repair_dependency(self, data):
        """Auto-repair dependencies: bootstrap pip, upgrade setuptools, install requirements."""
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        package_path = os.path.join(self.root_dir, "packages", package_id)
        app_path = os.path.join(package_path, "app")
        if os.name == 'nt':
            python_exe = os.path.join(package_path, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(package_path, "env", "bin", "python")

        if not os.path.exists(python_exe):
            self.send_json_response({"status": "error", "message": "Python env not found"}, 404)
            return

        logging.info(f"Auto-repairing dependencies for {package_id}...")
        repair_steps = []

        try:
            kwargs = {}
            if os.name == 'nt':
                kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

            # Step 1: Add git safe.directory to prevent dubious ownership errors
            if os.path.isdir(os.path.join(app_path, ".git")):
                try:
                    subprocess.run(
                        ["git", "config", "--global", "--add", "safe.directory",
                         app_path.replace("\\", "/")],
                        timeout=10, capture_output=True
                    )
                    repair_steps.append("git safe.directory configured")
                except Exception:
                    pass  # Non-critical

            # Step 2: Bootstrap pip if missing
            pip_check = subprocess.run(
                [python_exe, "-m", "pip", "--version"],
                capture_output=True, timeout=15
            )
            if pip_check.returncode != 0:
                logging.info(f"  pip not found, bootstrapping via ensurepip...")
                ensurepip_result = subprocess.run(
                    [python_exe, "-m", "ensurepip", "--upgrade"],
                    capture_output=True, timeout=120, **kwargs
                )
                if ensurepip_result.returncode == 0:
                    repair_steps.append("pip bootstrapped via ensurepip")
                else:
                    self.send_json_response({
                        "status": "error",
                        "message": "Failed to bootstrap pip: " + ensurepip_result.stderr.decode(errors='replace')[-200:]
                    }, 500)
                    return

            # Step 3: Upgrade pip + setuptools (fixes 'no module pkg_resources')
            subprocess.run(
                [python_exe, "-m", "pip", "install", "--upgrade", "pip", "setuptools"],
                capture_output=True, timeout=120, **kwargs
            )
            repair_steps.append("pip + setuptools upgraded")

            # Step 4: Install requirements
            req_candidates = ["requirements.txt", "requirements_versions.txt"]
            req_path = None
            for candidate in req_candidates:
                full_path = os.path.join(app_path, candidate)
                if os.path.exists(full_path):
                    req_path = full_path
                    break

            if req_path:
                subprocess.Popen(
                    [python_exe, "-m", "pip", "install", "-r", os.path.basename(req_path)],
                    cwd=app_path, **kwargs
                )
                repair_steps.append(f"installing {os.path.basename(req_path)} (background)")
            else:
                repair_steps.append("no requirements file found, skipped")

            self.send_json_response({
                "status": "success",
                "message": "Repair started: " + " → ".join(repair_steps)
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": f"Repair failed: {str(e)}"}, 500)

    def handle_repair_install(self, data):
        """Repair a corrupted package by re-running the install pipeline."""
        from server import AIWebServer
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        recipe_path = os.path.join(self.root_dir, ".backend", "recipes", f"{package_id}.json")
        if not os.path.exists(recipe_path):
            self.send_json_response({"status": "error", "message": f"No recipe found for {package_id}"}, 404)
            return

        # Auto-stop running process first
        AIWebServer._kill_tracked_process(package_id)

        # Clear stale install job status
        jobs_file = os.path.join(self.root_dir, ".backend", "cache", "install_jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, 'r', encoding='utf-8') as f:
                    jobs = json.load(f)
                if package_id in jobs:
                    del jobs[package_id]
                with open(jobs_file, 'w', encoding='utf-8') as f:
                    json.dump(jobs, f, indent=2)
        except Exception as e:
            logging.warning(f"Could not clear stale install job for {package_id}: {e}")

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        logging.info(f"Repair: Re-installing {package_id} from recipe...")

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)

        if AIWebServer.running_installs.is_running(package_id):
            self.send_json_response({"status": "error", "message": f"{package_id} repair is already in progress."}, 409)
            return

        proc = subprocess.Popen([sys.executable, installer_script, recipe_path], **kwargs)
        AIWebServer.running_installs.register(package_id, proc)
        self.send_json_response({"status": "success", "message": f"Repair started for {package_id}. The app will be re-downloaded."})

    def handle_stop(self, data=None):
        from server import AIWebServer
        package_id = data.get("package_id") if data else None
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        if not AIWebServer.running_processes.is_running(package_id):
            self.send_json_response({"status": "error", "message": "Package not running or not tracked"}, 404)
            return

        logging.info(f"Terminating package {package_id}...")
        AIWebServer._kill_tracked_process(package_id)
        self.send_json_response({"status": "success", "message": "Package stopped successfully"})

    def handle_restart(self, data):
        """Atomic restart: stop → wait for port release → re-launch."""
        from server import AIWebServer
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return
        AIWebServer._kill_tracked_process(package_id)
        time.sleep(1.0)
        self.handle_launch(data)

    def handle_uninstall(self, data):
        from server import AIWebServer
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return
        AIWebServer._kill_tracked_process(package_id)
        logging.info(f"Triggering uninstallation for {package_id}")
        try:
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
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(self.path).query)
            package_id = qs.get("package_id", [""])[0]
            if not package_id:
                self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
                return
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
        job_id = str(uuid.uuid4())[:8]
        try:
            from installer_engine import ExtensionCloneTracker
            tracker = ExtensionCloneTracker(self.root_dir)
            logging.info(f"Starting tracked clone of {repo_url} (job: {job_id})")
            t = threading.Thread(target=tracker.clone_with_progress, args=(repo_url, target_dir, job_id), daemon=False)
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
        try:
            shutil.rmtree(target_path)
            self.send_json_response({"status": "success", "message": "Extension removed."})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Prompt Library ───────────────────────────────────────────────

    def handle_list_prompts(self):
        try:
            from server import _get_db
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            search = qs.get("search", [None])[0]
            limit = int(qs.get("limit", [100])[0])
            db = _get_db()
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
            from server import _get_db
            db = _get_db()
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
            from server import _get_db
            db = _get_db()
            db.delete_prompt(prompt_id)
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    # ── Ollama Integration ───────────────────────────────────────────

    def handle_ollama_status(self):
        """GET /api/ollama/status — Check if local Ollama is running"""
        import urllib.request as urllib_req
        try:
            req = urllib_req.Request("http://127.0.0.1:11434/api/tags")
            with urllib_req.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self.send_json_response({"online": True, "models": models})
        except Exception:
            self.send_json_response({"online": False, "models": []})

    def handle_ollama_enhance(self, data):
        """POST /api/ollama/enhance — Enhance a prompt using Ollama"""
        import urllib.request as urllib_req
        prompt = data.get("prompt", "")
        model = data.get("model", "llama3.2")

        if not prompt.strip():
            self.send_json_response({"error": "Empty prompt"}, 400)
            return

        system_msg = (
            "You are an expert Stable Diffusion prompt engineer. "
            "Given a user's rough prompt idea, rewrite it as a detailed, high-quality image generation prompt. "
            "Include specific artistic styles, lighting, composition, and quality tags. "
            "Output ONLY the enhanced prompt text, no explanations or markdown. "
            "Keep the prompt under 200 words."
        )

        ollama_payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Enhance this prompt for image generation: {prompt}"}
            ],
            "stream": False
        }).encode()

        try:
            req = urllib_req.Request(
                "http://127.0.0.1:11434/api/chat",
                data=ollama_payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib_req.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                enhanced = result.get("message", {}).get("content", "")
                self.send_json_response({"enhanced_prompt": enhanced.strip()})
        except Exception as e:
            self.send_json_response({"error": f"Ollama request failed: {str(e)}"}, 500)
