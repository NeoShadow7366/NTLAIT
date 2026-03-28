import os
import urllib.request
import json
import time

def download_file(url, dest_path):
    if os.path.exists(dest_path):
        print(f"Already exists: {dest_path}")
        return
    print(f"Downloading {url} to {dest_path}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    count = 0
    try:
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = response.read(8192 * 4)
                    if not chunk:
                        break
                    f.write(chunk)
                    count += len(chunk)
                    if count % (1024*1024*100) == 0:  # Every 100MB
                        print(f"  Downloaded {count/(1024*1024*100):.1f}00 MB / {total_size/(1024*1024):.1f} MB")
        print(f"Successfully downloaded {dest_path}")
    except Exception as e:
         print(f"Failed to download {url}: {e}")

models_to_download = [
    # FLUX-schnell FP8 Checkpoint (~12GB) from HuggingFace
    ("https://huggingface.co/Kijai/flux-fp8/resolve/main/flux1-schnell-fp8.safetensors", "Global_Vault/checkpoints/flux1-schnell-fp8.safetensors"),
    # FLUX VAE (~335MB)
    ("https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors", "Global_Vault/vaes/ae.safetensors"),
    # CLIP L (~246MB)
    ("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors", "Global_Vault/clip/clip_l.safetensors"),
    # T5 FP8 (~4.89GB)
    ("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors", "Global_Vault/clip/t5xxl_fp8_e4m3fn.safetensors"),
    # FLUX ControlNet Canny (~1GB X-Labs)
    ("https://huggingface.co/XLabs-AI/flux-controlnet-canny-v3/resolve/main/flux-canny-controlnet-v3.safetensors", "Global_Vault/controlnet/flux-canny-controlnet-v3.safetensors"),
    # 2 FLUX LoRAs (Realistic & Detailer)
    ("https://civitai.com/api/download/models/730248", "Global_Vault/loras/flux_realism_lora.safetensors"), # Boreal
    ("https://civitai.com/api/download/models/729828", "Global_Vault/loras/flux_detailer_lora.safetensors") # Detailer
]

for url, dest in models_to_download:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    download_file(url, dest)
