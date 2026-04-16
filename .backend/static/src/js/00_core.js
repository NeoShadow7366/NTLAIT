        // S2-15: Global HTML escape utility — prevents XSS in innerHTML templates
        function escHtml(s) {
            if (!s) return '';
            const d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }

        // ═══ Global Toast Notification ═══════════════════════════════
        // BUG-G1 fix: showToast() was called 28+ times across modules
        // but never defined. Late-binds to showSettingsToast (09_settings.js)
        // with a direct DOM fallback for load-order safety.
        function showToast(msg) {
            if (typeof showSettingsToast === 'function') {
                showSettingsToast(msg);
            } else {
                const toast = document.getElementById('global-sync-toast');
                if (toast) {
                    toast.innerText = msg;
                    toast.style.display = 'flex';
                    setTimeout(() => { toast.style.display = 'none'; }, 3000);
                }
            }
        }

        // ═══ Unified API Call Wrapper ════════════════════════════════
        class ApiError extends Error {
            constructor(message, status) {
                super(message);
                this.name = 'ApiError';
                this.status = status;
            }
        }

        /**
         * Centralized fetch wrapper with consistent error handling.
         * Normalizes all backend error shapes into a single ApiError.
         * @param {string} url - The API endpoint
         * @param {object} options - Standard fetch options (method, headers, body, etc.)
         * @returns {Promise<object>} - Parsed JSON response
         * @throws {ApiError} - On HTTP errors or network failures
         */
        async function apiCall(url, options = {}) {
            try {
                const res = await fetch(url, options);
                // Handle non-JSON responses (binary, streaming, etc.)
                const ct = res.headers.get('content-type') || '';
                if (!ct.includes('application/json')) {
                    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
                    return res;
                }
                const data = await res.json();
                if (data.status === 'error' || data.error) {
                    throw new ApiError(data.message || data.error || 'Unknown error', res.status);
                }
                return data;
            } catch (e) {
                if (e instanceof ApiError) throw e;
                throw new ApiError(`Network error: ${e.message}`, 0);
            }
        }

        // Global State
        let activeModels = {}; 
        let currentModalModel = null;
        let currentModalVersion = null;
        window.isVaultMode = false;
        window.currentVaultFilename = null;
        window.currentVaultCategory = null;
        window.availableLoras = [];
        window.comfyUploadedImg2Img = null;
        window.comfyUploadedCn = null;
        
        // D-1 fix: Shared server status fetch with TTL dedup
        let _statusCache = null, _statusPromise = null, _statusTime = 0;
        async function fetchServerStatus() {
            const now = Date.now();
            if (_statusCache && now - _statusTime < 2000) return _statusCache;
            if (_statusPromise) return _statusPromise;
            _statusPromise = fetch('/api/server_status').then(r => r.json()).catch(() => null);
            _statusCache = await _statusPromise;
            _statusTime = Date.now();
            _statusPromise = null;
            return _statusCache;
        }
        
        async function uploadFileToProxy(file) {
            // BUG-6 fix: Only ComfyUI requires server-side file upload.
            // A1111/Forge use base64 inline in the payload — skip upload to avoid errors.
            const engine = document.getElementById('inf-engine')?.value || 'comfyui';
            if (engine !== 'comfyui') return null;

            document.getElementById('inf-generate-btn').disabled = true;
            document.getElementById('inf-generate-text').innerText = "Uploading Image to Engine...";
            
            const formData = new FormData();
            formData.append("image", file);
            try {
                const res = await fetch('/api/comfy_upload', { method: 'POST', body: formData });
                const data = await res.json();
                document.getElementById('inf-generate-btn').disabled = false;
                document.getElementById('inf-generate-text').innerText = "Generate Image";
                return data.name; 
            } catch(e) {
                alert("Engine upload failed! Is ComfyUI running?");
                document.getElementById('inf-generate-btn').disabled = false;
                document.getElementById('inf-generate-text').innerText = "Generate Image";
                return null;
            }
        }

        /* ═══════ FLUX MODEL SUPPORT ═══════ */
        const SD_ONLY_IDS  = ['inf-sd-refiner-row','inf-sd-model-row','inf-sd-cfg-row','inf-sd-cn-row','inf-sd-neg-row'];
        const FLUX_ONLY_IDS = ['inf-flux-unet-row','inf-flux-clip-l-row','inf-flux-t5xxl-row'];

        function onModelTypeChange(type) {
            const isFlux = type==='flux-dev'||type==='flux-schnell';
            SD_ONLY_IDS.forEach(id => { const el=document.getElementById(id); if(el) el.style.display=isFlux?'none':''; });
            FLUX_ONLY_IDS.forEach(id => { const el=document.getElementById(id); if(el) el.style.display=isFlux?'':'none'; });
            const gRow=document.getElementById('inf-flux-guidance-row');
            if(gRow) gRow.style.display=(type==='flux-dev')?'':'none';
            if(type==='flux-schnell') document.getElementById('inf-steps').value=4;
            if(type==='flux-dev') document.getElementById('inf-steps').value=20;
        }

        function autoDetectModelType(filename) {
            const sel=document.getElementById('inf-model-type');
            if(sel.value!=='auto') return;
            const lower=(filename||'').toLowerCase();
            if(lower.includes('flux')||lower.includes('f1-')) {
                const type=lower.includes('schnell')?'flux-schnell':'flux-dev';
                sel.value=type; onModelTypeChange(type);
            } else if(lower.includes('xl')||lower.includes('sdxl')) {
                sel.value='sdxl'; onModelTypeChange('sdxl');
            } else {
                sel.value='sd'; onModelTypeChange('sd');
            }
        }

        function onEngineChange(engine) {
            console.log("Switched inference engine to: " + engine);
            
            // Reset launch button state for new engine
            const btn = document.getElementById('inf-launch-btn');
            btn.innerText = 'Launch Engine';
            btn.style.color = '#cbd5e1';
            btn.onclick = launchActiveEngine;
            window.engineLaunching = false;
            // I-11 fix: Clear stale ComfyUI img2img reference when switching engines
            window.comfyUploadedImg2Img = null;
            
            // Apply engine-specific UI visibility
            applyEngineVisibility(engine);
            
            // Probe engine connectivity
            const probes = {
                comfyui:  { proxy: '/api/comfy_proxy',   body: {endpoint: '/system_stats'} },
                a1111:    { proxy: '/api/a1111_proxy',    body: {endpoint: '/sdapi/v1/options'} },
                forge:    { proxy: '/api/forge_proxy',    body: {endpoint: '/sdapi/v1/options'} },
                fooocus:  { proxy: '/api/fooocus_proxy',  body: {endpoint: '/'} }
            };
            const probe = probes[engine];
            if(probe) {
                btn.innerText = 'Checking...';
                btn.style.color = '#fbbf24';
                fetch(probe.proxy, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(probe.body)
                }).then(res => {
                    if(res.ok) {
                        btn.innerText = 'Backend Connected 🟢';
                        btn.style.color = '#4ade80';
                    } else throw new Error('offline');
                }).catch(() => {
                    btn.innerText = 'Launch Engine';
                    btn.style.color = '#cbd5e1';
                });
            }
        }

        /* ═══ Engine-Specific UI Visibility ═══ */
        function applyEngineVisibility(engine) {
            // All toggleable row IDs in the Config panel
            const allRows = [
                'inf-model-type-row', 'inf-sd-model-row', 'inf-sd-refiner-row',
                'inf-vae-row', 'inf-lora-section', 'inf-sampler-row',
                'inf-scheduler-row', 'inf-steps-row', 'inf-sd-cfg-row',
                'inf-dimensions-row', 'inf-seed-row', 'inf-hires-section',
                'inf-sd-cn-row'
            ];

            // Per-engine: which rows to HIDE (everything else stays visible)
            const hideMap = {
                comfyui: [],
                a1111:  ['inf-scheduler-row', 'inf-vae-row', 'inf-sd-refiner-row'],
                forge:  ['inf-scheduler-row', 'inf-vae-row', 'inf-sd-refiner-row'],
                fooocus: [
                    'inf-model-type-row', 'inf-sd-model-row', 'inf-sd-refiner-row',
                    'inf-vae-row', 'inf-lora-section', 'inf-sampler-row',
                    'inf-scheduler-row', 'inf-steps-row', 'inf-sd-cfg-row',
                    'inf-dimensions-row', 'inf-seed-row', 'inf-hires-section',
                    'inf-sd-cn-row'
                ]
            };

            const toHide = new Set(hideMap[engine] || []);

            allRows.forEach(id => {
                const el = document.getElementById(id);
                if(el) el.style.display = toHide.has(id) ? 'none' : '';
            });
        }

        // executeFluxInference logic moved to server backend
        /* --- Smart Img2Img Drop Handler: supports OS files AND gallery drags --- */
        async function handleDropOnImg2Img(e) {
            // Check for gallery drag first (custom MIME type, no files)
            const galleryUrl = e.dataTransfer.getData('application/x-gallery-img');
            if(galleryUrl) {
                try {
                    const res = await fetch(galleryUrl);
                    const blob = await res.blob();
                    const ext = blob.type.includes('png') ? 'png' : 'jpg';
                    const file = new File([blob], 'gallery_image.' + ext, { type: blob.type });
                    await handleImg2ImgUploadFile(file);
                } catch(err) {
                    alert('Failed to load gallery image: ' + err.message);
                }
                return;
            }
            // Fall back to OS file drop
            if(e.dataTransfer.files && e.dataTransfer.files.length) {
                await handleImg2ImgUploadFile(e.dataTransfer.files[0]);
            }
        }

        async function handleImg2ImgUploadFile(file) {
            if(!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
                const prev = document.getElementById('inf-img2img-preview');
                prev.src = ev.target.result;
                window.comfyUploadedImg2ImgB64 = ev.target.result.split(',')[1];
                prev.style.display = 'block';
                document.getElementById('inf-img2img-text').style.display = 'none';
            };
            reader.readAsDataURL(file);
            window.comfyUploadedImg2Img = await uploadFileToProxy(file);
        }
        
        // Legacy alias kept for compatibility
        async function handleImg2ImgUpload(e) {
            return handleImg2ImgUploadFile(e.target.files[0]);
        }
        
        function clearImg2Img() {
            window.comfyUploadedImg2Img = null;
            window.comfyUploadedImg2ImgB64 = null;
            document.getElementById('inf-img2img-file').value = "";
            document.getElementById('inf-img2img-preview').style.display = 'none';
            document.getElementById('inf-img2img-text').style.display = 'block';
        }

        async function handleCnUploadFile(file) {
            if(!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
                const prev = document.getElementById('inf-cn-preview');
                prev.src = ev.target.result;
                window.comfyUploadedCnB64 = ev.target.result.split(',')[1];
                prev.style.display = 'block';
                document.getElementById('inf-cn-text').style.display = 'none';
            };
            reader.readAsDataURL(file);
            window.comfyUploadedCn = await uploadFileToProxy(file);
        }

        // Legacy alias kept for compatibility
        async function handleCnUpload(e) {
            return handleCnUploadFile(e.target.files[0]);
        }

        /* --- Scroll-to-Zoom & Drag-to-Pan on Output Canvas --- */
        (function() {
            let _zoom = 1.0;
            let _panX = 0;
            let _panY = 0;
            let _isPanning = false;
            let _startX = 0;
            let _startY = 0;
            // I-7 fix: Expose zoom/pan for inpaint coordinate correction
            window._canvasZoom = 1.0;
            window._canvasPanX = 0;
            window._canvasPanY = 0;

            document.addEventListener('DOMContentLoaded', () => {
                const container = document.getElementById('inf-canvas-container');
                const img = document.getElementById('inf-canvas-img');
                if(!container || !img) return;

                const updateTransform = () => {
                    img.style.transform = `scale(${_zoom}) translate(${_panX}px, ${_panY}px)`;
                };

                container.addEventListener('wheel', (e) => {
                    if(img.style.display === 'none') return;
                    e.preventDefault();
                    _zoom = Math.min(8, Math.max(0.2, _zoom * (e.deltaY < 0 ? 1.12 : 0.9)));
                    window._canvasZoom = _zoom;
                    updateTransform();
                    // I-7 fix: Realign inpaint canvas overlay after zoom
                    if (typeof resizeInpaintCanvas === 'function') resizeInpaintCanvas();
                }, { passive: false });

                container.addEventListener('mousedown', (e) => {
                    if(img.style.display === 'none') return;
                    _isPanning = true;
                    _startX = e.clientX - (_panX * _zoom);
                    _startY = e.clientY - (_panY * _zoom);
                    container.style.cursor = 'grabbing';
                });

                window.addEventListener('mousemove', (e) => {
                    if(!_isPanning) return;
                    _panX = (e.clientX - _startX) / _zoom;
                    _panY = (e.clientY - _startY) / _zoom;
                    window._canvasPanX = _panX;
                    window._canvasPanY = _panY;
                    updateTransform();
                });

                window.addEventListener('mouseup', () => {
                    if (_isPanning && typeof resizeInpaintCanvas === 'function') resizeInpaintCanvas();
                    _isPanning = false;
                    container.style.cursor = 'default';
                });

                container.addEventListener('dblclick', () => {
                    _zoom = 1.0;
                    _panX = 0;
                    _panY = 0;
                    updateTransform();
                });
            });
        })();

        /* --- Column Resizer Drag Handles --- */
        (function() {
            function initResizer(handle, leftCol, rightCol) {
                handle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    window._resizing = true;
                    handle.style.background = 'var(--primary)';
                    const startX = e.clientX;
                    const startLeft = leftCol.offsetWidth;
                    const startRight = rightCol.offsetWidth;
                    function onMove(ev) {
                        const dx = ev.clientX - startX;
                        const newLeft = Math.max(180, startLeft + dx);
                        const newRight = Math.max(180, startRight - dx);
                        leftCol.style.width = newLeft + 'px';
                        leftCol.style.flexBasis = newLeft + 'px';
                        rightCol.style.width = newRight + 'px';
                        rightCol.style.flexBasis = newRight + 'px';
                    }
                    function onUp() {
                        window._resizing = false;
                        handle.style.background = 'transparent';
                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);
                    }
                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });
            }
            document.addEventListener('DOMContentLoaded', () => {
                const lh = document.getElementById('resizer-left');
                const rh = document.getElementById('resizer-right');
                const colL = document.getElementById('inf-col-left');
                const colM = document.getElementById('inf-col-mid');
                const colR = document.getElementById('inf-col-right');
                if(lh && colL && colM) initResizer(lh, colL, colM);
                if(rh && colM && colR) initResizer(rh, colM, colR);
            });
        })();

        /* --- Persistent Gallery: Save to DB + Update UI --- */
        async function saveToGallery(imgUrl, workflow) {
            // Extract metadata from UI for cleaner gallery storage
            const prompt = document.getElementById('inf-prompt').value;
            const negative = document.getElementById('inf-negative').value;
            const model = document.getElementById('inf-model').value;
            const seed = parseInt(document.getElementById('inf-seed').value);
            const steps = parseInt(document.getElementById('inf-steps').value);
            const cfg = parseFloat(document.getElementById('inf-cfg').value);
            const sampler = document.getElementById('inf-sampler').value;
            const width = parseInt(document.getElementById('inf-width').value);
            const height = parseInt(document.getElementById('inf-height').value);

            const payload = {
                image_path: imgUrl,
                prompt, negative, model, seed, steps, cfg, sampler, width, height,
                extra: { workflow }
            };

            try {
                await fetch('/api/gallery/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
            } catch(e) {
                console.warn("Failed to save to gallery DB:", e);
            }
        }

        function addToGallery(imgUrl, promptObj) {
            // 1. Add to the transient horizontal strip in Studio
            const gal = document.getElementById('inf-gallery');
            if(!gal) return;
            const wrap = document.createElement('div');
            wrap.style.cssText = 'position:relative;flex-shrink:0;height:110px;cursor:pointer;border-radius:8px;overflow:hidden;border:2px solid transparent;transition:border-color 0.2s;';
            wrap.title = 'Click to view · Drag to canvas to restore settings';

            const thumb = document.createElement('img');
            thumb.src = imgUrl;
            thumb.style.cssText = 'height:100%;width:auto;display:block;pointer-events:none;';
            thumb.draggable = false;

            wrap.dataset.imgUrl = imgUrl;
            wrap.dataset.prompt = JSON.stringify(promptObj);

            wrap.addEventListener('mouseenter', () => wrap.style.borderColor = 'var(--primary)');
            wrap.addEventListener('mouseleave', () => wrap.style.borderColor = 'transparent');
            wrap.addEventListener('click', () => {
                const canvasImg = document.getElementById('inf-canvas-img');
                canvasImg.src = imgUrl;
                canvasImg.style.display = 'block';
                document.getElementById('inf-canvas-empty').style.display = 'none';
            });

            wrap.draggable = true;
            wrap.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('application/x-gallery-img', imgUrl);
                e.dataTransfer.setData('application/x-gallery-prompt', wrap.dataset.prompt);
                e.dataTransfer.effectAllowed = 'copy';
            });

            wrap.appendChild(thumb);
            gal.insertBefore(wrap, gal.firstChild);

            // 2. Persist to DB
            saveToGallery(imgUrl, promptObj);
        }

        /* --- Gallery Drop on Canvas: show image + restore settings --- */
        function restoreFromGalleryDrop(e) {
            const imgUrl = e.dataTransfer.getData('application/x-gallery-img');
            const promptStr = e.dataTransfer.getData('application/x-gallery-prompt');
            if(imgUrl) {
                const canvasImg = document.getElementById('inf-canvas-img');
                canvasImg.src = imgUrl;
                canvasImg.style.display = 'block';
                document.getElementById('inf-canvas-empty').style.display = 'none';
            }
            if(promptStr) {
                try { repopulateUI(JSON.parse(promptStr)); } catch(ex) {}
            } else if(e.dataTransfer.files && e.dataTransfer.files.length) {
                restoreMetadataFromDrop(e);
            }
        }

        // IS-09: restoreMetadataFromDrop is defined in 05_inference.js
        // with full ComfyUI metadata extraction. No duplicate needed here.

        function repopulateUI(metadata) {
            if(!metadata) return;
            const setVal = (id, val) => {
                const el = document.getElementById(id);
                if(el && val !== undefined && val !== null) el.value = val;
            };

            setVal('inf-prompt', metadata.prompt || '');
            setVal('inf-negative', metadata.negative || '');
            setVal('inf-model', metadata.model || '');
            setVal('inf-sampler', metadata.sampler || 'euler');
            setVal('inf-steps', metadata.steps || 20);
            setVal('inf-cfg', metadata.cfg || 7.0);
            setVal('inf-seed', metadata.seed || -1);
            setVal('inf-width', metadata.width || 1024);
            setVal('inf-height', metadata.height || 1024);
            
            showSettingsToast("Canvas & Generation Parameters Restored");
        }

        /* --- Hires Upscaler: map UI value to ComfyUI node params --- */
        function getHiresUpscalerParams(val) {
            const latentMethods = {
                'latent_nearest': 'nearest',
                'latent_bilinear': 'bilinear',
                'latent_bicubic': 'bicubic',
                'latent_nearest_exact': 'nearest-exact'
            };
            if(latentMethods[val]) return { type: 'latent', method: latentMethods[val] };
            return { type: 'esrgan', model: val }; // esrgan_4x, esrgan_4x_anime, swinir_4x etc.
        }

        function addLoraSlot() {
            const container = document.getElementById('inf-lora-container');
            const row = document.createElement('div');
            row.style.cssText = "display: flex; gap: 10px; align-items: center; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; border: 1px solid var(--border);";
            
            const select = document.createElement('select');
            select.className = "select-fancy lora-select";
            select.style.flex = "2";
            window.availableLoras.forEach(l => {
                const opt = document.createElement('option');
                opt.value = l.filename;
                opt.innerText = (l.metadata?.model?.name ? (l.metadata.model.name + " (" + l.filename + ")") : l.filename);
                select.appendChild(opt);
            });
            
            const weight = document.createElement('input');
            weight.type = "number";
            weight.className = "select-fancy lora-weight";
            weight.style.flex = "1";
            weight.value = "1.0";
            weight.step = "0.05";
            weight.min = "-2.0";
            weight.max = "2.0";
            weight.title = "LoRA Weight / Strength";
            
            const delBtn = document.createElement('button');
            delBtn.innerText = "❌";
            delBtn.style.cssText = "background: none; border: none; font-size: 1.0rem; cursor: pointer; color: #ef4444;";
            delBtn.onclick = () => row.remove();
            
            row.appendChild(select);
            row.appendChild(weight);
            row.appendChild(delBtn);
            container.appendChild(row);
        }

        function switchTab(tabId, el) {
            document.querySelectorAll('.nav-item').forEach(e => e.classList.remove('active'));
            if (el) el.classList.add('active');
            else {
                // Fallback: Find nav item matching tabId
                document.querySelectorAll('.nav-item').forEach(e => {
                    if (e.getAttribute('onclick') && e.getAttribute('onclick').includes(`'${tabId}'`)) {
                        e.classList.add('active');
                    }
                });
            }
            
            document.getElementById('view-dashboard').style.display = 'none';
            document.getElementById('view-explorer').style.display = 'none';
            document.getElementById('view-vault').style.display = 'none';
            document.getElementById('view-creations').style.display = 'none';
            document.getElementById('view-inference').style.display = 'none';
            document.getElementById('view-appstore').style.display = 'none';
            document.getElementById('view-packages').style.display = 'none';
            document.getElementById('view-settings').style.display = 'none';
            
            // IS-13: Stop Ollama polling when leaving Inference tab
            if (tabId !== 'inference' && typeof stopOllamaPolling === 'function') stopOllamaPolling();
            
            if(tabId === 'dashboard') {
                document.getElementById('view-dashboard').style.display = 'block';
                document.getElementById('page-title').innerText = 'Dashboard';
                document.getElementById('page-subtitle').innerText = 'System overview and real-time analytics.';
                refreshDashboard();
            } else if(tabId === 'explorer') {
                document.getElementById('view-explorer').style.display = 'block';
                document.getElementById('page-title').innerText = 'Model Explorer';
                document.getElementById('page-subtitle').innerText = 'Discover and download native models directly from CivitAI.';
                if(Object.keys(activeModels).length === 0) loadExplorer();
            } else if(tabId === 'inference') {
                document.getElementById('view-inference').style.display = 'flex';
                document.getElementById('page-title').innerText = 'Inference Studio';
                document.getElementById('page-subtitle').innerText = 'Generate artwork identically to Stability Matrix natively driven by ComfyUI.';
                initInferenceUI();
                // IS-13: Start Ollama polling only when Inference tab is active
                if (typeof startOllamaPolling === 'function') startOllamaPolling();
            } else if(tabId === 'vault') {
                document.getElementById('view-vault').style.display = 'block';
                document.getElementById('page-title').innerText = 'Global Vault';
                document.getElementById('page-subtitle').innerText = 'Managing your centralized AI assets.';
                loadModels(false);
            } else if(tabId === 'creations') {
                document.getElementById('view-creations').style.display = 'block';
                document.getElementById('page-title').innerText = 'My Creations';
                document.getElementById('page-subtitle').innerText = 'Your generation history, beautifully organized.';
                loadGallery();
            } else if (tabId === 'appstore') {
                document.getElementById('view-appstore').style.display = 'block';
                document.getElementById('page-title').innerText = 'App Store';
                document.getElementById('page-subtitle').innerText = 'Install new Generative AI frameworks automatically.';
                loadRecipes();
            } else if (tabId === 'packages') {
                document.getElementById('view-packages').style.display = 'block';
                document.getElementById('page-title').innerText = 'Installed Packages';
                document.getElementById('page-subtitle').innerText = 'Manage and launch your isolated AI UIs.';
                loadPackages();
            } else if (tabId === 'settings') {
                document.getElementById('view-settings').style.display = 'block';
                document.getElementById('page-title').innerText = 'Settings';
                document.getElementById('page-subtitle').innerText = 'API keys, theme preferences, and system maintenance.';
                loadSettings();
            }
        }

        /* ═══════════════════════════════════════════════
