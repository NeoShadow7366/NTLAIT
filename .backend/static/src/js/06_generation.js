        /* ═══ IS-01/IS-05: Unified Generation Payload Builder ═══
           Single source of truth for both executeInference() and getInferencePayload().
           Returns a payload compatible with build_comfy_workflow() field names. */
        function buildGenerationPayload() {
            const engine = document.getElementById('inf-engine')?.value || 'comfyui';
            const modelType = document.getElementById('inf-model-type')?.value || 'sdxl';

            const payload = {
                engine: engine,
                backend: engine,  // Alias for batch queue's _batch_worker
                model_type: modelType,
                prompt: document.getElementById('inf-prompt')?.value || '',
                negative_prompt: document.getElementById('inf-negative')?.value || '',
                seed: parseInt(document.getElementById('inf-seed')?.value || '-1'),
                steps: parseInt(document.getElementById('inf-steps')?.value || '20'),
                cfg_scale: parseFloat(document.getElementById('inf-cfg')?.value || '7'),
                width: parseInt(document.getElementById('inf-width')?.value || '1024'),
                height: parseInt(document.getElementById('inf-height')?.value || '1024'),
                sampler_name: document.getElementById('inf-sampler')?.value || 'euler',
                scheduler: document.getElementById('inf-scheduler')?.value || 'normal',
                override_settings: {
                    sd_model_checkpoint: document.getElementById('inf-model')?.value || ''
                },
                vae: document.getElementById('inf-vae')?.value || 'none',
                refiner: document.getElementById('inf-refiner')?.value || 'none',
                refiner_steps: parseInt(document.getElementById('inf-refiner-steps')?.value || '10')
            };

            // FLUX parameters
            if (modelType.includes('flux')) {
                payload.flux_unet = document.getElementById('inf-flux-unet')?.value || '';
                payload.flux_clip_l = document.getElementById('inf-flux-clip-l')?.value || '';
                payload.flux_t5xxl = document.getElementById('inf-flux-t5xxl')?.value || '';
                payload.flux_guidance = parseFloat(document.getElementById('inf-flux-guidance')?.value || '3.5');
            }

            // LoRAs
            payload.loras = [];
            document.querySelectorAll('#inf-lora-container > div').forEach(row => {
                const sel = row.querySelector('.lora-select');
                const wgt = row.querySelector('.lora-weight');
                if (sel && wgt && sel.value && sel.value !== 'none') {
                    payload.loras.push({ name: sel.value, weight: parseFloat(wgt.value) });
                }
            });

            // Img2Img
            if (window.comfyUploadedImg2Img) {
                payload.init_image_name = window.comfyUploadedImg2Img;
                payload.init_image_b64 = window.comfyUploadedImg2ImgB64;
                payload.denoising_strength = parseFloat(document.getElementById('inf-img2img-denoise')?.value || '0.75');
            }

            // Hires Fix
            const doHires = document.getElementById('inf-hires-enable')?.checked;
            if (doHires && !payload.init_image_name) {
                payload.hires = {
                    enable: true,
                    factor: parseFloat(document.getElementById('inf-hires-factor')?.value || '1.5'),
                    denoise: parseFloat(document.getElementById('inf-hires-denoise')?.value || '0.4'),
                    steps: parseInt(document.getElementById('inf-hires-steps')?.value || '10'),
                    upscaler: document.getElementById('inf-hires-upscaler')?.value || 'latent'
                };
            }

            // ControlNet
            const cnEnable = document.getElementById('inf-cn-enable')?.checked;
            if (cnEnable && window.comfyUploadedCn) {
                payload.controlnet = {
                    enable: true,
                    model: document.getElementById('inf-cn-model')?.value || '',
                    strength: parseFloat(document.getElementById('inf-cn-strength')?.value || '1.0'),
                    image: window.comfyUploadedCn,
                    image_b64: window.comfyUploadedCnB64
                };
            }

            // IS-01: Inpainting mask (was missing from executeInference)
            if (typeof hasInpaintMask === 'function' && hasInpaintMask()) {
                payload.mask_b64 = getInpaintMaskBase64();
                const canvasImg = document.getElementById('inf-canvas-img');
                if (canvasImg && canvasImg.src && canvasImg.style.display !== 'none' && !payload.init_image_b64) {
                    const tmpCanvas = document.createElement('canvas');
                    tmpCanvas.width = canvasImg.naturalWidth;
                    tmpCanvas.height = canvasImg.naturalHeight;
                    tmpCanvas.getContext('2d').drawImage(canvasImg, 0, 0);
                    payload.init_image_b64 = tmpCanvas.toDataURL('image/png').split(',')[1];
                }
            }

            // IS-01: Regional prompting (was missing from executeInference)
            if (typeof getRegionData === 'function') {
                const regionData = getRegionData();
                if (regionData) payload.regions = regionData;
            }

            return payload;
        }

        async function initInferenceUI() {
            // Check selected engine server status
            const engine = document.getElementById('inf-engine')?.value || 'comfyui';
            
            // Apply engine-specific UI visibility on load
            applyEngineVisibility(engine);
            
            const probes = {
                comfyui: { proxy: '/api/comfy_proxy', body: {endpoint: '/system_stats'} },
                a1111:   { proxy: '/api/a1111_proxy',  body: {endpoint: '/sdapi/v1/options'} },
                forge:   { proxy: '/api/forge_proxy',  body: {endpoint: '/sdapi/v1/options'} },
                fooocus: { proxy: '/api/fooocus_proxy', body: {endpoint: '/'} }
            };
            const probe = probes[engine] || probes['comfyui'];
            try {
                const res = await fetch(probe.proxy, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(probe.body) });
                if(!res.ok) throw new Error("Offline");
                document.getElementById('inf-launch-btn').innerText = "Backend Connected 🟢";
                document.getElementById('inf-launch-btn').style.color = "#4ade80";
                window.engineLaunching = false;
            } catch(e) {
                document.getElementById('inf-launch-btn').innerText = "Launch Engine";
                document.getElementById('inf-launch-btn').style.color = "#cbd5e1";
                
                // I-3 fix: Persistent guard prevents re-launch on tab switching.
                // _engineAutoLaunched tracks per-engine so switching engines still auto-launches the new one.
                if(!window._engineAutoLaunched) window._engineAutoLaunched = {};
                if(!window.engineLaunching && !window._engineAutoLaunched[engine]) {
                    window._engineAutoLaunched[engine] = true;
                    launchActiveEngine();
                }
            }
            
            // Populate Models natively from vault
            fetch('/api/models?limit=5000').then(r => r.json()).then(data => {
                if(!data.models) return;
                
                const ddw = document.getElementById('inf-model');
                const lastVal = ddw.value;
                ddw.innerHTML = '';
                
                const ref = document.getElementById('inf-refiner');
                const lastRef = ref.value;
                ref.innerHTML = '<option value="none">None</option>';
                
                const vae = document.getElementById('inf-vae');
                const lastVae = vae.value;
                vae.innerHTML = '<option value="none">Baked VAE</option>';

                window.availableLoras = data.models.filter(m => m.vault_category === 'loras');
                
                data.models.filter(m => m.vault_category === 'checkpoints').forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.filename;
                    opt.innerText = (m.metadata?.model?.name ? (m.metadata.model.name + " (" + m.filename + ")") : m.filename);
                    ddw.appendChild(opt);
                    
                    const optRef = opt.cloneNode(true);
                    ref.appendChild(optRef);
                });
                
                data.models.filter(m => m.vault_category === 'vaes').forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.filename;
                    opt.innerText = (m.metadata?.model?.name ? (m.metadata.model.name + " (" + m.filename + ")") : m.filename);
                    vae.appendChild(opt);
                });
                
                const cnd = document.getElementById('inf-cn-model');
                cnd.innerHTML = '<option value="">Select ControlNet Model...</option>';
                data.models.filter(m => m.vault_category === 'controlnet').forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.filename;
                    opt.innerText = (m.metadata?.model?.name ? (m.metadata.model.name + " (" + m.filename + ")") : m.filename);
                    cnd.appendChild(opt);
                });

                if(lastVal) ddw.value = lastVal;
                if(lastRef) ref.value = lastRef;
                if(lastVae) vae.value = lastVae;

                // Also populate FLUX UNET dropdown from /unet category
                const unetSel = document.getElementById('inf-flux-unet');
                const prevUnet = unetSel.value;
                unetSel.innerHTML = '<option value="">Select FLUX UNET...</option>';
                data.models.filter(m => m.vault_category === 'unet').forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.filename; opt.innerText = m.filename;
                    unetSel.appendChild(opt);
                });
                if(prevUnet) unetSel.value = prevUnet;

                // Populate CLIP-L and T5-XXL from /clip category
                const clipL = document.getElementById('inf-flux-clip-l');
                const t5sel = document.getElementById('inf-flux-t5xxl');
                const prevClipL = clipL.value;
                const prevT5    = t5sel.value;
                clipL.innerHTML = '<option value="">Select CLIP-L...</option>';
                t5sel.innerHTML  = '<option value="">Select T5-XXL...</option>';
                // Accept files from both 'clip' and 'text_encoders' vault categories
                const encoderModels = data.models.filter(m => m.vault_category === 'clip' || m.vault_category === 'text_encoders');
                encoderModels.forEach(m => {
                    const f = m.filename.toLowerCase();
                    const label = m.metadata?.model?.name ? `${m.metadata.model.name} (${m.filename})` : m.filename;
                    const isClip = f.includes('clip') && !f.includes('t5');
                    const isT5 = f.includes('t5');
                    
                    // BUG-10 fix: Only add CLIP models to CLIP dropdown and T5 models to T5 dropdown
                    if(isClip || (!isClip && !isT5)) {
                        const optC = new Option(label, m.filename);
                        clipL.appendChild(optC);
                    }
                    if(isT5 || (!isClip && !isT5)) {
                        const optT = new Option(label, m.filename);
                        t5sel.appendChild(optT);
                    }
                    // Auto-preselect by common naming conventions
                    if((f.includes('clip_l') || f.includes('clip-l')) && !f.includes('t5')) clipL.value = m.filename;
                    if(f.includes('t5') || f.includes('t5xxl') || f.includes('t5-xxl')) t5sel.value = m.filename;
                });
                if(prevClipL) clipL.value = prevClipL;
                if(prevT5)    t5sel.value = prevT5;
            });
        }

        /* --- Download Status Management --- */
        let dlPollInterval = null;

        function toggleDownloadPopup() {
            const el = document.getElementById('dl-status-modal');
            const isVisible = el.style.display === 'flex';
            el.style.display = isVisible ? 'none' : 'flex';
            if(!isVisible) updateDownloadStatus();
        }

        async function updateDownloadStatus() {
            try {
                const res = await fetch('/api/downloads');
                const data = await res.json();
                
                const list = document.getElementById('dl-status-list');
                const badge = document.getElementById('ex-dl-badge');
                
                const entries = Object.entries(data);
                if(entries.length === 0) {
                    list.innerHTML = '<div style="color: var(--text-muted); text-align: center; margin-top: 40px;">No downloads in history</div>';
                    badge.style.display = 'none';
                    return;
                }

                let html = '';
                let activeCount = 0;
                
                // Sort entries: active first, then by name
                entries.sort((a,b) => {
                    const aActive = (a[1].status === 'starting' || a[1].status === 'downloading');
                    const bActive = (b[1].status === 'starting' || b[1].status === 'downloading');
                    if(aActive && !bActive) return -1;
                    if(!aActive && bActive) return 1;
                    return (a[1].model_name || "").localeCompare(b[1].model_name || "");
                });

                entries.forEach(([id, job]) => {
                    const isActive = (job.status === 'starting' || job.status === 'downloading');
                    if(isActive) activeCount++;
                    
                    let statusColor = '#94a3b8';
                    if(job.status === 'completed') statusColor = '#4ade80';
                    if(job.status === 'error') statusColor = '#f87171';
                    if(isActive) statusColor = '#3b82f6';

                    const retryBtn = job.status === 'error' ? `<button onclick="retryDownload('${id}')" style="background:var(--primary); border:none; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.7rem; cursor:pointer; margin-left:10px; font-weight:bold;">RETRY</button>` : '';

                    html += `
                        <div class="dl-status-item">
                            <div class="dl-status-header">
                                <strong style="color: #fff;">${job.model_name || job.filename || 'Unknown Model'}</strong>
                                <span style="color: ${statusColor}; font-size: 0.8rem; font-weight: 600;">${(job.status || 'unknown').toUpperCase()}${retryBtn}</span>
                            </div>
                            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${job.filename || ''}</div>
                            ${isActive ? `
                                <div class="dl-status-progress">
                                    <div class="dl-status-bar" style="width: ${job.progress || 0}%"></div>
                                </div>
                                <div style="display: flex; justify-content: space-between; font-size: 0.7rem; color: var(--text-muted);">
                                    <span>${job.progress || 0}%</span>
                                    <span>${((job.downloaded || 0) / (1024*1024)).toFixed(1)} / ${((job.total || 0) / (1024*1024)).toFixed(1)} MB</span>
                                </div>
                            ` : ''}
                            ${job.status === 'error' ? `<div style="color: #f87171; font-size: 0.75rem; margin-top: 4px;">${job.message || 'Unknown error'}</div>` : ''}
                        </div>
                    `;
                });

                list.innerHTML = html;
                
                if(activeCount > 0) {
                    badge.innerText = activeCount;
                    badge.style.display = 'block';
                    if(!dlPollInterval) dlPollInterval = setInterval(updateDownloadStatus, 2000);
                } else {
                    badge.style.display = 'none';
                    if(dlPollInterval) {
                        clearInterval(dlPollInterval);
                        dlPollInterval = null;
                        // R-13: Use setTimeout to break the recursive call stack
                        setTimeout(updateDownloadStatus, 500);
                    }
                }
            } catch(e) {
                console.error("Failed to poll downloads", e);
            }
        }

        async function clearDownloadHistory() {
            if(!confirm("Are you sure you want to clear your download history?")) return;
            try {
                const res = await fetch('/api/downloads/clear', { method: 'POST' });
                const data = await res.json();
                if(data.status === 'success') {
                    updateDownloadStatus();
                } else {
                    alert("Failed to clear: " + data.message);
                }
            } catch(e) {
                alert("Request failed");
            }
        }

        function toggleSettings() {
            // Navigate to the unified Settings tab instead of opening a modal
            switchTab('settings');
        }

        function saveExplorerApiKeys() {
            // Legacy compat: redirect to the main Settings tab save
            switchTab('settings');
        }

        async function retryDownload(jobId) {
            try {
                const res = await fetch('/api/download/retry', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        job_id: jobId,
                        api_key: localStorage.getItem('civitai_api_key') || ""
                    })
                });
                const data = await res.json();
                if(data.status === 'success') {
                    // Update UI quickly
                    updateDownloadStatus();
                } else {
                    alert("Retry failed: " + data.message);
                }
            } catch(e) { alert("Retry request failed"); }
        }

        // Initial poll on load
        setTimeout(updateDownloadStatus, 1000);

        async function launchActiveEngine() {
            if(window.engineLaunching) return; // Prevent duplicate launches
            window.engineLaunching = true;
            try {
                const engine = document.getElementById('inf-engine')?.value || 'comfyui';
                const appId = engine === 'a1111' ? 'auto1111' : engine;
                
                const btn = document.getElementById('inf-launch-btn');
                btn.innerText = "Starting...";
                btn.style.color = "#fbbf24";
                
                // S-1: Check launch response for port conflicts / errors before polling
                const launchRes = await fetch('/api/launch', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: appId})
                });
                const launchData = await launchRes.json().catch(() => ({}));

                if (!launchRes.ok || launchData.status === 'error') {
                    const msg = launchData.message || 'Failed to launch engine';
                    btn.innerText = launchData.port_conflict ? '\u26a0\ufe0f Port Conflict' : '\u274c Launch Failed';
                    btn.style.color = '#ef4444';
                    btn.onclick = launchActiveEngine;
                    window.engineLaunching = false;
                    showToast(`\ud83d\udeab ${msg}`);
                    return;
                }

                // S-6: Store port for WebSocket connection
                if (launchData.port && engine === 'comfyui') {
                    window._comfyPort = launchData.port;
                }
                
                let retries = 0;
                const proxyMap = {
                    comfyui: { proxy: '/api/comfy_proxy', body: {endpoint: '/system_stats'} },
                    a1111:   { proxy: '/api/a1111_proxy',  body: {endpoint: '/sdapi/v1/options'} },
                    forge:   { proxy: '/api/forge_proxy',  body: {endpoint: '/sdapi/v1/options'} },
                    fooocus: { proxy: '/api/fooocus_proxy', body: {endpoint: '/'} }
                };
                const probe = proxyMap[engine] || proxyMap['comfyui'];
                
                const poll = setInterval(async () => {
                    try {
                        const res = await fetch(probe.proxy, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(probe.body) });
                        if(res.ok) {
                            clearInterval(poll);
                            btn.innerText = "Engine Active";
                            btn.style.color = "#4ade80";
                            btn.onclick = launchActiveEngine;
                            window.engineLaunching = false;
                            initInferenceUI();
                            return;
                        }

                        const data = await res.json().catch(()=>({}));
                        if(data.error === "engine_crashed") {
                            clearInterval(poll);
                            window.engineLaunching = false;

                            // S-2: Handle expanded crash types from BUG-4
                            if (data.repair_available) {
                                // Missing module — offer repair button
                                btn.innerHTML = `Repair 🛠️ <span style="font-size:0.6rem">(${data.detail || 'Missing dependency'})</span>`;
                                btn.style.color = "#ef4444";
                                btn.onclick = async () => {
                                    btn.innerText = "Repairing...";
                                    btn.style.color = "#fbbf24";
                                    btn.onclick = launchActiveEngine;
                                    await fetch('/api/repair_dependency', {
                                        method: 'POST', 
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({package_id: appId})
                                    });
                                    setTimeout(() => { window.engineLaunching = false; launchActiveEngine(); }, 3000);
                                };
                            } else {
                                // Non-repairable crash (CUDA OOM, port-in-use, etc.)
                                const errorLabel = {
                                    cuda_oom: '💥 GPU Out of Memory',
                                    cuda_error: '💥 CUDA Error',
                                    port_in_use: '⚠️ Port Conflict',
                                    permission_error: '🔒 Permission Denied'
                                }[data.error_type] || '❌ Engine Crashed';
                                btn.innerText = `${errorLabel} — Click to Retry`;
                                btn.style.color = '#ef4444';
                                btn.onclick = launchActiveEngine;
                                showToast(`${errorLabel}: ${data.message || 'Check engine logs.'}`);
                            }
                            return;
                        }
                        
                        throw new Error("Not ready");
                    } catch(e) {
                        retries++;
                        // BUG-7 fix: Show retry progress with progressive messaging (180s ceiling)
                        if(retries > 30) {
                            btn.innerText = `Still starting... (${retries}s)`;
                        } else {
                            btn.innerText = `Connecting... (${retries}s)`;
                        }
                        if(retries > 180) {
                            clearInterval(poll);
                            btn.innerText = "Launch Timeout — Click to Retry";
                            btn.style.color = "#ef4444";
                            btn.onclick = launchActiveEngine;
                            window.engineLaunching = false;
                        }
                    }
                }, 1000);
            } catch(e) { 
                alert("Failed to launch Engine");
                window.engineLaunching = false; 
            }
        }

        /* IS-11: Active generation AbortController for cancel support */
        window._activeGenController = null;

        async function cancelInference() {
            // IS-11: Cancel in-flight generation + send ComfyUI /interrupt
            if (window._activeGenController) {
                window._activeGenController.abort();
                window._activeGenController = null;
            }
            // Clear all ComfyUI polling intervals
            if (window.comfyPollInterval) { clearInterval(window.comfyPollInterval); window.comfyPollInterval = null; }
            if (window.comfyProgressInterval) { clearInterval(window.comfyProgressInterval); window.comfyProgressInterval = null; }

            // Send /interrupt to ComfyUI to stop GPU work
            const engine = document.getElementById('inf-engine')?.value || 'comfyui';
            if (engine === 'comfyui') {
                try {
                    await fetch('/api/comfy_proxy', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({endpoint: '/interrupt', payload: {}})
                    });
                } catch(e) { console.debug('[Cancel] ComfyUI interrupt failed:', e); }
            }

            // Reset UI
            const btn = document.getElementById('inf-generate-btn');
            const txt = document.getElementById('inf-generate-text');
            const fill = document.getElementById('inf-progress-fill');
            if (btn) btn.disabled = false;
            if (txt) txt.innerText = 'Generate Image';
            if (fill) { fill.style.width = '0%'; fill.classList.remove('progress-pulsing'); }
            // Hide cancel, show generate
            const cancelBtn = document.getElementById('inf-cancel-btn');
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (btn) btn.style.display = '';
            // Hide progress bar
            const bar = document.getElementById('gen-progress-bar');
            const info = document.getElementById('gen-progress-info');
            if (bar) bar.classList.remove('active');
            if (info) { info.classList.remove('active'); info.textContent = ''; }
            document.getElementById('inf-canvas-empty').innerText = 'Generation cancelled.';
            showToast('🛑 Generation cancelled.');
        }

        async function executeInference() {
            // IS-01/IS-05: Use unified payload builder
            const payload = buildGenerationPayload();
            const engine = payload.engine;
            let endpoint = engine === 'comfyui' ? '/api/comfy_proxy' : `/api/${engine}_proxy`;
            
            const btn = document.getElementById('inf-generate-btn');
            const txt = document.getElementById('inf-generate-text');
            const fill = document.getElementById('inf-progress-fill');
            
            // R-12: Prompt length validation — prevent engine timeouts from extreme inputs
            const _PROMPT_MAX = 10000;
            if(payload.prompt.length > _PROMPT_MAX || payload.negative_prompt.length > _PROMPT_MAX) {
                showToast(`⚠️ Prompt exceeds ${_PROMPT_MAX} character limit. Please shorten it.`);
                return;
            }

            // IS-11: Create AbortController for cancel support
            const controller = new AbortController();
            window._activeGenController = controller;
            
            fill.style.width = '0%';
            btn.disabled = true;
            txt.innerText = "Queueing...";
            // IS-11: Show cancel button
            const cancelBtn = document.getElementById('inf-cancel-btn');
            if (cancelBtn) cancelBtn.style.display = 'inline-flex';
            document.getElementById('inf-canvas-img').style.display = 'none';
            document.getElementById('inf-canvas-empty').style.display = 'block';
            document.getElementById('inf-canvas-empty').innerText = "Waking Engine...";

            let a1111ProgressInterval = null;
            let genStartTime = Date.now();

            // Sprint 12: Progress bar helper
            function updateGenProgress(pct, stepText) {
                const bar = document.getElementById('gen-progress-bar');
                const barFill = document.getElementById('gen-progress-fill');
                const info = document.getElementById('gen-progress-info');
                if (bar) bar.classList.add('active');
                if (barFill) barFill.style.width = pct + '%';
                if (info) { info.classList.add('active'); info.textContent = stepText; }
            }
            function hideGenProgress() {
                const bar = document.getElementById('gen-progress-bar');
                const barFill = document.getElementById('gen-progress-fill');
                const info = document.getElementById('gen-progress-info');
                if (bar) bar.classList.remove('active');
                if (barFill) barFill.style.width = '0%';
                if (info) { info.classList.remove('active'); info.textContent = ''; }
            }

            if (engine === 'a1111' || engine === 'forge') {
                fill.style.width = '5%';
                fill.classList.add('progress-pulsing');
                txt.innerText = "Processing...";
                document.getElementById('inf-canvas-empty').innerText = "Generating your image...";
                a1111ProgressInterval = setInterval(async () => {
                    try {
                        const progRes = await fetch(endpoint, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({endpoint: '/sdapi/v1/progress?skip_current_image=false'})
                        });
                        const progData = await progRes.json();
                        if (progData && typeof progData.progress === 'number') {
                            fill.style.width = Math.max(5, progData.progress * 100) + '%';
                            const pct = Math.floor(progData.progress * 100);
                            const eta = Math.floor(progData.eta_relative || 0);
                            txt.innerText = `Processing... (${eta}s)`;
                            updateGenProgress(pct, `Step ${progData.state?.sampling_step || '?'}/${progData.state?.sampling_steps || '?'} — ETA ${eta}s`);
                            if (progData.current_image) {
                                const canvasImg = document.getElementById('inf-canvas-img');
                                canvasImg.src = "data:image/png;base64," + progData.current_image;
                                canvasImg.style.display = 'block';
                                document.getElementById('inf-canvas-empty').style.display = 'none';
                            }
                        }
                    } catch(e) { console.debug('[Progress] A1111/Forge poll error:', e); }
                }, 1000);
            } else if (engine === 'fooocus') {
                fill.style.width = '5%';
                fill.classList.add('progress-pulsing');
                txt.innerText = "Processing...";
                document.getElementById('inf-canvas-empty').innerText = "Generating your image...";
                a1111ProgressInterval = setInterval(() => {
                    const elapsed = Math.floor((Date.now() - genStartTime) / 1000);
                    txt.innerText = `Processing... (${elapsed}s)`;
                }, 1000);
            }

            try {                
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({endpoint: '/api/generate', payload: payload}),
                    signal: controller.signal  // IS-11: AbortController support
                });
                const data = await res.json();
                
                if (a1111ProgressInterval) clearInterval(a1111ProgressInterval);
                
                if(data.error) throw new Error(data.error);

                if(engine === 'comfyui') {
                    window.currentPromptId = data.prompt_id;
                    
                    if(window.comfyPollInterval) clearInterval(window.comfyPollInterval);
                    if(window.comfyProgressInterval) clearInterval(window.comfyProgressInterval);
                    
                    fill.style.width = '5%';
                    fill.classList.add('progress-pulsing');
                    txt.innerText = "Processing...";
                    document.getElementById('inf-canvas-empty').innerText = "Generating your image...";
                    
                    // R-4: Dynamic WebSocket URL for LAN sharing support
                    // IS-02 fix: was `activeEngine` (undefined) — now uses local `engine` variable
                    // IS-12 fix: Read ComfyUI port from server status if available
                    if(!window.comfyWS && engine === 'comfyui') {
                        // S-3: WebSocket connection with auto-reconnect backoff
                        function connectComfyWS(attempt) {
                            if (attempt > 3) { console.warn('[ComfyUI WS] Max reconnect attempts reached.'); return; }
                            try {
                                const wsHost = window.location.hostname || '127.0.0.1';
                                const wsPort = window._comfyPort || 8188;
                                const ws = new WebSocket(`ws://${wsHost}:${wsPort}/ws`);
                                ws.onopen = () => { console.log('[ComfyUI WS] Connected (attempt ' + attempt + ')'); };
                                ws.onmessage = (event) => {
                                    if(typeof event.data === 'string') {
                                        try {
                                            const msg = JSON.parse(event.data);
                                            if(msg.type === 'progress') {
                                                const pfill = document.getElementById('inf-progress-fill');
                                                if(pfill && msg.data.max > 0) {
                                                    const pct = (msg.data.value / msg.data.max) * 100;
                                                    pfill.style.width = pct + '%';
                                                    pfill.classList.remove('progress-pulsing');
                                                    updateGenProgress(pct, `Step ${msg.data.value}/${msg.data.max}`);
                                                }
                                            }
                                        } catch(parseErr) { console.debug('[ComfyUI WS] Parse error:', parseErr); }
                                    } else {
                                        const reader = new FileReader();
                                        reader.onload = () => {
                                            const buffer = new Uint8Array(reader.result);
                                            if(buffer.length > 8) {
                                                const imgBlob = new Blob([buffer.slice(8)]);
                                                const imgUrl = URL.createObjectURL(imgBlob);
                                                const cimg = document.getElementById('inf-canvas-img');
                                                if(cimg) {
                                                    // IS-04: Revoke previous blob URL to prevent memory leak
                                                    if (cimg._lastBlobUrl) URL.revokeObjectURL(cimg._lastBlobUrl);
                                                    cimg._lastBlobUrl = imgUrl;
                                                    cimg.src = imgUrl;
                                                    cimg.style.display = 'block';
                                                    document.getElementById('inf-canvas-empty').style.display = 'none';
                                                }
                                            }
                                        };
                                        reader.readAsArrayBuffer(event.data);
                                    }
                                };
                                // S-3: Auto-reconnect with exponential backoff during active generation
                                ws.onclose = () => {
                                    console.log('[ComfyUI WS] Connection closed.');
                                    window.comfyWS = null;
                                    // Only reconnect if generation is still in-flight
                                    if (window.comfyPollInterval) {
                                        const delay = Math.min(1000 * Math.pow(2, attempt - 1), 4000);
                                        console.log(`[ComfyUI WS] Reconnecting in ${delay}ms (attempt ${attempt + 1})...`);
                                        setTimeout(() => connectComfyWS(attempt + 1), delay);
                                    }
                                };
                                ws.onerror = (err) => {
                                    console.warn('[ComfyUI WS] Error:', err);
                                    // onclose will fire after onerror — reconnect happens there
                                };
                                window.comfyWS = ws;
                            } catch(e) {
                                console.warn('[ComfyUI WS] Failed to connect:', e);
                            }
                        }
                        connectComfyWS(1);
                    }
                    
                    window.comfyProgressInterval = setInterval(() => {
                        const elapsed = Math.floor((Date.now() - genStartTime) / 1000);
                        txt.innerText = `Processing... (${elapsed}s)`;
                    }, 1000);
                    
                    // R-1: Poll ComfyUI history with a timeout ceiling (300 polls × 1.5s ≈ 7.5 min max)
                    let comfyPollCount = 0;
                    const COMFY_POLL_MAX = 300;
                    window.comfyPollInterval = setInterval(async () => {
                        comfyPollCount++;
                        if(comfyPollCount > COMFY_POLL_MAX) {
                            clearInterval(window.comfyPollInterval);
                            clearInterval(window.comfyProgressInterval);
                            btn.disabled = false;
                            txt.innerText = "Generate Image";
                            fill.style.width = '0%';
                            fill.classList.remove('progress-pulsing');
                            hideGenProgress();
                            document.getElementById('inf-canvas-empty').style.display = 'block';
                            document.getElementById('inf-canvas-empty').innerText = "⏱️ Generation timed out after ~7 minutes. Engine may have stalled.";
                            showToast('⚠️ ComfyUI generation timed out. Check engine logs.');
                            return;
                        }
                        try {
                            const histRes = await fetch('/api/comfy_proxy', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({endpoint: `/history/${window.currentPromptId}`})
                            });
                            const histData = await histRes.json();
                            
                            if(histData[window.currentPromptId]) {
                                clearInterval(window.comfyPollInterval);
                                clearInterval(window.comfyProgressInterval);
                                const outputs = histData[window.currentPromptId].outputs;
                                
                                for(const nodeId in outputs) {
                                    if(outputs[nodeId].images && outputs[nodeId].images.length > 0) {
                                        const imgData = outputs[nodeId].images[0];
                                        const imgUrl = `/api/comfy_image?filename=${imgData.filename}&subfolder=${imgData.subfolder}&type=${imgData.type}&t=${Date.now()}`;
                                        
                                        const canvasImg = document.getElementById('inf-canvas-img');
                                        canvasImg.src = imgUrl;
                                        canvasImg.style.display = 'block';
                                        document.getElementById('inf-canvas-empty').style.display = 'none';
                                        
                                        addToGallery(imgUrl, payload);
                                        
                                        btn.disabled = false;
                                        txt.innerText = "Generate Image";
                                        fill.style.width = '100%';
                                        fill.classList.remove('progress-pulsing');
                                        hideGenProgress();
                                        // IS-11: Hide cancel button on completion
                                        if (cancelBtn) cancelBtn.style.display = 'none';
                                        window._activeGenController = null;
                                        setTimeout(() => fill.style.width = '0%', 800);
                                        break;
                                    }
                                }
                            }
                        } catch(e) { console.debug('[ComfyUI] History poll error:', e); }
                    }, 1500);

                } else if(engine === 'a1111' || engine === 'forge') {
                    if(data.images && data.images.length > 0) {
                        const b64 = "data:image/png;base64," + data.images[0];
                        const canvasImg = document.getElementById('inf-canvas-img');
                        canvasImg.src = b64;
                        canvasImg.style.display = 'block';
                        document.getElementById('inf-canvas-empty').style.display = 'none';
                        addToGallery(b64, payload);
                    }
                    btn.disabled = false;
                    txt.innerText = "Generate Image";
                    fill.style.width = '0%';
                    fill.classList.remove('progress-pulsing');
                    hideGenProgress();
                    if (cancelBtn) cancelBtn.style.display = 'none';
                    window._activeGenController = null;
                } else if(engine === 'fooocus') {
                    if(data.image) {
                        const canvasImg = document.getElementById('inf-canvas-img');
                        canvasImg.src = data.image.url || "data:image/png;base64," + data.image.base64;
                        canvasImg.style.display = 'block';
                        document.getElementById('inf-canvas-empty').style.display = 'none';
                        addToGallery(canvasImg.src, payload);
                    }
                    btn.disabled = false;
                    txt.innerText = "Generate Image";
                    fill.style.width = '0%';
                    fill.classList.remove('progress-pulsing');
                    hideGenProgress();
                    if (cancelBtn) cancelBtn.style.display = 'none';
                    window._activeGenController = null;
                }
            } catch(e) {
                if (e.name === 'AbortError') return;  // IS-11: User cancelled — cancelInference already cleaned up
                if (a1111ProgressInterval) clearInterval(a1111ProgressInterval);
                alert("Generation Failed: " + e.message + `\n\nIs ${engine} running?`);
                btn.disabled = false;
                txt.innerText = "Generate Image";
                fill.style.width = '0%';
                fill.classList.remove('progress-pulsing');
                hideGenProgress();
                if(window.comfyPollInterval) clearInterval(window.comfyPollInterval);
                if(window.comfyProgressInterval) clearInterval(window.comfyProgressInterval);
                if (cancelBtn) cancelBtn.style.display = 'none';
                window._activeGenController = null;
                document.getElementById('inf-canvas-empty').innerText = "No Output";
            }
        }

        /* --- Download Polling Engine --- */
        let knownCompletedJobs = new Set();

        async function pollDownloads() {
            try {
                const res = await fetch('/api/downloads');
                const jobs = await res.json();
                const container = document.getElementById('active-downloads');
                container.innerHTML = '';
                
                Object.keys(jobs).forEach(jobId => {
                    const j = jobs[jobId];
                    if(j.status === 'completed' || j.status === 'error') {
                        if(j.status === 'completed' && !knownCompletedJobs.has(jobId)) {
                            knownCompletedJobs.add(jobId);
                            // Ensure the Python vault crawler has a second to finish parsing
                            setTimeout(loadModels, 2000); 
                        }
                        return; // Hide finished
                    }
                    
                    const progress = j.progress || 0;
                    const statText = j.status === 'starting' ? 'Initializing...' : `${progress}%`;
                    
                    container.innerHTML += `
                        <div class="download-toast">
                            <div style="font-size:0.85rem; font-weight:600; margin-bottom:5px;">Downloading: ${j.model_name}</div>
                            <div style="font-size:0.75rem; color:var(--text-muted); display:flex; justify-content:space-between;">
                                <span>${j.filename}</span>
                                <span>${statText}</span>
                            </div>
                            <div class="dl-bar-bg">
                                <div class="dl-bar-fill" style="width: ${progress}%"></div>
                            </div>
                        </div>
                    `;
                });
            } catch(e) { console.debug('[Downloads] Poll error:', e); }
        }
        
        async function checkSystemStatus() {
            try {
                // D-1 fix: Use shared deduped fetch
                const data = await fetchServerStatus();
                if (!data) return;
                const toast = document.getElementById('global-sync-toast');
                if(data.is_syncing) {
                    let msgs = [];
                    if(data.unpopulated_models > 0) msgs.push(`Indexing ${data.unpopulated_models} Models`);
                    if(data.active_downloads > 0) msgs.push(`${data.active_downloads} Downloads Active`);
                    
                    if(msgs.length > 0) {
                        toast.style.display = 'flex';
                        toast.innerText = `✨ ${msgs.join(" | ")}...`;
                    } else {
                        toast.style.display = 'none';
                    }
                } else {
                    toast.style.display = 'none';
                }
