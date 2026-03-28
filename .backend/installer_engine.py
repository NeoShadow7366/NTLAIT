import os
import sys
import json
import logging
import subprocess
import re
import threading
import time

# Ensure we import the safe symlinking code
from symlink_manager import create_safe_directory_link

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


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
    
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.packages_dir = os.path.join(self.root_dir, "packages")
        self.vault_dir = os.path.join(self.root_dir, "Global_Vault")
        # Ensure our base folders exist
        os.makedirs(self.packages_dir, exist_ok=True)
        os.makedirs(self.vault_dir, exist_ok=True)

    def _get_python_executable(self, venv_dir: str) -> str:
        """Returns the isolated python executable for a given venv."""
        if os.name == 'nt':
            return os.path.join(venv_dir, "Scripts", "python.exe")
        return os.path.join(venv_dir, "bin", "python")

    def install(self, recipe_path: str):
        if not os.path.exists(recipe_path):
            logging.error(f"Recipe not found: {recipe_path}")
            return False

        with open(recipe_path, 'r', encoding='utf-8') as f:
            recipe = json.load(f)

        app_id = recipe.get("app_id")
        app_base = os.path.join(self.packages_dir, app_id)
        app_clone_dir = os.path.join(app_base, "app")
        venv_dir = os.path.join(app_base, "env")

        logging.info(f"=== Starting Installation for {recipe.get('name')} ===")
        
        # 1. Directory Structure inside package manager
        is_new_install = not os.path.exists(app_base)
        os.makedirs(app_base, exist_ok=True)

        try:
            # 2. Git Clone
            if not os.path.exists(app_clone_dir):
                logging.info(f"Cloning {recipe.get('repository')} into {app_clone_dir}...")
                # Ideally this calls bin/git/git.exe to prevent git permission inheritance.
                subprocess.run(["git", "clone", recipe["repository"], app_clone_dir], check=True)
            else:
                logging.info(f"Directory {app_clone_dir} already exists. Skipping clone.")

            # 3. Virtual Environment Creation
            if not os.path.exists(venv_dir):
                logging.info(f"Creating strictly isolated Python VENV at {venv_dir}...")
                # Real deployment uses self.root_dir/bin/python/python.exe
                portable_python = os.path.join(self.root_dir, "bin", "python", "python.exe") if os.name == 'nt' else os.path.join(self.root_dir, "bin", "python", "bin", "python")
                python_exe = portable_python if os.path.exists(portable_python) else sys.executable
                subprocess.run([python_exe, "-m", "venv", venv_dir], check=True)
            
            venv_python = self._get_python_executable(venv_dir)

            # 4. Proxied Pip Installs (Using Isolated VENV python)
            commands = recipe.get("install_commands", [])
            if commands:
                logging.info("Executing isolated PIP commands...")
                for cmd in commands:
                    # Intercept `pip install` to force `venv/python -m pip install`
                    if cmd.startswith("pip "):
                        parts = cmd.split(" ")[1:] 
                        exec_cmd = [venv_python, "-m", "pip"] + parts
                    else:
                        exec_cmd = cmd.split(" ")
                        
                    logging.info(f"Running: {' '.join(exec_cmd)}")
                    subprocess.run(exec_cmd, cwd=app_clone_dir, check=True)

            # 5. Global Vault Route Symlinking
            symlinks = recipe.get("model_symlinks", {})
            if symlinks:
                logging.info("Routing Global Vault references securely...")
                for vault_src, app_target in symlinks.items():
                    source_path = os.path.join(self.vault_dir, vault_src)
                    target_path = os.path.join(app_clone_dir, app_target)
                    
                    # Ensure the vault category folder natively exists so we can map it
                    os.makedirs(source_path, exist_ok=True) 
                    create_safe_directory_link(source_path, target_path)

            # 6. Saving Local Manifest for Tracking
            manifest_path = os.path.join(app_base, "manifest.json")
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(recipe, f, indent=4)
            
            logging.info(f"=== Installation of {recipe.get('name')} Complete! ===")
            return True

        except Exception as e:
            logging.error(f"Installation failed: {e}")
            if is_new_install:
                logging.info(f"Rolling back failed installation of {recipe.get('name')} at {app_base}")
                import shutil
                shutil.rmtree(app_base, ignore_errors=True)
            return False

    def uninstall(self, package_id: str):
        import shutil
        app_base = os.path.join(self.packages_dir, package_id)
        
        if not os.path.exists(app_base):
            logging.error(f"Cannot uninstall: Package {package_id} not found at {app_base}")
            return False
            
        logging.info(f"=== Starting Uninstallation of {package_id} ===")
        
        # Native safe tree removal. Since models are symlinks/junctions,
        # shutil.rmtree securely removes the link, NOT the target contents.
        try:
            def remove_readonly(func, path, _):
                import stat
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
