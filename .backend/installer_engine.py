import os
import sys
import json
import logging
import subprocess
import re
import threading
import time
import shutil
import stat
import tempfile
import platform

# Ensure we import the safe symlinking code
from symlink_manager import create_safe_directory_link

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# ── S-5: Platform-aware PyTorch Index URL Resolver ──────────────────
# Recipes declare `cu121` as intent ("I need GPU-accelerated PyTorch").
# At install time, this resolver detects the actual GPU and rewrites
# the pip --index-url to match the user's hardware.

def _detect_gpu_vendor() -> str:
    """Detect GPU vendor at install time. Returns 'nvidia', 'amd', 'mps', or 'cpu'."""
    system = platform.system()

    # macOS: Apple Silicon uses MPS (Metal Performance Shaders) — no CUDA
    if system == "Darwin":
        try:
            chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                           timeout=5).decode().strip()
            if "Apple" in chip:
                return "mps"
        except Exception:
            pass
        return "cpu"

    # Windows/Linux: Check for NVIDIA GPU via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, timeout=5,
            creationflags=0x08000000 if os.name == 'nt' else 0
        )
        if result.returncode == 0 and result.stdout.strip():
            return "nvidia"
    except (FileNotFoundError, Exception):
        pass

    # Check for AMD/ROCm GPU
    if system == "Linux":
        try:
            result = subprocess.run(["rocminfo"], capture_output=True, timeout=5)
            if result.returncode == 0 and b"gfx" in result.stdout:
                return "amd"
        except (FileNotFoundError, Exception):
            pass

    return "cpu"


# Cache the detection result — GPU doesn't change during a session
_gpu_vendor_cache: str | None = None


def _get_gpu_vendor() -> str:
    """Cached GPU vendor detection."""
    global _gpu_vendor_cache
    if _gpu_vendor_cache is None:
        _gpu_vendor_cache = _detect_gpu_vendor()
        logging.info(f"Detected GPU vendor: {_gpu_vendor_cache}")
    return _gpu_vendor_cache


# Map GPU vendor to PyTorch pip index URL
_PYTORCH_INDEX_URLS = {
    "nvidia": "https://download.pytorch.org/whl/cu121",
    "amd":    "https://download.pytorch.org/whl/rocm6.2",
    "cpu":    "https://download.pytorch.org/whl/cpu",
    "mps":    None,  # macOS MPS uses default PyPI (no --index-url needed)
}


def resolve_pytorch_command(cmd: str) -> str:
    """Rewrite a pip install torch command's --index-url based on detected GPU.

    Input:  "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121"
    Output: Same command with the index URL replaced for the current platform.
            On macOS (MPS), --index-url is removed entirely (uses default PyPI).

    Non-torch pip commands are returned unchanged.
    """
    # Only transform pip install commands that contain torch and an index URL
    if not (cmd.startswith("pip ") and "torch" in cmd and "--index-url" in cmd):
        return cmd

    vendor = _get_gpu_vendor()
    target_url = _PYTORCH_INDEX_URLS.get(vendor)

    if target_url is None:
        # macOS MPS: remove --index-url entirely — PyPI default has MPS support
        cmd = re.sub(r'\s*--index-url\s+\S+', '', cmd)
        logging.info(f"[PyTorch] macOS MPS detected — removed --index-url (using PyPI default)")
    else:
        # Replace the existing index URL with the platform-specific one
        original = cmd
        cmd = re.sub(r'--index-url\s+\S+', f'--index-url {target_url}', cmd)
        if cmd != original:
            logging.info(f"[PyTorch] Rewrote index URL for {vendor}: {target_url}")

    return cmd


# ── Extension Clone Progress Tracker ────────────────────────────────

