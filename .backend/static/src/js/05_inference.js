        /* ═══ Sprint 12 — Inpainting Canvas Engine ═══ */
        window._inpaintActive = false;
        window._inpaintTool = 'brush';
        window._inpaintBrushSize = 30;
        window._inpaintDrawing = false;
        window._inpaintLastPos = null;
        window._inpaintOpacity = 0.55;
        window._inpaintDenoise = 0.75;
        window._inpaintMaskBlur = 4;
        window._inpaintMaskPadding = 0;
        window._inpaintFillMode = 'original';
        /* Phase 1: Undo/redo state stack */
        window._inpaintHistory = [];
        window._inpaintHistoryIdx = -1;
        const _INPAINT_MAX_HISTORY = 20;

        function toggleInpaintMode() {
            const img = document.getElementById('inf-canvas-img');
            if (img.style.display === 'none' || !img.src) {
                showToast('Generate or load an image first before inpainting.');
                return;
            }
            /* Phase 1: Mutual exclusion — deactivate region mode first */
            if (!window._inpaintActive && window._regionMode) {
                toggleRegionMode();
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
                toggleBtn.classList.add('active');
                /* Phase 1: Show mode banner */
                showModeBanner('inpaint', '🖌️ INPAINT MODE — Paint mask on the image to define the inpainting area');
                /* Phase 1: Capture before snapshot for comparison */
                captureBeforeSnapshot();
                /* Phase 1: Initialize undo history with blank state */
                resetInpaintHistory();
                showBrushCursor();
            } else {
                canvas.classList.remove('active');
                toolbar.classList.remove('active');
                outpaint.classList.remove('active');
                toggleBtn.classList.remove('active');
                hideModeBanner();
                hideBrushCursor();
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

        /* ═══ Mask Post-Processing Utilities ═══ */

        /**
         * Morphological grow (dilate) or shrink (erode) on a binary mask.
         * Operates on the red channel of ImageData (white=255, black=0).
         * @param {ImageData} imageData - The mask image data
         * @param {number} w - Image width
         * @param {number} h - Image height
         * @param {number} radius - Positive=grow, negative=shrink
         */
        function applyMaskMorphology(imageData, w, h, radius) {
            if (radius === 0) return;
            const d = imageData.data;
            const abs_r = Math.abs(radius);
            const grow = radius > 0;
            // Work on a copy of the red channel (binary: 0 or 255)
            const src = new Uint8Array(w * h);
            for (let i = 0; i < w * h; i++) src[i] = d[i * 4] > 127 ? 255 : 0;
            const dst = new Uint8Array(src);

            for (let y = 0; y < h; y++) {
                for (let x = 0; x < w; x++) {
                    const idx = y * w + x;
                    if (grow) {
                        // Dilate: if any neighbor in radius is white, set white
                        if (src[idx] === 255) continue; // already white
                        let found = false;
                        for (let dy = -abs_r; dy <= abs_r && !found; dy++) {
                            for (let dx = -abs_r; dx <= abs_r && !found; dx++) {
                                if (dx * dx + dy * dy > abs_r * abs_r) continue; // circular kernel
                                const nx = x + dx, ny = y + dy;
                                if (nx >= 0 && nx < w && ny >= 0 && ny < h && src[ny * w + nx] === 255) found = true;
                            }
                        }
                        if (found) dst[idx] = 255;
                    } else {
                        // Erode: if any neighbor in radius is black, set black
                        if (src[idx] === 0) continue; // already black
                        let found = false;
                        for (let dy = -abs_r; dy <= abs_r && !found; dy++) {
                            for (let dx = -abs_r; dx <= abs_r && !found; dx++) {
                                if (dx * dx + dy * dy > abs_r * abs_r) continue;
                                const nx = x + dx, ny = y + dy;
                                if (nx < 0 || nx >= w || ny < 0 || ny >= h || src[ny * w + nx] === 0) found = true;
                            }
                        }
                        if (found) dst[idx] = 0;
                    }
                }
            }
            // Write back
            for (let i = 0; i < w * h; i++) {
                const v = dst[i];
                d[i * 4] = v; d[i * 4 + 1] = v; d[i * 4 + 2] = v; d[i * 4 + 3] = 255;
            }
        }

        /**
         * Two-pass box blur on a binary mask's red channel.
         * @param {ImageData} imageData
         * @param {number} w - Width
         * @param {number} h - Height
         * @param {number} radius - Blur radius in pixels
         */
        function applyBoxBlur(imageData, w, h, radius) {
            if (radius <= 0) return;
            const d = imageData.data;
            const buf = new Float32Array(w * h);
            // Read red channel into buffer
            for (let i = 0; i < w * h; i++) buf[i] = d[i * 4];

            const tmp = new Float32Array(w * h);
            const kern = radius * 2 + 1;

            // Horizontal pass
            for (let y = 0; y < h; y++) {
                let sum = 0;
                // Seed the window
                for (let x = -radius; x <= radius; x++) {
                    sum += buf[y * w + Math.max(0, Math.min(w - 1, x))];
                }
                for (let x = 0; x < w; x++) {
                    tmp[y * w + x] = sum / kern;
                    // Slide window
                    const removeX = Math.max(0, Math.min(w - 1, x - radius));
                    const addX = Math.max(0, Math.min(w - 1, x + radius + 1));
                    sum += buf[y * w + addX] - buf[y * w + removeX];
                }
            }
            // Vertical pass
            for (let x = 0; x < w; x++) {
                let sum = 0;
                for (let y = -radius; y <= radius; y++) {
                    sum += tmp[Math.max(0, Math.min(h - 1, y)) * w + x];
                }
                for (let y = 0; y < h; y++) {
                    buf[y * w + x] = sum / kern;
                    const removeY = Math.max(0, Math.min(h - 1, y - radius));
                    const addY = Math.max(0, Math.min(h - 1, y + radius + 1));
                    sum += tmp[addY * w + x] - tmp[removeY * w + x];
                }
            }
            // Write back — clamp to 0/255 binary after blur for clean mask edges
            for (let i = 0; i < w * h; i++) {
                const v = Math.round(Math.max(0, Math.min(255, buf[i])));
                d[i * 4] = v; d[i * 4 + 1] = v; d[i * 4 + 2] = v; d[i * 4 + 3] = 255;
            }
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

            // Post-process: mask grow/shrink (morphological dilation/erosion)
            const padding = window._inpaintMaskPadding || 0;
            if (padding !== 0) {
                applyMaskMorphology(dstData, exportCanvas.width, exportCanvas.height, padding);
            }

            // Post-process: client-side box blur for soft mask edges
            const blur = window._inpaintMaskBlur || 0;
            if (blur > 0) {
                applyBoxBlur(dstData, exportCanvas.width, exportCanvas.height, blur);
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
                    /* Phase 1: Push undo state BEFORE first stroke */
                    pushInpaintState();
                    window._inpaintDrawing = true;
                    window._inpaintLastPos = getCanvasPos(e);
                    drawInpaintDot(window._inpaintLastPos);
                });

                canvas.addEventListener('mousemove', (e) => {
                    /* Phase 1: Update brush cursor position */
                    updateBrushCursorPosition(e);
                    if (!window._inpaintDrawing) return;
                    const pos = getCanvasPos(e);
                    drawInpaintLine(window._inpaintLastPos, pos);
                    window._inpaintLastPos = pos;
                    // Update brush size label
                    const label = document.getElementById('inpaint-brush-size-label');
                    if (label) label.textContent = window._inpaintBrushSize;
                });

                canvas.addEventListener('mouseenter', () => {
                    if (window._inpaintActive) showBrushCursor();
                });

                canvas.addEventListener('mouseleave', () => {
                    hideBrushCursor();
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

                /* Phase 1: Watch canvas image for visibility changes → update outpaint buttons */
                const canvasImg = document.getElementById('inf-canvas-img');
                if (canvasImg) {
                    const observer = new MutationObserver(() => updateOutpaintVisibility());
                    observer.observe(canvasImg, { attributes: true, attributeFilter: ['style', 'src'] });
                    // Also check on image load
                    canvasImg.addEventListener('load', () => updateOutpaintVisibility());
                }

                /* Phase 3: Sync outpaint size selector with stored value */
                const storedSize = parseInt(localStorage.getItem('outpaint_extension_size') || '256');
                document.querySelectorAll('.outpaint-size-btn').forEach(b => {
                    b.classList.toggle('active', parseInt(b.textContent) === storedSize);
                });
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
            ctx.fillStyle = `rgba(255, 255, 255, ${window._inpaintOpacity})`;
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, window._inpaintBrushSize / 2, 0, Math.PI * 2);
            ctx.fill();
        }

        function drawInpaintLine(from, to) {
            const canvas = document.getElementById('inpaint-canvas');
            const ctx = canvas.getContext('2d');
            ctx.globalCompositeOperation = window._inpaintTool === 'eraser' ? 'destination-out' : 'source-over';
            ctx.strokeStyle = `rgba(255, 255, 255, ${window._inpaintOpacity})`;
            ctx.lineWidth = window._inpaintBrushSize;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.beginPath();
            ctx.moveTo(from.x, from.y);
            ctx.lineTo(to.x, to.y);
            ctx.stroke();
        }

        /* ═══ Phase 1 — Mode Banner Management ═══ */
        function showModeBanner(mode, text) {
            const banner = document.getElementById('inf-mode-banner');
            const textEl = document.getElementById('inf-mode-banner-text');
            if (!banner) return;
            banner.className = 'mode-banner active ' + mode;
            textEl.textContent = text;
        }

        function hideModeBanner() {
            const banner = document.getElementById('inf-mode-banner');
            if (banner) banner.className = 'mode-banner';
        }

        function exitActiveMode() {
            if (window._inpaintActive) toggleInpaintMode();
            else if (window._regionMode) toggleRegionMode();
            else if (window._compareActive) toggleCompareMode();
        }

        /* ═══ Phase 1 — Outpaint Visibility ═══ */
        function updateOutpaintVisibility() {
            const img = document.getElementById('inf-canvas-img');
            const outpaint = document.getElementById('outpaint-controls');
            if (!outpaint) return;
            if (img && img.src && img.style.display !== 'none') {
                outpaint.classList.add('has-image');
            } else {
                outpaint.classList.remove('has-image');
            }
        }

        /* ═══ Phase 1 — Custom Brush Cursor ═══ */
        function updateBrushCursor() {
            const cursor = document.getElementById('brush-cursor');
            if (!cursor || !window._inpaintActive) return;
            const size = window._inpaintBrushSize;
            cursor.style.width = size + 'px';
            cursor.style.height = size + 'px';
            cursor.className = window._inpaintTool === 'eraser' ? 'eraser-mode' : 'brush-mode';
        }

        function updateBrushCursorPosition(e) {
            const cursor = document.getElementById('brush-cursor');
            if (!cursor || !window._inpaintActive) return;
            const size = window._inpaintBrushSize;
            cursor.style.left = (e.clientX - size / 2) + 'px';
            cursor.style.top = (e.clientY - size / 2) + 'px';
        }

        function showBrushCursor() {
            const cursor = document.getElementById('brush-cursor');
            if (!cursor) return;
            cursor.style.display = 'block';
            updateBrushCursor();
        }

        function hideBrushCursor() {
            const cursor = document.getElementById('brush-cursor');
            if (cursor) cursor.style.display = 'none';
        }

        /* ═══ Phase 1 — Undo / Redo System ═══ */
        function pushInpaintState() {
            const canvas = document.getElementById('inpaint-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const state = ctx.getImageData(0, 0, canvas.width, canvas.height);
            // Trim future states when new action branches
            if (window._inpaintHistoryIdx < window._inpaintHistory.length - 1) {
                window._inpaintHistory = window._inpaintHistory.slice(0, window._inpaintHistoryIdx + 1);
            }
            window._inpaintHistory.push(state);
            // Cap at max
            if (window._inpaintHistory.length > _INPAINT_MAX_HISTORY) {
                window._inpaintHistory.shift();
            }
            window._inpaintHistoryIdx = window._inpaintHistory.length - 1;
            updateUndoRedoButtons();
        }

        function undoInpaint() {
            if (window._inpaintHistoryIdx <= 0) return;
            window._inpaintHistoryIdx--;
            restoreInpaintState(window._inpaintHistoryIdx);
            updateUndoRedoButtons();
        }

        function redoInpaint() {
            if (window._inpaintHistoryIdx >= window._inpaintHistory.length - 1) return;
            window._inpaintHistoryIdx++;
            restoreInpaintState(window._inpaintHistoryIdx);
            updateUndoRedoButtons();
        }

        function restoreInpaintState(idx) {
            const canvas = document.getElementById('inpaint-canvas');
            if (!canvas || !window._inpaintHistory[idx]) return;
            const ctx = canvas.getContext('2d');
            ctx.putImageData(window._inpaintHistory[idx], 0, 0);
        }

        function resetInpaintHistory() {
            const canvas = document.getElementById('inpaint-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            window._inpaintHistory = [ctx.getImageData(0, 0, canvas.width, canvas.height)];
            window._inpaintHistoryIdx = 0;
            updateUndoRedoButtons();
        }

        function updateUndoRedoButtons() {
            const undoBtn = document.getElementById('inpaint-undo-btn');
            const redoBtn = document.getElementById('inpaint-redo-btn');
            if (undoBtn) undoBtn.disabled = window._inpaintHistoryIdx <= 0;
            if (redoBtn) redoBtn.disabled = window._inpaintHistoryIdx >= window._inpaintHistory.length - 1;
        }

        /* ═══ Phase 1 — Keyboard Shortcuts (inpaint mode only) ═══ */
        document.addEventListener('keydown', (e) => {
            if (!window._inpaintActive) return;
            // Skip if user is typing in an input/textarea
            const tag = e.target.tagName.toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

            if (e.key === '[') {
                e.preventDefault();
                window._inpaintBrushSize = Math.max(5, window._inpaintBrushSize - 5);
                const slider = document.getElementById('inpaint-brush-size');
                if (slider) slider.value = window._inpaintBrushSize;
                document.getElementById('inpaint-brush-size-label').textContent = window._inpaintBrushSize;
                updateBrushCursor();
            } else if (e.key === ']') {
                e.preventDefault();
                window._inpaintBrushSize = Math.min(100, window._inpaintBrushSize + 5);
                const slider = document.getElementById('inpaint-brush-size');
                if (slider) slider.value = window._inpaintBrushSize;
                document.getElementById('inpaint-brush-size-label').textContent = window._inpaintBrushSize;
                updateBrushCursor();
            } else if (e.key.toLowerCase() === 'b' && !e.ctrlKey && !e.altKey) {
                e.preventDefault();
                setInpaintTool('brush');
                updateBrushCursor();
            } else if (e.key.toLowerCase() === 'e' && !e.ctrlKey && !e.altKey) {
                e.preventDefault();
                setInpaintTool('eraser');
                updateBrushCursor();
            } else if (e.key === 'z' && e.ctrlKey && !e.shiftKey) {
                e.preventDefault();
                undoInpaint();
            } else if (e.key === 'Z' && e.ctrlKey && e.shiftKey) {
                e.preventDefault();
                redoInpaint();
            }
        });

        /* ═══ Phase 1 — Before/After Comparison View ═══ */
        window._beforeSnapshot = null;   // data URL of the "before" image
        window._compareActive = false;
        window._compareFlipped = false;
        window._compareSideBySide = false;

        /**
         * Capture the current canvas image as the "before" snapshot.
         * Called automatically when inpaint/outpaint activates.
         */
        function captureBeforeSnapshot() {
            const img = document.getElementById('inf-canvas-img');
            if (!img || !img.src || img.style.display === 'none') return;
            // Draw to a temp canvas to get a data URL (handles blob and cross-origin urls)
            try {
                const c = document.createElement('canvas');
                c.width = img.naturalWidth;
                c.height = img.naturalHeight;
                c.getContext('2d').drawImage(img, 0, 0);
                window._beforeSnapshot = c.toDataURL('image/png');
            } catch (e) {
                // Fallback: use img.src directly (works for same-origin / data URLs)
                window._beforeSnapshot = img.src;
            }
            updateCompareButtonState();
        }

        /** Enable/disable the Compare toolbar button based on snapshot availability */
        function updateCompareButtonState() {
            const btn = document.getElementById('inf-compare-toggle');
            if (!btn) return;
            const hasAfter = (() => {
                const img = document.getElementById('inf-canvas-img');
                return img && img.src && img.style.display !== 'none';
            })();
            btn.disabled = !window._beforeSnapshot || !hasAfter;
        }

        /**
         * Toggle the Before/After comparison overlay on/off.
         */
        function toggleCompareMode() {
            if (!window._beforeSnapshot) {
                showToast('📷 No "before" snapshot captured. Generate, inpaint, or load an image first.');
                return;
            }
            const afterImg = document.getElementById('inf-canvas-img');
            if (!afterImg || !afterImg.src || afterImg.style.display === 'none') {
                showToast('🖼️ No "after" image available. Generate an image first.');
                return;
            }

            window._compareActive = !window._compareActive;
            const overlay = document.getElementById('compare-overlay');
            const toggleBtn = document.getElementById('inf-compare-toggle');

            if (window._compareActive) {
                // Exit inpaint/region modes if active
                if (window._inpaintActive) toggleInpaintMode();
                if (window._regionMode) toggleRegionMode();

                // Set image sources respecting flip state
                applyCompareImages();

                // Reset divider position
                const divider = document.getElementById('compare-divider');
                if (divider) divider.style.left = '50%';

                // Reset side-by-side
                overlay.classList.remove('side-by-side');
                window._compareSideBySide = false;
                const sbsBtn = document.getElementById('compare-sbs-btn');
                if (sbsBtn) sbsBtn.classList.remove('active');

                // Apply clip on the before image
                updateCompareClip(0.5);

                overlay.classList.add('active');
                toggleBtn.classList.add('active');
                showModeBanner('compare', '🔀 COMPARE MODE — Drag the divider to reveal before/after');
            } else {
                overlay.classList.remove('active');
                overlay.classList.remove('side-by-side');
                toggleBtn.classList.remove('active');
                window._compareFlipped = false;
                window._compareSideBySide = false;
                hideModeBanner();
            }
        }

        /** Set the correct src on before/after images based on flip state */
        function applyCompareImages() {
            const beforeImg = document.getElementById('compare-before-img');
            const afterImg = document.getElementById('compare-after-img');
            const canvasImg = document.getElementById('inf-canvas-img');
            const labelBefore = document.getElementById('compare-label-before');
            const labelAfter = document.getElementById('compare-label-after');

            if (window._compareFlipped) {
                beforeImg.src = canvasImg.src;
                afterImg.src = window._beforeSnapshot;
                if (labelBefore) labelBefore.textContent = 'AFTER';
                if (labelAfter) labelAfter.textContent = 'BEFORE';
            } else {
                beforeImg.src = window._beforeSnapshot;
                afterImg.src = canvasImg.src;
                if (labelBefore) labelBefore.textContent = 'BEFORE';
                if (labelAfter) labelAfter.textContent = 'AFTER';
            }
        }

        /** Update the clip-path on the before image based on divider position (0–1) */
        function updateCompareClip(ratio) {
            const beforeImg = document.getElementById('compare-before-img');
            if (!beforeImg) return;
            // Clip the before image to show only the left portion up to the divider
            const pct = (ratio * 100).toFixed(2);
            beforeImg.style.clipPath = `inset(0 ${(100 - ratio * 100).toFixed(2)}% 0 0)`;
        }

        /** Swap the before/after images */
        function flipCompareImages() {
            window._compareFlipped = !window._compareFlipped;
            applyCompareImages();
            // Re-apply clip at current divider position
            const divider = document.getElementById('compare-divider');
            const overlay = document.getElementById('compare-overlay');
            if (divider && overlay) {
                const rect = overlay.getBoundingClientRect();
                const divLeft = divider.offsetLeft + divider.offsetWidth / 2;
                updateCompareClip(divLeft / rect.width);
            }
            const flipBtn = document.getElementById('compare-flip-btn');
            if (flipBtn) flipBtn.classList.toggle('active', window._compareFlipped);
        }

        /** Toggle side-by-side vs overlay mode */
        function toggleCompareSideBySide() {
            window._compareSideBySide = !window._compareSideBySide;
            const overlay = document.getElementById('compare-overlay');
            const sbsBtn = document.getElementById('compare-sbs-btn');
            const divider = document.getElementById('compare-divider');
            const beforeImg = document.getElementById('compare-before-img');
            const afterImg = document.getElementById('compare-after-img');
            const labelBefore = document.getElementById('compare-label-before');
            const labelAfter = document.getElementById('compare-label-after');

            if (window._compareSideBySide) {
                // Transform to side-by-side flex layout
                overlay.classList.add('side-by-side');
                if (sbsBtn) sbsBtn.classList.add('active');
                // Hide the clip divider
                if (divider) divider.style.display = 'none';

                // Clear clip-path
                if (beforeImg) beforeImg.style.clipPath = '';

                // Re-position images into flex panes
                // Remove absolute positioning for side-by-side
                if (beforeImg) { beforeImg.style.position = 'relative'; beforeImg.style.width = '100%'; beforeImg.style.height = '100%'; }
                if (afterImg) { afterImg.style.position = 'relative'; afterImg.style.width = '100%'; afterImg.style.height = '100%'; }

                // Wrap each image in a pane div (if not already done)
                if (!overlay.querySelector('.compare-pane')) {
                    const paneA = document.createElement('div');
                    paneA.className = 'compare-pane';
                    const paneB = document.createElement('div');
                    paneB.className = 'compare-pane';
                    const divSbs = document.createElement('div');
                    divSbs.className = 'compare-divider-sbs';

                    // Move labels into panes
                    paneA.appendChild(beforeImg);
                    if (labelBefore) paneA.appendChild(labelBefore);
                    paneB.appendChild(afterImg);
                    if (labelAfter) paneB.appendChild(labelAfter);

                    // Insert before toolbar
                    const toolbar = document.getElementById('compare-toolbar');
                    overlay.insertBefore(paneA, toolbar);
                    overlay.insertBefore(divSbs, toolbar);
                    overlay.insertBefore(paneB, toolbar);
                }
            } else {
                // Revert to overlay/clip mode
                overlay.classList.remove('side-by-side');
                if (sbsBtn) sbsBtn.classList.remove('active');
                if (divider) divider.style.display = '';

                // Remove pane wrappers — move images and labels back to overlay root
                const panes = overlay.querySelectorAll('.compare-pane');
                const divSbs = overlay.querySelector('.compare-divider-sbs');
                const toolbar = document.getElementById('compare-toolbar');

                if (panes.length > 0) {
                    // Move children back
                    overlay.insertBefore(beforeImg, toolbar);
                    overlay.insertBefore(afterImg, toolbar);
                    overlay.insertBefore(divider, toolbar);
                    if (labelBefore) overlay.insertBefore(labelBefore, toolbar);
                    if (labelAfter) overlay.insertBefore(labelAfter, toolbar);
                    panes.forEach(p => p.remove());
                    if (divSbs) divSbs.remove();
                }

                // Restore absolute positioning
                if (beforeImg) { beforeImg.style.position = ''; beforeImg.style.width = ''; beforeImg.style.height = ''; }
                if (afterImg) { afterImg.style.position = ''; afterImg.style.width = ''; afterImg.style.height = ''; }

                // Re-apply clip
                const rect = overlay.getBoundingClientRect();
                const divLeft = divider.offsetLeft + divider.offsetWidth / 2;
                updateCompareClip(divLeft / rect.width);
            }
        }

        /** Draggable compare divider setup */
        (function setupCompareDivider() {
            document.addEventListener('DOMContentLoaded', () => {
                const divider = document.getElementById('compare-divider');
                if (!divider) return;

                divider.addEventListener('mousedown', (e) => {
                    if (!window._compareActive || window._compareSideBySide) return;
                    e.preventDefault();
                    divider.classList.add('dragging');

                    const overlay = document.getElementById('compare-overlay');
                    const rect = overlay.getBoundingClientRect();

                    function onMove(ev) {
                        const x = Math.max(0, Math.min(ev.clientX - rect.left, rect.width));
                        const ratio = x / rect.width;
                        divider.style.left = (ratio * 100) + '%';
                        updateCompareClip(ratio);
                    }
                    function onUp() {
                        divider.classList.remove('dragging');
                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);
                    }
                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });
            });
        })();

        /** Keyboard shortcut: C to toggle compare mode (outside input fields) */
        document.addEventListener('keydown', (e) => {
            const tag = e.target.tagName.toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
            // Only active when Inference tab is visible
            const infView = document.getElementById('view-inference');
            if (!infView || infView.style.display === 'none') return;

            if (e.key.toLowerCase() === 'c' && !e.ctrlKey && !e.altKey && !e.shiftKey) {
                e.preventDefault();
                toggleCompareMode();
            }
        });

        /* ═══ Phase 2 — Non-Destructive Session Editing ═══ */
        window._editHistory = [];        // Array of { imageUrl, params, timestamp, label }
        window._editHistoryIndex = -1;   // Current position (-1 = no entries)
        const _EDIT_HISTORY_MAX = 30;    // Memory cap

        /**
         * Add a new entry to the edit history timeline.
         * Called automatically when a new image is generated or an inpaint/outpaint result lands.
         * If the user is viewing a non-latest entry, forward history is truncated (branch).
         */
        function addEditHistoryEntry(imageUrl, params, label) {
            if (!imageUrl) return;

            // Branch: if not at the end, truncate forward history
            if (window._editHistoryIndex >= 0 && window._editHistoryIndex < window._editHistory.length - 1) {
                window._editHistory = window._editHistory.slice(0, window._editHistoryIndex + 1);
            }

            const entry = {
                imageUrl: imageUrl,
                params: params || {},
                timestamp: Date.now(),
                label: label || `Step ${window._editHistory.length + 1}`
            };

            window._editHistory.push(entry);

            // Memory cap: evict oldest
            while (window._editHistory.length > _EDIT_HISTORY_MAX) {
                window._editHistory.shift();
            }

            window._editHistoryIndex = window._editHistory.length - 1;

            renderEditTimeline();
        }

        /**
         * Navigate through the edit history.
         * delta: -1 for back, +1 for forward
         */
        function stepEditHistory(delta) {
            const newIdx = window._editHistoryIndex + delta;
            if (newIdx < 0 || newIdx >= window._editHistory.length) return;
            jumpToEditHistoryEntry(newIdx);
        }

        /**
         * Jump to a specific history entry by index.
         */
        function jumpToEditHistoryEntry(idx) {
            if (idx < 0 || idx >= window._editHistory.length) return;

            // If compare mode is active, exit it
            if (window._compareActive) toggleCompareMode();

            const entry = window._editHistory[idx];
            const prevIdx = window._editHistoryIndex;
            window._editHistoryIndex = idx;

            // Update the canvas image
            const canvasImg = document.getElementById('inf-canvas-img');
            if (canvasImg && entry.imageUrl) {
                canvasImg.src = entry.imageUrl;
                canvasImg.style.display = 'block';
                document.getElementById('inf-canvas-empty').style.display = 'none';
            }

            // Phase 1 integration: set before snapshot to the previous entry
            if (idx > 0) {
                window._beforeSnapshot = window._editHistory[idx - 1].imageUrl;
            }
            updateCompareButtonState();

            // Update outpaint visibility
            if (typeof updateOutpaintVisibility === 'function') updateOutpaintVisibility();

            renderEditTimeline();
        }

        /**
         * Render the edit timeline strip in the DOM.
         */
        function renderEditTimeline() {
            const timeline = document.getElementById('edit-timeline');
            const strip = document.getElementById('edit-timeline-strip');
            const countEl = document.getElementById('edit-timeline-count');
            const stepLabel = document.getElementById('edit-step-label');
            const prevBtn = document.getElementById('edit-prev-btn');
            const nextBtn = document.getElementById('edit-next-btn');

            if (!timeline || !strip) return;

            const len = window._editHistory.length;

            if (len === 0) {
                timeline.classList.remove('has-entries');
                strip.innerHTML = '';
                return;
            }

            timeline.classList.add('has-entries');

            // Update header
            if (countEl) countEl.textContent = `(${window._editHistoryIndex + 1}/${len})`;
            if (stepLabel) stepLabel.textContent = `${window._editHistoryIndex + 1} / ${len}`;

            // Update nav button states
            if (prevBtn) prevBtn.disabled = window._editHistoryIndex <= 0;
            if (nextBtn) nextBtn.disabled = window._editHistoryIndex >= len - 1;

            // Render thumbnails
            strip.innerHTML = '';
            window._editHistory.forEach((entry, i) => {
                const item = document.createElement('div');
                item.className = 'edit-timeline-item' + (i === window._editHistoryIndex ? ' active' : '');

                const img = document.createElement('img');
                img.src = entry.imageUrl;
                img.alt = entry.label;
                img.loading = 'lazy';

                const badge = document.createElement('span');
                badge.className = 'step-badge';
                badge.textContent = i + 1;

                item.appendChild(img);
                item.appendChild(badge);

                // Tooltip
                const time = new Date(entry.timestamp);
                const timeStr = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                item.title = `${entry.label}\n${timeStr}`;

                // Click to jump
                item.addEventListener('click', () => jumpToEditHistoryEntry(i));

                strip.appendChild(item);
            });

            // Auto-scroll to active item
            const activeItem = strip.querySelector('.edit-timeline-item.active');
            if (activeItem) {
                activeItem.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
            }
        }

        /** Keyboard shortcuts: [ and ] for history navigation */
        document.addEventListener('keydown', (e) => {
            const tag = e.target.tagName.toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
            const infView = document.getElementById('view-inference');
            if (!infView || infView.style.display === 'none') return;

            if (e.key === '[' && !e.ctrlKey && !e.altKey) {
                e.preventDefault();
                stepEditHistory(-1);
            } else if (e.key === ']' && !e.ctrlKey && !e.altKey) {
                e.preventDefault();
                stepEditHistory(1);
            }
        });

        /* ═══ Sprint 12 — Outpainting ═══ */
        function setOutpaintSize(size, btn) {
            localStorage.setItem('outpaint_extension_size', String(size));
            // Update active button styling
            document.querySelectorAll('.outpaint-size-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            // Update direction button tooltips
            document.querySelectorAll('.outpaint-btn').forEach(b => {
                const dir = b.textContent.trim();
                const dirMap = {'↑': 'Up', '↓': 'Down', '←': 'Left', '→': 'Right'};
                if (dirMap[dir]) b.title = `Extend ${dirMap[dir]} (${size}px)`;
            });
            showToast(`📐 Outpaint extension: ${size}px`);
        }

        function outpaint(direction) {
            const img = document.getElementById('inf-canvas-img');
            if (!img.src || img.style.display === 'none') return;
            /* Phase 1: Capture before snapshot before extending canvas */
            captureBeforeSnapshot();

            const extendSize = parseInt(localStorage.getItem('outpaint_extension_size') || '256');
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
        window._regionBaseRatio = 0.0;
        const ZONE_COLORS = ['#ef4444','#3b82f6','#10b981','#f59e0b','#8b5cf6','#ec4899','#06b6d4','#f97316'];

        function toggleRegionMode() {
            /* Phase 1: Mutual exclusion — deactivate inpaint mode first */
            if (!window._regionMode && window._inpaintActive) {
                toggleInpaintMode();
            }
            window._regionMode = !window._regionMode;
            const editor = document.getElementById('region-editor');
            const toolbar = document.getElementById('region-toolbar');
            const toggleBtn = document.getElementById('inf-region-toggle');

            if (window._regionMode) {
                editor.classList.add('active');
                toolbar.classList.add('active');
                toggleBtn.classList.add('active');
                /* Phase 1: Show mode banner */
                showModeBanner('region', '📐 REGION MODE — Drag zones to define regional prompts');
                // Auto-add first zone if empty
                if (window._regionZones.length === 0) addRegionZone();
            } else {
                editor.classList.remove('active');
                toolbar.classList.remove('active');
                toggleBtn.classList.remove('active');
                hideModeBanner();
            }
        }

        function addRegionZone(preset) {
            const editor = document.getElementById('region-editor');
            const idx = window._regionZones.length;
            const color = ZONE_COLORS[idx % ZONE_COLORS.length];

            // Determine position — from preset or auto-grid
            let zoneLeft, zoneTop, zoneW, zoneH;
            if (preset) {
                zoneLeft = preset.x; zoneTop = preset.y;
                zoneW = preset.w; zoneH = preset.h;
            } else {
                const cols = Math.ceil(Math.sqrt(idx + 1));
                const rows = Math.ceil((idx + 1) / cols);
                const col = idx % cols;
                const row = Math.floor(idx / cols);
                zoneW = 100 / cols;
                zoneH = 100 / rows;
                zoneLeft = col * zoneW;
                zoneTop = row * zoneH;
            }

            const zone = document.createElement('div');
            zone.className = 'region-zone';
            zone.style.borderColor = color;
            zone.style.background = color + '18'; /* Semi-transparent color fill */
            zone.style.left = zoneLeft + '%';
            zone.style.top = zoneTop + '%';
            zone.style.width = zoneW + '%';
            zone.style.height = zoneH + '%';
            zone.dataset.zoneIdx = idx;
            zone.dataset.strength = '1.0';

            zone.innerHTML = `
                <div class="zone-header" style="background:${color}55;">
                    <span class="zone-label"><span class="zone-color-dot" style="background:${color}"></span>Zone ${idx + 1}</span>
                    <span class="zone-close" onclick="removeRegionZone(${idx})">✕</span>
                </div>
                <div class="zone-body">
                    <textarea class="zone-pos" placeholder="Describe this region..."></textarea>
                    <textarea class="zone-neg" placeholder="Negative (optional)..." style="font-size:0.7rem; min-height:22px; max-height:44px; opacity:0.7; border-top:1px dashed ${color}44;"></textarea>
                    <div class="zone-strength">
                        <span>Str</span>
                        <input type="range" min="0" max="150" value="100" oninput="this.nextElementSibling.textContent=((+this.value)/100).toFixed(1); this.closest('.region-zone').dataset.strength=((+this.value)/100).toFixed(1);">
                        <span>1.0</span>
                    </div>
                </div>
                <div class="zone-resize">◢</div>
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
                    zone.style.width = Math.max(60, startWidth + (ev.clientX - startMX)) + 'px';
                    zone.style.height = Math.max(60, startHeight + (ev.clientY - startMY)) + 'px';
                }
                function onUp() {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
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
                    const lbl = z.element.querySelector('.zone-label');
                    if (lbl) {
                        const dot = lbl.querySelector('.zone-color-dot');
                        lbl.textContent = '';
                        if (dot) lbl.appendChild(dot);
                        lbl.appendChild(document.createTextNode(`Zone ${i + 1}`));
                    }
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

        /* ═══ Phase 2 — Layout Presets ═══ */
        function applyRegionLayout(layout) {
            clearAllRegions();
            const presets = {
                '2col': [
                    { x: 0, y: 0, w: 49.5, h: 100 },
                    { x: 50.5, y: 0, w: 49.5, h: 100 }
                ],
                '3col': [
                    { x: 0, y: 0, w: 32.5, h: 100 },
                    { x: 33.75, y: 0, w: 32.5, h: 100 },
                    { x: 67.5, y: 0, w: 32.5, h: 100 }
                ],
                '2row': [
                    { x: 0, y: 0, w: 100, h: 49 },
                    { x: 0, y: 51, w: 100, h: 49 }
                ],
                '2x2': [
                    { x: 0, y: 0, w: 49.5, h: 49 },
                    { x: 50.5, y: 0, w: 49.5, h: 49 },
                    { x: 0, y: 51, w: 49.5, h: 49 },
                    { x: 50.5, y: 51, w: 49.5, h: 49 }
                ]
            };
            const zones = presets[layout];
            if (!zones) return;
            zones.forEach(p => addRegionZone(p));
            showToast(`📐 Applied ${layout.replace('col', '-column').replace('row', '-row').replace('2x2', '2×2 grid')} layout`);
        }

        function updateZoneCount() {
            const el = document.getElementById('region-zone-count');
            if (el) el.textContent = `${window._regionZones.length} zone${window._regionZones.length !== 1 ? 's' : ''}`;
        }

        function getRegionData() {
            // Returns normalized region data for backend translators
            // Each zone: { prompt, negative, x, y, w, h, strength } (0-1 normalized to canvas dimensions)
            if (!window._regionMode || window._regionZones.length === 0) return null;
            const editor = document.getElementById('region-editor');
            const editorW = editor.offsetWidth;
            const editorH = editor.offsetHeight;
            if (!editorW || !editorH) return null;

            const regions = [];
            for (const z of window._regionZones) {
                const el = z.element;
                const prompt = el.querySelector('.zone-pos')?.value || el.querySelector('textarea')?.value || '';
                if (!prompt.trim()) continue;
                const negative = el.querySelector('.zone-neg')?.value || '';
                regions.push({
                    prompt: prompt.trim(),
                    negative: negative.trim(),
                    x: el.offsetLeft / editorW,
                    y: el.offsetTop / editorH,
                    w: el.offsetWidth / editorW,
                    h: el.offsetHeight / editorH,
                    strength: parseFloat(el.dataset.strength || '1.0')
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
                showToast('⚠️ X axis requires a parameter and at least one value.');
                return;
            }

            const statusEl = document.getElementById('xyz-status');
            const gridEl = document.getElementById('xyz-grid');
            const basePayload = buildGenerationPayload();  // Audit #4: Use raw payload — no wildcard resolution for controlled sweeps

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
            const basePayload = buildGenerationPayload();  // Audit #4: Use raw payload — no wildcard resolution for controlled sweeps
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
            // Audit #12: Wrapped in try/catch with bounds check for malformed PNGs
            try {
                const buf = await blob.arrayBuffer();
                const view = new DataView(buf);
                let offset = 8;
                while(offset + 8 < view.byteLength) {
                     const length = view.getUint32(offset);
                     offset += 4;
                     if (offset + 4 + length + 4 > view.byteLength) break;  // Audit #12: bounds check
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
            } catch(e) {
                console.warn('[Metadata] Failed to parse PNG metadata:', e);
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
                showToast('⚠️ This PNG image does not contain AIManager/ComfyUI generative metadata.');
                return;
            }
            
            repopulateFromComfyWorkflow(promptObj);
        }

        async function repopulateFromComfyWorkflow(promptObj) {
            let cModel="", cSampler="", cScheduler="", cSteps=20, cCfg=7.0, cWidth=1024, cHeight=1024, cSeed=-1, cPrompt="", cNeg="";
            let cVae="none", cRefiner="none", cRefSteps=10, cDenoise=1.0;
            let cHiresEnable = false, cHiresUpType = "latent", cHiresSteps = 10, cHiresFactor = 1.5, cHiresDenoise = 0.4;
            let loras = [];
            // Audit #2: FLUX-specific fields
            let isFlux = false, cFluxUnet = "", cFluxClipL = "", cFluxT5 = "", cFluxGuidance = 3.5;
            
            for(const nodeId in promptObj) {
                const node = promptObj[nodeId];
                // SD/SDXL checkpoint
                if(node.class_type === "CheckpointLoaderSimple") {
                    if(nodeId === "4") cModel = node.inputs.ckpt_name;
                    if(nodeId === "202") cRefiner = node.inputs.ckpt_name;
                }
                // Audit #2: FLUX UNETLoader
                if(node.class_type === "UNETLoader") {
                    isFlux = true;
                    cFluxUnet = node.inputs.unet_name || '';
                }
                // Audit #2: FLUX DualCLIPLoader
                if(node.class_type === "DualCLIPLoader") {
                    cFluxClipL = node.inputs.clip_name2 || '';
                    cFluxT5 = node.inputs.clip_name1 || '';
                }
                // Audit #2: FluxGuidance
                if(node.class_type === "FluxGuidance") {
                    cFluxGuidance = node.inputs.guidance || 3.5;
                }
                if(node.class_type === "VAELoader") cVae = node.inputs.vae_name;
                if(node.class_type === "EmptyLatentImage") {
                    cWidth = node.inputs.width;
                    cHeight = node.inputs.height;
                }
                if(node.class_type === "KSampler" || node.class_type === "KSamplerAdvanced") {
                    // SD/SDXL base sampler is node "3", FLUX base sampler is node "18"
                    if(nodeId === "3" || nodeId === "18") {
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
                    // SD/SDXL prompt nodes: 6/7, FLUX prompt nodes: 15/16
                    if(nodeId === "6" || nodeId === "15") cPrompt = node.inputs.text;
                    if(nodeId === "7" || nodeId === "16") cNeg = node.inputs.text;
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
            
            // Audit #2: Set model type dropdown for FLUX workflows
            if (isFlux) {
                const modelTypeSel = document.getElementById('inf-model-type');
                if (modelTypeSel) {
                    // Try to guess schnell vs dev from unet name
                    const unetLower = cFluxUnet.toLowerCase();
                    modelTypeSel.value = unetLower.includes('schnell') ? 'flux-schnell' : 'flux-dev';
                    // Trigger visibility update for FLUX fields
                    modelTypeSel.dispatchEvent(new Event('change'));
                }
                // Populate FLUX-specific dropdowns
                const unetEl = document.getElementById('inf-flux-unet');
                if (unetEl && cFluxUnet) unetEl.value = cFluxUnet;
                const clipEl = document.getElementById('inf-flux-clip-l');
                if (clipEl && cFluxClipL) clipEl.value = cFluxClipL;
                const t5El = document.getElementById('inf-flux-t5xxl');
                if (t5El && cFluxT5) t5El.value = cFluxT5;
                const guidanceEl = document.getElementById('inf-flux-guidance');
                if (guidanceEl) guidanceEl.value = cFluxGuidance;
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
            
            showToast(isFlux ? '✅ FLUX workflow settings restored!' : '✅ Settings restored from image metadata!');
        }

        /* ═══ Task 2.1: Custom Workflow Import ═══════════════════ */
        async function importCustomWorkflow(fileOrBlob) {
            if (!fileOrBlob) return;
            try {
                const text = await fileOrBlob.text();
                let parsed;
                try {
                    parsed = JSON.parse(text);
                } catch(e) {
                    showToast('❌ Invalid JSON file — could not parse.');
                    return;
                }

                // Structural validation: must have a 'prompt' key with node objects
                const workflow = parsed.prompt || parsed;
                if (typeof workflow !== 'object' || Array.isArray(workflow)) {
                    showToast('❌ Invalid workflow — expected a ComfyUI prompt object.');
                    return;
                }

                // Validate each node has class_type + inputs
                const nodeIds = Object.keys(workflow);
                if (nodeIds.length === 0) {
                    showToast('❌ Empty workflow — no nodes found.');
                    return;
                }
                for (const nodeId of nodeIds) {
                    const node = workflow[nodeId];
                    if (!node || typeof node.class_type !== 'string' || typeof node.inputs !== 'object') {
                        showToast(`❌ Invalid node "${nodeId}" — missing class_type or inputs.`);
                        return;
                    }
                }

                showToast('⚡ Running custom workflow — no parameter validation applied.');

                // Send directly to ComfyUI, bypassing build_comfy_workflow
                const btn = document.getElementById('inf-generate-btn');
                const txt = document.getElementById('inf-generate-text');
                const fill = document.getElementById('inf-progress-fill');
                if (btn) btn.disabled = true;
                if (txt) txt.innerText = 'Running Custom Workflow...';

                const res = await fetch('/api/comfy_proxy', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        endpoint: '/prompt',
                        payload: { prompt: workflow }
                    })
                });
                const data = await res.json();

                if (data.error) {
                    showToast('❌ ComfyUI rejected workflow: ' + data.error);
                    if (btn) btn.disabled = false;
                    if (txt) txt.innerText = 'Generate Image';
                    return;
                }

                const promptId = data.prompt_id;
                if (!promptId) {
                    showToast('❌ No prompt_id returned — check ComfyUI logs.');
                    if (btn) btn.disabled = false;
                    if (txt) txt.innerText = 'Generate Image';
                    return;
                }

                // Poll history for results, reusing the same pattern as executeInference
                window.currentPromptId = promptId;
                if (fill) { fill.style.width = '50%'; fill.classList.add('progress-pulsing'); }

                const pollInterval = setInterval(async () => {
                    try {
                        const histRes = await fetch('/api/comfy_proxy', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({endpoint: `/history/${promptId}`})
                        });
                        const histData = await histRes.json();
                        if (histData[promptId]) {
                            clearInterval(pollInterval);
                            const outputs = histData[promptId].outputs;
                            for (const nodeId in outputs) {
                                if (outputs[nodeId].images && outputs[nodeId].images.length > 0) {
                                    outputs[nodeId].images.forEach((imgData, idx) => {
                                        const imgUrl = `/api/comfy_image?filename=${imgData.filename}&subfolder=${imgData.subfolder}&type=${imgData.type}&t=${Date.now()}`;
                                        if (idx === 0) {
                                            const canvasImg = document.getElementById('inf-canvas-img');
                                            canvasImg.src = imgUrl;
                                            canvasImg.style.display = 'block';
                                            document.getElementById('inf-canvas-empty').style.display = 'none';
                                        }
                                        addToGallery(imgUrl, { prompt: '(custom workflow)', custom_workflow: true });
                                    });
                                    break;
                                }
                            }
                            if (btn) btn.disabled = false;
                            if (txt) txt.innerText = 'Generate Image';
                            if (fill) { fill.style.width = '100%'; fill.classList.remove('progress-pulsing'); setTimeout(() => fill.style.width = '0%', 800); }
                            showToast('✅ Custom workflow completed!');
                        }
                    } catch(_) {}
                }, 1500);

            } catch(e) {
                showToast('❌ Workflow import error: ' + e.message);
            }
        }

        /* ═══ Feature 1: Prompt Enhancement Keyboard Shortcuts ═══
           Ctrl+Up/Down adjusts emphasis (word:weight) on selected text
           or the word under the caret. Matches Stability Matrix behavior. */

        function adjustEmphasis(textarea, delta) {
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const text = textarea.value;

            let selStart, selEnd;

            if (start !== end) {
                // Text is selected
                selStart = start;
                selEnd = end;
            } else {
                // No selection — find word under caret
                selStart = start;
                selEnd = start;
                // Expand left to word boundary
                while (selStart > 0 && /[^\s,()]/.test(text[selStart - 1])) selStart--;
                // Expand right to word boundary
                while (selEnd < text.length && /[^\s,()]/.test(text[selEnd])) selEnd++;
                if (selStart === selEnd) return; // Nothing under caret
            }

            const selected = text.substring(selStart, selEnd);

            // Check if already wrapped in (text:N.N) — look outward
            const beforeSel = text.substring(0, selStart);
            const afterSel = text.substring(selEnd);

            // Pattern: text is already "(selected:1.2)" or we're inside one
            const existingWrap = selected.match(/^\((.+?):([\d.]+)\)$/);
            if (existingWrap) {
                // Already wrapped — adjust weight
                const innerText = existingWrap[1];
                let weight = parseFloat(existingWrap[2]) + delta;
                weight = Math.round(weight * 10) / 10; // Fix float precision
                weight = Math.max(0.1, Math.min(2.0, weight));

                let replacement;
                if (Math.abs(weight - 1.0) < 0.01) {
                    // Weight is 1.0 — remove wrapper
                    replacement = innerText;
                } else {
                    replacement = `(${innerText}:${weight.toFixed(1)})`;
                }

                textarea.value = text.substring(0, selStart) + replacement + text.substring(selEnd);
                textarea.selectionStart = selStart;
                textarea.selectionEnd = selStart + replacement.length;
                textarea.dispatchEvent(new Event('input'));
                return;
            }

            // Check if selection is inside an existing emphasis wrapper
            // Look backwards for an unclosed ( and forwards for the matching )
            const outerMatch = findOuterEmphasis(text, selStart, selEnd);
            if (outerMatch) {
                let weight = parseFloat(outerMatch.weight) + delta;
                weight = Math.round(weight * 10) / 10;
                weight = Math.max(0.1, Math.min(2.0, weight));

                let replacement;
                if (Math.abs(weight - 1.0) < 0.01) {
                    replacement = outerMatch.inner;
                } else {
                    replacement = `(${outerMatch.inner}:${weight.toFixed(1)})`;
                }

                textarea.value = text.substring(0, outerMatch.start) + replacement + text.substring(outerMatch.end);
                // Reposition cursor inside the replacement
                const cursorOffset = selStart - outerMatch.start;
                const newCursor = outerMatch.start + Math.min(cursorOffset, replacement.length);
                textarea.selectionStart = outerMatch.start;
                textarea.selectionEnd = outerMatch.start + replacement.length;
                textarea.dispatchEvent(new Event('input'));
                return;
            }

            // Not wrapped — add new wrapper
            const newWeight = delta > 0 ? 1.1 : 0.9;
            const wrapped = `(${selected}:${newWeight.toFixed(1)})`;
            textarea.value = text.substring(0, selStart) + wrapped + text.substring(selEnd);
            textarea.selectionStart = selStart;
            textarea.selectionEnd = selStart + wrapped.length;
            textarea.dispatchEvent(new Event('input'));
        }

        function findOuterEmphasis(text, selStart, selEnd) {
            // Walk backwards from selStart to find '('
            let depth = 0;
            let parenStart = -1;
            for (let i = selStart - 1; i >= 0; i--) {
                if (text[i] === ')') depth++;
                if (text[i] === '(') {
                    if (depth === 0) { parenStart = i; break; }
                    depth--;
                }
            }
            if (parenStart < 0) return null;

            // Walk forward from the paren to find matching ')'
            depth = 0;
            let parenEnd = -1;
            for (let i = parenStart; i < text.length; i++) {
                if (text[i] === '(') depth++;
                if (text[i] === ')') {
                    depth--;
                    if (depth === 0) { parenEnd = i + 1; break; }
                }
            }
            if (parenEnd < 0) return null;

            const full = text.substring(parenStart, parenEnd);
            const match = full.match(/^\((.+?):([\d.]+)\)$/);
            if (!match) return null;

            return { start: parenStart, end: parenEnd, inner: match[1], weight: match[2] };
        }

        // Wire keyboard handlers on DOMContentLoaded
        document.addEventListener('DOMContentLoaded', () => {
            ['inf-prompt', 'inf-negative'].forEach(id => {
                const el = document.getElementById(id);
                if (!el) return;
                el.addEventListener('keydown', (e) => {
                    if (e.ctrlKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                        e.preventDefault();
                        const delta = e.key === 'ArrowUp' ? 0.1 : -0.1;
                        adjustEmphasis(el, delta);
                    }
                });
            });
        });


        /* ═══ Feature 2: Prompt Syntax Highlighting ═══
           Renders a colored overlay behind the transparent textarea.
           Highlights: (emphasis), [deemphasis], <lora:...>, {wildcards}, # comments */

        function highlightPromptSyntax(text) {
            // Escape HTML first
            let html = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');

            // Order matters — process comments first (entire line), then inline tokens

            // 1. Comments: # until end of line
            html = html.replace(/(#[^\n]*)/g, '<span class="prompt-comment">$1</span>');

            // 2. Networks: <lora:name:weight> or <embedding:name>
            html = html.replace(/(&lt;(?:lora|lyco|embedding):([^&]*?)(?::([\d.]+))?&gt;)/g, (match, full, name, weight) => {
                if (weight) {
                    return `<span class="prompt-network">&lt;${full.includes('lora') ? 'lora' : full.includes('lyco') ? 'lyco' : 'embedding'}:${name}:<span class="prompt-weight">${weight}</span>&gt;</span>`;
                }
                return `<span class="prompt-network">${full}</span>`;
            });

            // 3. Emphasis with weight: (text:1.2)
            html = html.replace(/\(([^()]+?):([\d.]+)\)/g, (match, inner, weight) => {
                return `<span class="prompt-emphasis">(${inner}:<span class="prompt-weight">${weight}</span>)</span>`;
            });

            // 4. Simple emphasis: (text) — but not already highlighted
            html = html.replace(/\(([^():<]+?)\)/g, (match, inner) => {
                // Skip if this is inside an already-highlighted span
                return `<span class="prompt-emphasis">(${inner})</span>`;
            });

            // 5. De-emphasis: [text]
            html = html.replace(/\[([^\[\]]+?)\]/g, '<span class="prompt-deemphasis">[$1]</span>');

            // 6. Wildcards: {a|b|c}
            html = html.replace(/\{([^{}]+?)\}/g, '<span class="prompt-wildcard">{$1}</span>');

            return html;
        }

        let _highlightDebounce = {};
        function updatePromptHighlight(textareaId) {
            clearTimeout(_highlightDebounce[textareaId]);
            _highlightDebounce[textareaId] = setTimeout(() => {
                const textarea = document.getElementById(textareaId);
                const highlight = document.getElementById(textareaId + '-highlight');
                if (!textarea || !highlight) return;

                const text = textarea.value;
                if (!text.trim()) {
                    // Empty — show placeholder through transparent textarea
                    highlight.innerHTML = '';
                    textarea.classList.remove('highlighting-active');
                    return;
                }

                textarea.classList.add('highlighting-active');
                highlight.innerHTML = highlightPromptSyntax(text);

                // Sync scroll position
                highlight.scrollTop = textarea.scrollTop;
                highlight.scrollLeft = textarea.scrollLeft;
            }, 50);
        }

        // Sync scroll events + resize observer
        document.addEventListener('DOMContentLoaded', () => {
            ['inf-prompt', 'inf-negative'].forEach(id => {
                const textarea = document.getElementById(id);
                const highlight = document.getElementById(id + '-highlight');
                if (!textarea || !highlight) return;

                textarea.addEventListener('scroll', () => {
                    highlight.scrollTop = textarea.scrollTop;
                    highlight.scrollLeft = textarea.scrollLeft;
                });

                // Keep highlight layer sized to match textarea on resize (drag handle)
                if (typeof ResizeObserver !== 'undefined') {
                    new ResizeObserver(() => {
                        highlight.style.height = textarea.offsetHeight + 'px';
                    }).observe(textarea);
                }

                // Initial render
                updatePromptHighlight(id);
            });
        });


        /* ═══ Feature 3: Custom Dimension Presets ═══
           User-saved W×H presets stored in localStorage.
           Includes model-type-aware defaults. */

        const _DEFAULT_DIM_PRESETS = {
            sd:   [{ label: 'Square 512', w: 512, h: 512 }, { label: 'Portrait 512×768', w: 512, h: 768 }, { label: 'Landscape 768×512', w: 768, h: 512 }],
            sdxl: [{ label: 'Square 1024', w: 1024, h: 1024 }, { label: 'Portrait 832×1216', w: 832, h: 1216 }, { label: 'Landscape 1216×832', w: 1216, h: 832 }],
            flux: [{ label: 'Square 1024', w: 1024, h: 1024 }, { label: 'Portrait 768×1344', w: 768, h: 1344 }, { label: 'Cinematic 1344×768', w: 1344, h: 768 }]
        };

        function getDimPresets() {
            try {
                const raw = localStorage.getItem('dim_presets');
                if (raw) return JSON.parse(raw);
            } catch (_) {}
            return [];
        }

        function saveDimPresets(presets) {
            localStorage.setItem('dim_presets', JSON.stringify(presets));
        }

        function toggleDimPresetsPopover() {
            const pop = document.getElementById('inf-dim-presets-popover');
            const isOpen = pop.style.display !== 'none';
            pop.style.display = isOpen ? 'none' : 'block';
            if (!isOpen) renderDimPresets();
        }

        function renderDimPresets() {
            const list = document.getElementById('inf-dim-preset-list');
            const userPresets = getDimPresets();
            const modelType = document.getElementById('inf-model-type')?.value || 'sdxl';
            const modelKey = modelType.includes('flux') ? 'flux' : modelType === 'sd' ? 'sd' : 'sdxl';
            const defaults = _DEFAULT_DIM_PRESETS[modelKey] || [];

            let html = '';

            // Default presets for current model type
            if (defaults.length > 0) {
                html += `<div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Defaults (${modelKey.toUpperCase()})</div>`;
                defaults.forEach(p => {
                    html += `<div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; background:rgba(99,102,241,0.08); border-radius:6px; cursor:pointer; transition:background 0.15s;" onmouseenter="this.style.background='rgba(99,102,241,0.2)'" onmouseleave="this.style.background='rgba(99,102,241,0.08)'" onclick="applyDimPreset(${p.w},${p.h})">
                        <span style="font-size:0.82rem; color:#e2e8f0;">${escHtml(p.label)}</span>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${p.w}×${p.h}</span>
                    </div>`;
                });
            }

            // User presets
            if (userPresets.length > 0) {
                html += `<div style="font-size:0.7rem; color:var(--text-muted); margin-top:8px; margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px;">Your Presets</div>`;
                userPresets.forEach((p, i) => {
                    html += `<div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; background:rgba(251,191,36,0.08); border-radius:6px; cursor:pointer; transition:background 0.15s;" onmouseenter="this.style.background='rgba(251,191,36,0.2)'" onmouseleave="this.style.background='rgba(251,191,36,0.08)'" onclick="applyDimPreset(${p.w},${p.h})">
                        <span style="font-size:0.82rem; color:#e2e8f0;">${escHtml(p.label)}</span>
                        <div style="display:flex; align-items:center; gap:6px;">
                            <span style="font-size:0.75rem; color:var(--text-muted);">${p.w}×${p.h}</span>
                            <button onclick="event.stopPropagation(); removeDimPreset(${i})" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.9rem; padding:0;" title="Remove">✕</button>
                        </div>
                    </div>`;
                });
            }

            if (!html) {
                html = '<div style="text-align:center; color:var(--text-muted); font-size:0.82rem; padding:8px;">No presets saved yet.</div>';
            }

            list.innerHTML = html;
        }

        function addCurrentDimsAsPreset() {
            const w = parseInt(document.getElementById('inf-width')?.value || '1024');
            const h = parseInt(document.getElementById('inf-height')?.value || '1024');
            const label = prompt(`Save ${w}×${h} as preset:\n\nEnter a label:`);
            if (!label || !label.trim()) return;

            const presets = getDimPresets();
            presets.push({ label: label.trim(), w, h });
            saveDimPresets(presets);
            renderDimPresets();
            showToast(`⭐ Saved preset: ${label.trim()} (${w}×${h})`);
        }

        function removeDimPreset(idx) {
            const presets = getDimPresets();
            if (idx >= 0 && idx < presets.length) {
                presets.splice(idx, 1);
                saveDimPresets(presets);
                renderDimPresets();
            }
        }

        function applyDimPreset(w, h) {
            document.getElementById('inf-width').value = w;
            document.getElementById('inf-height').value = h;
            // Deactivate aspect ratio pills since we're using a custom size
            document.querySelectorAll('.aspect-pill').forEach(p => {
                p.style.background = 'var(--surface-hover)';
                p.style.color = 'var(--text-muted)';
                p.style.borderColor = 'var(--border)';
            });
            // Highlight custom button
            const customBtn = document.getElementById('inf-custom-dims-btn');
            if (customBtn) {
                customBtn.style.background = 'var(--primary)';
                customBtn.style.color = '#fff';
                customBtn.style.borderColor = 'var(--primary)';
            }
            window._activeAspectRatio = null;
            window._activeAspectPill = null;
            showToast(`📐 Applied ${w}×${h}`);
        }


        /* ═══ Feature 4: Project Save/Load (.avproj) ═══
           Save the complete generation workspace to a portable JSON file.
           Load restores all parameters, model selections, and LoRA configs. */

        function saveProject() {
            const payload = buildGenerationPayload();
            const modelType = document.getElementById('inf-model-type')?.value || 'sdxl';

            const project = {
                version: 1,
                format: 'avproj',
                created: new Date().toISOString(),
                app: 'AetherVault Inference Studio',
                model_type: modelType,
                payload: payload,
                ui_state: {
                    hires_enable: document.getElementById('inf-hires-enable')?.checked || false,
                    hires_upscaler: document.getElementById('inf-hires-upscaler')?.value || 'latent_bilinear',
                    cn_enable: document.getElementById('inf-cn-enable')?.checked || false,
                    cn_model: document.getElementById('inf-cn-model')?.value || '',
                    cn_strength: parseFloat(document.getElementById('inf-cn-strength')?.value || '1.0'),
                    scheduler: document.getElementById('inf-scheduler')?.value || 'karras'
                }
            };

            // Generate filename
            const promptSnippet = (payload.prompt || 'untitled').substring(0, 30).replace(/[^a-zA-Z0-9]/g, '_');
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19);
            const filename = `${promptSnippet}_${timestamp}.avproj`;

            // Download as file
            const blob = new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);

            showToast(`📁 Project saved: ${filename}`);
        }

        async function loadProject(file) {
            if (!file) return;
            try {
                const text = await file.text();
                let project;
                try {
                    project = JSON.parse(text);
                } catch (e) {
                    showToast('❌ Invalid project file — could not parse JSON.');
                    return;
                }

                // Validate structure
                if (!project.payload) {
                    showToast('❌ Invalid project — missing payload data.');
                    return;
                }

                const p = project.payload;
                const ui = project.ui_state || {};

                // Restore model type first (affects field visibility)
                if (project.model_type) {
                    const modelTypeSel = document.getElementById('inf-model-type');
                    if (modelTypeSel) {
                        modelTypeSel.value = project.model_type;
                        onModelTypeChange(project.model_type);
                    }
                }

                // Restore basic fields
                const setVal = (id, val) => {
                    const el = document.getElementById(id);
                    if (el && val !== undefined && val !== null) el.value = val;
                };

                setVal('inf-prompt', p.prompt);
                setVal('inf-negative', p.negative_prompt);
                setVal('inf-seed', p.seed);
                setVal('inf-steps', p.steps);
                setVal('inf-cfg', p.cfg_scale);
                setVal('inf-width', p.width);
                setVal('inf-height', p.height);
                setVal('inf-sampler', p.sampler_name);
                setVal('inf-scheduler', ui.scheduler || p.scheduler);
                setVal('inf-batch-size', p.batch_size || 1);

                // Model checkpoint
                if (p.override_settings?.sd_model_checkpoint) {
                    setVal('inf-model', p.override_settings.sd_model_checkpoint);
                }

                // VAE + Refiner
                setVal('inf-vae', p.vae);
                setVal('inf-refiner', p.refiner);
                setVal('inf-refiner-steps', p.refiner_steps);
                const refinerStepsRow = document.getElementById('inf-refiner-steps-row');
                if (refinerStepsRow) refinerStepsRow.style.display = (p.refiner && p.refiner !== 'none') ? 'flex' : 'none';

                // FLUX fields
                if (project.model_type?.includes('flux')) {
                    setVal('inf-flux-unet', p.flux_unet);
                    setVal('inf-flux-clip-l', p.flux_clip_l);
                    setVal('inf-flux-t5xxl', p.flux_t5xxl);
                    setVal('inf-flux-guidance', p.flux_guidance);
                }

                // Hires Fix
                const hiresCheck = document.getElementById('inf-hires-enable');
                if (hiresCheck) hiresCheck.checked = ui.hires_enable || false;
                const hiresContainer = document.getElementById('inf-hires-container');
                if (hiresContainer) hiresContainer.style.display = ui.hires_enable ? 'flex' : 'none';
                if (p.hires) {
                    setVal('inf-hires-factor', p.hires.factor);
                    setVal('inf-hires-denoise', p.hires.denoise);
                    setVal('inf-hires-steps', p.hires.steps);
                    setVal('inf-hires-upscaler', p.hires.upscaler || ui.hires_upscaler);
                }

                // ControlNet
                const cnCheck = document.getElementById('inf-cn-enable');
                if (cnCheck) cnCheck.checked = ui.cn_enable || false;
                if (ui.cn_model) setVal('inf-cn-model', ui.cn_model);
                if (ui.cn_strength) setVal('inf-cn-strength', ui.cn_strength);

                // LoRAs
                if (p.loras && p.loras.length > 0) {
                    // Ensure availableLoras is loaded
                    if (!window.availableLoras || window.availableLoras.length === 0) {
                        try {
                            const lr = await fetch('/api/models?limit=5000');
                            const ld = await lr.json();
                            if (ld.models) window.availableLoras = ld.models.filter(m => m.vault_category === 'loras');
                        } catch (_) {}
                    }
                    const lCont = document.getElementById('inf-lora-container');
                    lCont.innerHTML = '';
                    p.loras.forEach(l => {
                        addLoraSlot();
                        const rows = lCont.querySelectorAll('.lora-select');
                        rows[rows.length - 1].value = l.name;
                        const weights = lCont.querySelectorAll('.lora-weight');
                        weights[weights.length - 1].value = l.weight;
                    });
                }

                // Update highlights
                updatePromptHighlight('inf-prompt');
                updatePromptHighlight('inf-negative');
                if (typeof updateTokenCounter === 'function') updateTokenCounter();

                showToast(`📂 Project loaded: ${file.name}`);
            } catch (e) {
                showToast('❌ Failed to load project: ' + e.message);
            }
        }


        /* ═══ Feature 5: Prompt Auto-Complete (Tag Database) ═══
           Curated Stable Diffusion tag database with dropdown suggestions.
           Matches SM's auto-complete but uses a lightweight client-side approach. */

        const _SD_TAGS = [
            // Quality
            'masterpiece','best quality','high quality','highres','absurdres','ultra-detailed','extremely detailed',
            'official art','8k','4k','uhd','hdr','photorealistic','photo realistic','realistic','hyperrealistic',
            'cinematic lighting','volumetric lighting','studio lighting','dramatic lighting','rim lighting',
            'depth of field','bokeh','lens flare','chromatic aberration','film grain','sharp focus','intricate detail',
            // Style
            'anime','manga','illustration','digital painting','concept art','oil painting','watercolor',
            'sketch','pencil drawing','charcoal','pixel art','3d render','cgi','fantasy art','dark fantasy',
            'art nouveau','art deco','impressionism','surrealism','abstract','minimalist','retro','vintage',
            'cyberpunk','steampunk','dieselpunk','solarpunk','vaporwave','synthwave','retrowave',
            // Subject
            'portrait','full body','upper body','cowboy shot','close-up','headshot','from above','from below',
            'from side','from behind','dynamic angle','wide shot','establishing shot','pov','profile',
            '1girl','1boy','solo','couple','group','crowd','chibi','mecha','monster','creature','animal',
            'landscape','cityscape','seascape','interior','exterior','architecture','ruins','castle',
            // Face/Expression
            'beautiful face','detailed face','detailed eyes','beautiful eyes','expressive eyes','glowing eyes',
            'heterochromia','slit pupils','crying','laughing','smiling','grinning','blushing','serious',
            'surprised','angry','sad','determined','confident','shy','embarrassed','scared',
            // Hair
            'long hair','short hair','medium hair','very long hair','ponytail','twintails','braids','bun',
            'bob cut','pixie cut','side ponytail','hair ornament','flower in hair','hair ribbon','bangs',
            'blonde hair','black hair','brown hair','red hair','blue hair','white hair','silver hair',
            'pink hair','purple hair','green hair','multicolored hair','gradient hair','streaked hair',
            // Clothing
            'dress','shirt','skirt','pants','jacket','coat','uniform','school uniform','military uniform',
            'armor','kimono','yukata','suit','hoodie','sweater','cloak','cape','scarf','gloves','boots',
            'hat','crown','tiara','glasses','sunglasses','mask','wings','tail','horns','halo',
            // Nature/Environment
            'nature','forest','mountains','ocean','beach','desert','snow','rain','sunset','sunrise',
            'night sky','starry sky','aurora','clouds','fog','mist','underwater','space','galaxy','nebula',
            'cherry blossoms','flowers','garden','field','meadow','waterfall','river','lake','cave','volcano',
            // Composition/Effects
            'detailed background','simple background','white background','black background','gradient background',
            'blurry background','scenic','panorama','symmetry','rule of thirds','golden ratio',
            'magic','particles','sparkles','petals','floating','reflection','shadow','silhouette',
            'explosion','fire','ice','lightning','smoke','wind','energy','aura','glowing',
            // Negative (commonly used in negatives)
            'worst quality','low quality','normal quality','jpeg artifacts','signature','watermark',
            'username','blurry','bad anatomy','bad hands','missing fingers','extra digit','fewer digits',
            'cropped','out of frame','deformed','disfigured','mutation','mutated','ugly','duplicate',
            'morbid','error','poorly drawn face','poorly drawn hands','extra limbs','extra fingers',
            'missing limbs','fused fingers','too many fingers','long neck','text','logo','censored',
            // Technical
            'raw photo','dslr','nikon','canon','35mm','50mm','85mm','wide angle','telephoto',
            'macro','tilt shift','long exposure','double exposure','motion blur','radial blur',
            'color grading','desaturated','monochrome','sepia','cross-process','split toning'
        ];

        // Tag index for fast prefix lookup
        const _tagIndex = {};
        _SD_TAGS.forEach(tag => {
            const key = tag.substring(0, 2).toLowerCase();
            if (!_tagIndex[key]) _tagIndex[key] = [];
            _tagIndex[key].push(tag);
        });

        let _acDropdown = null;
        let _acActive = -1;
        let _acMatches = [];
        let _acTarget = null;

        function getAutoCompleteDropdown() {
            if (_acDropdown) return _acDropdown;
            const dd = document.createElement('div');
            dd.id = 'inf-autocomplete-dropdown';
            dd.style.cssText = `
                position: absolute; z-index: 100; background: var(--bg-color);
                border: 1px solid var(--border); border-radius: 8px;
                max-height: 200px; overflow-y: auto; display: none;
                box-shadow: 0 8px 24px rgba(0,0,0,0.5); min-width: 200px;
            `;
            document.body.appendChild(dd);
            _acDropdown = dd;
            return dd;
        }

        function showAutoComplete(textarea) {
            const text = textarea.value;
            const cursor = textarea.selectionStart;

            // Find the current word being typed (after last comma or start)
            let wordStart = cursor;
            while (wordStart > 0 && text[wordStart - 1] !== ',' && text[wordStart - 1] !== '\n') wordStart--;
            const word = text.substring(wordStart, cursor).trim().toLowerCase();

            if (word.length < 2) {
                hideAutoComplete();
                return;
            }

            // Search tags
            const prefix = word.substring(0, 2);
            const candidates = _tagIndex[prefix] || [];
            _acMatches = candidates.filter(t => t.toLowerCase().startsWith(word)).slice(0, 10);

            // Also search full list for non-prefix matches
            if (_acMatches.length < 5) {
                const extra = _SD_TAGS.filter(t =>
                    t.toLowerCase().includes(word) && !_acMatches.includes(t)
                ).slice(0, 10 - _acMatches.length);
                _acMatches.push(...extra);
            }

            if (_acMatches.length === 0) {
                hideAutoComplete();
                return;
            }

            _acTarget = textarea;
            _acActive = -1;
            const dd = getAutoCompleteDropdown();

            dd.innerHTML = _acMatches.map((tag, i) => {
                const highlighted = tag.replace(new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<b>$1</b>');
                return `<div class="ac-item" data-idx="${i}" style="padding:6px 12px; cursor:pointer; font-size:0.85rem; color:#e2e8f0; transition:background 0.1s;"
                    onmouseenter="this.style.background='rgba(99,102,241,0.2)'"
                    onmouseleave="this.style.background='${i === _acActive ? 'rgba(99,102,241,0.15)' : 'transparent'}'"
                    onclick="acceptAutoComplete(${i})">${highlighted}</div>`;
            }).join('');

            // Position dropdown below the textarea cursor
            const rect = textarea.getBoundingClientRect();
            dd.style.left = rect.left + 'px';
            dd.style.top = (rect.bottom + 2) + 'px';
            dd.style.width = rect.width + 'px';
            dd.style.display = 'block';
        }

        function hideAutoComplete() {
            const dd = getAutoCompleteDropdown();
            dd.style.display = 'none';
            _acMatches = [];
            _acActive = -1;
            _acTarget = null;
        }

        function acceptAutoComplete(idx) {
            if (!_acTarget || idx < 0 || idx >= _acMatches.length) return;
            const textarea = _acTarget;
            const text = textarea.value;
            const cursor = textarea.selectionStart;

            // Find the current word boundaries
            let wordStart = cursor;
            while (wordStart > 0 && text[wordStart - 1] !== ',' && text[wordStart - 1] !== '\n') wordStart--;
            // Trim leading space
            while (wordStart < cursor && text[wordStart] === ' ') wordStart++;

            const replacement = _acMatches[idx];
            const before = text.substring(0, wordStart);
            const after = text.substring(cursor);

            textarea.value = before + replacement + after;
            const newCursor = wordStart + replacement.length;
            textarea.selectionStart = newCursor;
            textarea.selectionEnd = newCursor;
            textarea.focus();
            textarea.dispatchEvent(new Event('input'));

            hideAutoComplete();
        }

        // Wire auto-complete on prompt textareas
        document.addEventListener('DOMContentLoaded', () => {
            ['inf-prompt', 'inf-negative'].forEach(id => {
                const el = document.getElementById(id);
                if (!el) return;

                let _acDebounce = null;
                el.addEventListener('input', () => {
                    clearTimeout(_acDebounce);
                    _acDebounce = setTimeout(() => showAutoComplete(el), 150);
                });

                el.addEventListener('keydown', (e) => {
                    if (_acMatches.length === 0) return;
                    const dd = getAutoCompleteDropdown();
                    if (dd.style.display === 'none') return;

                    if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        _acActive = Math.min(_acActive + 1, _acMatches.length - 1);
                        updateACHighlight();
                    } else if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        _acActive = Math.max(_acActive - 1, 0);
                        updateACHighlight();
                    } else if (e.key === 'Tab' || e.key === 'Enter') {
                        if (_acActive >= 0) {
                            e.preventDefault();
                            acceptAutoComplete(_acActive);
                        }
                    } else if (e.key === 'Escape') {
                        hideAutoComplete();
                    }
                });

                el.addEventListener('blur', () => {
                    // Delay to allow click on dropdown item
                    setTimeout(hideAutoComplete, 200);
                });
            });
        });

        function updateACHighlight() {
            const dd = getAutoCompleteDropdown();
            dd.querySelectorAll('.ac-item').forEach((item, i) => {
                item.style.background = i === _acActive ? 'rgba(99,102,241,0.15)' : 'transparent';
            });
            // Scroll active item into view
            const activeItem = dd.querySelector(`.ac-item[data-idx="${_acActive}"]`);
            if (activeItem) activeItem.scrollIntoView({ block: 'nearest' });
        }


        /* ═══ Feature 6: PNG Metadata Embedding (Post-Generation) ═══
           After generation completes, optionally embed generation parameters
           into the output PNG as tEXt chunks (A1111 compatible format).
           Uses the backend /api/gallery/embed_metadata endpoint. */

        async function embedMetadataInImage(imageUrl, payload) {
            try {
                const res = await fetch('/api/gallery/embed_metadata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image_url: imageUrl,
                        params: payload
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    return data.file_path;
                }
                console.warn('Metadata embedding failed:', data.message);
                return null;
            } catch (e) {
                console.warn('Metadata embedding error:', e);
                return null;
            }
        }


        /* ═══ Feature 7: Image Grid Assembly ═══
           Composes multiple batch output images into a single grid image.
           Useful for comparing batch results side by side. */

        async function assembleImageGrid(imageUrls, columns) {
            if (!imageUrls || imageUrls.length === 0) {
                showToast('⚠️ No images to assemble.');
                return;
            }

            columns = columns || Math.ceil(Math.sqrt(imageUrls.length));
            const rows = Math.ceil(imageUrls.length / columns);
            const padding = 4;

            // Load all images
            const images = await Promise.all(imageUrls.map(url => {
                return new Promise((resolve, reject) => {
                    const img = new Image();
                    img.crossOrigin = 'anonymous';
                    img.onload = () => resolve(img);
                    img.onerror = () => reject(new Error(`Failed to load: ${url}`));
                    img.src = url;
                });
            }));

            // Calculate cell size (use largest dimensions)
            const cellW = Math.max(...images.map(i => i.naturalWidth));
            const cellH = Math.max(...images.map(i => i.naturalHeight));

            // Create canvas
            const canvas = document.createElement('canvas');
            canvas.width = columns * cellW + (columns + 1) * padding;
            canvas.height = rows * cellH + (rows + 1) * padding;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // Draw images into grid
            images.forEach((img, idx) => {
                const col = idx % columns;
                const row = Math.floor(idx / columns);
                const x = padding + col * (cellW + padding);
                const y = padding + row * (cellH + padding);

                // Center the image within the cell
                const scale = Math.min(cellW / img.naturalWidth, cellH / img.naturalHeight);
                const drawW = img.naturalWidth * scale;
                const drawH = img.naturalHeight * scale;
                const offsetX = (cellW - drawW) / 2;
                const offsetY = (cellH - drawH) / 2;

                ctx.drawImage(img, x + offsetX, y + offsetY, drawW, drawH);
            });

            // Add grid label
            ctx.fillStyle = 'rgba(255,255,255,0.4)';
            ctx.font = '12px sans-serif';
            ctx.fillText(`AetherVault Grid — ${images.length} images`, padding + 4, canvas.height - 8);

            // Download
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `av_grid_${Date.now()}.png`;
            a.click();
            URL.revokeObjectURL(url);

            showToast(`🖼️ Grid assembled: ${images.length} images (${columns}×${rows})`);
        }

        // Quick-access: assemble grid from current session gallery strip
        function assembleSessionGrid() {
            const gallery = document.getElementById('inf-gallery');
            if (!gallery) return;
            const imgs = gallery.querySelectorAll('[data-img-url]');
            if (imgs.length === 0) {
                showToast('⚠️ No images in the session gallery to assemble.');
                return;
            }
            const urls = Array.from(imgs).map(el => el.dataset.imgUrl);
            assembleImageGrid(urls);
        }


        /* ═══ Feature 8: Prompt Wildcards ═══
           Expands {option1|option2|option3} syntax to a random selection at generation time.
           Supports nested wildcards and multiple wildcards per prompt.
           Processing happens client-side before sending to ComfyUI. */

        function expandWildcards(text) {
            // Match {option1|option2|...} patterns (supports nesting by iterating)
            let result = text;
            let iterations = 0;
            const maxIterations = 10;  // Prevent infinite loops from malformed input

            while (result.includes('{') && result.includes('|') && iterations < maxIterations) {
                result = result.replace(/\{([^{}]+)\}/g, (match, inner) => {
                    if (!inner.includes('|')) return match;  // Not a wildcard, skip
                    const options = inner.split('|').map(o => o.trim()).filter(o => o.length > 0);
                    if (options.length === 0) return '';
                    return options[Math.floor(Math.random() * options.length)];
                });
                iterations++;
            }
            return result;
        }

        // Monkey-patch: Intercept buildGenerationPayload to expand wildcards
        if (typeof buildGenerationPayload === 'function') {
            const _origBuildPayload = buildGenerationPayload;
            // Note: We can't override directly since it's declared with function keyword.
            // Instead, we'll expand wildcards in executeInference before payload is sent.
        }

        // Hook into generation: expand wildcards in the prompt before sending
        // This is called from the enhanced executeInference flow
        function preprocessPromptWildcards(payload) {
            if (payload.prompt) {
                const original = payload.prompt;
                payload.prompt = expandWildcards(payload.prompt);
                if (payload.prompt !== original) {
                    console.debug('[Wildcards] Expanded:', original, '→', payload.prompt);
                }
            }
            if (payload.negative_prompt) {
                payload.negative_prompt = expandWildcards(payload.negative_prompt);
            }
            return payload;
        }


        /* ═══ Feature 9: Enhanced Seed Tools ═══
           - Lock seed toggle (prevent -1 randomization)
           - Reuse last seed button
           - Quick seed variation (+1, -1 from current) */

        window._lastUsedSeed = null;
        window._seedLocked = false;

        function toggleSeedLock() {
            window._seedLocked = !window._seedLocked;
            const btn = document.getElementById('inf-seed-lock');
            if (btn) {
                btn.innerText = window._seedLocked ? '🔒' : '🔓';
                btn.title = window._seedLocked ? 'Seed locked — will reuse same seed' : 'Seed unlocked — random each time';
                btn.style.background = window._seedLocked ? 'rgba(99,102,241,0.3)' : 'var(--surface-hover)';
            }
            const seedInput = document.getElementById('inf-seed');
            if (window._seedLocked && seedInput && seedInput.value === '-1' && window._lastUsedSeed) {
                seedInput.value = window._lastUsedSeed;
            }
        }

        function reuseLastSeed() {
            if (window._lastUsedSeed !== null) {
                document.getElementById('inf-seed').value = window._lastUsedSeed;
                showToast(`🌱 Reusing seed: ${window._lastUsedSeed}`);
            } else {
                showToast('⚠️ No previous seed to reuse.');
            }
        }

        function seedVariation(delta) {
            const seedInput = document.getElementById('inf-seed');
            const current = parseInt(seedInput.value);
            if (current <= 0 && window._lastUsedSeed) {
                seedInput.value = window._lastUsedSeed + delta;
            } else if (current > 0) {
                seedInput.value = current + delta;
            } else {
                showToast('⚠️ Generate an image first to create seed variations.');
                return;
            }
            showToast(`🌱 Seed variation: ${seedInput.value}`);
        }

        // Track the seed used in each generation
        function trackGeneratedSeed(seed) {
            if (seed && seed > 0) {
                window._lastUsedSeed = seed;
            }
        }


        /* ═══ Feature 10: Prompt Style Presets ═══
           Save and load reusable prompt templates.
           Stores positive + negative prompt pairs in localStorage. */

        function getPromptPresets() {
            try { return JSON.parse(localStorage.getItem('prompt_presets') || '[]'); }
            catch { return []; }
        }

        function savePromptPresets(presets) {
            localStorage.setItem('prompt_presets', JSON.stringify(presets));
        }

        function saveCurrentAsPreset() {
            const prompt = document.getElementById('inf-prompt')?.value || '';
            const negative = document.getElementById('inf-negative')?.value || '';
            if (!prompt.trim()) {
                showToast('⚠️ Enter a prompt before saving a preset.');
                return;
            }

            const name = window.prompt('Name this preset:');
            if (!name || !name.trim()) return;

            const presets = getPromptPresets();
            presets.push({ name: name.trim(), prompt, negative, created: Date.now() });
            savePromptPresets(presets);
            showToast(`💾 Preset "${name.trim()}" saved!`);
            renderPromptPresets();
        }

        function loadPromptPreset(idx) {
            const presets = getPromptPresets();
            if (idx < 0 || idx >= presets.length) return;
            const p = presets[idx];
            document.getElementById('inf-prompt').value = p.prompt;
            document.getElementById('inf-negative').value = p.negative || '';

            // Trigger syntax highlighting update
            ['inf-prompt', 'inf-negative'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.dispatchEvent(new Event('input'));
            });

            showToast(`📋 Loaded preset: ${p.name}`);
            closePromptPresets();
        }

        function deletePromptPreset(idx) {
            const presets = getPromptPresets();
            if (idx < 0 || idx >= presets.length) return;
            const name = presets[idx].name;
            presets.splice(idx, 1);
            savePromptPresets(presets);
            showToast(`🗑️ Deleted preset: ${name}`);
            renderPromptPresets();
        }

        function renderPromptPresets() {
            const container = document.getElementById('inf-prompt-presets-list');
            if (!container) return;
            const presets = getPromptPresets();
            if (presets.length === 0) {
                container.innerHTML = '<div style="color:var(--text-muted); font-size:0.8rem; text-align:center; padding:16px;">No presets saved yet.<br>Write a prompt and click "+ Save Current".</div>';
                return;
            }
            container.innerHTML = presets.map((p, i) => `
                <div style="display:flex; align-items:center; gap:8px; padding:8px 12px; border-radius:8px; cursor:pointer; transition:background 0.15s; border:1px solid var(--border);"
                     onmouseenter="this.style.background='rgba(99,102,241,0.1)'" onmouseleave="this.style.background='transparent'">
                    <div style="flex:1; min-width:0;" onclick="loadPromptPreset(${i})">
                        <div style="font-weight:600; font-size:0.85rem; color:#e2e8f0;">${escHtml(p.name)}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;">${escHtml(p.prompt.substring(0, 60))}${p.prompt.length > 60 ? '…' : ''}</div>
                    </div>
                    <button onclick="event.stopPropagation(); deletePromptPreset(${i})" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.9rem; padding:2px 4px;" title="Delete preset">✕</button>
                </div>
            `).join('');
        }

        function togglePromptPresets() {
            const popover = document.getElementById('inf-prompt-presets-popover');
            if (!popover) return;
            const visible = popover.style.display === 'block';
            popover.style.display = visible ? 'none' : 'block';
            if (!visible) renderPromptPresets();
        }

        function closePromptPresets() {
            const popover = document.getElementById('inf-prompt-presets-popover');
            if (popover) popover.style.display = 'none';
        }


        /* ═══ Feature 11: Gallery Lightbox Enhancements ═══
           - Copy generation parameters to clipboard
           - Download image with embedded metadata
           - Send to img2img mode */

        function copyGenerationParams() {
            const g = _glCurrentItem;
            if (!g) { showToast('⚠️ No image selected.'); return; }

            const parts = [];
            if (g.prompt) parts.push(g.prompt);
            if (g.negative) parts.push(`Negative prompt: ${g.negative}`);

            const meta = [];
            if (g.steps) meta.push(`Steps: ${g.steps}`);
            if (g.sampler) meta.push(`Sampler: ${g.sampler}`);
            if (g.cfg) meta.push(`CFG scale: ${g.cfg}`);
            if (g.seed) meta.push(`Seed: ${g.seed}`);
            if (g.width && g.height) meta.push(`Size: ${g.width}x${g.height}`);
            if (g.model) meta.push(`Model: ${g.model}`);
            if (meta.length) parts.push(meta.join(', '));

            navigator.clipboard.writeText(parts.join('\n')).then(() => {
                showToast('📋 Parameters copied to clipboard!');
            }).catch(() => {
                showToast('⚠️ Copy failed — check clipboard permissions.');
            });
        }

        async function downloadWithMetadata() {
            const g = _glCurrentItem;
            if (!g) { showToast('⚠️ No image selected.'); return; }

            showToast('⏳ Embedding metadata...');

            try {
                const res = await fetch('/api/gallery/embed_metadata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image_url: g.image_path,
                        params: {
                            prompt: g.prompt || '',
                            negative_prompt: g.negative || '',
                            steps: g.steps,
                            sampler_name: g.sampler,
                            cfg_scale: g.cfg,
                            seed: g.seed,
                            width: g.width,
                            height: g.height,
                            override_settings: { sd_model_checkpoint: g.model || '' }
                        }
                    })
                });
                const data = await res.json();
                if (data.status === 'success' && data.file_path) {
                    // Download the file with metadata
                    const a = document.createElement('a');
                    a.href = g.image_path;
                    a.download = data.filename || `av_${Date.now()}.png`;
                    a.click();
                    showToast(`✅ Downloaded with embedded metadata!`);
                } else {
                    throw new Error(data.message || 'Embedding failed');
                }
            } catch (e) {
                // Fallback: download without metadata
                const a = document.createElement('a');
                a.href = g.image_path;
                a.download = `av_${Date.now()}.png`;
                a.click();
                showToast('⚠️ Downloaded without metadata (embedding failed).');
            }
        }

        function sendToImg2Img() {
            const g = _glCurrentItem;
            if (!g || !g.image_path) { showToast('⚠️ No image selected.'); return; }

            // Set the img2img source
            window.comfyUploadedImg2Img = null;  // Clear filename-based source
            window.comfyUploadedImg2ImgB64 = null;

            // Load the image and convert to base64 for upload
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                canvas.getContext('2d').drawImage(img, 0, 0);
                const b64 = canvas.toDataURL('image/png').split(',')[1];
                window.comfyUploadedImg2ImgB64 = b64;

                // Also set the canvas image
                const canvasImg = document.getElementById('inf-canvas-img');
                if (canvasImg) {
                    canvasImg.src = g.image_path;
                    canvasImg.style.display = 'block';
                    document.getElementById('inf-canvas-empty').style.display = 'none';
                }

                // Show img2img denoise slider
                const denoiseRow = document.getElementById('inf-img2img-row');
                if (denoiseRow) denoiseRow.style.display = 'block';

                // Restore prompts if available
                if (g.prompt) document.getElementById('inf-prompt').value = g.prompt;
                if (g.negative) document.getElementById('inf-negative').value = g.negative;

                // Close lightbox and switch to inference
                document.getElementById('gallery-lightbox').style.display = 'none';
                switchTab('inference', document.querySelector('.nav-item[onclick*="inference"]'));
                showToast('🖼️ Sent to Img2Img! Adjust denoise strength and generate.');
            };
            img.onerror = () => {
                showToast('⚠️ Failed to load image for img2img.');
            };
            img.src = g.image_path;
        }


        /* ═══ Feature 12: Global Keyboard Shortcuts ═══
           System-wide hotkeys for rapid generation workflow.
           Only active when inference tab is visible. */

        document.addEventListener('keydown', (e) => {
            // Only activate shortcuts when inference tab is active
            const infTab = document.getElementById('page-inference');
            if (!infTab || infTab.style.display === 'none') return;

            // Don't capture when typing in input fields (except for Ctrl combos)
            const activeTag = document.activeElement?.tagName;
            const isTyping = activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT';

            // Ctrl+Enter: Generate
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                if (typeof executeInference === 'function') executeInference();
                return;
            }

            // Ctrl+S: Save project
            if (e.ctrlKey && !e.shiftKey && e.key === 's') {
                e.preventDefault();
                if (typeof exportProject === 'function') exportProject();
                return;
            }

            // Ctrl+Shift+R: Random seed
            if (e.ctrlKey && e.shiftKey && e.key === 'R') {
                e.preventDefault();
                const seedEl = document.getElementById('inf-seed');
                if (seedEl) {
                    seedEl.value = Math.floor(Math.random() * 1e15);
                    showToast('🎲 Random seed generated');
                }
                return;
            }

            // Ctrl+Shift+G: Assemble grid
            if (e.ctrlKey && e.shiftKey && e.key === 'G') {
                e.preventDefault();
                if (typeof assembleSessionGrid === 'function') assembleSessionGrid();
                return;
            }

            // Ctrl+Shift+V: Seed variation (+1)
            if (e.ctrlKey && e.shiftKey && e.key === 'V') {
                e.preventDefault();
                if (typeof seedVariation === 'function') seedVariation(1);
                return;
            }

            // Escape: Dismiss popovers/modals
            if (e.key === 'Escape' && !isTyping) {
                // Close prompt presets popover
                const presetsPopover = document.getElementById('inf-prompt-presets-popover');
                if (presetsPopover && presetsPopover.style.display === 'block') {
                    presetsPopover.style.display = 'none';
                    return;
                }
                // Close autocomplete
                if (typeof hideAutoComplete === 'function' && _acMatches.length > 0) {
                    hideAutoComplete();
                    return;
                }
                // Close dimension presets
                const dimPopover = document.getElementById('inf-dim-presets-popover');
                if (dimPopover && dimPopover.style.display === 'block') {
                    dimPopover.style.display = 'none';
                    return;
                }
            }
        });


        /* ═══ Feature 13: AI Enhance with "Feel" Selector ═══
           Adds mood/style presets to the Ollama prompt enhancement.
           Matches StabilityMatrix's "Magic Wand" with a Feel selector.
           Each feel modifies the system prompt to bias the AI output. */

        const _ENHANCE_FEELS = {
            'default':     { label: '🎨 Default',      instruction: 'Include specific artistic styles, lighting, composition, and quality tags.' },
            'cinematic':   { label: '🎬 Cinematic',     instruction: 'Focus on cinematic composition with dramatic lighting, film-like framing, depth of field, and movie poster aesthetics.' },
            'anime':       { label: '🌸 Anime',         instruction: 'Enhance with anime/manga art style tags. Include specific anime quality markers like illustration, detailed eyes, and cel shading references.' },
            'photorealistic': { label: '📷 Photo Real',  instruction: 'Enhance for photorealism with DSLR camera settings, natural lighting, specific lens types, and real-world material textures.' },
            'fantasy':     { label: '⚔️ Fantasy',       instruction: 'Enhance with high fantasy elements including magical lighting, ethereal atmospheres, ornate details, and epic compositions.' },
            'dark':        { label: '🌑 Dark/Horror',   instruction: 'Enhance with dark, moody atmosphere. Include horror elements, dramatic shadows, unsettling compositions, and gothic aesthetics.' },
            'vibrant':     { label: '🌈 Vibrant',       instruction: 'Maximize color saturation and vibrancy. Include neon accents, bold color contrasts, and energetic compositions.' },
            'minimalist':  { label: '◻️ Minimalist',    instruction: 'Keep the prompt clean and focused with minimal elements. Emphasize negative space, simple compositions, and elegant simplicity.' },
        };

        window._selectedFeel = 'default';

        function setEnhanceFeel(feel) {
            window._selectedFeel = feel;
            const btn = document.getElementById('ollama-feel-btn');
            if (btn) {
                btn.innerText = _ENHANCE_FEELS[feel]?.label || '🎨 Default';
            }
            const dd = document.getElementById('ollama-feel-dropdown');
            if (dd) dd.style.display = 'none';
        }

        function toggleFeelDropdown() {
            const dd = document.getElementById('ollama-feel-dropdown');
            if (!dd) return;
            if (dd.style.display === 'block') {
                dd.style.display = 'none';
            } else {
                dd.innerHTML = Object.entries(_ENHANCE_FEELS).map(([key, val]) => {
                    const active = key === window._selectedFeel;
                    return `<div onclick="setEnhanceFeel('${key}')" style="padding:6px 12px; cursor:pointer; font-size:0.8rem; border-radius:6px; color:${active ? '#fff' : '#e2e8f0'}; background:${active ? 'rgba(99,102,241,0.2)' : 'transparent'}; transition:background 0.1s;"
                        onmouseenter="this.style.background='rgba(99,102,241,0.15)'" onmouseleave="this.style.background='${active ? 'rgba(99,102,241,0.2)' : 'transparent'}'">${val.label}</div>`;
                }).join('');
                dd.style.display = 'block';
            }
        }

        // Override enhancePromptWithOllama to include Feel
        const _origEnhanceOllama = enhancePromptWithOllama;

        async function enhancePromptWithOllamaFeel() {
            const promptEl = document.getElementById('inf-prompt');
            const btn = document.getElementById('ollama-enhance-btn');
            if (!promptEl || !promptEl.value.trim()) {
                showToast('Enter a prompt first, then click Enhance.');
                return;
            }
            const original = btn.innerHTML;
            btn.innerHTML = '⏳ Enhancing...';
            btn.disabled = true;

            const feel = _ENHANCE_FEELS[window._selectedFeel] || _ENHANCE_FEELS['default'];

            try {
                const model = window._ollamaModels.length > 0 ? window._ollamaModels[0] : 'llama3.2';
                const res = await fetch('/api/ollama/enhance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prompt: promptEl.value,
                        model: model,
                        feel: window._selectedFeel
                    })
                });
                const data = await res.json();
                if (data.enhanced_prompt) {
                    promptEl.value = data.enhanced_prompt;
                    updateTokenCounter();
                    if (typeof updatePromptHighlight === 'function') updatePromptHighlight('inf-prompt');
                    showToast(`✨ Prompt enhanced (${feel.label})!`);
                } else {
                    showToast('⚠️ ' + (data.error || 'Enhancement failed'));
                }
            } catch(e) {
                showToast('⚠️ Ollama not reachable. Is it running?');
            }
            btn.innerHTML = original;
            btn.disabled = false;
        }


        /* ═══ Feature 14: Batch Seed Variations ═══
           Generate N images with incrementing seeds from a base seed.
           Uses the batch queue for sequential processing. */

        async function generateSeedVariations(count) {
            count = count || parseInt(window.prompt('How many seed variations?', '4'));
            if (!count || count < 1 || count > 16) {
                showToast('⚠️ Enter 1–16 variations.');
                return;
            }

            const baseSeed = window._lastUsedSeed || Math.floor(Math.random() * 1e15);

            // Build payloads with incrementing seeds
            if (typeof buildGenerationPayload !== 'function') {
                showToast('⚠️ Generation system not ready.');
                return;
            }

            const payloads = [];
            for (let i = 0; i < count; i++) {
                const payload = buildGenerationPayload();
                payload.seed = baseSeed + i;

                // Expand wildcards for each variation independently
                if (typeof preprocessPromptWildcards === 'function') {
                    preprocessPromptWildcards(payload);
                }

                payloads.push(payload);
            }

            try {
                const res = await fetch('/api/generate/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payloads })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`🌱 Queued ${count} seed variations (${baseSeed} → ${baseSeed + count - 1})`);
                } else {
                    showToast('⚠️ ' + (data.message || 'Failed to queue variations'));
                }
            } catch (e) {
                showToast('⚠️ Failed to submit batch: ' + e.message);
            }
        }

        /* ═══ Phase 5: Extension Auto-Detection & Install ═══════════ */
        async function checkAddonExtensions() {
            try {
                const res = await fetch('/api/comfy_proxy', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({endpoint: '/object_info'})
                });
                if (!res.ok) return;
                const nodeInfo = await res.json();
                
                // FaceDetailer: requires Impact Pack (FaceDetailer node)
                const hasFaceDetailer = !!nodeInfo['FaceDetailer'];
                const fdBanner = document.getElementById('inf-fd-install-banner');
                if (fdBanner) fdBanner.style.display = hasFaceDetailer ? 'none' : 'block';
                
                // LayerDiffuse: requires LayeredDiffusionApply node
                const hasLayerDiffuse = !!nodeInfo['LayeredDiffusionApply'];
                const ldBanner = document.getElementById('inf-ld-install-banner');
                if (ldBanner) ldBanner.style.display = hasLayerDiffuse ? 'none' : 'block';
            } catch(e) {
                // ComfyUI offline — don't show banners
            }
        }

        async function installFaceDetailer() {
            const btn = document.getElementById('inf-fd-install-btn');
            if (btn) { btn.disabled = true; btn.textContent = 'Installing...'; }
            try {
                const res = await fetch('/api/extensions/install', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: 'ComfyUI-Impact-Pack',
                        url: 'https://github.com/ltdrdata/ComfyUI-Impact-Pack.git'
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✅ Impact Pack installed! Restart ComfyUI to activate.');
                    if (btn) btn.textContent = 'Restart Required';
                } else {
                    showToast('⚠️ Install failed: ' + (data.message || 'Unknown error'));
                    if (btn) { btn.disabled = false; btn.textContent = 'Install Now'; }
                }
            } catch(e) {
                showToast('⚠️ Install request failed: ' + e.message);
                if (btn) { btn.disabled = false; btn.textContent = 'Install Now'; }
            }
        }

        async function installLayerDiffuse() {
            const btn = document.getElementById('inf-ld-install-btn');
            if (btn) { btn.disabled = true; btn.textContent = 'Installing...'; }
            try {
                const res = await fetch('/api/extensions/install', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: 'ComfyUI-layerdiffuse',
                        url: 'https://github.com/huchenlei/ComfyUI-layerdiffuse.git'
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✅ LayerDiffuse installed! Restart ComfyUI to activate.');
                    if (btn) btn.textContent = 'Restart Required';
                } else {
                    showToast('⚠️ Install failed: ' + (data.message || 'Unknown error'));
                    if (btn) { btn.disabled = false; btn.textContent = 'Install Now'; }
                }
            } catch(e) {
                showToast('⚠️ Install request failed: ' + e.message);
                if (btn) { btn.disabled = false; btn.textContent = 'Install Now'; }
            }
        }

        // Run extension check when Inference tab is activated
        // (checkAddonExtensions is lightweight — only fires when ComfyUI is online)
        document.addEventListener('DOMContentLoaded', () => {
            const _origSwitchTab = window.switchTab;
            if (typeof switchTab === 'function') {
                // Piggyback on switchTab to re-check each time user enters Inference
                // Initial check fires 3s after first DOMContentLoaded
                setTimeout(checkAddonExtensions, 3000);
            }
        });
