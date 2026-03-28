---
name: Universal Inference Router
description: Proxies generation requests to ComfyUI, SD WebUI Forge, Automatic1111, and Fooocus backends. Translates a unified payload into engine-native formats, routes img2img vs txt2img automatically, and streams results back to the dashboard.
---

# Universal Inference Router

## Purpose

Translate a single, engine-agnostic generation payload into the target backend's native API format, dispatch the request, and return the result to the frontend — all through one consistent interface.

## When to Use

```
IF the task involves:
  ├── Sending a txt2img or img2img generation request → USE THIS SKILL
  ├── Adding support for a new inference backend      → USE THIS SKILL
  ├── Modifying payload translation logic             → USE THIS SKILL
  ├── Fixing proxy connection errors to engines       → USE THIS SKILL
  └── Anything else                                   → DO NOT USE THIS SKILL
```

## Architecture

```
Frontend (index.html)
    │
    ▼
POST /api/comfy_proxy   ──→ ComfyUI    (localhost:8188)
POST /api/a1111_proxy   ──→ A1111      (localhost:7860)
POST /api/fooocus_proxy ──→ Fooocus    (localhost:8888)
POST /api/forge_proxy   ──→ Forge      (localhost:7861)
    │
    ▼ (Sprint 9: Batch Queue)
POST /api/generate/batch ──→ In-memory queue → sequential dispatch
GET  /api/generate/queue ──→ Queue status polling
```

## Input Contract

All proxy endpoints accept a JSON body with:

```json
{
  "endpoint": "/api/prompt",
  "payload": {
    "prompt": "...",
    "negative_prompt": "...",
    "seed": 42,
    "steps": 20,
    "cfg_scale": 7.0,
    "width": 512,
    "height": 512,
    "sampler_name": "euler",
    "model": "v1-5-pruned.safetensors",
    "loras": [{"name": "detail_tweaker", "weight": 0.8}],
    "controlnet": null,
    "init_image": null,
    "denoising_strength": null
  }
}
```

## Output Contract

```json
{
  "status": "success",
  "images": ["base64_encoded_png_or_url"],
  "seed": 42,
  "info": { ... }
}
```

On failure:
```json
{
  "error": "Connection refused: ComfyUI is not running on localhost:8188"
}
```

## Payload Translation Rules

### ComfyUI
- Convert flat parameters into a ComfyUI workflow JSON graph (`build_comfy_workflow` in `proxy_translators.py`)
- **SD1.5 / SDXL Block**:
  - LoRAs become `LoraLoader` nodes chained between `CheckpointLoaderSimple` and `KSampler`.
  - ControlNet uses `ControlNetApplyAdvanced` node with image input.
  - Img2Img sets `denoise` on `KSampler` and adds `LoadImage` / `VAEEncode` nodes.
- **FLUX Block**:
  - Instantiates specific `UNETLoader`, `DualCLIPLoader` (t5xxl + clip_l), and `VAELoader`.
  - Routes text conditioning through explicit `FluxGuidance` nodes based on `flux_guidance` parameter.
  - Fully supports Multi-LoRA stacking, Img2Img pipelines, ControlNet constraints, and High-Res Fix (Refiner mode via `LatentUpscaleBy`) natively integrated into the FLUX execution graph.
- **Important**: ComfyUI strictly validates nodes (Checkpoints, VAEs). If a missing `.safetensors` model is passed, it halts graph execution with an error format like `Failed to validate prompt`. Always ensure exact matching between frontend parameters (`override_settings`) and `proxy_translators.py`.

### Automatic1111 / SD WebUI
- Maps directly to `/sdapi/v1/txt2img` or `/sdapi/v1/img2img`
- LoRAs are injected as `<lora:name:weight>` in the positive prompt string
- ControlNet uses the ControlNet extension API

### Fooocus
- Maps to `/v1/generation/text-to-image`
- Limited parameter support; prompt + negative + style only

## Key Implementation Files

| File | Role |
|------|------|
| `.backend/server.py` → `handle_comfy_proxy()` | ComfyUI dispatch |
| `.backend/server.py` → `handle_a1111_proxy()` | A1111 dispatch |
| `.backend/server.py` → `handle_fooocus_proxy()` | Fooocus dispatch |
| `.backend/server.py` → `handle_forge_proxy()` | Forge dispatch |
| `.backend/server.py` → `handle_batch_generate()` | Batch queue submission (Sprint 9) |
| `.backend/server.py` → `handle_batch_queue_status()` | Batch queue polling (Sprint 9) |
| `.backend/server.py` → `_batch_worker()` | Background sequential dispatcher (Sprint 9) |
| `.backend/server.py` → `handle_comfy_image()` | Image byte proxy for ComfyUI |
| `.backend/server.py` → `handle_comfy_upload()` | Multipart upload proxy for img2img |
| `.backend/static/index.html` | Frontend inference studio UI |

## Example Usage

```python
# Adding a new backend (e.g., Forge)
def handle_forge_proxy(self, data):
    payload = data.get("payload")
    endpoint = data.get("endpoint", "/sdapi/v1/txt2img")
    import urllib.request
    url = f"http://127.0.0.1:7861{endpoint}"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as res:
            content = res.read().decode('utf-8')
            self.send_json_response(json.loads(content))
    except Exception as e:
        self.send_json_response({"error": str(e)}, 500)
```

## Safety Checklist

- [ ] Never forward raw user strings into shell commands
- [ ] Always wrap `urllib.request.urlopen` in try/except
- [ ] Validate endpoint parameter does not contain `..` or absolute paths
- [ ] Log proxy failures with full URL and status code for debugging
- [ ] Timeout all outbound requests (10s default)
