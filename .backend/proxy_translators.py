import random

def get_hires_upscaler_params(name):
    if 'latent' in name.lower():
        method = 'bilinear' if 'bilinear' in name.lower() else ('bicubic' if 'bicubic' in name.lower() else 'nearest-exact')
        return {"type": "latent", "method": method}
    return {"type": "pixel", "method": name}

def build_comfy_workflow(payload: dict) -> dict:
    """
    Maps engine-agnostic generator payload to a ComfyUI execution graph.
    """
    prompt = payload.get("prompt", "")
    negative = payload.get("negative_prompt", "")
    seed = int(payload.get("seed", -1))
    if seed == -1:
        seed = random.randint(1, 999999999999999)
    
    steps = int(payload.get("steps", 20))
    cfg = float(payload.get("cfg_scale", 7.0))
    width = int(payload.get("width", 1024))
    height = int(payload.get("height", 1024))
    sampler = payload.get("sampler_name", "euler")
    scheduler = payload.get("scheduler", "normal")
    ckpt_name = payload.get("override_settings", {}).get("sd_model_checkpoint", "")
    vae_name = payload.get("vae", "none")
    
    # Extension params
    loras = payload.get("loras", [])
    hires = payload.get("hires", {})
    init_image = payload.get("init_image_name", "")  # Uses uploaded filename
    denoise = float(payload.get("denoising_strength", 1.0))
    controlnet = payload.get("controlnet", {})
    refiner_name = payload.get("refiner", "none")
    refiner_steps = int(payload.get("refiner_steps", 10))
    
    # Model Type
    model_type = payload.get("model_type", "sdxl")
    
    workflow = {}
    
    # ==========================
    # FLUX PIPELINE
    # ==========================
    if model_type in ["flux-dev", "flux-schnell"]:
        unet_name = ckpt_name  # Flux UI drop uses the main ckpt dropdown for Unet
        clip_name = payload.get("flux_clip_l", "")
        t5_name = payload.get("flux_t5xxl", "")
        flux_guidance = float(payload.get("flux_guidance", 3.5))
        
        if not unet_name:
            raise ValueError("FLUX requires a UNET model.")
            
        workflow["11"] = {"inputs": {"unet_name": unet_name, "weight_dtype": "default"}, "class_type": "UNETLoader"}
        workflow["12"] = {"inputs": {"clip_name1": t5_name, "clip_name2": clip_name, "type": "flux"}, "class_type": "DualCLIPLoader"}
        workflow["13"] = {"inputs": {"vae_name": vae_name if vae_name != "none" else "ae.safetensors"}, "class_type": "VAELoader"}
        workflow["14"] = {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyLatentImage"}
        
        # Text Encode
        workflow["15"] = {"inputs": {"text": prompt, "clip": ["12", 0]}, "class_type": "CLIPTextEncode"}
        workflow["16"] = {"inputs": {"text": negative, "clip": ["12", 0]}, "class_type": "CLIPTextEncode"}
        
        model_source = ["11", 0]
        
        # LoRAs
        lora_idx = 110
        for l in loras:
            workflow[str(lora_idx)] = {
                "inputs": {
                    "lora_name": l["name"], 
                    "strength_model": l["weight"], 
                    "strength_clip": l["weight"], 
                    "model": model_source, 
                    "clip": ["12", 0]
                },
                "class_type": "LoraLoader"
            }
            model_source = [str(lora_idx), 0]
            lora_idx += 1
        
        workflow["17"] = {"inputs": {"guidance": flux_guidance, "conditioning": ["15", 0]}, "class_type": "FluxGuidance"}
        
        workflow["18"] = {
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler, "denoise": denoise,
                "model": model_source,
                "positive": ["17", 0],
                "negative": ["16", 0],
                "latent_image": ["14", 0]
            },
            "class_type": "KSampler"
        }
        
        workflow["19"] = {"inputs": {"samples": ["18", 0], "vae": ["13", 0]}, "class_type": "VAEDecode"}
        workflow["20"] = {"inputs": {"filename_prefix": "AIManager_Flux", "images": ["19", 0]}, "class_type": "SaveImage"}
        return {"prompt": workflow}

    # ==========================
    # SD1.5 / SDXL PIPELINE
    # ==========================
    if not ckpt_name:
        raise ValueError("Checkpoint model required.")
        
    workflow["4"] = {"inputs": {"ckpt_name": ckpt_name}, "class_type": "CheckpointLoaderSimple"}
    workflow["5"] = {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyLatentImage"}
    
    current_model_source = ["4", 0]
    current_clip_source = ["4", 1]
    current_vae_source = ["4", 2]
    
    if vae_name and vae_name != "none":
        workflow["100"] = {"inputs": {"vae_name": vae_name}, "class_type": "VAELoader"}
        current_vae_source = ["100", 0]
        
    # LoRAs
    lora_idx = 110
    for l in loras:
        workflow[str(lora_idx)] = {
            "inputs": {
                "lora_name": l.get("name"),
                "strength_model": l.get("weight", 1.0),
                "strength_clip": l.get("weight", 1.0),
                "model": current_model_source,
                "clip": current_clip_source
            },
            "class_type": "LoraLoader"
        }
        current_model_source = [str(lora_idx), 0]
        current_clip_source = [str(lora_idx), 1]
        lora_idx += 1
        
    workflow["6"] = {"inputs": {"text": prompt, "clip": current_clip_source}, "class_type": "CLIPTextEncode"}
    workflow["7"] = {"inputs": {"text": negative, "clip": current_clip_source}, "class_type": "CLIPTextEncode"}
    
    pos_cond = ["6", 0]
    neg_cond = ["7", 0]
    final_latent_source = ["5", 0]
    
    # Img2Img
    if init_image:
        workflow["1001"] = {"inputs": {"image": init_image}, "class_type": "LoadImage"}
        workflow["1002"] = {"inputs": {"pixels": ["1001", 0], "vae": current_vae_source}, "class_type": "VAEEncode"}
        final_latent_source = ["1002", 0]
        
    # ControlNet
    if controlnet and controlnet.get("enable") and controlnet.get("image"):
        cn_model = controlnet.get("model")
        cn_strength = controlnet.get("strength", 1.0)
        cn_img = controlnet.get("image")
        
        workflow["1003"] = {"inputs": {"control_net_name": cn_model}, "class_type": "ControlNetLoader"}
        workflow["1004"] = {"inputs": {"image": cn_img}, "class_type": "LoadImage"}
        workflow["1005"] = {
            "inputs": {
                "strength": cn_strength,
                "positive": pos_cond,
                "negative": neg_cond,
                "control_net": ["1003", 0],
                "image": ["1004", 0]
            },
            "class_type": "ControlNetApplyAdvanced"
        }
        pos_cond = ["1005", 0]
        neg_cond = ["1005", 1]
        
    # Base Sampler / Refiner
    use_refiner = (refiner_name and refiner_name != "none")
    
    if use_refiner:
        workflow["3"] = {
            "inputs": {
                "add_noise": "enable", "noise_seed": seed, "steps": steps + refiner_steps, "cfg": cfg,
                "sampler_name": sampler, "scheduler": scheduler, "start_at_step": 0, "end_at_step": steps,
                "return_with_leftover_noise": "enable", "model": current_model_source,
                "positive": pos_cond, "negative": neg_cond, "latent_image": final_latent_source
            },
            "class_type": "KSamplerAdvanced"
        }
        workflow["202"] = {"inputs": {"ckpt_name": refiner_name}, "class_type": "CheckpointLoaderSimple"}
        workflow["203"] = {"inputs": {"text": prompt, "clip": ["202", 1]}, "class_type": "CLIPTextEncode"}
        workflow["204"] = {"inputs": {"text": negative, "clip": ["202", 1]}, "class_type": "CLIPTextEncode"}
        workflow["205"] = {
            "inputs": {
                "add_noise": "disable", "noise_seed": seed, "steps": steps + refiner_steps, "cfg": cfg,
                "sampler_name": sampler, "scheduler": scheduler, "start_at_step": steps, "end_at_step": 10000,
                "return_with_leftover_noise": "disable", "model": ["202", 0],
                "positive": ["203", 0], "negative": ["204", 0], "latent_image": ["3", 0]
            },
            "class_type": "KSamplerAdvanced"
        }
        final_latent_source = ["205", 0]
    else:
        workflow["3"] = {
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                "denoise": denoise, "model": current_model_source,
                "positive": pos_cond, "negative": neg_cond, "latent_image": final_latent_source
            },
            "class_type": "KSampler"
        }
        final_latent_source = ["3", 0]
        
    # High-Res Fix
    if hires and hires.get("enable"):
        h_factor = hires.get("factor", 1.5)
        h_denoise = hires.get("denoise", 0.4)
        h_steps = hires.get("steps", 10)
        h_upscaler = hires.get("upscaler", "latent")
        
        up_params = get_hires_upscaler_params(h_upscaler)
        upscaled_latent_source = ["300", 0]
        
        if up_params["type"] == "latent":
            workflow["300"] = {
                "inputs": {"upscale_method": up_params["method"], "scale_by": h_factor, "samples": final_latent_source},
                "class_type": "LatentUpscaleBy"
            }
            upscaled_latent_source = ["300", 0]
        else:
            workflow["301"] = {"inputs": {"samples": final_latent_source, "vae": current_vae_source}, "class_type": "VAEDecode"}
            workflow["302"] = {
                "inputs": {"upscale_method": "bicubic", "scale_by": h_factor, "image": ["301", 0]},
                "class_type": "ImageScaleBy"
            }
            workflow["303"] = {"inputs": {"pixels": ["302", 0], "vae": current_vae_source}, "class_type": "VAEEncode"}
            upscaled_latent_source = ["303", 0]
            
        workflow["305"] = {
            "inputs": {
                "seed": seed + 1, "steps": h_steps, "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                "denoise": h_denoise, "model": current_model_source,
                "positive": pos_cond, "negative": neg_cond, "latent_image": upscaled_latent_source
            },
            "class_type": "KSampler"
        }
        final_latent_source = ["305", 0]
        
    # Output Decode
    workflow["8"] = {"inputs": {"samples": final_latent_source, "vae": current_vae_source}, "class_type": "VAEDecode"}
    workflow["9"] = {"inputs": {"filename_prefix": "AIManager", "images": ["8", 0]}, "class_type": "SaveImage"}
    
    return {"prompt": workflow}