class ExtensionCloneTracker:
    """Tracks git clone progress for extension installs with cross-platform output parsing."""

    _PROGRESS_RE = re.compile(r'(\w[\w\s]+?):\s+(\d+)%\s+\((\d+)/(\d+)\)')

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.jobs_file = os.path.join(root_dir, ".backend", "cache", "extension_jobs.json")
        os.makedirs(os.path.dirname(self.jobs_file), exist_ok=True)

    def _read_jobs(self) -> dict:
        if os.path.exists(self.jobs_file):
            try:
                with open(self.jobs_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_jobs(self, jobs: dict) -> None:
        with open(self.jobs_file, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2)

    def _update_job(self, job_id: str, updates: dict) -> None:
        jobs = self._read_jobs()
        if job_id not in jobs:
            jobs[job_id] = {}
        jobs[job_id].update(updates)
        self._write_jobs(jobs)

    def get_job_status(self, job_id: str) -> dict:
        jobs = self._read_jobs()
        return jobs.get(job_id, {})

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running clone by killing its PID."""
        job = self.get_job_status(job_id)
        pid = job.get("pid")
        if not pid:
            return False
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], check=False,
                                capture_output=True)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
            self._update_job(job_id, {"status": "cancelled", "progress_text": "Cancelled by user"})
            return True
        except (ProcessLookupError, OSError) as e:
            logging.warning(f"Failed to cancel clone job {job_id}: {e}")
            return False

    def clone_with_progress(self, repo_url: str, target_dir: str, job_id: str) -> None:
        """Clone a git repo with real-time progress tracking.

        This runs in the calling thread (expected to be spawned as a background thread).
        Progress is written to extension_jobs.json for /api/extensions/status polling.
        """
        self._update_job(job_id, {
            "status": "cloning",
            "repo_url": repo_url,
            "target_dir": target_dir,
            "percent": 0,
            "progress_text": "Starting clone...",
            "log_lines": [],
            "pid": None
        })

        cmd = ["git", "clone", "--progress", repo_url]
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=target_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs
            )
            self._update_job(job_id, {"pid": proc.pid})

            # Git clone --progress writes to stderr
            log_lines = []
            buffer = b""

            while True:
                chunk = proc.stderr.read(1)
                if not chunk:
                    break

                if chunk in (b'\r', b'\n'):
                    if buffer:
                        line_text = buffer.decode('utf-8', errors='replace').strip()
                        buffer = b""
                        if line_text:
                            log_lines.append(line_text)
                            # Keep last 50 lines only
                            if len(log_lines) > 50:
                                log_lines = log_lines[-50:]

                            # Parse percentage from git progress output
                            match = self._PROGRESS_RE.search(line_text)
                            percent = 0
                            if match:
                                percent = int(match.group(2))

                            self._update_job(job_id, {
                                "progress_text": line_text,
                                "percent": percent,
                                "log_lines": log_lines
                            })
                else:
                    buffer += chunk

            # Process remaining buffer
            if buffer:
                line_text = buffer.decode('utf-8', errors='replace').strip()
                if line_text:
                    log_lines.append(line_text)

            proc.wait()
            exit_code = proc.returncode

            # Read any remaining stdout
            stdout_data = proc.stdout.read().decode('utf-8', errors='replace').strip()
            if stdout_data:
                log_lines.extend(stdout_data.split('\n'))

            if exit_code == 0:
                self._update_job(job_id, {
                    "status": "completed",
                    "percent": 100,
                    "progress_text": "Clone completed successfully",
                    "log_lines": log_lines,
                    "pid": None
                })
                logging.info(f"Extension clone {job_id} completed successfully.")
            else:
                self._update_job(job_id, {
                    "status": "failed",
                    "progress_text": f"Clone failed with exit code {exit_code}",
                    "log_lines": log_lines,
                    "pid": None
                })
                logging.error(f"Extension clone {job_id} failed with exit code {exit_code}.")

        except FileNotFoundError:
            self._update_job(job_id, {
                "status": "failed",
                "progress_text": "Git executable not found. Is git installed and on PATH?",
                "pid": None
            })
            logging.error(f"Extension clone {job_id}: git not found.")
        except Exception as e:
            self._update_job(job_id, {
                "status": "failed",
                "progress_text": f"Unexpected error: {str(e)}",
                "pid": None
            })
            logging.error(f"Extension clone {job_id} error: {e}")

class RecipeInstaller:
    """Config-Driven AI Package Installer Engine"""

    # Reuse the same git progress regex from ExtensionCloneTracker
    _GIT_PROGRESS_RE = re.compile(r'(\w[\w\s]+?):\s+(\d+)%\s+\((\d+)/(\d+)\)')

    # ── Weighted progress allocations (must sum to 100) ──────────
    _WEIGHT_CLONE   = 20
    _WEIGHT_VENV    = 5
    _WEIGHT_PIP     = 60  # Shared across all pip commands
    _WEIGHT_SYMLINK = 5
    _WEIGHT_MANIFEST = 10
    
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.packages_dir = os.path.join(self.root_dir, "packages")
        self.vault_dir = os.path.join(self.root_dir, "Global_Vault")
        self.jobs_file = os.path.join(self.root_dir, ".backend", "cache", "install_jobs.json")
        # Ensure our base folders exist
        os.makedirs(self.packages_dir, exist_ok=True)
        os.makedirs(self.vault_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.jobs_file), exist_ok=True)

    # ── Pre-flight Checks ───────────────────────────────────────

    @staticmethod
    def _check_git_available() -> bool:
        """Verify that git is installed and accessible on PATH."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _resolve_latest_release_tag(self, repo_url: str) -> str | None:
        """Resolve the latest release tag from a GitHub repository URL.

        Uses the GitHub REST API (unauthenticated). Returns the tag name string
        on success, or None if the API call fails or the repo has no releases.
        """
        import urllib.request
        import urllib.error

        # Extract owner/repo from clone URL
        # Handles: https://github.com/owner/repo.git  or  https://github.com/owner/repo
        clean = repo_url.replace(".git", "").rstrip("/")
        parts = clean.split("github.com/")
        if len(parts) < 2:
            logging.warning(f"Cannot parse GitHub owner/repo from: {repo_url}")
            return None
        owner_repo = parts[1]  # e.g. "comfyanonymous/ComfyUI"

        api_url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
        logging.info(f"Resolving latest release tag from {api_url}...")

        try:
            req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name")
                if tag:
                    logging.info(f"Resolved latest release tag: {tag}")
                    return tag
                logging.warning(f"GitHub API returned release without tag_name for {owner_repo}")
                return None
        except urllib.error.HTTPError as e:
            # 404 = no releases exist for this repo
            logging.warning(f"GitHub API error for {owner_repo}: HTTP {e.code}")
            return None
        except Exception as e:
            logging.warning(f"Failed to resolve release tag for {owner_repo}: {e}")
            return None

    # ── Helpers ──────────────────────────────────────────────────

    def _get_python_executable(self, venv_dir: str) -> str:
        """Returns the isolated python executable for a given venv."""
        if os.name == 'nt':
            return os.path.join(venv_dir, "Scripts", "python.exe")
        return os.path.join(venv_dir, "bin", "python")

    def _read_jobs(self) -> dict:
        if os.path.exists(self.jobs_file):
            try:
                with open(self.jobs_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_jobs(self, jobs: dict) -> None:
        with open(self.jobs_file, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2)

    def _update_progress(self, app_id: str, updates: dict) -> None:
        """Write progress updates to the shared install_jobs.json file."""
        jobs = self._read_jobs()
        if app_id not in jobs:
            jobs[app_id] = {}
        jobs[app_id].update(updates)
        self._write_jobs(jobs)

    # ── Streaming Subprocess Runners ────────────────────────────

    def _run_git_clone_with_progress(self, clone_cmd: list, app_id: str, base_pct: int, weight: int) -> None:
        """Run git clone with --progress and stream real-time progress to install_jobs.json.
        
        base_pct: The starting percentage for this phase.
        weight: The total percentage weight allocated to this phase.
        """
        cmd = clone_cmd[:2] + ["--progress"] + clone_cmd[2:]  # Insert --progress after 'git clone'
        
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200)

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        )

        buffer = b""
        while True:
            chunk = proc.stderr.read(1)
            if not chunk:
                break

            if chunk in (b'\r', b'\n'):
                if buffer:
                    line_text = buffer.decode('utf-8', errors='replace').strip()
                    buffer = b""
                    if line_text:
                        match = self._GIT_PROGRESS_RE.search(line_text)
                        if match:
                            git_pct = int(match.group(2))
                            overall_pct = base_pct + int(git_pct / 100 * weight)
                        else:
                            overall_pct = base_pct
                        self._update_progress(app_id, {
                            "phase": f"Cloning: {line_text[:60]}",
                            "percent": min(overall_pct, base_pct + weight),
                            "log": [line_text]
                        })
            else:
                buffer += chunk

        proc.wait()
        if proc.returncode != 0:
            stderr_tail = proc.stderr.read().decode('utf-8', errors='replace').strip()
            raise RuntimeError(f"Git clone failed (exit {proc.returncode}): {stderr_tail[-200:]}")

    def _run_pip_with_output(self, exec_cmd: list, cwd: str, app_id: str,
                              phase_label: str, base_pct: int) -> int:
        """Run a pip command and stream its output to install_jobs.json.
        
        Returns the process exit code.
        """
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200)

        proc = subprocess.Popen(
            exec_cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            **kwargs
        )

        log_lines = []
        for raw_line in proc.stdout:
            line = raw_line.decode('utf-8', errors='replace').rstrip()
            if line:
                log_lines.append(line)
                # Keep last 15 lines for the UI
                if len(log_lines) > 15:
                    log_lines = log_lines[-15:]
                self._update_progress(app_id, {
                    "phase": phase_label,
                    "percent": base_pct,
                    "log": log_lines
                })

        proc.wait()
        return proc.returncode

    # ── Main Install Pipeline ───────────────────────────────────

    def install(self, recipe_path: str):
        if not os.path.exists(recipe_path):
            logging.error(f"Recipe not found: {recipe_path}")
            return False

        with open(recipe_path, 'r', encoding='utf-8') as f:
            recipe = json.load(f)

        app_id = recipe.get("app_id")
        app_name = recipe.get("name", app_id)
        app_base = os.path.join(self.packages_dir, app_id)
        app_clone_dir = os.path.join(app_base, "app")
        venv_dir = os.path.join(app_base, "env")

        logging.info(f"=== Starting Installation for {app_name} ===")
        self._update_progress(app_id, {
            "status": "installing",
            "name": app_name,
            "phase": "Pre-flight checks...",
            "step": 0,
            "total_steps": 5,
            "percent": 0,
            "log": []
        })

        # ── Pre-flight: Git availability ────────────────────────
        if not os.path.exists(app_clone_dir):
            if not self._check_git_available():
                err = "Git is not installed or not on PATH. Please install Git and try again."
                logging.error(err)
                self._update_progress(app_id, {
                    "status": "failed",
                    "phase": "Pre-flight Failed",
                    "log": [f"❌ {err}"]
                })
                return False
        
        # 1. Directory Structure inside package manager
        is_new_install = not os.path.exists(app_base)
        os.makedirs(app_base, exist_ok=True)

        # Calculate pip weight per command
        pip_commands = recipe.get("install_commands", [])
        num_pip = max(len(pip_commands), 1)
        pip_weight_each = self._WEIGHT_PIP // num_pip

        try:
            # ── Phase 1: Git Clone (release-aware, shallow, streamed) ──
            pct = 0
            installed_version = None

            # Determine if the clone is valid (not just an orphaned .git dir)
            clone_looks_valid = os.path.exists(app_clone_dir) and (
                os.path.exists(os.path.join(app_clone_dir, "requirements.txt")) or
                os.path.exists(os.path.join(app_clone_dir, recipe.get("launch_command", "NONE").split(" ")[0]))
            )

            if not clone_looks_valid:
                repo_url = recipe["repository"]
                install_mode = recipe.get("install_mode", "head")

                # Resolve release tag if requested
                release_tag = None
                if install_mode == "latest_release":
                    self._update_progress(app_id, {
                        "phase": "Resolving latest release...",
                        "percent": 1,
                        "log": [f"Checking GitHub for latest release of {app_name}..."]
                    })
                    release_tag = self._resolve_latest_release_tag(repo_url)

                # Build the clone command
                clone_cmd = ["git", "clone", "--depth", "1"]
                if release_tag:
                    clone_cmd += ["--branch", release_tag]
                    installed_version = release_tag
                    log_msg = f"Cloning {app_name} release {release_tag} (shallow)..."
                else:
                    if install_mode == "latest_release":
                        logging.warning(f"No release found for {app_name}, falling back to HEAD")
                    installed_version = "HEAD"
                    log_msg = f"Cloning {app_name} HEAD (shallow)..."

                # If dir exists but is corrupted, try to clean it first
                if os.path.exists(app_clone_dir):
                    logging.warning(f"Directory {app_clone_dir} exists but source is missing — attempting cleanup...")
                    try:
                        def remove_readonly(func, path, _):
                            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                            func(path)
                        shutil.rmtree(app_clone_dir, onerror=remove_readonly)
                    except Exception:
                        if os.name == 'nt':
                            subprocess.run(['cmd', '/c', 'rmdir', '/s', '/q', app_clone_dir],
                                           check=False, capture_output=True, timeout=30)

                if os.path.exists(app_clone_dir):
                    # Dir is locked — clone into temp dir and copy source files over
                    logging.warning(f"Cannot delete {app_clone_dir} — cloning into temp dir and copying...")
                    with tempfile.TemporaryDirectory(prefix=f"{app_id}_repair_") as tmp_dir:
                        tmp_clone = os.path.join(tmp_dir, "app")
                        clone_cmd_tmp = clone_cmd + [repo_url, tmp_clone]

                        logging.info(log_msg + " (via temp fallback)")
                        self._update_progress(app_id, {
                            "phase": "Cloning Repository (repair mode)",
                            "percent": pct,
                            "log": [log_msg]
                        })
                        self._run_git_clone_with_progress(clone_cmd_tmp, app_id, pct, self._WEIGHT_CLONE)

                        # Copy all files (excluding .git) from temp clone into the existing dir
                        for item in os.listdir(tmp_clone):
                            if item == ".git":
                                continue
                            src = os.path.join(tmp_clone, item)
                            dst = os.path.join(app_clone_dir, item)
                            if os.path.isdir(src):
                                if os.path.exists(dst):
                                    shutil.rmtree(dst, ignore_errors=True)
                                shutil.copytree(src, dst)
                            else:
                                shutil.copy2(src, dst)
                        logging.info(f"Copied source files from temp clone into {app_clone_dir}")
                else:
                    # Normal case: clean clone into target dir
                    clone_cmd.append(repo_url)
                    clone_cmd.append(app_clone_dir)

                    logging.info(log_msg)
                    self._update_progress(app_id, {
                        "phase": "Cloning Repository",
                        "percent": pct,
                        "log": [log_msg]
                    })
                    self._run_git_clone_with_progress(clone_cmd, app_id, pct, self._WEIGHT_CLONE)
            else:
                logging.info(f"Directory {app_clone_dir} already exists with valid source. Skipping clone.")
                self._update_progress(app_id, {
                    "phase": "Repository exists (skipped)",
                    "percent": self._WEIGHT_CLONE
                })

            pct = self._WEIGHT_CLONE

            # ── Phase 2: Virtual Environment Creation ──────────────
            venv_python = self._get_python_executable(venv_dir)
            # Validate venv integrity: directory may exist but be corrupted (missing python.exe)
            needs_venv = not os.path.exists(venv_dir)
            if not needs_venv and not os.path.exists(venv_python):
                logging.warning(f"Corrupted venv detected at {venv_dir} (python executable missing). Recreating...")
                shutil.rmtree(venv_dir, ignore_errors=True)
                needs_venv = True

            if needs_venv:
                log_msg = "Creating isolated Python environment..."
                logging.info(f"Creating strictly isolated Python VENV at {venv_dir}...")
                self._update_progress(app_id, {
                    "phase": "Creating Virtual Environment",
                    "percent": pct,
                    "log": [log_msg]
                })
                portable_python = os.path.join(self.root_dir, "bin", "python", "python.exe") if os.name == 'nt' else os.path.join(self.root_dir, "bin", "python", "bin", "python")
                python_exe = portable_python if os.path.exists(portable_python) else sys.executable
                subprocess.run([python_exe, "-m", "venv", venv_dir], check=True)
                # Re-resolve after creation
                venv_python = self._get_python_executable(venv_dir)

                # Upgrade pip in the fresh venv for speed + compatibility
                logging.info("Upgrading pip in fresh venv...")
                self._update_progress(app_id, {
                    "phase": "Upgrading pip...",
                    "percent": pct + 2,
                    "log": ["Upgrading pip for faster installs..."]
                })
                subprocess.run(
                    [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
                    capture_output=True, cwd=app_clone_dir if os.path.exists(app_clone_dir) else app_base
                )
            else:
                self._update_progress(app_id, {
                    "phase": "Virtual env exists (skipped)",
                    "percent": pct
                })

            pct = self._WEIGHT_CLONE + self._WEIGHT_VENV

            # ── Phase 3: Proxied Pip Installs (streamed output) ────
            pip_failures = []
            if pip_commands:
                logging.info("Executing isolated PIP commands...")
                for i, cmd in enumerate(pip_commands):
                    # S-5: Resolve platform-aware PyTorch index URL before execution
                    cmd = resolve_pytorch_command(cmd)
                    # Intercept `pip install` to force `venv/python -m pip install`
                    if cmd.startswith("pip "):
                        parts = cmd.split(" ")[1:] 
                        exec_cmd = [venv_python, "-m", "pip"] + parts
                    else:
                        exec_cmd = cmd.split(" ")
                    
                    display_cmd = cmd[:80] + ("..." if len(cmd) > 80 else "")
                    phase_label = f"Installing Dependencies ({i+1}/{len(pip_commands)})"
                    logging.info(f"Running: {' '.join(exec_cmd)}")
                    
                    cmd_base_pct = pct + (i * pip_weight_each)
                    self._update_progress(app_id, {
                        "phase": phase_label,
                        "percent": cmd_base_pct,
                        "log": [f"Running: {display_cmd}"]
                    })

                    exit_code = self._run_pip_with_output(
                        exec_cmd, app_clone_dir, app_id,
                        phase_label, cmd_base_pct
                    )
                    if exit_code != 0:
                        warn_msg = f"Warning: pip command failed (exit {exit_code}): {display_cmd}"
                        logging.warning(warn_msg)
                        pip_failures.append(display_cmd)
                        self._update_progress(app_id, {
                            "phase": f"Dependency warning ({i+1}/{len(pip_commands)})",
                            "log": [warn_msg]
                        })

            pct = self._WEIGHT_CLONE + self._WEIGHT_VENV + self._WEIGHT_PIP

            # ── Phase 4: Global Vault Route Symlinking ─────────────
            symlinks = recipe.get("model_symlinks", {})
            if symlinks:
                logging.info("Routing Global Vault references securely...")
                self._update_progress(app_id, {
                    "phase": "Linking Global Vault",
                    "percent": pct,
                    "log": [f"Creating {len(symlinks)} vault symlinks..."]
                })
                for vault_src, app_target in symlinks.items():
                    source_path = os.path.join(self.vault_dir, vault_src)
                    target_path = os.path.join(app_clone_dir, app_target)
                    
                    # Ensure the vault category folder natively exists so we can map it
                    os.makedirs(source_path, exist_ok=True) 
                    create_safe_directory_link(source_path, target_path)

            pct = self._WEIGHT_CLONE + self._WEIGHT_VENV + self._WEIGHT_PIP + self._WEIGHT_SYMLINK

            # ── Phase 5: Saving Local Manifest for Tracking ────────
            manifest_path = os.path.join(app_base, "manifest.json")
            manifest_data = dict(recipe)
            if installed_version:
                manifest_data["installed_version"] = installed_version
            manifest_data["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest_data, f, indent=4)
            
            logging.info(f"=== Installation of {app_name} Complete! ===")
            completion_log = [f"✅ Successfully installed {app_name}"]
            if installed_version and installed_version != "HEAD":
                completion_log.append(f"Version: {installed_version}")
            if pip_failures:
                completion_log.append(f"Note: {len(pip_failures)} optional dependency command(s) had warnings. The app may auto-resolve these on first launch.")
                logging.warning(f"Installation completed with {len(pip_failures)} pip warning(s)")
            self._update_progress(app_id, {
                "status": "completed",
                "phase": "Installation Complete",
                "step": 5,
                "total_steps": 5,
                "percent": 100,
                "log": completion_log
            })
            return True

        except Exception as e:
            logging.error(f"Installation failed: {e}")
            self._update_progress(app_id, {
                "status": "failed",
                "phase": f"Failed: {str(e)[:100]}",
                "log": [f"Error: {str(e)}"]
            })
            if is_new_install:
                logging.info(f"Rolling back failed installation of {app_name} at {app_base}")
                shutil.rmtree(app_base, ignore_errors=True)
            return False

    def uninstall(self, package_id: str):
        app_base = os.path.join(self.packages_dir, package_id)
        
        if not os.path.exists(app_base):
            logging.error(f"Cannot uninstall: Package {package_id} not found at {app_base}")
            return False
            
        logging.info(f"=== Starting Uninstallation of {package_id} ===")
        
        # Native safe tree removal. Since models are symlinks/junctions,
        # shutil.rmtree securely removes the link, NOT the target contents.
        try:
            def remove_readonly(func, path, _):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass
            shutil.rmtree(app_base, onerror=remove_readonly)
            logging.info(f"Successfully wiped isolated environment and app data for {package_id}.")
            return True
        except Exception as e:
            logging.error(f"Failed to uninstall {package_id}: {e}")
            return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Standard usage from command line wrapper
        installer = RecipeInstaller(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        installer.install(sys.argv[1])
    else:
        print("Usage: python installer_engine.py path_to_recipe.json")

