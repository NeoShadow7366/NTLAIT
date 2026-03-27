import pytest
import sys
import os

# Allow import of backend module
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(os.path.dirname(current_dir), ".backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from proxy_translators import build_comfy_workflow, build_a1111_payload, build_fooocus_payload

def test_a1111_sampler_translation():
    """Assert SD WebUI sampler mapping mathematically translates."""
    payload = {
        "sampler_name": "dpmpp_2m_sde",
        "prompt": "Test Prompt",
        "steps": 20
    }
    result = build_a1111_payload(payload)
    assert result["sampler_name"] == "DPM++ 2M SDE"

def test_a1111_lora_string_concatenation():
    """Assert SD WebUI concatenates loras securely without .safetensors."""
    payload = {
        "prompt": "Test Prompt",
        "loras": [
            {"name": "my_lora.safetensors", "weight": 0.8},
            {"name": "second_lora", "weight": 1.2}
        ]
    }
    result = build_a1111_payload(payload)
    # The lora extensions should be stripped and formatted <lora:name:weight>
    assert "<lora:my_lora:0.8>" in result["prompt"]
    assert "<lora:second_lora:1.2>" in result["prompt"]

def test_a1111_img2img_hires():
    """Assert SD WebUI resolves Img2Img and Hires cleanly."""
    payload = {
        "prompt": "Img",
        "init_image_b64": "data:image/png;base64,mock",
        "denoising_strength": 0.7,
        "hires": {"enable": True, "factor": 1.5, "upscaler": "Latent"}
    }
    result = build_a1111_payload(payload)
    # If init_image is passed, enable_hr MUST be false (A1111 limitation)
    assert "init_images" in result
    assert result["init_images"] == ["data:image/png;base64,mock"]
    assert "enable_hr" not in result

def test_comfy_flux_graph():
    """Assert FLUX builds unique node graphs (UNETLoader / DualCLIP)."""
    payload = {
        "prompt": "FLUX test",
        "model_type": "flux-dev",
        "override_settings": {"sd_model_checkpoint": "flux1-dev.safetensors"},
        "flux_clip_l": "clip_l.safetensors",
        "flux_t5xxl": "t5_xxl.safetensors"
    }
    workflow = build_comfy_workflow(payload)
    graph = workflow.get("prompt", {})
    
    assert "11" in graph
    assert graph["11"]["class_type"] == "UNETLoader"
    assert graph["11"]["inputs"]["unet_name"] == "flux1-dev.safetensors"
    
    assert "12" in graph
    assert graph["12"]["class_type"] == "DualCLIPLoader"
    assert graph["12"]["inputs"]["clip_name1"] == "t5_xxl.safetensors"
    assert graph["12"]["inputs"]["clip_name2"] == "clip_l.safetensors"

def test_comfy_sdxl_graph():
    """Assert SDXL builds CheckpointLoader templates with standard inputs."""
    payload = {
        "prompt": "SDXL test",
        "model_type": "sdxl",
        "override_settings": {"sd_model_checkpoint": "sdxl_base.safetensors"}
    }
    workflow = build_comfy_workflow(payload)
    graph = workflow.get("prompt", {})
    
    assert "4" in graph
    assert graph["4"]["class_type"] == "CheckpointLoaderSimple"
    assert graph["4"]["inputs"]["ckpt_name"] == "sdxl_base.safetensors"
    
    # Assert missing UNETLoader, proving SDXL branch executed
    assert "11" not in graph

def test_comfy_refiner_injection():
    """Assert SDXL utilizes secondary KSampler and Checkpoint for refiners."""
    payload = {
        "prompt": "Refiner Test",
        "model_type": "sdxl",
        "override_settings": {"sd_model_checkpoint": "sdxl_base.safetensors"},
        "refiner": "sdxl_refiner.safetensors",
        "steps": 20,
        "refiner_steps": 10
    }
    workflow = build_comfy_workflow(payload)
    graph = workflow.get("prompt", {})
    
    # Base sampler
    assert "3" in graph
    assert graph["3"]["class_type"] == "KSamplerAdvanced"
    
    # Refiner checkpoint
    assert "202" in graph
    assert graph["202"]["class_type"] == "CheckpointLoaderSimple"
    assert graph["202"]["inputs"]["ckpt_name"] == "sdxl_refiner.safetensors"

def test_fooocus_mapping():
    """Assert Fooocus payload map operates correctly."""
    result = build_fooocus_payload({"prompt": "Fooocus", "width": 1024, "height": 1024})
    assert result["prompt"] == "Fooocus"
    assert result["aspect_ratios_selection"] == "1024*1024"
