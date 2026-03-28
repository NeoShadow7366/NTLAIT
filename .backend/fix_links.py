import os
import json
from symlink_manager import create_safe_directory_link

root_dir = os.path.dirname(os.path.abspath(__file__))
recipe_path = os.path.join(root_dir, "recipes", "comfyui.json")

with open(recipe_path, 'r') as f:
    recipe = json.load(f)

app_clone_dir = os.path.join(os.path.dirname(root_dir), "packages", "comfyui", "app")
vault_dir = os.path.join(os.path.dirname(root_dir), "Global_Vault")

for vault_src, app_target in recipe.get("model_symlinks", {}).items():
    source_path = os.path.join(vault_dir, vault_src)
    target_path = os.path.join(app_clone_dir, app_target)
    os.makedirs(source_path, exist_ok=True) 
    create_safe_directory_link(source_path, target_path)

print("Symlinks created.")
