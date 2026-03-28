import urllib.request
import json
import base64

def test_comfy_combo2():
    payload = {
        "endpoint": "/api/generate",
        "payload": {
            "prompt": "testmasterpiece, highly detailed SDXL generation",
            "negative_prompt": "ugly, bad proportions",
            "seed": 42,
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "sampler_name": "euler",
            "override_settings": {"sd_model_checkpoint": "waiIllustriousSDXL_v160.safetensors"},
            "loras": [
                {"name": "artisandstyle-v3rsefx-sdxl-v1.safetensors", "weight": 0.8}
            ],
            "vae": "sdxlVAE_sdxlVAE.safetensors",
            "model_type": "sdxl",
            "refiner": "waiIllustriousSDXL_v160.safetensors",
            "refiner_steps": 10,
            # We skip controlnet for API test to avoid uploading a b64 image
            #"controlnet": {
            #    "enable": True,
            #    "model": "control_v11p_sd15_canny_fp16.safetensors",
            #    "strength": 0.8
            #}
        }
    }
    
    req = urllib.request.Request("http://localhost:8080/api/comfy_proxy", 
                                 data=json.dumps(payload).encode('utf-8'), 
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            print("Response Combo 2:", res.read().decode())
    except urllib.error.URLError as e:
        if hasattr(e, 'read'):
            print("HTTP Error:", e.read().decode())
        else:
            print("URL Error:", e)
    except Exception as e:
        print("General Error:", e)

if __name__ == "__main__":
    test_comfy_combo2()
