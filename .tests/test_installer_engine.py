import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import shutil
import sys
import json

# Allow import of backend module
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(os.path.dirname(current_dir), ".backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from installer_engine import RecipeInstaller

class TestInstallerEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.installer = RecipeInstaller(self.temp_dir)
        
        # Write dummy recipe
        self.recipe_path = os.path.join(self.temp_dir, "test_recipe.json")
        self.recipe_data = {
            "app_id": "comfyui_test",
            "name": "ComfyUI Mock",
            "repository": "https://github.com/mock/comfyui",
            "install_commands": [
                "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121"
            ],
            "model_symlinks": {
                "checkpoints": "models/checkpoints"
            }
        }
        with open(self.recipe_path, 'w') as f:
            json.dump(self.recipe_data, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("installer_engine.subprocess.run")
    def test_installation_pipeline(self, mock_subprocess):
        """Verify the entire installer parsing creates the requested directory tree and mock subprocess cmds."""
        # Ensure our subprocess mock pretends everything succeeded natively
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        result = self.installer.install(self.recipe_path)
        self.assertTrue(result)
        
        # Verify folder generation
        app_base = os.path.join(self.temp_dir, "packages", "comfyui_test")
        self.assertTrue(os.path.exists(app_base))
        
        # Verify Vault created the checkpoint dir natively before mapping
        source_vault = os.path.join(self.temp_dir, "Global_Vault", "checkpoints")
        self.assertTrue(os.path.exists(source_vault))
        
        # Verify Manifest
        manifest_path = os.path.join(app_base, "manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, 'r') as f:
            manifest_json = json.load(f)
            self.assertEqual(manifest_json["name"], "ComfyUI Mock")
            
        # Verify Subprocess Execution sequence (Clone -> Venv -> Pip)
        # subprocess.run should have been called at least 3 times implicitly (clone, venv, pip)
        # Windows will call it a 4th time natively via symlink_manager "mklink"
        self.assertGreaterEqual(mock_subprocess.call_count, 3)
        calls = mock_subprocess.call_args_list
        
        # Clone
        self.assertIn("clone", calls[0][0][0])
        self.assertIn("https://github.com/mock/comfyui", calls[0][0][0])
        
        # Venv
        self.assertIn("venv", calls[1][0][0])
        
        # Pip command correctly isolated to the Venv Python binary, NOT globally!
        pip_cmd = calls[2][0][0]
        self.assertTrue(pip_cmd[0].endswith("python") or pip_cmd[0].endswith("python.exe"))
        self.assertEqual(pip_cmd[1], "-m")
        self.assertEqual(pip_cmd[2], "pip")

    def test_uninstallation_wipes_isolated_environment(self):
        """Verify `rmtree` removes the virtual environment wrapper securely."""
        app_base = os.path.join(self.temp_dir, "packages", "comfyui_test")
        os.makedirs(app_base, exist_ok=True)
        # Dummy file
        with open(os.path.join(app_base, "manifest.json"), 'w') as f:
            f.write("{}")
            
        result = self.installer.uninstall("comfyui_test")
        self.assertTrue(result)
        self.assertFalse(os.path.exists(app_base))

    def test_uninstallation_wipes_readonly_environment(self):
        """Verify `rmtree` removes read-only files dynamically via the onerror chmod override."""
        import stat
        app_base = os.path.join(self.temp_dir, "packages", "readonly_test")
        os.makedirs(app_base, exist_ok=True)
        # Dummy file lock
        filepath = os.path.join(app_base, "readonly_file.txt")
        with open(filepath, 'w') as f:
            f.write("strict")
        # Ensure it is locked
        os.chmod(filepath, stat.S_IREAD)
        
        result = self.installer.uninstall("readonly_test")
        self.assertTrue(result)
        self.assertFalse(os.path.exists(app_base))

if __name__ == '__main__':
    unittest.main()
