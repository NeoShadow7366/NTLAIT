# 🌌 Generative AI Manager — agents.md

> **The ultimate cross-platform orchestrator that eliminates GenAI ecosystem fragmentation.**

This file defines the canonical three-layer agent architecture for all AI-assisted development on this project. Any agent (human or automated) modifying this codebase **MUST** read and comply with this document before making changes.

---

## 🌌 Generative AI Manager: Complete Feature Matrix

The ultimate, cross-platform orchestrator designed to solve fragmentation in the GenAI Ecosystem. Instead of re-downloading Python environments or duplicating 6GB Stable Diffusion models, the Manager acts as a singular hub automating your Runtimes, APIs, Assets, and Workflows seamlessly.

### 1. Zero-Friction Inference (Multi-Engine Abstraction)

- **Universal Dashboard**: A single, beautifully styled UI parameter board that drives generations across distinct backend engines.
- **Intelligent Payload Translators**: Automatically maps Prompts, LoRAs, Seeds, Width/Height, ControlNets and Samplers into the native language of the target engine.
- **Supported Backends**: ComfyUI (dynamic JSON workflow topologies), SD WebUI Forge (`<lora:...>` `<controlnet...>` REST payloads), Automatic1111 (sdapi/v1/txt2img & img2img).
- **Advanced Img2Img Routing**: Drag-and-drop images onto the Generation Canvas with native denoising_strength support.

### 2. Advanced App Store & Secure Sandbox

- **Config-Driven Recipes**: Install via simple `.json` templates (repo, flags, target dirs).
- **Isolated Virtual Environments**: Detached `.venv` per app to prevent PyTorch conflicts.
- **Cross-Platform Portable Hooks**: Bash/Batch scripts using `uname -m` + `python-build-standalone` binaries (Windows, macOS Silicon/Intel, Linux).

### 3. The Global Vault Asset System

- **Drop ANY model once** into `Global_Vault` and use across all engines.
- **Dynamic Symlinking**: Auto-create Junctions (Windows) or Symbolic Links (UNIX) on app launch.
- **FLUX.1 Native Tracking**: Full support for clip/unet/checkpoints/loras/embeddings.

### 4. Agentic Metadata & Sync System

- **Ultra-Fast Crawlers**: Async Python threading for near-instant Safetensors hashing.
- **CivitAI Metadata Scraper**: Hash alignment with Civitai API + thumbnails.
- **Native HuggingFace Explorer**: Search + async headless downloads.
- **Real-time Status Syncing**: Live UI Toast system.

### 5. Studio Analytics & Historical Context

- **My Creations Gallery**: Persistent SQLite-backed lightbox with search/delete/scroll.
- **Drag-And-Drop Canvas Restore**: Thumbnails restore Seed, Steps, Models, Prompt, Configs.

### 6. Self-Healing Code Architecture

- **OTA Ghost Upgrades**: "Update System" button unhooks subprocess, runs `git pull` or zip extraction, patches dashboard without touching Global_Vault or configs.

---

## Layer 1 — Directive Layer

### Project Mission

Generative AI Manager is a singular hub that automates Runtimes, APIs, Assets, and Workflows for the fragmented GenAI ecosystem. Instead of re-downloading Python environments or duplicating 6GB Stable Diffusion models across applications, the Manager provides:

1. **Zero-Friction Inference** — A universal dashboard that drives generations across ComfyUI, SD WebUI Forge, Automatic1111, and Fooocus without altering your workflow.
2. **Advanced App Store** — Config-driven `.json` recipes that install, isolate, and manage generative applications with detached virtual environments.
3. **Global Vault** — Drop ANY model once, use it everywhere via zero-byte directory junctions (Windows) or symlinks (UNIX).
4. **Agentic Metadata** — Ultra-fast crawlers that hash multi-GB safetensors, scrape CivitAI/HuggingFace metadata, and maintain semantic search embeddings.
5. **Studio Analytics** — Persistent SQLite-backed gallery with drag-and-drop canvas restore.
6. **Self-Healing Architecture** — OTA ghost upgrades that patch the dashboard without touching user data.

