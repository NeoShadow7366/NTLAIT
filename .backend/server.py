import os
import sys
import json
import logging
import subprocess
import signal
import time
import uuid
import threading
import datetime
import shutil
import urllib.request
import urllib.parse
import urllib.error
import math
import base64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ── Centralized sys.path setup (done once, not per-request) ──────
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Import backend modules once at module level
from metadata_db import MetadataDB
from symlink_manager import create_safe_directory_link
from proxy_translators import build_comfy_workflow, build_a1111_payload, build_fooocus_payload
from process_registry import ProcessRegistry
from server_state import CachedValue, LRUCache, BatchQueue, RequestMetrics
from functools import wraps

# ── Unified Error Handling Decorator ─────────────────────────────
def api_handler(method):
    """Decorator that catches exceptions and sends consistent JSON error responses.
    Ensures every API handler returns {"status": "error", "message": ...} on failure."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except ValueError as e:
            self.send_json_response({"status": "error", "message": str(e)}, 400)
        except FileNotFoundError as e:
            self.send_json_response({"status": "error", "message": str(e)}, 404)
        except Exception as e:
            logging.error(f"Handler {method.__name__} failed: {e}", exc_info=True)
            self.send_json_response({"status": "error", "message": str(e)}, 500)
    return wrapper

# ── Server State Globals ─────────────────────────────────────────
global_http_server = None
embedding_process = None

# ── Thread Safety: Settings file lock ────────────────────────────
_settings_lock = threading.Lock()

# ── Cached MetadataDB singleton (avoid re-running DDL per request)
_db_instance = None
_db_lock = threading.Lock()

def _get_db() -> MetadataDB:
    """Returns a cached MetadataDB instance. Schema init runs once.
    Re-creates if AIWebServer.root_dir has been changed (e.g., by tests)."""
    global _db_instance
    # Use AIWebServer.root_dir so tests can override the data root
    server_cls = globals().get('AIWebServer')
    current_root = getattr(server_cls, 'root_dir', _ROOT_DIR) if server_cls else _ROOT_DIR
    db_path = os.path.join(current_root, ".backend", "metadata.sqlite")
    if _db_instance is None or _db_instance.db_path != db_path:
        with _db_lock:
            if _db_instance is None or _db_instance.db_path != db_path:
                _db_instance = MetadataDB(db_path)
    return _db_instance

# ── Cached Settings (avoid re-reading 627KB JSON per request) ────
_settings_cache = {"data": None, "mtime": 0}

def _get_settings() -> dict:
    """Returns cached settings.json, re-reads only if file changed."""
    settings_path = os.path.join(_ROOT_DIR, ".backend", "settings.json")
    try:
        current_mtime = os.path.getmtime(settings_path) if os.path.exists(settings_path) else 0
    except OSError:
        current_mtime = 0
    if _settings_cache["data"] is not None and current_mtime == _settings_cache["mtime"]:
        return dict(_settings_cache["data"])  # Return copy to prevent mutation
    with _settings_lock:
        try:
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"theme": "dark", "civitai_api_key": "", "auto_updates": True}
            _settings_cache["data"] = data
            _settings_cache["mtime"] = current_mtime
            return dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logging.warning(f"Failed to read settings.json: {e}")
            if _settings_cache["data"] is not None:
                return dict(_settings_cache["data"])
            return {"theme": "dark", "civitai_api_key": "", "auto_updates": True}

def _save_settings(data: dict) -> None:
    """Thread-safe settings save with merge semantics and atomic write.
    Uses os.replace() for atomic rename which prevents corruption if
    the process crashes mid-write."""
    settings_path = os.path.join(_ROOT_DIR, ".backend", "settings.json")
    tmp_path = settings_path + '.tmp'
    with _settings_lock:
        existing = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = {}
        existing.update(data)
        # Atomic write: write to temp file, then rename (atomic on NTFS and POSIX)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=4)
        os.replace(tmp_path, settings_path)
        # Update cache
        _settings_cache["data"] = existing
        try:
            _settings_cache["mtime"] = os.path.getmtime(settings_path)
        except OSError:
            _settings_cache["mtime"] = 0

# ── CivitAI MeiliSearch Public API Key ───────────────────────────
# This is CivitAI's public search key embedded in their web frontend.
# Override via settings.json "civitai_search_key" if rotated.
_CIVITAI_SEARCH_KEY = "8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"

def graceful_teardown():
    """Fixed: synchronous, kills sandboxes properly, no NameError"""
    print("\n[TEARDOWN] graceful_teardown() WAS CALLED")
    sys.stdout.flush()
    print("[TEARDOWN] Starting shutdown sequence...")
    sys.stdout.flush()

    # 1. Shutdown HTTP server (unblocks serve_forever on main thread)
    global global_http_server
    if global_http_server:
        print("[TEARDOWN] Shutting down HTTP server...")
        sys.stdout.flush()
        try:
            global_http_server.shutdown()
        except Exception as e:
            print(f"[TEARDOWN] HTTP shutdown warning: {e}")
            sys.stdout.flush()

    # 2. Kill ALL sandbox processes via thread-safe registry
    print("[TEARDOWN] Terminating sandbox engines...")
    sys.stdout.flush()
    try:
        killed = AIWebServer.running_processes.kill_all()
        print(f"[TEARDOWN] Killed {killed} sandbox process(es).")
        sys.stdout.flush()
    except Exception as e:
        print(f"[TEARDOWN] Sandbox cleanup warning: {e}")
        sys.stdout.flush()

    # 3. Kill tracked embedding engine
    global embedding_process
    if embedding_process and embedding_process.poll() is None:
        print(f"[TEARDOWN] Killing embedding engine (PID {embedding_process.pid})")
        sys.stdout.flush()
        try:
            if os.name == 'nt':
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(embedding_process.pid)],
                                creationflags=0x08000000)
            else:
                embedding_process.kill()
        except Exception as e:
            print(f"[TEARDOWN] Embedding kill warning: {e}")

    # 4. Safety wmic sweep for any orphaned embedding processes
    print("[TEARDOWN] Running safety sweep for orphaned embedding processes...")
    sys.stdout.flush()
    try:
        if os.name == 'nt':
            output = subprocess.check_output(
                r'wmic process where "name=\'python.exe\' and commandline like \'%embedding_engine.py%\'" get processid',
                shell=True,
                creationflags=0x08000000
            ).decode('utf-8', errors='ignore')
            for line in output.splitlines():
                pid = line.strip()
                if pid.isdigit() and pid != "ProcessId":
                    print(f"[TEARDOWN] Killing orphaned embedding PID {pid}")
                    sys.stdout.flush()
                    subprocess.call(['taskkill', '/F', '/T', '/PID', pid],
                                    creationflags=0x08000000)
        else:
            subprocess.call(['pkill', '-f', 'embedding_engine.py'])
    except Exception as e:
        print(f"[TEARDOWN] Fallback sweep warning: {e}")

    print("[TEARDOWN] Shutdown complete. Exiting.")
    sys.stdout.flush()
    time.sleep(0.5)
    os._exit(0)

# ── Sprint 9: Vault Size Cache (updated by background scanner) ───
_vault_size_cache = CachedValue(ttl=300)  # 5 min TTL

# ── Sprint 9: In-Memory Batch Generation Queue ──────────────────
# R-6: Encapsulated via BatchQueue class (thread-safe, bounded history/queue)
_batch_queue = BatchQueue(max_history=50, max_queue=200)

# R-9: Per-request metrics (success/fail counts, latency)
_request_metrics = RequestMetrics()

# ── Phase 5: Civitai Search Cache (LRU, max 50, 15min TTL) ────
_civitai_search_cache = LRUCache(max_size=50, ttl=900)

# ── Dashboard Stats Cache (30s TTL) ──────────────────────────────
_server_stats_cache = CachedValue(ttl=30)
_SERVER_STATS_TTL = 30

# ── Engine Proxy Configuration ───────────────────────────────────
_ENGINE_CONFIG = {
    "comfyui": {"port": 8188, "translator": build_comfy_workflow, "gen_endpoint": "/prompt"},
    "a1111":   {"port": 7861, "translator": build_a1111_payload, "gen_endpoint": "/sdapi/v1/txt2img"},
    "forge":   {"port": 7860, "translator": build_a1111_payload, "gen_endpoint": "/sdapi/v1/txt2img"},
    "fooocus": {"port": 8888, "translator": build_fooocus_payload, "gen_endpoint": "/v1/generation/text-to-image"},
}

from handlers.gallery_handlers import GalleryHandlersMixin
from handlers.vault_handlers import VaultHandlersMixin
from handlers.download_handlers import DownloadHandlersMixin
from handlers.system_handlers import SystemHandlersMixin
from handlers.proxy_handlers import ProxyHandlersMixin
from handlers.package_handlers import PackageHandlersMixin

class AIWebServer(
    GalleryHandlersMixin,
    VaultHandlersMixin,
    DownloadHandlersMixin,
    SystemHandlersMixin,
    ProxyHandlersMixin,
    PackageHandlersMixin,
    BaseHTTPRequestHandler
):
    root_dir = _ROOT_DIR
    db_path = os.path.join(_ROOT_DIR, ".backend", "metadata.sqlite")
    static_dir = os.path.join(_ROOT_DIR, ".backend", "static")
    running_processes = ProcessRegistry()   # Thread-safe PID tracking for launched packages
    running_installs = ProcessRegistry()    # Thread-safe PID tracking for active installer processes

    # ── Shared Process Kill Helper (delegates to ProcessRegistry) ──
    @classmethod
    def _kill_tracked_process(cls, package_id: str, remove_from_dict: bool = True) -> bool:
        """Kill a tracked sandbox process. Delegates to thread-safe ProcessRegistry."""
        return cls.running_processes.kill(package_id, remove=remove_from_dict)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


    # ── Route Registry (O(1) dict lookup replaces O(n) if/elif chains) ──
    _GET_ROUTES = {
        "/api/models":              "send_api_models",
        "/api/packages":            "send_api_packages",
        "/api/recipes":             "send_api_recipes",
        "/api/install/status":      "handle_install_status",
        "/api/downloads":           "handle_get_downloads",
        "/api/comfy_image":         "handle_comfy_image",
        "/api/import/status":       "handle_import_status",
        "/api/import/jobs":         "handle_import_jobs",
        "/api/gallery":             "handle_gallery_list",
        "/api/vault/search":        "handle_vault_search",
        "/api/vault/tags":          "handle_get_all_tags",
        "/api/hf/search":           "handle_hf_search",
        "/api/extensions":          "handle_get_extensions",
        "/api/extensions/status":   "handle_extension_status",
        "/api/settings":            "handle_get_settings",
        "/api/server_status":       "handle_server_status",
        "/api/logs":                "handle_get_logs",
        "/api/prompts":             "handle_list_prompts",
        "/api/generate/queue":      "handle_batch_queue_status",
        "/api/gallery/tags":        "handle_gallery_tags",
        "/api/civitai_search":      "handle_civitai_search",
        "/api/ollama/status":       "handle_ollama_status",
        "/api/favorites":           "handle_get_favorites",
        "/api/events":              "handle_event_stream",
        "/api/metrics":             "handle_get_metrics",
        "/api/model_paths":         "handle_get_model_paths",
        "/api/vault/scan_progress":  "handle_scan_progress",
        "/api/vault/external_sources": "handle_external_sources",
    }

    _POST_ROUTES = {
        "/api/install":             "handle_install",
        "/api/launch":              "handle_launch",
        "/api/repair_dependency":   "handle_repair_dependency",
        "/api/repair":              "handle_repair_install",
        "/api/stop":                "handle_stop",
        "/api/restart":             "handle_restart",
        "/api/comfy_upload":        ("handle_comfy_upload", False),  # (method, needs_data)
        "/api/uninstall":           "handle_uninstall",
        "/api/download":            "handle_download",
        "/api/download/retry":      "handle_retry_download",
        "/api/downloads/clear":     ("handle_clear_downloads", False),
        "/api/delete_model":        "handle_delete_model",
        "/api/open_folder":         "handle_open_folder",
        "/api/import":              "handle_import_file",
        "/api/gallery/save":        "handle_gallery_save",
        "/api/gallery/delete":      "handle_gallery_delete",
        "/api/gallery/rate":        "handle_gallery_rate",
        "/api/vault/tag/add":       "handle_add_tag",
        "/api/vault/tag/remove":    "handle_remove_tag",
        "/api/recipes/build":       "handle_build_recipe",
        "/api/extensions/install":  "handle_install_extension",
        "/api/extensions/remove":   "handle_remove_extension",
        "/api/extensions/cancel":   "handle_cancel_extension",
        "/api/vault/export":        "handle_vault_export",
        "/api/vault/import":        "handle_vault_import",
        "/api/vault/updates":       "handle_vault_updates",
        "/api/vault/repair":        "handle_vault_repair",
        "/api/vault/health_check":  "handle_vault_health_check",
        "/api/vault/import_scan":   "handle_import_scan",
        "/api/vault/bulk_delete":   "handle_vault_bulk_delete",
        "/api/generate/batch":      "handle_batch_generate",
        "/api/prompts/save":        "handle_save_prompt",
        "/api/prompts/delete":      "handle_delete_prompt",
        "/api/settings":            "handle_save_settings",
        "/api/dashboard/clear_history": "handle_clear_dashboard_history",
        "/api/import/external":     "handle_import_external",
        "/api/system/update":       "handle_system_update",
        "/api/comfy_proxy":         "handle_comfy_proxy",
        "/api/a1111_proxy":         "handle_a1111_proxy",
        "/api/forge_proxy":         "handle_forge_proxy",
        "/api/fooocus_proxy":       "handle_fooocus_proxy",
        "/api/ollama/enhance":      "handle_ollama_enhance",
        "/api/favorites/add":       "handle_add_favorite",
        "/api/favorites/remove":    "handle_remove_favorite",
        "/api/model_paths":         "handle_save_model_paths",
        "/api/vault/scan_external":  "handle_scan_external",
        "/api/vault/hash_library":   "handle_hash_library",
        "/api/vault/hash_single":    "handle_hash_single",
        "/api/vault/cancel_scan":    "handle_cancel_scan",
        "/api/vault/migrate":        "handle_migrate_models",
        "/api/probe_url":            "handle_probe_url",
    }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        start_time = time.time()
        success = True
        
        handler_name = self._GET_ROUTES.get(path)
        if handler_name:
            try:
                getattr(self, handler_name)()
            except Exception:
                success = False
                raise
            finally:
                if path != "/api/events":  # Don't track SSE long-poll
                    elapsed_ms = (time.time() - start_time) * 1000
                    _request_metrics.record(path, success, elapsed_ms)
        else:
            self.serve_static_files(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # /api/shutdown is special: sends response before teardown
        if path == "/api/shutdown":
            print("[SERVER] === /api/shutdown ENDPOINT WAS HIT ===")
            sys.stdout.flush()

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "shutting down gracefully"}).encode('utf-8'))
            self.wfile.flush()
            sys.stdout.flush()

            print("[SERVER] Response sent. Running graceful_teardown() SYNCHRONOUSLY (no daemon thread)...")
            sys.stdout.flush()

            # Critical fix: run directly on this thread
            graceful_teardown()
            return
        
        route = self._POST_ROUTES.get(path)
        if not route:
            self.send_json_response({"error": f"Endpoint {path} not found"}, 404)
            return
        
        start_time = time.time()
        success = True
        
        try:
            # Routes can be either "method_name" (receives data) or ("method_name", False) (no data arg)
            if isinstance(route, tuple):
                handler_name, needs_data = route
                getattr(self, handler_name)()
            else:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length > 0 else b"{}"
                
                try:
                    data = json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logging.warning(f"Failed to parse POST body as JSON: {e}")
                    data = {}
                
                getattr(self, route)(data)
        except Exception:
            success = False
            raise
        finally:
            elapsed_ms = (time.time() - start_time) * 1000
            _request_metrics.record(path, success, elapsed_ms)

    def serve_static_files(self, path):
        # Decode and normalize path separators for Windows
        path = urllib.parse.unquote(path).replace('\\', '/')
        
        # Default to index.html
        if path == "/":
            path = "/index.html"
            
        # Security: Prevent directory traversal
        if ".." in path:
            self.send_error(403, "Forbidden")
            return
            
        # Serve root UI logo (redirect legacy path to icons/)
        if path == "/Logo.ico":
            filepath = os.path.join(self.root_dir, "icons", "Logo.ico")
        # Serve custom user icons
        elif path.startswith("/icons/"):
            clean_path = urllib.parse.unquote(path.lstrip("/"))
            filepath = os.path.join(self.root_dir, clean_path)
        # Check if they are requesting a thumbnail
        elif path.startswith("/.backend/cache/thumbnails/"):
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
        elif ext == "ico": content_type = "image/x-icon"
        
        try:
            file_size = os.path.getsize(filepath)
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            
            if file_size > 1_048_576:  # 1MB threshold: stream in chunks
                with open(filepath, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
            else:
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
        except Exception as e:
            self.send_error(500, f"Server Error: {str(e)}")

    def handle_civitai_search(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            query = qs.get("query", [""])[0]
            type_filter = qs.get("type", [""])[0]
            offset = int(qs.get("offset", ["0"])[0])
            exact_id = qs.get("exact_id", [""])[0]
            browse = qs.get("browse", [""])[0]

            # ── E-1 fix: Exact model ID lookup via REST API v1 ──
            if exact_id:
                cache_key = f"exact_{exact_id}"
                cached = _civitai_search_cache.get(cache_key)
                if cached is not None:
                    self.send_json_response(cached)
                    return
                api_url = f"https://civitai.com/api/v1/models/{exact_id}"
                settings = _get_settings()
                api_key = settings.get("api_key", "")
                headers = {"User-Agent": "AetherVault/1.0"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as res:
                    data = json.loads(res.read().decode('utf-8'))
                _civitai_search_cache.set(cache_key, data)
                self.send_json_response(data)
                return

            # ── E-1 fix: Browse mode via REST API v1 ──
            if browse:
                sort_param = qs.get("sort", [""])[0]
                nsfw_param = qs.get("nsfw", ["false"])[0]
                types_param = qs.get("types", [""])[0]
                base_param = qs.get("baseModels", [""])[0]
                early_param = qs.get("earlyAccess", [""])[0]

                cache_key = f"browse_{sort_param}_{nsfw_param}_{types_param}_{base_param}_{query}_{offset}"
                cached = _civitai_search_cache.get(cache_key)
                if cached is not None:
                    self.send_json_response(cached)
                    return

                api_url = "https://civitai.com/api/v1/models"
                params = {"limit": "40", "nsfw": nsfw_param}
                if sort_param:
                    params["sort"] = sort_param
                if types_param:
                    params["types"] = types_param
                if base_param:
                    params["baseModels"] = base_param
                if early_param:
                    params["earlyAccess"] = early_param
                if query:
                    params["query"] = query
                param_str = urllib.parse.urlencode(params)
                full_url = f"{api_url}?{param_str}"

                settings = _get_settings()
                api_key = settings.get("api_key", "")
                headers = {"User-Agent": "AetherVault/1.0"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                req = urllib.request.Request(full_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as res:
                    data = json.loads(res.read().decode('utf-8'))
                _civitai_search_cache.set(cache_key, data)
                self.send_json_response(data)
                return

            # ── Standard MeiliSearch text query path ──
            cache_key = f"{query}_{type_filter}_{offset}"
            cached_items = _civitai_search_cache.get(cache_key)
            if cached_items is not None:
                self.send_json_response({"items": cached_items})
                return
            
            payload = {
                "queries": [
                    {
                        "q": query,
                        "indexUid": "models_v9",
                        "limit": 40,
                        "offset": offset
                    }
                ]
            }
            
            filters = []
            if type_filter and type_filter != "Text Encoder":
                filters.append(f'(type="{type_filter}")')
            if filters:
                payload["queries"][0]["filter"] = " AND ".join(filters)
            
            url = "https://search-new.civitai.com/multi-search"
            # Load override key from settings if available
            search_key = _get_settings().get("civitai_search_key", _CIVITAI_SEARCH_KEY)

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {search_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://civitai.com/",
                "Origin": "https://civitai.com"
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as res:
                ms_data = json.loads(res.read().decode('utf-8'))
            
            hits = ms_data.get("results", [{}])[0].get("hits", [])
            
            items = []
            for h in hits:
                version = h.get("version", {})
                images = h.get("images", [])
                mapped_imgs = []
                for img in images:
                    img_id = img.get("url") or img.get("id")
                    if not img_id or str(img_id).lower() == "undefined":
                        continue
                        
                    if not str(img_id).startswith("http"):
                        img_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{img_id}/width=450/image.jpeg"
                    else:
                        img_url = img_id
                        
                    mapped_imgs.append({
                        "url": img_url,
                        "type": img.get("type", "image")
                    })
                
                version_id = version.get("id")
                download_url = f"https://civitai.com/api/download/models/{version_id}" if version_id else None
                
                # Extract real file info from hashes/version if available
                version_hashes = h.get("hashes", [])
                file_name = version.get("fileName") or f"{h.get('name', 'ModelFile')}.safetensors"

                v1_item = {
                    "id": h.get("id"),
                    "name": h.get("name"),
                    "type": h.get("type", "Model"),
                    "nsfw": h.get("nsfw", False),
                    "creator": {"username": h.get("user", {}).get("username", "Unknown")},
                    "stats": {"downloadCount": h.get("metrics", {}).get("downloadCount", 0)},
                    "modelVersions": [{
                        "name": version.get("name", "Base"),
                        "baseModel": version.get("baseModel", "Unknown"),
                        "availability": version.get("availability") or h.get("availability", "Public"),
                        "earlyAccessEndsAt": version.get("earlyAccessEndsAt") or h.get("earlyAccessDeadline"),
                        "earlyAccessTimeFrame": version.get("earlyAccessTimeFrame", 0),
                        "images": mapped_imgs,
                        "files": [{
                            "sizeKB": version.get("fileSizeKB", 0),
                            "name": file_name,
                            "type": "Model",
                            "primary": True,
                            "downloadUrl": download_url
                        }],
                        "trainedWords": h.get("triggerWords", [])
                    }],
                    "tags": h.get("tags", [])
                }
                items.append(v1_item)
                
            _civitai_search_cache.set(cache_key, items)
            self.send_json_response({"items": items})
        except Exception as e:
            logging.error(f"Target CivitAI proxy search failed: {e}")
            self.send_json_response({"error": str(e), "items": []}, 500)


    # ── Extracted handler methods are provided by mixin classes ──────
    # Gallery:    GalleryHandlersMixin   (handlers/gallery_handlers.py)
    # Vault:      VaultHandlersMixin     (handlers/vault_handlers.py)
    # Downloads:  DownloadHandlersMixin  (handlers/download_handlers.py)
    # System:     SystemHandlersMixin    (handlers/system_handlers.py)
    # Proxy:      ProxyHandlersMixin     (handlers/proxy_handlers.py)
    # Packages:   PackageHandlersMixin   (handlers/package_handlers.py)

    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))




    # ── R-9: Metrics Endpoint ─────────────────────────────────

    def handle_get_metrics(self):
        """GET /api/metrics — returns per-endpoint request metrics."""
        self.send_json_response({
            "status": "success",
            "metrics": _request_metrics.get_snapshot()
        })

    @api_handler
    def handle_probe_url(self, data):
        """POST /api/probe_url — probe whether a URL is reachable (P-2 fix)."""
        url = data.get("url", "")
        if not url:
            self.send_json_response({"reachable": False, "error": "No URL provided"})
            return
        # Security: only allow localhost/LAN probes
        from urllib.parse import urlparse as _up
        parsed = _up(url)
        hostname = parsed.hostname or ""
        if hostname not in ("localhost", "127.0.0.1", "0.0.0.0") and not hostname.startswith("192.168.") and not hostname.startswith("10."):
            self.send_json_response({"reachable": False, "error": "Only local URLs allowed"})
            return
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=2)
            self.send_json_response({"reachable": True})
        except Exception:
            self.send_json_response({"reachable": False})

    # ── Sprint 9: Batch Generation Queue ────────────────────────────

    @api_handler
    def handle_batch_generate(self, data):
        """POST /api/generate/batch — add one or more payloads to the batch queue."""
        payloads = data.get("payloads", [])
        if not payloads:
            # Single payload shorthand
            payload = data.get("payload")
            if payload:
                payloads = [payload]

        if not payloads:
            self.send_json_response({"status": "error", "message": "No payloads provided"}, 400)
            return

        # R-3: Reject when queue is saturated to prevent memory exhaustion
        if _batch_queue.is_full(len(payloads)):
            self.send_json_response({
                "status": "error",
                "message": f"Queue full ({_batch_queue.count_active()} active jobs). Limit reached."
            }, 429)
            return

        job_ids = []
        start_worker = False
        with _batch_queue.lock:
            for p in payloads:
                job_id = str(uuid.uuid4())[:8]
                _batch_queue.add({
                    "id": job_id,
                    "status": "pending",
                    "payload": p,
                    "result": None,
                    "error": None,
                    "created_at": time.time()
                })
                job_ids.append(job_id)
            # Atomic check-then-set under lock to prevent double workers
            if not _batch_queue.worker_running:
                _batch_queue.worker_running = True
                start_worker = True

        if start_worker:
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
        self.send_json_response({"status": "success", "queue": _batch_queue.get_snapshot()})

    @staticmethod
    def _batch_worker():
        """Background worker that processes batch generation queue sequentially."""
        logging.info("Batch generation worker started.")
        try:
            from event_bus import event_bus as _bus
        except ImportError:
            _bus = None

        while True:
            job = _batch_queue.claim_next()

            if not job:
                _batch_queue.worker_running = False
                _batch_queue.trim_history()
                logging.info("Batch generation worker finished — queue empty.")
                break

            try:
                backend = job["payload"].get("backend", "comfyui")
                engine = _ENGINE_CONFIG.get(backend, _ENGINE_CONFIG["comfyui"])
                port = engine["port"]
                translator = engine["translator"]
                base_url = f"http://127.0.0.1:{port}"

                translated = translator(job["payload"])
                # Determine correct endpoint (img2img vs txt2img for A1111/Forge)
                if backend in ("a1111", "forge") and "init_images" in translated:
                    endpoint = "/sdapi/v1/img2img"
                else:
                    endpoint = engine["gen_endpoint"]

                url = f"{base_url}{endpoint}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(translated).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=300) as res:
                    content = json.loads(res.read().decode('utf-8'))

                # Strip base64 images from completed jobs to save memory
                result = content
                if isinstance(content, dict) and "images" in content:
                    result = {k: v for k, v in content.items() if k != "images"}
                    result["_image_count"] = len(content["images"])
                _batch_queue.update_status(job["id"], "done", result=result)
                logging.info(f"Batch job {job['id']} completed.")
                if _bus:
                    _bus.emit("batch_update", {"id": job["id"], "status": "done"})

            except Exception as e:
                _batch_queue.update_status(job["id"], "failed", error=str(e))
                logging.error(f"Batch job {job['id']} failed: {e}")
                if _bus:
                    _bus.emit("batch_update", {"id": job["id"], "status": "failed", "error": str(e)})





def start_background_scanners():
    """Starts background scanners and embedding engine"""
    global embedding_process

    # ── One-time favorites migration: settings.json → SQLite ──
    try:
        settings = _get_settings()
        if settings.get("favorites") and not settings.get("favorites_migrated_to_db"):
            favs = settings["favorites"]
            if isinstance(favs, dict) and len(favs) > 0:
                db = _get_db()
                db.bulk_import_favorites(favs)
                # Remove from settings.json to shrink it
                settings.pop("favorites", None)
                settings["favorites_migrated_to_db"] = True
                _save_settings(settings)
                logging.info(f"[MIGRATION] Migrated {len(favs)} favorites from settings.json to SQLite")
    except Exception as e:
        logging.warning(f"[MIGRATION] Favorites migration failed (non-fatal): {e}")

    def _run_scanners():
        global embedding_process
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            # --- Embedding Engine ---
            embedding_script = os.path.join(root_dir, ".backend", "embedding_engine.py")
            python_exe = os.path.join(root_dir, "bin", "python", "python.exe")
            if not os.path.exists(python_exe):
                python_exe = sys.executable

            if os.path.exists(embedding_script):
                print("[SERVER] Booting Embedding Engine (Semantic Indexer)...")
                
                popen_kwargs = {}
                if os.name == 'nt':
                    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
                    popen_kwargs['creationflags'] = CREATE_NEW_PROCESS_GROUP
                    
                embedding_process = subprocess.Popen(
                    [python_exe, embedding_script],
                    env=os.environ.copy(),
                    **popen_kwargs
                )
                print(f"[SERVER] Embedding engine started with PID: {embedding_process.pid}")

            # Background Vault and CivitAI Indexing Loop
            # Create scanner instances once, sharing the cached DB singleton
            from vault_crawler import VaultCrawler
            from civitai_client import CivitaiClient
            
            shared_db = _get_db()
            crawler = VaultCrawler(root_dir, db=shared_db)
            civitai = CivitaiClient(root_dir, db=shared_db)
            
            # Store crawler as module attribute for handler access
            import server as _self_mod
            _self_mod._vault_crawler = crawler
            
            while True:
                try:
                    crawler.crawl()
                    civitai.process_unpopulated_models()
                except Exception as sc_e:
                    print(f"[SERVER] Background scanners iteration error: {sc_e}")
                
                time.sleep(300) # Re-scan every 5 minutes

        except Exception as e:
            print(f"[SERVER] Background scanners thread crashed: {e}")

    t = threading.Thread(target=_run_scanners, daemon=True)
    t.start()
    print("[SERVER] Background scanners thread started.")

    # ── SSE Event Emitter Thread ──────────────────────────────
    def _sse_emitter():
        """Background thread that pushes state changes to the SSE EventBus.

        R-11: Change-driven emission — uses file mtime tracking so it only
        reads/parses JSON files when they actually change on disk. Process
        count changes are tracked with a cached value. This replaces the
        previous blind 2s polling approach.
        """
        try:
            from event_bus import event_bus
        except ImportError:
            logging.warning("event_bus not available, SSE emitter disabled")
            return

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _last_dl_mtime = 0.0
        _last_inst_mtime = 0.0
        _last_running_count = -1

        while True:
            try:
                # ── Download Progress (only when file changes) ──
                dl_file = os.path.join(root_dir, ".backend", "cache", "downloads.json")
                if os.path.exists(dl_file):
                    try:
                        mtime = os.path.getmtime(dl_file)
                        if mtime != _last_dl_mtime:
                            _last_dl_mtime = mtime
                            with open(dl_file, 'r') as f:
                                dl_data = json.load(f)
                            active = {k: v for k, v in dl_data.items()
                                      if v.get("status") not in ("completed", "failed", "error")}
                            event_bus.emit("download_progress", {
                                "active_count": len(active),
                                "jobs": dl_data
                            })
                    except (json.JSONDecodeError, OSError):
                        pass

                # ── Install Progress (only when file changes) ──
                inst_file = os.path.join(root_dir, ".backend", "cache", "install_jobs.json")
                if os.path.exists(inst_file):
                    try:
                        mtime = os.path.getmtime(inst_file)
                        if mtime != _last_inst_mtime:
                            _last_inst_mtime = mtime
                            with open(inst_file, 'r') as f:
                                inst_data = json.load(f)
                            event_bus.emit("install_progress", inst_data)
                    except (json.JSONDecodeError, OSError):
                        pass

                # ── Server Status (only when process count changes) ──
                try:
                    running_count = AIWebServer.running_processes.count_running()
                    if running_count != _last_running_count:
                        _last_running_count = running_count
                        event_bus.emit("server_status", {
                            "running_packages": running_count,
                            "timestamp": time.time()
                        })
                except Exception:
                    pass

            except Exception as e:
                logging.debug(f"SSE emitter cycle error: {e}")

            time.sleep(3)  # R-11: 3s cycle (up from 2s — change-driven reduces need for frequency)

    sse_thread = threading.Thread(target=_sse_emitter, daemon=True, name="sse-emitter")
    sse_thread.start()
    logging.info("SSE event emitter thread started.")

def run_server(port=8080):
    global global_http_server
    
    # ── Cold Start Initialization Guard ──
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend_sys = os.path.join(root_dir, ".backend")
    if backend_sys not in sys.path:
        sys.path.insert(0, backend_sys)
    try:
        import bootstrap
        bootstrap.main()
    except Exception as e:
        logging.error(f"[SERVER] Pre-flight Bootstrap Failed: {e}")
        
    # Check settings for LAN sharing
    lan_sharing = _get_settings().get("lan_sharing", False)

    host = '0.0.0.0' if lan_sharing else ''
    server_address = (host, port)
    global_http_server = ThreadingHTTPServer(server_address, AIWebServer)
    global_http_server.daemon_threads = True

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

    # ── Auto-rebuild index.html from src/ modules if stale ──
    try:
        src_dir = os.path.join(root_dir, ".backend", "static", "src")
        build_script = os.path.join(src_dir, "build.py")
        output_html = os.path.join(root_dir, ".backend", "static", "index.html")
        if os.path.exists(build_script):
            import glob
            src_files = [os.path.join(src_dir, "base.html")] + glob.glob(os.path.join(src_dir, "js", "*.js"))
            output_mtime = os.path.getmtime(output_html) if os.path.exists(output_html) else 0
            newest_src = max((os.path.getmtime(f) for f in src_files if os.path.exists(f)), default=0)
            if newest_src > output_mtime:
                logging.info("Rebuilding index.html from src/ modules (source files changed)...")
                subprocess.run([sys.executable, build_script], cwd=src_dir, check=True)
    except Exception as e:
        logging.warning(f"Auto-rebuild skipped: {e}")
    start_background_scanners()
    try:
        global_http_server.serve_forever()
    except KeyboardInterrupt:
        logging.info("\n[SERVER] KeyboardInterrupt detected. Triggering Teardown...")
        graceful_teardown()
        
    if global_http_server:
        global_http_server.server_close()
    logging.info("Server stopped.")

if __name__ == "__main__":
    run_server()
