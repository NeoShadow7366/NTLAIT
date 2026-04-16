"""
import_engine.py
Background file import engine for AI Manager.

Handles drag-and-drop model imports:
  1. Copies the file to the correct Global_Vault/<category>/ directory
  2. Hashes it and registers it in SQLite
  3. Queries CivitAI by-hash to fetch metadata + thumbnail
  4. Parses dependencies from the metadata and returns recommended installs
"""

import os
import sys
import json
import shutil
import hashlib
import logging
import threading
import time
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Map of inferred category names to vault subfolder names
CATEGORY_MAP = {
    "checkpoint": "checkpoints",
    "lora": "loras",
    "locon": "loras",
    "lycoris": "loras",
    "dora": "doras",
    "vae": "vaes",
    "controlnet": "controlnet",
    "textualinversion": "embeddings",
    "embedding": "embeddings",
    "hypernetwork": "hypernetworks",
    "aestheticgradient": "aesthetic_gradients",
    "upscaler": "upscalers",
    "unet": "unet",
    "clip": "clip",
    "text_encoder": "clip",
    "motion": "motion",
    "poses": "poses",
    "wildcards": "wildcards",
    "workflows": "workflows",
    "detection": "detection",
    "other": "misc",
    "misc": "misc",
}

# Global state dict: import_id -> {status, message, progress, deps, _completed_at}
_import_jobs: dict = {}
_lock = threading.Lock()
_IMPORT_JOB_TTL = 300  # Purge completed jobs older than 5 minutes

def _purge_stale_jobs():
    """Remove completed/error jobs older than _IMPORT_JOB_TTL seconds."""
    now = time.time()
    stale = [k for k, v in _import_jobs.items()
             if v.get("status") in ("done", "error")
             and now - v.get("_completed_at", now) > _IMPORT_JOB_TTL]
    for k in stale:
        del _import_jobs[k]


def _hash_file(path: str) -> Optional[str]:
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logging.error(f"Hash failed for {path}: {e}")
        return None


def _infer_category(filename: str, user_category: str) -> str:
    """Best-effort category inference from filename if user didn't specify."""
    if user_category and user_category in CATEGORY_MAP.values():
        return user_category
    lower = filename.lower()
    if any(k in lower for k in ("lora", "locon", "dora")):
        return "loras"
    if any(k in lower for k in ("vae",)):
        return "vaes"
    if any(k in lower for k in ("controlnet", "control_net")):
        return "controlnet"
    if any(k in lower for k in ("embed", "textual")):
        return "embeddings"
    if any(k in lower for k in ("upscal",)):
        return "upscalers"
    if any(k in lower for k in ("unet",)):
        return "unet"
    if any(k in lower for k in ("clip_l", "clip-l")):
        return "clip"
    if any(k in lower for k in ("t5", "t5xxl")):
        return "text_encoders"
    return "checkpoints"


def _extract_dependencies(metadata: dict) -> list:
    """
    Parse CivitAI model version metadata to find likely dependency recommendations.
    Returns list of {type, name, civitai_id, civitai_url} dicts.
    """
    deps = []
    if not metadata:
        return deps

    # Some models declare their recommended resources
    recommended = metadata.get("recommendedResources", [])
    for r in recommended:
        name = r.get("modelName") or r.get("name", "Unknown")
        rtype = r.get("modelType", "Unknown")
        model_id = r.get("modelId")
        deps.append({
            "type": rtype,
            "name": name,
            "civitai_id": model_id,
            "civitai_url": f"https://civitai.com/models/{model_id}" if model_id else None
        })

    # Check if the model references a specific base model that has a VAE
    base = metadata.get("baseModel", "")
    if "XL" in base:
        deps.append({
            "type": "VAE",
            "name": "sdxl-vae-fp16-fix (Recommended for SDXL)",
            "civitai_id": 101055,
            "civitai_url": "https://civitai.com/models/101055"
        })
    elif base in ("SD 1.5", "SD 1.4"):
        deps.append({
            "type": "VAE",
            "name": "vae-ft-mse-840000-ema-pruned (Recommended for SD 1.5)",
            "civitai_id": 1519,
            "civitai_url": "https://civitai.com/models/1519"
        })

    return deps