### Non-Negotiable Requirements

| # | Requirement | Rationale |
|---|-------------|-----------|
| 1 | **Zero user data loss** | Global_Vault, packages/, cache/thumbnails, metadata.sqlite, and settings.json are sacred. No operation may delete, corrupt, or overwrite them without explicit user consent. |
| 2 | **Cross-platform parity** | Every feature MUST work on Windows 10/11, macOS (Intel + Apple Silicon), and Linux (x86_64 + arm64). Use `os.name`, `platform.system()`, and `uname -m` for branching. |
| 3 | **Isolated environments** | Each installed app gets its own `.venv`. PyTorch version conflicts between apps are structurally impossible. |
| 4 | **No admin/root required** | Windows uses NTFS Directory Junctions (`mklink /J`), not symlinks. UNIX uses standard `os.symlink()`. |
| 5 | **Portable Python** | The project ships with `python-build-standalone` binaries. System Python is a fallback, never a requirement. |
| 6 | **Offline-first** | The dashboard must boot and render instantly from local SQLite. Network calls (CivitAI, HuggingFace, OTA) are background-only and failure-tolerant. |
| 7 | **Single-file frontend** | The UI is a monolithic `index.html` served by our Python HTTP server. No Node.js build step, no npm, no bundler. |
| 8 | **Subprocess safety** | All spawned processes use `CREATE_NEW_PROCESS_GROUP` on Windows. PIDs are tracked. Orphan detection is mandatory. |

### Success Metrics

- **< 2s** cold-start to dashboard render (local SQLite bootstrap)
- **0 duplicate model bytes** across any number of installed engines
- **100%** of CivitAI-listed models resolve metadata within one background scan cycle
- **Zero** cross-app PyTorch conflicts (venv isolation guarantee)
- **< 500ms** inference proxy round-trip to any backend engine on localhost

---

## Layer 2 — Orchestration Layer

### Reasoning Style: Chain-of-Thought with Red-Team Review

Every code change follows this mandatory reasoning pipeline:

```
1. UNDERSTAND  → Read the relevant skill SKILL.md + existing code
2. PLAN        → Outline the change in natural language (what, why, where)
3. RED-TEAM    → Ask: "What breaks? What edge case did I miss? What user data could this corrupt?"
4. IMPLEMENT   → Write the code change
5. VERIFY      → Run or describe the verification step
6. DOCUMENT    → Update agents.md, skills, or comments if behavior changed
```

### Model Selection & Switching Rules

> **Mandatory**: The `intelligent_model_router` skill (`.agents/skills/intelligent_model_router/SKILL.md`) MUST be invoked at the following trigger points:

| Trigger | Action |
|---------|--------|
| **Start of every major development phase** | Invoke model router → recommend optimal model → switch before work begins |
| **Performance degradation detected** | Agent output is slow, imprecise, or failing → re-evaluate model selection |
| **Task-type change** | Switching between architecture planning, coding, debugging, documentation → re-evaluate model |
| **Complex reasoning required** | Payload translators, symlink logic, FLUX structures, cross-platform branching → escalate to high-capability model |

#### Decision Tree — Generative AI Manager Tasks

```
┌─────────────────────────────────────────────────────────────────┐
│                    TASK ARRIVES                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       ▼
            ┌─────────────────────┐
            │  Classify Complexity │
            └──────┬──────────────┘
                   │
       ┌───────────┼───────────────┐
       ▼           ▼               ▼
   [COMPLEX]    [STANDARD]      [FAST]
       │           │               │
       ▼           ▼               ▼
 ┌───────────┐ ┌──────────┐  ┌──────────┐
 │Claude Opus│ │ Sonnet / │  │  Flash / │
 │/Thinking  │ │Gemini 3  │  │Gemini 3  │
 │or Gemini 3│ │Pro       │  │Pro Low   │
 │Pro High   │ │          │  │          │
 └───────────┘ └──────────┘  └──────────┘
```

