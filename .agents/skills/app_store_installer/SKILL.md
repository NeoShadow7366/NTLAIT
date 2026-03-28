---
name: App Store Installer
description: Config-driven application installer that reads JSON recipe files, clones repositories, creates isolated Python virtual environments, installs pip dependencies, creates Global Vault symlinks, and writes manifest.json for lifecycle tracking.
---

# App Store Installer

## Purpose

Install, configure, launch, and uninstall generative AI applications using declarative `.json` recipe files. Each application is fully sandboxed with its own virtual environment to prevent PyTorch version conflicts.

## When to Use

```
IF the task involves:
  ├── Installing a new generative app (ComfyUI, Forge, etc.) → USE THIS SKILL
  ├── Creating or editing a recipe .json file                → USE THIS SKILL
  ├── Modifying venv creation or pip install logic           → USE THIS SKILL
  ├── Fixing launch/stop lifecycle of installed packages     → USE THIS SKILL
  ├── Adding symlinks during app installation                → USE THIS SKILL (+ global_vault_symlinker)
  └── Anything else                                          → DO NOT USE THIS SKILL
```

## Recipe Format (Input)

Recipes live in `.backend/recipes/<app_id>.json`:

```json
{
  "app_id": "comfyui",
  "name": "ComfyUI",
  "repository": "https://github.com/comfyanonymous/ComfyUI.git",
  "install_commands": [
    "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121",
    "pip install -r requirements.txt"
  ],
  "model_symlinks": {
    "checkpoints": "models/checkpoints",
    "loras": "models/loras",
    "vaes": "models/vae"
  },
  "launch_command": "main.py"
}
```

## Installation Pipeline

```
1. CREATE   packages/<app_id>/               ← Sandbox root
2. CLONE    git clone <repo> → app/          ← Application source
3. VENV     python -m venv → env/            ← Isolated environment
4. PIP      env/python -m pip install ...     ← Dependencies
5. SYMLINK  Global_Vault/<cat> → app/models/ ← Zero-byte model links
6. MANIFEST Write manifest.json              ← Lifecycle metadata
```

## Output Contract

### On Success
```json
{"status": "success", "message": "Installation started in background"}
```

### Package Directory Layout
```
packages/comfyui/
├── app/              ← Git clone
├── env/              ← Isolated Python venv
├── manifest.json     ← Copy of recipe + runtime metadata
└── runtime.log       ← Live stdout/stderr from launch
```

## Key Implementation Files

| File | Role |
|------|------|
| `.backend/installer_engine.py` | Core `RecipeInstaller` class |
| `.backend/symlink_manager.py` | Cross-platform directory junction creation |
| `.backend/server.py` → `handle_install()` | API trigger for background install |
| `.backend/server.py` → `handle_launch()` | Start package with venv python |
| `.backend/server.py` → `handle_stop()` | Kill running process with PID tracking |
| `.backend/server.py` → `handle_uninstall()` | Safe tree removal |
| `.backend/recipes/*.json` | App Store templates |

## Launch Lifecycle

```
1. READ     manifest.json → extract launch_command
2. RESOLVE  env/Scripts/python.exe (Windows) or env/bin/python (UNIX)
3. POPEN    [python_exe] + launch_command.split(" ")
4. LOG      stdout/stderr → runtime.log
5. TRACK    Store PID in AIWebServer.running_processes[package_id]
6. STOP     taskkill /F /T /PID (Windows) or SIGTERM (UNIX)
```

## Safety Checklist

- [ ] Installs MUST BE ATOMIC. Wrap in try...except and use `shutil.rmtree(app_base)` on failure to prevent lingering broken state.
- [ ] Never run `pip install` with system Python — always use `env/python -m pip`
- [ ] `pip install` commands must be intercepted and rewritten to use venv python
- [ ] Always use `subprocess.run([...])` list form, never `shell=True`
- [ ] `shutil.rmtree` on uninstall is safe because models are junctions/symlinks (target is preserved)
- [ ] Create `CREATE_NEW_PROCESS_GROUP` flag on Windows for all spawned processes
- [ ] One installation at a time — never parallelize pip operations
