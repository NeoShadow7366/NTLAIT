import urllib.request, json
import time

payload = {
    'endpoint': '/api/prompt',
    'payload': {
        'prompt': 'Rainbow lady',
        'negative_prompt': '',
        'seed': 42,
        'steps': 20,
        'cfg_scale': 1.0,
        'width': 1024,
        'height': 1024,
        'sampler_name': 'euler',
        'scheduler': 'simple',
        'model_type': 'flux-schnell',
        'override_settings': {'sd_model_checkpoint': 'flux1-schnell-fp8.safetensors'},
        'flux_clip_l': 'clip_l.safetensors',
        'flux_t5xxl': 't5xxl_fp8_e4m3fn.safetensors',
        'vae': 'ae.safetensors',
        'loras': [
            {'name': 'flux_realism_lora.safetensors', 'weight': 0.8},
            {'name': 'flux_detailer_lora.safetensors', 'weight': 0.5}
        ],
        'hires': {
            'enable': True,
            'factor': 1.5,
            'denoise': 0.4,
            'steps': 10,
            'upscaler': 'latent'
        },
        'controlnet': {
            'enable': True,
            'model': 'flux-canny-controlnet-v3.safetensors',
            'strength': 0.8,
            'image': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
        }
    }
}

print("Sleeping 3 seconds for server to boot...")
time.sleep(3)

req = urllib.request.Request('http://localhost:8080/api/comfy_proxy', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        print('Status:', response.status)
        print('Response:', response.read().decode())
except Exception as e:
    print('Error:', e)
    if hasattr(e, 'read'):
        print('Body:', e.read().decode())