def _run_import(import_id: str, src_path: str, category: str, root_dir: str, api_key: str = ""):
    """Background worker thread that performs the full import pipeline."""
    from metadata_db import MetadataDB
    from civitai_client import CivitaiClient

    vault_dir = os.path.join(root_dir, "Global_Vault", category)
    os.makedirs(vault_dir, exist_ok=True)

    filename = os.path.basename(src_path)
    dest_path = os.path.join(vault_dir, filename)

    def _update(status, message, progress=None, deps=None, metadata=None, thumbnail=None):
        with _lock:
            _import_jobs[import_id]["status"] = status
            _import_jobs[import_id]["message"] = message
            if progress is not None:
                _import_jobs[import_id]["progress"] = progress
            if deps is not None:
                _import_jobs[import_id]["deps"] = deps
            if metadata is not None:
                _import_jobs[import_id]["metadata"] = metadata
            if thumbnail is not None:
                _import_jobs[import_id]["thumbnail"] = thumbnail

    try:
        # 1. Copy file
        _update("copying", f"Copying {filename} to vault...", progress=10)
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            # M-4 fix: Pre-copy disk space check
            try:
                file_size = os.path.getsize(src_path)
                free_space = shutil.disk_usage(vault_dir).free
                # Require 10% headroom above file size
                if free_space < file_size * 1.1:
                    free_gb = free_space / (1024 ** 3)
                    need_gb = file_size / (1024 ** 3)
                    _update("error", f"Insufficient disk space. Need {need_gb:.1f}GB, only {free_gb:.1f}GB free.")
                    return
            except OSError:
                pass  # Non-blocking — allow import to proceed if disk check fails
            
            shutil.copy2(src_path, dest_path)
            
            # M-3 fix: Post-copy size verification
            try:
                src_size = os.path.getsize(src_path)
                dst_size = os.path.getsize(dest_path)
                if src_size != dst_size:
                    _update("error", f"Copy verification failed: size mismatch ({src_size} vs {dst_size}). Partial file removed.")
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    return
            except OSError:
                pass  # Non-blocking
        
        # 2. Hash
        _update("hashing", "Computing SHA-256 hash...", progress=30)
        file_hash = _hash_file(dest_path)
        if not file_hash:
            _update("error", "Failed to hash file.")
            return

        # 3. Register in DB
        _update("registering", "Registering in vault database...", progress=50)
        # P2-5 fix: Use server's singleton DB when available to avoid lock contention
        try:
            server_mod = sys.modules.get('server', None)
            if server_mod and hasattr(server_mod, '_get_db'):
                db = server_mod._get_db()
            else:
                db = MetadataDB(os.path.join(root_dir, ".backend", "metadata.sqlite"))
        except Exception:
            db = MetadataDB(os.path.join(root_dir, ".backend", "metadata.sqlite"))
        db.insert_or_update_model(filename=filename, vault_category=category, file_hash=file_hash)

        # 4. Fetch CivitAI metadata by hash
        _update("fetching", "Looking up metadata on CivitAI...", progress=65)
        client = CivitaiClient(root_dir)
        if api_key:
            client.headers["Authorization"] = f"Bearer {api_key}"
        
        civitai_data = client.fetch_model_by_hash(file_hash)
        thumbnail_path = None

        if civitai_data and "error" not in civitai_data:
            # 5. Download thumbnail
            _update("thumbnail", "Downloading preview image...", progress=80)
            images = civitai_data.get("images", [])
            if images:
                image_url = CivitaiClient._select_thumbnail_url(civitai_data)
                if image_url:
                    thumbnail_path = client.download_thumbnail(image_url, file_hash)
                    if thumbnail_path:
                        try:
                            thumbnail_path = os.path.relpath(thumbnail_path, root_dir)
                        except ValueError:
                            pass

            db.update_model_metadata(
                file_hash=file_hash,
                metadata_json=json.dumps(civitai_data),
                thumbnail_path=thumbnail_path
            )

            # 6. Extract dependencies
            _update("resolving", "Resolving dependencies...", progress=90)
            deps = _extract_dependencies(civitai_data)

            model_name = civitai_data.get("model", {}).get("name", filename)
            _update("done", f"Import complete: {model_name}",
                    progress=100, deps=deps,
                    metadata=civitai_data,
                    thumbnail=thumbnail_path)
        else:
            # Not found on CivitAI — still complete but without metadata
            reason = "Model not found on CivitAI (local-only model)." if civitai_data else "CivitAI lookup failed."
            _update("done", f"Import complete (no metadata). {reason}",
                    progress=100, deps=[], metadata={}, thumbnail=None)

    except Exception as e:
        logging.exception(f"Import failed for {filename}: {e}")
        _update("error", f"Import failed: {str(e)}")
    finally:
        # Mark completion timestamp for auto-purge
        with _lock:
            if import_id in _import_jobs:
                _import_jobs[import_id]["_completed_at"] = time.time()


def start_import(src_path: str, category: str, root_dir: str, api_key: str = "") -> str:
    """Start a background import. Returns the import_id for polling."""
    import uuid
    import_id = str(uuid.uuid4())[:8]
    
    # Infer category if not explicitly set
    final_category = _infer_category(os.path.basename(src_path), category)
    
    with _lock:
        # Auto-purge old completed jobs before adding new ones
        _purge_stale_jobs()
        _import_jobs[import_id] = {
            "status": "queued",
            "message": "Queued...",
            "progress": 0,
            "deps": [],
            "metadata": {},
            "thumbnail": None,
            "filename": os.path.basename(src_path),
            "category": final_category
        }

    t = threading.Thread(target=_run_import, args=(import_id, src_path, final_category, root_dir, api_key), daemon=True)
    t.start()
    return import_id


def get_import_status(import_id: str) -> Optional[dict]:
    with _lock:
        return dict(_import_jobs.get(import_id, {}))


def list_import_jobs() -> dict:
    with _lock:
        return dict(_import_jobs)
