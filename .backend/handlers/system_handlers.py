"""System domain handlers — settings, server status, logs, updates, dashboard.

Mixin class providing system-level HTTP handler methods.
Composed into AIWebServer via multiple inheritance.
"""
import os
import sys
import json
import time
import subprocess
import logging
import datetime
import threading


class SystemHandlersMixin:
    """System domain handlers for the AIWebServer class.

    Handles:
        GET  /api/settings       → handle_get_settings
        POST /api/settings       → handle_save_settings
        POST /api/system/update  → handle_system_update
        GET  /api/logs           → handle_get_logs
        GET  /api/server_status  → handle_server_status
        POST /api/dashboard/clear_history → handle_clear_dashboard_history
    """

    def handle_get_settings(self):
        try:
            from server import _get_settings
            data = _get_settings()
            self.send_json_response(data)
        except Exception as e:
            logging.warning(f"Failed to read settings, returning defaults: {e}")
            self.send_json_response({"theme": "dark", "civitai_api_key": "", "auto_updates": True})

    def handle_save_settings(self, data):
        try:
            from server import _save_settings
            _save_settings(data)
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

            # Tail-seek optimization: read only the last 32KB instead of the entire file
            _TAIL_BYTES = 32 * 1024
            try:
                file_size = os.path.getsize(log_path)
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    if file_size > _TAIL_BYTES:
                        f.seek(file_size - _TAIL_BYTES)
                        f.readline()  # Skip partial first line after seek
                    tail = f.read()
            except OSError:
                tail = "--- Error reading log file ---"

            self.send_json_response({"status": "success", "logs": tail})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_server_status(self):
        from server import _get_db, _get_settings, _vault_size_cache, _server_stats_cache, AIWebServer
        try:
            db = _get_db()

            # Use cached settings instead of reading 627KB JSON every 3 seconds
            settings_data = _get_settings()
            lan_sharing = settings_data.get("lan_sharing", False)
            vault_size_warning_gb = settings_data.get('vault_size_warning_gb', 50)
            activity_cleared_at = settings_data.get('activity_cleared_at', 0)

            # Cache expensive DB queries with 30s TTL (polled every 3s = 10x reduction)
            now = time.time()
            cached = _server_stats_cache.get()
            if cached is None:
                unpopulated = len(db.get_unpopulated_models())
                stats = db.get_dashboard_stats()
                raw_generations = db.get_recent_activity(limit=5)
                category_distribution = db.get_vault_category_distribution()
                cached = {
                    "unpopulated": unpopulated,
                    "stats": stats,
                    "raw_generations": raw_generations,
                    "category_distribution": category_distribution
                }
                _server_stats_cache.set(cached)

            unpopulated = cached["unpopulated"]
            stats = cached["stats"]
            raw_generations = cached["raw_generations"]
            category_distribution = cached["category_distribution"]

            downloads_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
            active_downloads = 0
            recent_downloads = []
            if os.path.exists(downloads_file):
                try:
                    with open(downloads_file, 'r') as f:
                        jobs = json.load(f)
                        active_downloads = sum(1 for j in jobs.values() if j.get("status") not in ["completed", "failed", "error"])
                        completed = [{"id": k, **v} for k, v in jobs.items() if v.get("status") == "completed"]
                        completed.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
                        recent_downloads = completed[:5]
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

            # Vault size: read from cache (updated by background scanner or 60s inline fallback)
            vault_size_bytes = _vault_size_cache.get(default=0)
            if vault_size_bytes == 0:
                # First-time only fallback if background scanner hasn't run yet
                def _calc_vault_size():
                    vault_dir = os.path.join(self.root_dir, "Global_Vault")
                    total = 0
                    if os.path.exists(vault_dir):
                        for root, dirs, files in os.walk(vault_dir):
                            for f in files:
                                try:
                                    total += os.path.getsize(os.path.join(root, f))
                                except OSError:
                                    pass
                    _vault_size_cache.set(total)
                threading.Thread(target=_calc_vault_size, daemon=True).start()

            # Installed / running packages
            packages_dir = os.path.join(self.root_dir, "packages")
            installed_packages = 0
            if os.path.exists(packages_dir):
                installed_packages = sum(1 for d in os.listdir(packages_dir) if os.path.isdir(os.path.join(packages_dir, d)))
            running_packages = AIWebServer.running_processes.count_running()

            # Filter recent activity by cleared-at timestamp
            recent_generations = []
            for g in raw_generations:
                try:
                    dt = datetime.datetime.strptime(g.get("created_at", ""), "%Y-%m-%d %H:%M:%S.%f")
                    if dt.timestamp() > activity_cleared_at:
                        recent_generations.append(g)
                except Exception:
                    recent_generations.append(g)

            self.send_json_response({
                "unpopulated_models": unpopulated,
                "active_downloads": active_downloads,
                "is_syncing": (unpopulated > 0 or active_downloads > 0),
                "lan_sharing": lan_sharing,
                "lan_ip": lan_ip,
                "total_models": stats.get('total_models', 0),
                "total_generations": stats.get('total_generations', 0),
                "prompts_saved": stats.get('prompts_saved', 0),
                "vault_size_bytes": vault_size_bytes,
                "installed_packages": installed_packages,
                "running_packages": running_packages,
                "recent_generations": recent_generations,
                "recent_downloads": recent_downloads,
                "category_distribution": category_distribution,
                "vault_size_warning_gb": vault_size_warning_gb
            })
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_clear_dashboard_history(self, data):
        from server import _save_settings, _server_stats_cache
        try:
            # Clear downloads.json
            downloads_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
            if os.path.exists(downloads_file):
                with open(downloads_file, 'w') as f:
                    json.dump({}, f)
            # Add cleared_at timestamp via thread-safe settings helper
            _save_settings({"activity_cleared_at": time.time()})
            # Invalidate stats cache so next poll sees the change instantly
            _server_stats_cache.invalidate()
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_event_stream(self):
        """GET /api/events — Server-Sent Events stream.

        Keeps the connection open and pushes events as they arrive.
        Uses EventBus.wait_for_events() with Condition-based blocking
        instead of busy-polling. Auto-reconnection supported via Last-Event-ID.
        """
        from event_bus import event_bus, format_sse

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # Support reconnection via Last-Event-ID header
        last_id = 0
        last_event_id = self.headers.get("Last-Event-ID")
        if last_event_id:
            try:
                last_id = int(last_event_id)
            except (ValueError, TypeError):
                pass

        try:
            # Send initial heartbeat so client knows connection is alive
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                events = event_bus.wait_for_events(last_id=last_id, timeout=15.0)

                if events:
                    for event in events:
                        self.wfile.write(format_sse(event))
                        last_id = event["id"]
                    self.wfile.flush()
                else:
                    # Send heartbeat comment to keep connection alive
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # Client disconnected — this is normal for SSE
            logging.debug("SSE client disconnected")
        except Exception as e:
            logging.error(f"SSE stream error: {e}")