##### COMPLEX (Claude Opus/Thinking or Gemini 3 Pro High)
- Inference payload translator design (ComfyUI JSON graph topology, A1111 sdapi mapping)
- Cross-platform symlink/junction logic with edge-case handling
- FLUX.1 model structure resolution (clip/unet/text_encoder dependency graphs)
- Multi-engine architecture decisions and refactors
- Database schema migrations with backward compatibility
- OTA update pipeline safety analysis
- Debugging elusive race conditions in background scanners

##### STANDARD (Sonnet or Gemini 3 Pro)
- General backend feature implementation (new API endpoints, CRUD operations)
- Frontend UI components and interactivity (JavaScript/CSS in index.html)
- Recipe `.json` template creation for new engines
- Unit/integration test writing
- Documentation generation and README updates
- Routine bug fixes with clear stack traces

##### FAST (Flash or Gemini 3 Pro Low)
- Code formatting, linting, and comment cleanup
- Simple configuration changes (settings.json, gitignore entries)
- Renaming, reorganization, file moves
- Quick lookups and factual questions
- Generating boilerplate (docstrings, type stubs)
- Resolving trivial syntax errors

#### Switching Protocol

```
1. PAUSE    → Stop current heavy work (do not abandon context mid-task)
2. ANALYZE  → Read .agents/skills/intelligent_model_router/SKILL.md
3. CLASSIFY → Determine task complexity using the decision tree above
4. RECOMMEND→ State the recommended model and reasoning
5. REQUEST  → Explicitly ask the user to switch models in the Antigravity UI
6. WAIT     → Do NOT proceed until user confirms the switch
7. RESUME   → Continue work with the new model
```

### Self-Correction Loops

Before committing any file change, the agent must self-check:

- [ ] Does this change respect the Non-Negotiable Requirements table?
- [ ] Does this change work on Windows AND UNIX? (Check every `os.path`, `subprocess`, `symlink` call)
- [ ] Could this change corrupt `metadata.sqlite`? (Check for raw SQL without transactions)
- [ ] Does this change leak file handles or subprocess PIDs?
- [ ] Is there a race condition with the background scanners?
- [ ] Was the correct model tier used for this task complexity? (Model Selection check)

If any check fails, **STOP and refactor** before proceeding.

### Error Recovery Policy

#### Terminal Command Failures
```
IF command fails:
  1. Capture stderr + return code
  2. Log with full context (command, cwd, env vars)
  3. IF retryable (network timeout, file lock):
     → Wait 2s, retry up to 3 times with exponential backoff
  4. IF non-retryable (missing binary, permission denied):
     → Surface to user via /api/server_status or toast system
     → NEVER silently swallow the error
```

#### Subprocess Failures
```
IF subprocess.Popen fails or crashes silently:
  1. Check if binary exists at expected path
  2. PRE-FLIGHT CHECK: Automatically recover missing manifest.json and recreate missing Global_Vault symlinks before spawning.
  3. SMART DIAGNOSTICS: If proxy connection is refused (URLError), `poll()` the process. If dead, read runtime.log tail.
     → Search for `ModuleNotFoundError` or `ImportError`.
     → Return structured `{"error": "engine_crashed", "missing_module": "..."}` to frontend.
  4. UI AUTO-REPAIR: Frontend must halt polling and offer a one-click "Repair 🛠️" button that calls `/api/repair_dependency`.
  5. IF process is zombie:
     → Force-kill via PID tracking (taskkill /F /T on Windows, SIGKILL on UNIX)
     → Clean up running_processes dict
```

