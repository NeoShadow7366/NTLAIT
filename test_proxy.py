import urllib.request
import json

def test_comfy():
    payload = {
        "endpoint": "/api/generate",
        "payload": {
            "prompt": "testmasterpiece, best quality, absurdres, newest, 1Girl, beautifu",
            "negative_prompt": "many fingers, long neck, gross proportions",
            "seed": 42,
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
            "sampler_name": "euler",
            "override_settings": {"sd_model_checkpoint": "dreamshaper_8.safetensors"},
            "loras": [
                {"name": "GoodHands-beta2.safetensors", "weight": 0.8},
                {"name": "artisandstyle-v3rsefx-sdxl-v1.safetensors", "weight": 0.5}
            ],
            "hires": {"enable": True, "factor": 1.5, "denoise": 0.4, "steps": 10, "upscaler": "latent"},
            "vae": "clearvaeSD15_v23.safetensors",
            "model_type": "sd15"
        }
    }
    
    req = urllib.request.Request("http://localhost:8080/api/comfy_proxy", 
                                 data=json.dumps(payload).encode('utf-8'), 
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            print("Response:", res.read().decode())
    except urllib.error.URLError as e:
        if hasattr(e, 'read'):
            print("HTTP Error:", e.read().decode())
        else:
            print("URL Error:", e)
    except Exception as e:
        print("General Error:", e)

if __name__ == "__main__":
    test_comfy()
