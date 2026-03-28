import os
import json
import sys

sys.path.insert(0, os.path.join(r"g:\AG SM", ".backend"))
from symlink_manager import create_safe_directory_link

def fix_links():
    root = r"g:\AG SM"
    comfy_dir = os.path.join(root, "packages", "comfyui", "app")
    with open(os.path.join(root, ".backend", "recipes", "comfyui.json")) as f:
        meta = json.load(f)
    
    for vault_cat, app_rel_path in meta.get("model_symlinks", {}).items():
        src = os.path.join(root, "Global_Vault", vault_cat)
        target = os.path.join(comfy_dir, app_rel_path.replace("/", os.sep))
        os.makedirs(src, exist_ok=True)
        
        # Remove target if it's an empty real dir
        if os.path.isdir(target) and not os.path.islink(target):
            import shutil
            try:
                shutil.rmtree(target)
            except Exception as e:
                print(f"Skipping rmtree for {target}: {e}")
                
        res = create_safe_directory_link(src, target)
        print(f"[{res}] Linked {src} -> {target}")

if __name__ == "__main__":
    fix_links()
