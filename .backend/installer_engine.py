import os
import sys
import json
import logging
import subprocess

# Ensure we import the safe symlinking code
from symlink_manager import create_safe_directory_link

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

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
        os.makedirs(app_base, exist_ok=True)

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
                try:
                    subprocess.run(exec_cmd, cwd=app_clone_dir, check=True)
                except subprocess.CalledProcessError as e:
                    logging.error(f"Install command failed during setup: {e}")
                    return False

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
            shutil.rmtree(app_base)
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
