        /* ═══ Sprint 12 — Inpainting Canvas Engine ═══ */
        window._inpaintActive = false;
        window._inpaintTool = 'brush';
        window._inpaintBrushSize = 30;
        window._inpaintDrawing = false;
        window._inpaintLastPos = null;

        function toggleInpaintMode() {
            const img = document.getElementById('inf-canvas-img');
            if (img.style.display === 'none' || !img.src) {
                alert('Generate or load an image first before inpainting.');
                return;
            }
            window._inpaintActive = !window._inpaintActive;
            const canvas = document.getElementById('inpaint-canvas');
            const toolbar = document.getElementById('inpaint-toolbar');
            const outpaint = document.getElementById('outpaint-controls');
            const toggleBtn = document.getElementById('inf-inpaint-toggle');

            if (window._inpaintActive) {
                // Size canvas to match displayed image dimensions
                resizeInpaintCanvas();
                canvas.classList.add('active');
                toolbar.classList.add('active');
                outpaint.classList.add('active');
                toggleBtn.style.background = 'var(--primary)';
                toggleBtn.style.color = '#fff';
                toggleBtn.style.borderColor = 'var(--primary)';
            } else {
                canvas.classList.remove('active');
                toolbar.classList.remove('active');
                outpaint.classList.remove('active');
                toggleBtn.style.background = 'var(--surface-hover)';
                toggleBtn.style.color = '#94a3b8';
                toggleBtn.style.borderColor = 'var(--border)';
            }
        }

        function resizeInpaintCanvas() {
            const img = document.getElementById('inf-canvas-img');
            const canvas = document.getElementById('inpaint-canvas');
            const container = document.getElementById('inf-canvas-container');
            // Match canvas to the rendered image bounds
            const imgRect = img.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            canvas.width = imgRect.width;
            canvas.height = imgRect.height;
            canvas.style.left = (imgRect.left - containerRect.left) + 'px';
            canvas.style.top = (imgRect.top - containerRect.top) + 'px';
            canvas.style.width = imgRect.width + 'px';
            canvas.style.height = imgRect.height + 'px';
        }

        // IS-07: Debounced window resize handler to keep inpaint canvas aligned
        let _resizeDebounce = null;
        window.addEventListener('resize', () => {
            if (!window._inpaintActive) return;
            clearTimeout(_resizeDebounce);
            _resizeDebounce = setTimeout(resizeInpaintCanvas, 150);
        });

        function setInpaintTool(tool) {
            window._inpaintTool = tool;
            document.getElementById('inpaint-brush-btn').classList.toggle('active-tool', tool === 'brush');
            document.getElementById('inpaint-eraser-btn').classList.toggle('active-tool', tool === 'eraser');
        }

        function clearInpaintMask() {
            const canvas = document.getElementById('inpaint-canvas');
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }

        function invertInpaintMask() {
            const canvas = document.getElementById('inpaint-canvas');
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;
            // Create a full white canvas, then make painted areas transparent
            const inverted = ctx.createImageData(canvas.width, canvas.height);
            for (let i = 0; i < data.length; i += 4) {
                if (data[i + 3] > 0) {
                    // Was painted (mask) → make transparent
                    inverted.data[i] = 0;
                    inverted.data[i + 1] = 0;
                    inverted.data[i + 2] = 0;
                    inverted.data[i + 3] = 0;
                } else {
                    // Was empty → fill with mask color
                    inverted.data[i] = 255;
                    inverted.data[i + 1] = 255;
                    inverted.data[i + 2] = 255;
                    inverted.data[i + 3] = 140;
                }
            }
            ctx.putImageData(inverted, 0, 0);
        }

        function getInpaintMaskBase64() {
            // Export the mask as a pure black/white PNG (white = inpaint region)
            const srcCanvas = document.getElementById('inpaint-canvas');
            const img = document.getElementById('inf-canvas-img');
            // Create export canvas at original image resolution
            const exportCanvas = document.createElement('canvas');
            exportCanvas.width = img.naturalWidth;
            exportCanvas.height = img.naturalHeight;
            const ectx = exportCanvas.getContext('2d');
            // Fill black (keep all)
            ectx.fillStyle = '#000000';
            ectx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
            // Scale mask drawing to original resolution
            const scaleX = img.naturalWidth / srcCanvas.width;
            const scaleY = img.naturalHeight / srcCanvas.height;
            const srcCtx = srcCanvas.getContext('2d');
            const srcData = srcCtx.getImageData(0, 0, srcCanvas.width, srcCanvas.height);
            const dstData = ectx.getImageData(0, 0, exportCanvas.width, exportCanvas.height);
            for (let sy = 0; sy < srcCanvas.height; sy++) {
                for (let sx = 0; sx < srcCanvas.width; sx++) {
                    const si = (sy * srcCanvas.width + sx) * 4;
                    if (srcData.data[si + 3] > 0) {
                        // Map to destination
                        const dx = Math.floor(sx * scaleX);
                        const dy = Math.floor(sy * scaleY);
                        // Fill a scaled block to avoid gaps
                        const bw = Math.ceil(scaleX);
                        const bh = Math.ceil(scaleY);
                        for (let by = 0; by < bh && dy + by < exportCanvas.height; by++) {
                            for (let bx = 0; bx < bw && dx + bx < exportCanvas.width; bx++) {
                                const di = ((dy + by) * exportCanvas.width + (dx + bx)) * 4;
                                dstData.data[di] = 255;
                                dstData.data[di + 1] = 255;
                                dstData.data[di + 2] = 255;
                                dstData.data[di + 3] = 255;
                            }
                        }
                    }
                }
            }
            ectx.putImageData(dstData, 0, 0);
            return exportCanvas.toDataURL('image/png').split(',')[1];
        }

        function hasInpaintMask() {
            const canvas = document.getElementById('inpaint-canvas');
            if (!canvas || !window._inpaintActive) return false;
            const ctx = canvas.getContext('2d');
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            for (let i = 3; i < data.length; i += 4) {
                if (data[i] > 0) return true;
            }
            return false;
        }

        // Canvas drawing event handlers
        (function setupInpaintEvents() {
            document.addEventListener('DOMContentLoaded', () => {
                const canvas = document.getElementById('inpaint-canvas');
                if (!canvas) return;

                canvas.addEventListener('mousedown', (e) => {
                    if (!window._inpaintActive) return;
                    window._inpaintDrawing = true;
                    window._inpaintLastPos = getCanvasPos(e);
                    drawInpaintDot(window._inpaintLastPos);
                });

                canvas.addEventListener('mousemove', (e) => {
                    if (!window._inpaintDrawing) return;
                    const pos = getCanvasPos(e);
                    drawInpaintLine(window._inpaintLastPos, pos);
                    window._inpaintLastPos = pos;
                    // Update brush size label
                    const label = document.getElementById('inpaint-brush-size-label');
                    if (label) label.textContent = window._inpaintBrushSize;
                });

                document.addEventListener('mouseup', () => {
                    window._inpaintDrawing = false;
                    window._inpaintLastPos = null;
                });

                // Brush size slider live label
                const sizeSlider = document.getElementById('inpaint-brush-size');
                if (sizeSlider) {
                    sizeSlider.addEventListener('input', () => {
                        document.getElementById('inpaint-brush-size-label').textContent = sizeSlider.value;
                    });
                }
            });
        })();

        function getCanvasPos(e) {
            const canvas = document.getElementById('inpaint-canvas');
            const rect = canvas.getBoundingClientRect();
            // I-7 fix: Scale from display coordinates to canvas internal coordinates
            // getBoundingClientRect already reflects CSS transforms, but the canvas
            // internal resolution (canvas.width) may differ from display size (rect.width)
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;
            return {
                x: (e.clientX - rect.left) * scaleX,
                y: (e.clientY - rect.top) * scaleY
            };
        }

        function drawInpaintDot(pos) {
            const canvas = document.getElementById('inpaint-canvas');
            const ctx = canvas.getContext('2d');
            ctx.globalCompositeOperation = window._inpaintTool === 'eraser' ? 'destination-out' : 'source-over';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, window._inpaintBrushSize / 2, 0, Math.PI * 2);
            ctx.fill();
        }

        function drawInpaintLine(from, to) {
            const canvas = document.getElementById('inpaint-canvas');
            const ctx = canvas.getContext('2d');
            ctx.globalCompositeOperation = window._inpaintTool === 'eraser' ? 'destination-out' : 'source-over';
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)';
            ctx.lineWidth = window._inpaintBrushSize;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.beginPath();
            ctx.moveTo(from.x, from.y);
            ctx.lineTo(to.x, to.y);
            ctx.stroke();
        }

        /* ═══ Sprint 12 — Outpainting ═══ */
        function outpaint(direction) {
            const img = document.getElementById('inf-canvas-img');
            if (!img.src || img.style.display === 'none') return;

            const extendSize = 128; // pixels to extend
            const canvas = document.createElement('canvas');
            const naturalW = img.naturalWidth;
            const naturalH = img.naturalHeight;

            let newW = naturalW, newH = naturalH, offsetX = 0, offsetY = 0;

            if (direction === 'up')    { newH += extendSize; offsetY = extendSize; }
            if (direction === 'down')  { newH += extendSize; offsetY = 0; }
            if (direction === 'left')  { newW += extendSize; offsetX = extendSize; }
            if (direction === 'right') { newW += extendSize; offsetX = 0; }

            canvas.width = newW;
            canvas.height = newH;
            const ctx = canvas.getContext('2d');

            // Fill with transparency (will show as black in engines)
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, newW, newH);

            // Draw existing image at offset
            ctx.drawImage(img, offsetX, offsetY);

            // Set the padded image back onto the canvas
            img.src = canvas.toDataURL('image/png');
            img.style.display = 'block';

            // Update dimensions fields
            document.getElementById('inf-width').value = newW;
            document.getElementById('inf-height').value = newH;

            // IS-08: Use img.onload instead of fragile setTimeout
            // Auto-create mask for the extended region after image loads
            function _applyOutpaintMask() {
                resizeInpaintCanvas();
                const maskCanvas = document.getElementById('inpaint-canvas');
                const mctx = maskCanvas.getContext('2d');
                mctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);

                const scaleX = maskCanvas.width / newW;
                const scaleY = maskCanvas.height / newH;

                mctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
                if (direction === 'up')    mctx.fillRect(0, 0, maskCanvas.width, extendSize * scaleY);
                if (direction === 'down')  mctx.fillRect(0, maskCanvas.height - extendSize * scaleY, maskCanvas.width, extendSize * scaleY);
                if (direction === 'left')  mctx.fillRect(0, 0, extendSize * scaleX, maskCanvas.height);
                if (direction === 'right') mctx.fillRect(maskCanvas.width - extendSize * scaleX, 0, extendSize * scaleX, maskCanvas.height);
            }

            if (window._inpaintActive) {
                img.onload = _applyOutpaintMask;
            } else {
                // Auto-enable inpaint mode for outpainting
                toggleInpaintMode();
                img.onload = _applyOutpaintMask;
            }
        }

        /* ═══ Sprint 12 — Regional Prompting Engine ═══ */
        window._regionMode = false;
        window._regionZones = [];
        const ZONE_COLORS = ['#ef4444','#3b82f6','#10b981','#f59e0b','#8b5cf6','#ec4899','#06b6d4','#f97316'];

        function toggleRegionMode() {
            window._regionMode = !window._regionMode;
            const editor = document.getElementById('region-editor');
            const toolbar = document.getElementById('region-toolbar');
            const toggleBtn = document.getElementById('inf-region-toggle');

            if (window._regionMode) {
                editor.classList.add('active');
                toolbar.classList.add('active');
                toggleBtn.style.background = 'var(--primary)';
                toggleBtn.style.color = '#fff';
                toggleBtn.style.borderColor = 'var(--primary)';
                // Auto-add first zone if empty
                if (window._regionZones.length === 0) addRegionZone();
            } else {
                editor.classList.remove('active');
                toolbar.classList.remove('active');
                toggleBtn.style.background = 'var(--surface-hover)';
                toggleBtn.style.color = '#94a3b8';
                toggleBtn.style.borderColor = 'var(--border)';
            }
        }

        function addRegionZone() {
            const editor = document.getElementById('region-editor');
            const container = document.getElementById('inf-canvas-container');
            const idx = window._regionZones.length;
            const color = ZONE_COLORS[idx % ZONE_COLORS.length];

            // Default size/position: evenly distributed grid
            const cols = Math.ceil(Math.sqrt(idx + 1));
            const rows = Math.ceil((idx + 1) / cols);
            const col = idx % cols;
            const row = Math.floor(idx / cols);
            const zoneW = 100 / cols;
            const zoneH = 100 / rows;

            const zone = document.createElement('div');
            zone.className = 'region-zone';
            zone.style.borderColor = color;
            zone.style.left = (col * zoneW) + '%';
            zone.style.top = (row * zoneH) + '%';
            zone.style.width = zoneW + '%';
            zone.style.height = zoneH + '%';
            zone.dataset.zoneIdx = idx;

            zone.innerHTML = `
                <div class="zone-header" style="background:${color}44;">
                    <span>Zone ${idx + 1}</span>
                    <span class="zone-close" onclick="removeRegionZone(${idx})">✕</span>
                </div>
                <textarea placeholder="Prompt for zone ${idx + 1}..."></textarea>
                <div class="zone-resize"></div>
            `;

            // Drag to move
            const header = zone.querySelector('.zone-header');
            header.addEventListener('mousedown', (e) => {
                if (e.target.classList.contains('zone-close')) return;
                e.preventDefault();
                const editorRect = editor.getBoundingClientRect();
                const startX = e.clientX - zone.offsetLeft;
                const startY = e.clientY - zone.offsetTop;
                function onMove(ev) {
                    let newX = ev.clientX - startX;
                    let newY = ev.clientY - startY;
                    newX = Math.max(0, Math.min(newX, editorRect.width - zone.offsetWidth));
                    newY = Math.max(0, Math.min(newY, editorRect.height - zone.offsetHeight));
                    zone.style.left = newX + 'px';
                    zone.style.top = newY + 'px';
                }
                function onUp() {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    // I-8 fix: Convert px → % so zones survive window resize
                    const finalRect = editor.getBoundingClientRect();
                    zone.style.left = (zone.offsetLeft / finalRect.width * 100) + '%';
                    zone.style.top = (zone.offsetTop / finalRect.height * 100) + '%';
                }
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });

            // Drag to resize
            const resizer = zone.querySelector('.zone-resize');
            resizer.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const startWidth = zone.offsetWidth;
                const startHeight = zone.offsetHeight;
                const startMX = e.clientX;
                const startMY = e.clientY;
                function onMove(ev) {
                    zone.style.width = Math.max(40, startWidth + (ev.clientX - startMX)) + 'px';
                    zone.style.height = Math.max(40, startHeight + (ev.clientY - startMY)) + 'px';
                }
                function onUp() {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    // I-8 fix: Convert px → % so zones survive window resize
                    const finalRect = editor.getBoundingClientRect();
                    zone.style.width = (zone.offsetWidth / finalRect.width * 100) + '%';
                    zone.style.height = (zone.offsetHeight / finalRect.height * 100) + '%';
                }
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });

            editor.appendChild(zone);
            window._regionZones.push({ element: zone, color: color });
            updateZoneCount();
        }

        function removeRegionZone(idx) {
            const zones = window._regionZones;
            if (idx >= 0 && idx < zones.length) {
                zones[idx].element.remove();
                zones.splice(idx, 1);
                // Re-index remaining zones
                zones.forEach((z, i) => {
                    z.element.dataset.zoneIdx = i;
                    const hdr = z.element.querySelector('.zone-header span:first-child');
                    if (hdr) hdr.textContent = `Zone ${i + 1}`;
                    const closeBtn = z.element.querySelector('.zone-close');
                    if (closeBtn) closeBtn.setAttribute('onclick', `removeRegionZone(${i})`);
                });
                updateZoneCount();
            }
        }

        function clearAllRegions() {
            window._regionZones.forEach(z => z.element.remove());
            window._regionZones = [];
            updateZoneCount();
        }

        function updateZoneCount() {
            const el = document.getElementById('region-zone-count');
            if (el) el.textContent = `${window._regionZones.length} zone${window._regionZones.length !== 1 ? 's' : ''}`;
        }

        function getRegionData() {
            // Returns normalized region data for backend translators
            // Each zone: { prompt, x, y, w, h } (0-1 normalized to canvas dimensions)
            if (!window._regionMode || window._regionZones.length === 0) return null;
            const editor = document.getElementById('region-editor');
            const editorW = editor.offsetWidth;
            const editorH = editor.offsetHeight;
            if (!editorW || !editorH) return null;

            const regions = [];
            for (const z of window._regionZones) {
                const el = z.element;
                const prompt = el.querySelector('textarea')?.value || '';
                if (!prompt.trim()) continue;
                regions.push({
                    prompt: prompt.trim(),
                    x: el.offsetLeft / editorW,
                    y: el.offsetTop / editorH,
                    w: el.offsetWidth / editorW,
                    h: el.offsetHeight / editorH
                });
            }
            return regions.length > 0 ? regions : null;
        }

        /* ═══ Sprint 12 — X/Y/Z Parameter Plot ═══ */
        function toggleXYZPanel() {
            document.getElementById('xyz-panel').classList.toggle('active');
        }

        async function runXYZPlot() {
            const xParam = document.getElementById('xyz-x-param').value;
            const yParam = document.getElementById('xyz-y-param').value;
            const zParam = document.getElementById('xyz-z-param').value;
            const xVals = parseAxisValues(document.getElementById('xyz-x-values').value);
            const yVals = parseAxisValues(document.getElementById('xyz-y-values').value);
            const zVals = parseAxisValues(document.getElementById('xyz-z-values').value);

            if (xParam === 'none' || xVals.length === 0) {
                alert('X axis requires a parameter and at least one value.');
                return;
            }

            const statusEl = document.getElementById('xyz-status');
            const gridEl = document.getElementById('xyz-grid');
            const basePayload = getInferencePayload();

            // Build the matrix of parameter combinations
            const combos = [];
            const xList = xVals.length > 0 ? xVals : ['_default_'];
            const yList = yVals.length > 0 && yParam !== 'none' ? yVals : ['_default_'];
            const zList = zVals.length > 0 && zParam !== 'none' ? zVals : ['_default_'];

            for (const z of zList) {
                for (const y of yList) {
                    for (const x of xList) {
                        const p = JSON.parse(JSON.stringify(basePayload));
                        if (x !== '_default_') applyAxisValue(p, xParam, x);
                        if (y !== '_default_') applyAxisValue(p, yParam, y);
                        if (z !== '_default_') applyAxisValue(p, zParam, z);
                        p._xyz_label = `${xParam}=${x}${y !== '_default_' ? `, ${yParam}=${y}` : ''}${z !== '_default_' ? `, ${zParam}=${z}` : ''}`;
                        combos.push(p);
                    }
                }
            }

            statusEl.textContent = `Queuing ${combos.length} generation${combos.length !== 1 ? 's' : ''}...`;

            // Queue all to batch
            let queued = 0;
            const allJobIds = [];
            for (const combo of combos) {
                try {
                    const res = await fetch('/api/generate/batch', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ payload: combo })
                    });
                    const resData = await res.json();
                    if (resData.job_ids) allJobIds.push(...resData.job_ids);
                    queued++;
                    statusEl.textContent = `Queued ${queued} / ${combos.length}...`;
                } catch(e) {
                    console.error('XYZ plot queue error:', e);
                }
            }

            statusEl.textContent = `✅ ${queued} generations queued!`;
            
            // IS-06: Track job IDs for SSE-driven result collection
            window._xyzJobIds = allJobIds;
            window._xyzCombos = combos;
            window._xyzGridEl = gridEl;

            // Show grid layout with placeholders
            gridEl.style.display = 'grid';
            gridEl.style.gridTemplateColumns = `repeat(${xList.length}, 1fr)`;
            gridEl.innerHTML = combos.map((c, i) => 
                `<div class="xyz-grid-cell" data-xyz-idx="${i}" style="aspect-ratio:1; display:flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:6px; background:rgba(0,0,0,0.2); font-size:0.7rem; color:var(--text-muted); padding:4px; text-align:center; position:relative; overflow:hidden;">
                    <span class="xyz-grid-label">${c._xyz_label}</span>
                </div>`
            ).join('');
        }

        function parseAxisValues(str) {
            if (!str || !str.trim()) return [];
            return str.split(',').map(s => s.trim()).filter(s => s.length > 0);
        }

        function applyAxisValue(payload, param, value) {
            // IS-05: Use unified payload field names (cfg_scale, sampler_name)
            switch(param) {
                case 'steps': payload.steps = parseInt(value); break;
                case 'cfg': payload.cfg_scale = parseFloat(value); break;
                case 'sampler': payload.sampler_name = value; break;
                case 'seed': payload.seed = parseInt(value); break;
                case 'width': payload.width = parseInt(value); break;
                case 'height': payload.height = parseInt(value); break;
                case 'denoise': payload.denoising_strength = parseFloat(value); break;
            }
        }

        /* ═══ Sprint 12 — Wildcard Engine ═══ */
        function resolveWildcards(text) {
            // Resolve {a|b|c} syntax → pick random option
            return text.replace(/\{([^}]+)\}/g, (match, group) => {
                const options = group.split('|').map(s => s.trim());
                return options[Math.floor(Math.random() * options.length)];
            });
        }

        /* ═══ Sprint 12 — Seed Explorer ═══ */
        async function runSeedExplorer(count = 9) {
            const basePayload = getInferencePayload();
            const baseSeed = basePayload.seed === -1 ? Math.floor(Math.random() * 999999999) : basePayload.seed;

            const statusEl = document.getElementById('xyz-status');
            const gridEl = document.getElementById('xyz-grid');
            
            statusEl.textContent = `Queuing ${count} seed variations...`;
            gridEl.style.display = 'grid';
            gridEl.style.gridTemplateColumns = 'repeat(3, 1fr)';
            gridEl.innerHTML = '';

            let queued = 0;
            const allJobIds = [];
            for (let i = 0; i < count; i++) {
                const p = JSON.parse(JSON.stringify(basePayload));
                p.seed = baseSeed + i;
                try {
                    const res = await fetch('/api/generate/batch', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ payload: p })
                    });
                    const data = await res.json();
                    if (data.job_ids) allJobIds.push(...data.job_ids);
                    queued++;
                    gridEl.innerHTML += `<div class="xyz-grid-cell" data-xyz-idx="${i}" style="aspect-ratio:1; display:flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:6px; background:rgba(0,0,0,0.2); font-size:0.7rem; color:var(--text-muted); padding:4px; text-align:center;"><span class="xyz-grid-label">Seed: ${p.seed}</span></div>`;
                    statusEl.textContent = `Queued ${queued} / ${count}...`;
                } catch(e) {
                    console.error('Seed explorer queue error:', e);
                }
            }
            statusEl.textContent = `✅ ${queued} seed variations queued!`;

            // IS-06: Track job IDs for SSE result collection
            window._xyzJobIds = allJobIds;
            window._xyzGridEl = gridEl;
        }

        /* ═══ Sprint 12 — Ollama Integration ═══ */
        window._ollamaModels = [];
        async function checkOllamaStatus() {
            const dot = document.getElementById('ollama-status-dot');
            try {
                const res = await fetch('/api/ollama/status');
                const data = await res.json();
                if (data.online) {
                    dot.style.background = '#10b981';
                    dot.title = `Ollama: Online (${data.models.length} model${data.models.length !== 1 ? 's' : ''})`;
                    window._ollamaModels = data.models || [];
                } else {
                    dot.style.background = '#ef4444';
                    dot.title = 'Ollama: Offline';
                    window._ollamaModels = [];
                }
            } catch(e) {
                if (dot) { dot.style.background = '#ef4444'; dot.title = 'Ollama: Offline'; }
            }
        }
        // IS-13: Lazy-init Ollama polling — only when Inference tab is active
        window._ollamaPollingActive = false;
        window._ollamaInterval = null;
        function startOllamaPolling() {
            if (window._ollamaPollingActive) return;
            window._ollamaPollingActive = true;
            checkOllamaStatus();
            window._ollamaInterval = setInterval(checkOllamaStatus, 30000);
        }
        function stopOllamaPolling() {
            window._ollamaPollingActive = false;
            if (window._ollamaInterval) { clearInterval(window._ollamaInterval); window._ollamaInterval = null; }
        }

        async function enhancePromptWithOllama() {
            const promptEl = document.getElementById('inf-prompt');
            const btn = document.getElementById('ollama-enhance-btn');
            if (!promptEl || !promptEl.value.trim()) {
                showToast('Enter a prompt first, then click Enhance.');
                return;
            }
            const original = btn.innerHTML;
            btn.innerHTML = '⏳ Enhancing...';
            btn.disabled = true;
            try {
                const model = window._ollamaModels.length > 0 ? window._ollamaModels[0] : 'llama3.2';
                const res = await fetch('/api/ollama/enhance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt: promptEl.value, model: model })
                });
                const data = await res.json();
                if (data.enhanced_prompt) {
                    promptEl.value = data.enhanced_prompt;
                    updateTokenCounter();
                    showToast('✨ Prompt enhanced!');
                } else {
                    showToast('⚠️ ' + (data.error || 'Enhancement failed'));
                }
            } catch(e) {
                showToast('⚠️ Ollama not reachable. Is it running?');
            }
            btn.innerHTML = original;
            btn.disabled = false;
        }

        /* --- Inference Studio UI Engine --- */
        async function extractComfyMetadata(blob) {
            const buf = await blob.arrayBuffer();
            const view = new DataView(buf);
            let offset = 8;
            while(offset < view.byteLength) {
                 const length = view.getUint32(offset);
                 offset += 4;
                 const type = String.fromCharCode(view.getUint8(offset), view.getUint8(offset+1), view.getUint8(offset+2), view.getUint8(offset+3));
                 offset += 4;
                 if(type === 'tEXt') {
                     const data = new Uint8Array(buf, offset, length);
                     const text = new TextDecoder().decode(data);
                     const split = text.indexOf('\0');
                     if(text.substring(0, split) === 'prompt') return JSON.parse(text.substring(split + 1));
                 }
                 offset += length + 4;
            }
            return null;
        }

        async function restoreMetadataFromDrop(e) {
            let file = null;
            if(e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                file = e.dataTransfer.files[0];
            } else {
                const url = e.dataTransfer.getData('text/plain');
                if(!url) return;
                const res = await fetch(url);
                file = await res.blob();
            }
            if(!file) return;

            const promptObj = await extractComfyMetadata(file);
            if(!promptObj) {
                alert("This PNG image does not contain AIManager/ComfyUI generative metadata.");
                return;
            }
            
            repopulateFromComfyWorkflow(promptObj);
        }

        async function repopulateFromComfyWorkflow(promptObj) {
            let cModel="", cSampler="", cScheduler="", cSteps=20, cCfg=7.0, cWidth=1024, cHeight=1024, cSeed=-1, cPrompt="", cNeg="";
            let cVae="none", cRefiner="none", cRefSteps=10, cDenoise=1.0;
            let cHiresEnable = false, cHiresUpType = "latent", cHiresSteps = 10, cHiresFactor = 1.5, cHiresDenoise = 0.4;
            let loras = [];
            
            for(const nodeId in promptObj) {
                const node = promptObj[nodeId];
                if(node.class_type === "CheckpointLoaderSimple") {
                    if(nodeId === "4") cModel = node.inputs.ckpt_name;
                    if(nodeId === "202") cRefiner = node.inputs.ckpt_name;
                }
                if(node.class_type === "VAELoader") cVae = node.inputs.vae_name;
                if(node.class_type === "EmptyLatentImage") {
                    cWidth = node.inputs.width;
                    cHeight = node.inputs.height;
                }
                if(node.class_type === "KSampler" || node.class_type === "KSamplerAdvanced") {
                    if(nodeId === "3") { // Base Sampler
                        cSeed = node.inputs.seed || node.inputs.noise_seed;
                        cSteps = node.inputs.steps;
                        cCfg = node.inputs.cfg;
                        cSampler = node.inputs.sampler_name;
                        cScheduler = node.inputs.scheduler;
                    }
                    if(nodeId === "205") cRefSteps = node.inputs.steps - cSteps; // KSamplerAdvanced Refiner
                    if(nodeId === "201" || nodeId === "305") { // Hires KSampler
                        cHiresEnable = true;
                        cHiresSteps = node.inputs.steps;
                        cHiresDenoise = node.inputs.denoise;
                    }
                }
                if(node.class_type === "CLIPTextEncode") {
                    if(nodeId === "6") cPrompt = node.inputs.text;
                    if(nodeId === "7") cNeg = node.inputs.text;
                }
                if(node.class_type === "LoraLoader") {
                    loras.push({ name: node.inputs.lora_name, weight: node.inputs.strength_model });
                }
                if(node.class_type === "LatentUpscaleBy") {
                    cHiresEnable = true; cHiresUpType = "latent"; cHiresFactor = node.inputs.scale_by;
                }
                if(node.class_type === "ImageScaleBy") {
                    cHiresEnable = true; cHiresUpType = "esrgan"; cHiresFactor = node.inputs.scale_by;
                }
            }
            
            // Assign fields safely checking bounds
            if(cModel) document.getElementById('inf-model').value = cModel;
            if(cRefiner) document.getElementById('inf-refiner').value = cRefiner;
            if(cVae) document.getElementById('inf-vae').value = cVae;
            
            document.getElementById('inf-prompt').value = cPrompt;
            document.getElementById('inf-negative').value = cNeg;
            document.getElementById('inf-seed').value = cSeed;
            document.getElementById('inf-steps').value = cSteps;
            document.getElementById('inf-refiner-steps').value = cRefSteps;
            document.getElementById('inf-cfg').value = cCfg;
            document.getElementById('inf-sampler').value = cSampler;
            document.getElementById('inf-scheduler').value = cScheduler;
            document.getElementById('inf-width').value = cWidth;
            document.getElementById('inf-height').value = cHeight;
            
            document.getElementById('inf-hires-enable').checked = cHiresEnable;
            if(cHiresEnable) {
                document.getElementById('inf-hires-upscaler').value = cHiresUpType;
                document.getElementById('inf-hires-steps').value = cHiresSteps;
                document.getElementById('inf-hires-factor').value = cHiresFactor;
                document.getElementById('inf-hires-denoise').value = cHiresDenoise;
                document.getElementById('inf-hires-container').style.display = 'flex';
            } else {
                document.getElementById('inf-hires-container').style.display = 'none';
            }
            
            // Show/hide refiner steps based on whether a refiner is selected
            const refinerStepsRow = document.getElementById('inf-refiner-steps-row');
            if(refinerStepsRow) refinerStepsRow.style.display = (cRefiner && cRefiner !== 'none') ? 'flex' : 'none';
            
            // Reset canvas zoom
            const canvasImg2 = document.getElementById('inf-canvas-img');
            if(canvasImg2) canvasImg2.style.transform = 'scale(1)';
            
            // Restore LoRAs natively
            // I-6 fix: Ensure availableLoras is populated before restoring
            if (loras.length > 0 && (!window.availableLoras || window.availableLoras.length === 0)) {
                try {
                    const lr = await fetch('/api/models?limit=5000');
                    const ld = await lr.json();
                    if (ld.models) window.availableLoras = ld.models.filter(m => m.vault_category === 'loras');
                } catch(_) {}
            }
            const lCont = document.getElementById('inf-lora-container');
            lCont.innerHTML = '';
            loras.forEach(l => {
                addLoraSlot();
                const rows = lCont.querySelectorAll('.lora-select');
                rows[rows.length-1].value = l.name;
                const weights = lCont.querySelectorAll('.lora-weight');
                weights[weights.length-1].value = l.weight;
            });
            
            alert("Settings successfully restored from image metadata!");
        }

