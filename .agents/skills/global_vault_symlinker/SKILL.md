---
name: Global Vault Symlinker
description: Creates zero-byte cross-platform directory junctions (Windows NTFS) or symbolic links (UNIX) to share Global_Vault model files across multiple installed applications without duplicating bytes on disk.
---

# Global Vault Symlinker

## Purpose

Eliminate multi-gigabyte model file duplication by creating zero-byte directory links from each installed application's model directory back to the canonical `Global_Vault/` location. One copy of a 6GB checkpoint serves all engines simultaneously.

## When to Use

```
IF the task involves:
  ├── Creating directory links between Vault and app model dirs  → USE THIS SKILL
  ├── Fixing broken symlinks / junctions after moves             → USE THIS SKILL
  ├── Adding a new model category to the Vault structure         → USE THIS SKILL
  ├── Debugging "model not found" in an engine after install     → USE THIS SKILL
  ├── Health-checking symlink integrity across packages          → USE THIS SKILL
  └── Anything else                                              → DO NOT USE THIS SKILL
```

## Architecture

```
Global_Vault/                        packages/comfyui/app/models/
├── checkpoints/  ◄── junction ──── checkpoints/
├── loras/        ◄── junction ──── loras/
├── vaes/         ◄── junction ──── vae/
├── controlnet/   ◄── junction ──── controlnet/
├── unet/         ◄── junction ──── unet/
├── clip/         ◄── junction ──── clip/
└── embeddings/   ◄── junction ──── embeddings/
```

## Input Contract

```python
create_safe_directory_link(
    source_dir: str,   # Absolute path to Global_Vault/<category>
    target_link: str    # Absolute path where app expects models
) -> bool
```

## Output Contract

- Returns `True` on success
- Returns `False` with logged error on failure
- Idempotent: returns `True` if link already exists and points to correct source

## Platform Implementation

### Windows (NTFS Directory Junctions)
```cmd
mklink /J "target_link" "source_dir"
```
- **No admin required** — junctions work for standard users
- `shutil.rmtree()` on the junction removes only the link, not the target contents
- Cannot span across drive letters (must be same volume). 
  - **Fallback**: If symlinks fail due to volume isolation (e.g., target app is on a different drive than Global_Vault), rely on application-specific config file routing instead (e.g. creating `extra_model_paths.yaml` for ComfyUI pointing directly to Vault paths).

### UNIX (Symbolic Links)
```python
os.symlink(source_dir, target_link, target_is_directory=True)
```
- Works across mount points
- Standard user permissions sufficient

## Conflict Resolution

```
IF target_link already exists:
  ├── IS symlink pointing to source_dir → SKIP (already correct)
  ├── IS symlink pointing elsewhere     → UNLINK + recreate
  ├── IS real directory                 → RMTREE + create link
  └── IS real file                      → REFUSE (log error, return False)
```

## Key Implementation Files

| File | Role |
|------|------|
| `.backend/symlink_manager.py` | Core `create_safe_directory_link()` function |
| `.backend/installer_engine.py` | Calls symlinker during app installation (step 5) |
| `.backend/server.py` → `handle_vault_health_check()` | Walks packages/ to find and repair broken links |

## Health Check

The `/api/vault/health_check` endpoint walks all `packages/*/models/` directories and:
1. Finds broken symlinks where the target no longer exists
2. Calls `os.unlink()` to remove stale links
3. Returns count of repaired links

## Safety Checklist

- [ ] Always `os.path.abspath()` both source and target before creating links
- [ ] Never create links pointing outside the project root
- [ ] Never delete the source (Global_Vault) — only delete the link
- [ ] Validate source exists before attempting to create link
- [ ] On Windows, use `cmd.exe /c mklink /J` (list form), never `shell=True`
- [ ] Sequential link creation only — no parallel symlink operations