def build_a1111_payload(payload: dict) -> dict:
    """
    Maps engine-agnostic generator payload to SDAPI (A1111 / Forge) format.
    """
    sampler = payload.get("sampler_name", "euler")
    sampler_map = {
        'euler_ancestral': 'Euler a', 'euler': 'Euler',
        'dpmpp_2m': 'DPM++ 2M', 'dpmpp_2m_sde': 'DPM++ 2M SDE',
        'dpmpp_sde': 'DPM++ SDE', 'karras': 'Euler a'
    }
    mapped_sampler = sampler_map.get(sampler.lower(), 'Euler a')
    
    # Inject LoRAs into prompt string
    final_prompt = payload.get("prompt", "")
    loras = payload.get("loras", [])
    for lora in loras:
        name = lora.get("name")
        if name and name.endswith(".safetensors"):
            name = name[:-12]  # strip extension for A1111
        final_prompt += f" <lora:{name}:{lora.get('weight', 1.0)}>"
        
    result = {
        "prompt": final_prompt,
        "negative_prompt": payload.get("negative_prompt", ""),
        "steps": int(payload.get("steps", 20)),
        "cfg_scale": float(payload.get("cfg_scale", 7.0)),
        "width": int(payload.get("width", 1024)),
        "height": int(payload.get("height", 1024)),
        "seed": int(payload.get("seed", -1)),
        "sampler_name": mapped_sampler,
        "override_settings": {}
    }
    
    ckpt_name = payload.get("override_settings", {}).get("sd_model_checkpoint", "")
    if ckpt_name:
        result["override_settings"]["sd_model_checkpoint"] = ckpt_name
        
    # Img2Img
    b64_image = payload.get("init_image_b64")
    if b64_image:
        result["init_images"] = [b64_image]
        result["denoising_strength"] = float(payload.get("denoising_strength", 0.5))
        
    # High-Res Fix
    hires = payload.get("hires", {})
    if hires and hires.get("enable") and not b64_image:
        result["enable_hr"] = True
        result["hr_scale"] = float(hires.get("factor", 1.5))
        up_raw = hires.get("upscaler", "Latent")
        result["hr_upscaler"] = "Latent" if "latent" in up_raw.lower() else up_raw
        result["hr_second_pass_steps"] = int(hires.get("steps", 10))
        result["denoising_strength"] = float(hires.get("denoise", 0.4))
        
    # ControlNet
    controlnet = payload.get("controlnet", {})
    if controlnet and controlnet.get("enable") and controlnet.get("image_b64"):
        cn_model = controlnet.get("model")
        # Strip .safetensors if passed
        if cn_model and cn_model.endswith(".safetensors"):
            cn_model = cn_model[:-12]
            
        result["alwayson_scripts"] = {
            "controlnet": {
                "args": [
                    {
                        "input_image": controlnet.get("image_b64"),
                        "module": "none",
                        "model": cn_model,
                        "weight": float(controlnet.get("strength", 1.0)),
                        "resize_mode": 1
                    }
                ]
            }
        }
        
    return result

def build_fooocus_payload(payload: dict) -> dict:
    return {
        "prompt": payload.get("prompt", ""),
        "negative_prompt": payload.get("negative_prompt", ""),
        "style_selections": ["Fooocus V2", "Fooocus Enhance", "Fooocus Sharp"],
        "performance_selection": "Quality",
        "aspect_ratios_selection": f"{payload.get('width', 1024)}*{payload.get('height', 1024)}"
    }