#### Database Failures
```
IF sqlite3 operation fails:
  1. IF "database is locked":
     → Retry with 500ms backoff, max 5 attempts
     → Consider WAL mode migration
  2. IF "disk I/O error":
     → Surface critical alert to user
     → NEVER attempt auto-repair on user's database
  3. IF schema mismatch:
     → Use ALTER TABLE with try/except for backward compatibility (see metadata_db.py pattern)
```

### Parallel Agent Delegation Rules

| Task Type | Can Parallelize? | Constraint |
|-----------|-----------------|------------|
| File hashing (vault_crawler) | ✅ Yes, ThreadPoolExecutor(4) | Never hash and write metadata for same file concurrently |
| CivitAI API calls | ❌ No | Rate-limited to 1 req/sec with `time.sleep(1)` |
| HuggingFace API calls | ✅ Yes, up to 3 concurrent | Respect HF rate limits |
| Package installations | ❌ No | One install at a time to prevent pip lock conflicts |
| Symlink creation | ❌ No | Sequential to prevent race conditions on directory creation |
| Background embedding | ✅ Yes, but single model instance | SentenceTransformer is not thread-safe, use single worker loop |
| Batch generation jobs | ❌ No | Sequential by design — one job at a time through `_batch_worker` |

### Skill Discovery

When an agent needs to perform a task, it should:
1. Check `.agents/skills/` for a matching SKILL.md
2. Read the SKILL.md `description` field for keyword matching
3. Follow the skill's exact input/output contract
4. If no skill matches, check if the task should be a new skill

Available skills:

| Skill | Location | Purpose |
|-------|----------|---------|
| Universal Inference Router | `.agents/skills/universal_inference_router/` | Multi-engine payload translation, proxy dispatch, and batch queue |
| App Store Installer | `.agents/skills/app_store_installer/` | Config-driven app installation with isolated venvs |
| Global Vault Symlinker | `.agents/skills/global_vault_symlinker/` | Zero-byte cross-platform directory junctions |
| Asset Crawler & Metadata Scraper | `.agents/skills/asset_crawler_metadata_scraper/` | Background file indexing, hashing, CivitAI/HF metadata |
| Canvas Gallery Restore | `.agents/skills/canvas_gallery_restore/` | My Creations gallery with drag-and-drop restore |
| OTA Ghost Updater | `.agents/skills/ota_ghost_updater/` | Self-healing code updates without data loss |
| **Intelligent Model Router** | `.agents/skills/intelligent_model_router/` | AI model tier selection for development tasks |
| **QA Guardian Agent** | `.agents/skills/qa_guardian_agent/` | Automated regression testing on save/commit |

---

## Layer 3 — Execution Layer

### Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Backend Server** | Python 3.11+ stdlib `http.server.ThreadingHTTPServer` | Zero dependencies. Portable. Ships with python-build-standalone. |
| **Database** | SQLite3 (stdlib) | Single-file, zero-config, survives crashes, portable across OS. |
| **Frontend** | Monolithic HTML/CSS/JS (`index.html`) | No build step. Instant reload. Ships as single file. |
| **Hashing** | `hashlib.sha256` (stdlib) | CivitAI API uses SHA-256 for model identification. |
| **HTTP Client** | `urllib.request` (stdlib) | Zero-dependency HTTP for API calls. |
| **Semantic Search** | `sentence-transformers` (all-MiniLM-L6-v2) | ~80MB model, runs on CPU, produces 384-dim embeddings. |
| **Process Management** | `subprocess.Popen` with PID tracking | Full lifecycle control of engine processes. |
| **Symlinks** | `mklink /J` (Windows) / `os.symlink` (UNIX) | Zero-byte directory links. No admin required on Windows. |
| **Portable Python** | `python-build-standalone` by indygreg | Self-contained CPython builds for all platforms. |

### Folder Structure

