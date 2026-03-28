import os
import urllib.request

models = {
    "controlnet/control_v11p_sd15_canny_fp16.safetensors": "https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main/control_v11p_sd15_canny_fp16.safetensors"
}

vault_dir = r"g:\AG SM\Global_Vault"

for path, url in models.items():
    full_path = os.path.join(vault_dir, path)
    if os.path.exists(full_path):
        print(f"Already exists: {full_path}")
        continue
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    print(f"Downloading {url} to {full_path}...")
    try:
        urllib.request.urlretrieve(url, full_path)
        print("Done.")
    except Exception as e:
        print(f"Failed to download {path}: {e}")