```
AG SM/                              ← Project Root
├── agents.md                       ← THIS FILE — master agent instructions
├── README.md                       ← User-facing documentation
├── .gitignore                      ← Ignores runtime artifacts
├── .gitmodules                     ← Git submodule declarations
│
├── install.bat / install.sh        ← Platform bootstrap scripts
├── start_manager.bat / .sh         ← Platform startup scripts
├── build.py                        ← Release packaging script
│
├── .agents/                        ← Agent skill definitions
│   └── skills/                     ← One SKILL.md per capability
│       ├── universal_inference_router/
│       ├── app_store_installer/
│       ├── global_vault_symlinker/
│       ├── asset_crawler_metadata_scraper/
│       ├── canvas_gallery_restore/
│       ├── ota_ghost_updater/
│       └── intelligent_model_router/   ← NEW — AI model tier routing
│
├── .agent/                         ← Global rules and policies
│   ├── rules/
│   │   ├── security.md
│   │   ├── cross_platform.md
│   │   ├── data_safety.md
│   │   └── model_switch_confirmation.md  ← NEW — pause-and-confirm rule
│   └── workflows/
│       └── New_Phase_Start_With_Model_Router.md  ← NEW — phase-start workflow
│
├── Workflows/                      ← Reusable development workflows
│   └── new_feature.md
│
├── .backend/                       ← Python backend (served at runtime)
│   ├── server.py                   ← HTTP server + API router (~1700 lines, 44 endpoints)
│   ├── metadata_db.py              ← SQLite ORM layer (~485 lines, models/generations/embeddings/tags)
│   ├── vault_crawler.py            ← Background file indexer with ThreadPoolExecutor
│   ├── civitai_client.py           ← CivitAI API v1 hash-based metadata scraper
│   ├── hf_client.py                ← HuggingFace Hub search client
│   ├── download_engine.py          ← Chunked file downloader with JSON progress tracking
│   ├── import_engine.py            ← Drag-drop model import pipeline with dependency resolution
│   ├── embedding_engine.py         ← Semantic search via sentence-transformers
│   ├── installer_engine.py         ← Config-driven app installer (git clone + venv + pip + symlinks)
│   ├── symlink_manager.py          ← Cross-platform directory junction/symlink creation
│   ├── updater.py                  ← OTA ghost upgrade daemon (git pull / zip extraction)
│   ├── update_checker.py           ← CivitAI model version comparator
│   ├── bootstrap.py                ← First-run directory structure initialization
│   │
│   ├── static/
│   │   └── index.html              ← Monolithic frontend (~260KB, all UI tabs + Sprint 9 widgets)
│   │
│   ├── recipes/                    ← App Store installation templates
│   │   ├── comfyui.json
│   │   ├── forge.json
│   │   ├── auto1111.json
│   │   └── fooocus.json
│   │
│   ├── cache/                      ← Runtime cache (gitignored)
│   │   ├── downloads.json          ← Active download progress tracking
│   │   └── thumbnails/             ← CivitAI preview images
│   │
│   ├── metadata.sqlite             ← Canonical database (gitignored)
│   └── settings.json               ← User preferences (gitignored)
│
├── Global_Vault/                   ← Universal model storage (gitignored)
│   ├── checkpoints/
│   ├── loras/
│   ├── vaes/
│   ├── controlnet/
│   ├── unet/
│   ├── clip/
│   ├── text_encoders/
│   ├── embeddings/
│   └── misc/
│
├── packages/                       ← Installed applications (gitignored)
│   └── comfyui/
│       ├── app/                    ← Git clone of the application
│       ├── env/                    ← Isolated .venv
│       ├── manifest.json           ← Installation metadata
│       └── runtime.log             ← Live stdout/stderr capture
│
├── bin/                            ← Portable binaries (gitignored)
│   └── python/                     ← python-build-standalone
│
└── dist/                           ← Release builds (gitignored)
    └── AIManager_Release.zip
```

### Coding Standards

#### Python (.backend/)

```python
# ✅ REQUIRED: Type hints on all public functions
def create_safe_directory_link(source_dir: str, target_link: str) -> bool:

# ✅ REQUIRED: Docstrings on classes and non-trivial functions
class VaultCrawler:
    """Background worker designed to index massive files optimally
    and stash references in SQLite."""

# ✅ REQUIRED: Logging over print() — use module-level logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ✅ REQUIRED: Exception handling with context
except subprocess.CalledProcessError as e:
    logging.error(f"Install command failed during setup: {e}")

# ✅ REQUIRED: Cross-platform branching
if os.name == 'nt':
    kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200)

# ❌ FORBIDDEN: Bare except clauses without logging
except:
    pass  # NEVER DO THIS

# ❌ FORBIDDEN: Hard-coded absolute paths
path = "C:\\Users\\user\\models"  # NEVER DO THIS

# ❌ FORBIDDEN: os.remove() on user model files without explicit confirmation
os.remove(vault_file)  # MUST be behind /api/delete_model with user intent
```

#### JavaScript (static/index.html)

```javascript
// ✅ REQUIRED: Unique IDs on all interactive elements
<button id="btn-install-comfyui">

// ✅ REQUIRED: Error handling on all fetch() calls
fetch('/api/models').then(r => r.json()).catch(err => showToast('Error: ' + err));

// ✅ REQUIRED: Template literals for dynamic HTML (no string concatenation)
const card = `<div class="model-card" data-hash="${model.file_hash}">`;

// ✅ REQUIRED: Explicit Route Mapping
// UI values (e.g., 'comfyui') MUST be explicitly mapped to expected backend endpoints (e.g., '/api/comfy_proxy'). Do NOT blindly interpolate `${engine}_proxy` without checking.

// ❌ FORBIDDEN: Global event object access (use event parameter)
function switchTab(event, tabId) {  // CORRECT
function switchTab(tabId) { const e = event; }  // WRONG
```

#### Security Rules

| Rule | Implementation |
|------|---------------|
| **Path traversal prevention** | `if ".." in path: send_error(403)` on all static file serving |
| **API Fallback Routing** | Never use `send_error(404)` on `/api/` endpoints as it returns `<!DOCTYPE HTML>`. Always use `send_json_response({"error": ...}, 404)` to prevent JS `json()` parse errors. |
| **Symlink target validation** | `os.path.abspath()` both source and target before creating links |
| **Subprocess injection prevention** | Always use list-form `subprocess.run([...])`, never `shell=True` with user input |
| **API key protection** | Keys stored in `settings.json` (gitignored), never logged, never in error responses |
| **SQLite injection prevention** | Always use parameterized queries `cursor.execute('...?...', (param,))` |
| **HTTP Redirect Authentication** | Always strip `Authorization` headers when processing HTTP redirects (e.g., using `HTTPRedirectHandler`) to prevent AWS S3/Cloudfront `400 Bad Request` exceptions on CDNs. |

### Preferred Libraries

| Library | Purpose | Why This One |
|---------|---------|-------------|
| `http.server` (stdlib) | Web server | Zero deps, ships with Python, threading support |
| `sqlite3` (stdlib) | Database | Single-file, crash-safe, no separate process |
| `hashlib` (stdlib) | Hashing | CivitAI requires SHA-256, stdlib is fastest pure-Python option |
| `urllib.request` (stdlib) | HTTP client | Zero deps, sufficient for REST APIs |
| `subprocess` (stdlib) | Process management | Full PID lifecycle control |
| `threading` (stdlib) | Concurrency | Lightweight for I/O-bound tasks (hashing, API calls) |
| `concurrent.futures` (stdlib) | Thread pools | Clean API for parallel file hashing |
| `sentence-transformers` | Semantic search | Small model (80MB), CPU-only, high-quality embeddings |
| `zipfile` (stdlib) | Release packaging | Native Python zip creation |
| `shutil` (stdlib) | File operations | Safe copy/delete with metadata preservation |
