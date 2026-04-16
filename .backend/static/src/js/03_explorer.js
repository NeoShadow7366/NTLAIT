        async function loadExplorer() {
            const grid = document.getElementById('explorer-grid');
            const source = document.getElementById('ex-source').value;
            grid.innerHTML = `<div class="empty-state">Fetching ${source==='huggingface'?'Hugging Face':'CivitAI'} Catalog...</div>`;
            
            if(installedHashes.size === 0) {
                try {
                    const lres = await fetch('/api/models?limit=5000');
                    const ldata = await lres.json();
                    if(ldata.models) ldata.models.forEach(m => installedHashes.add(m.metadata?.model?.name || m.filename));
                } catch(e) {}
            }

            const sort = document.getElementById('ex-sort').value;
            if(sort === "Favorites") {
                grid.innerHTML = '';
                try {
                    const favRes = await fetch('/api/favorites');
                    const favData = await favRes.json();
                    window.appFavorites = favData || {};
                    const favItems = Object.values(window.appFavorites);
                    if(favItems.length === 0) {
                         grid.innerHTML = '<div class="empty-state">No Favorites saved yet! Click the star on a Model Card.</div>';
                         return;
                    }
                    renderExplorerGrid(favItems);
                } catch(e) {
                    grid.innerHTML = '<div class="empty-state">Failed to load favorites.</div>';
                }
                return;
            }

            const q = document.getElementById('ex-search').value;

            const type = document.getElementById('ex-type').value;

            if(source === 'huggingface') {
                try {
                    const hfRes = await fetch(`/api/hf/search?query=${encodeURIComponent(q)}&type=${encodeURIComponent(type)}&limit=40`);
                    const hfData = await hfRes.json();
                    if(hfData.status === 'success') {
                        renderExplorerGrid(hfData.items);
                    } else {
                        grid.innerHTML = `<div class="empty-state" style="color:#ef4444;">HF Error: ${hfData.message}</div>`;
                    }
                } catch(e) {
                    grid.innerHTML = `<div class="empty-state" style="color:#ef4444;">HF Search Failed: ${e.message}</div>`;
                }
                return;
            }

            const base = document.getElementById('ex-base').value;
            const nsfw = document.getElementById('ex-nsfw').checked ? 'true' : 'false';
            const includeEarly = document.getElementById('ex-early').checked;

            let url;
            let isExactId = false;

            // Direct ID / URL parsing for precision searches
            const idMatch = q.match(/models\/(\d+)/) || q.match(/^(\d+)$/);
            if(idMatch) {
                isExactId = true;
                url = new URL(window.location.origin + '/api/civitai_search');
                url.searchParams.append('exact_id', idMatch[1]);
            } else if (q) {
                url = new URL(window.location.origin + '/api/civitai_search');
                url.searchParams.append('query', q);
                url.searchParams.append('nsfw', nsfw);
                if(type) url.searchParams.append('type', type);
                if(base) url.searchParams.append('base', base);
            } else {
                url = new URL(window.location.origin + '/api/civitai_search');
                url.searchParams.append('browse', 'true');
                let apiSort = sort;
                if (sort === 'Size High' || sort === 'Size Low') apiSort = 'Highest Rated';
                if (apiSort !== 'Search Match') {
                    url.searchParams.append('sort', apiSort);
                }
                url.searchParams.append('nsfw', nsfw);
                if(includeEarly) url.searchParams.append('earlyAccess', 'true');
                if(type) {
                    if(type === 'Text Encoder') {
                        url.searchParams.append('query', 'text encoder clip');
                    } else {
                        url.searchParams.append('types', type);
                    }
                }
                if(base) url.searchParams.append('baseModels', base);
            }

            try {
                const res = await fetch(url);
                const data = await res.json();
                
                // Unified rendering: If exact ID, it returns a single object instead of data.items
                if(isExactId) {
                    renderExplorerGrid(data.id ? [data] : []);
                } else {
                    renderExplorerGrid(data.items || []);
                }
            } catch(e) {
                grid.innerHTML = `<div class="empty-state" style="color:#ef4444;">Failed to load API: ${e.message}</div>`;
            }
        }

        function renderExplorerGrid(items) {
            const grid = document.getElementById('explorer-grid');
            grid.innerHTML = '';
            if(!items || items.length === 0) {
                grid.innerHTML = '<div class="empty-state">No models found matching criteria.</div>';
                return;
            }

            // BUG-1: Client-side size sorting
            const sort = document.getElementById('ex-sort').value;
            if(sort === 'Size High' || sort === 'Size Low') {
                items.sort((a, b) => {
                    const sizeA = (a.modelVersions && a.modelVersions[0] && a.modelVersions[0].files && a.modelVersions[0].files[0]) ? a.modelVersions[0].files[0].sizeKB || 0 : 0;
                    const sizeB = (b.modelVersions && b.modelVersions[0] && b.modelVersions[0].files && b.modelVersions[0].files[0]) ? b.modelVersions[0].files[0].sizeKB || 0 : 0;
                    return sort === 'Size High' ? sizeB - sizeA : sizeA - sizeB;
                });
            } else if (sort === 'Search Match') {
                // Trust the server-side Meilisearch relevancy ranking
            }

            const hideInstalled = document.getElementById('ex-installed').checked;
            const favs = window.appFavorites || {};
            activeModels = {};
            const htmlParts = [];

            items.forEach(model => {
                if (hideInstalled && installedHashes.has(model.name)) return;
                if (window.onlyNsfw && !model.nsfw) return;
                
                // Early access filter: when unchecked, skip models where ALL versions are early access
                const _includeEA = document.getElementById('ex-early').checked;
                if(!_includeEA && model.modelVersions && model.modelVersions.length > 0) {
                    const allEA = model.modelVersions.every(v => isVersionEarlyAccess(v));
                    if(allEA) return;
                }

                activeModels[model.id] = model;
                // E-6 fix: Stamp source so download uses correct params later
                if (!model._source) model._source = document.getElementById('ex-source').value;
                window.cardState[model.id] = 0;
                
                let bgHtml = '';
                let imgCount = 0;
                if(model.modelVersions && model.modelVersions[0] && model.modelVersions[0].images) {
                    const imgs = model.modelVersions[0].images;
                    imgCount = imgs.length;
                    const first = imgs[0];
                    if(first) {
                        if(first.type === "video") {
                            bgHtml = `<video class="card-img" id="card-media-${model.id}" src="${first.url}" autoplay loop muted playsinline></video>`;
                        } else {
                            bgHtml = `<img class="card-img" id="card-media-${model.id}" src="${first.url}">`;
                        }
                    }
                }
                if(!bgHtml) bgHtml = `<img class="card-img" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100px' height='100px'><rect fill='%231e293b' width='100%' height='100%'/></svg>">`;
                
                const creatorName = (model.creator && model.creator.username) ? model.creator.username : 'Unknown';
                const dlCount = (model.stats && model.stats.downloadCount) ? model.stats.downloadCount : 0;
                const dl = formatDownloadCount(dlCount);
                const isFav = !!favs[model.id];

                // Badge logic: NSFW, Early Access, Base Model
                let extraBadges = '';
                if(model.nsfw) {
                    extraBadges += '<span class="badge nsfw">🔞 NSFW</span>';
                }
                const firstVersion = model.modelVersions && model.modelVersions[0];
                if(firstVersion && isVersionEarlyAccess(firstVersion)) {
                    extraBadges += '<span class="badge early-access">⏳ Early Access</span>';
                }
                if(firstVersion && firstVersion.baseModel && firstVersion.baseModel !== 'Unknown') {
                    extraBadges += `<span class="badge base-model">${firstVersion.baseModel}</span>`;
                }
                
                let carouselBtns = '';
                if(imgCount > 1) {
                    carouselBtns = `
                        <button class="carousel-btn left" onclick="event.stopPropagation(); cycleImage(${model.id}, -1)">&lt;</button>
                        <button class="carousel-btn right" onclick="event.stopPropagation(); cycleImage(${model.id}, 1)">&gt;</button>
                    `;
                }
                
                htmlParts.push(`
                    <div class="card" onclick="openLightbox(${model.id})">
                        <div class="card-tags">
                            <span class="badge type">${model.type || 'Model'}</span>
                            ${extraBadges}
                            <button class="fav-btn" onclick="event.stopPropagation(); toggleFavorite(${model.id})" style="margin-left:auto; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); border:1px solid rgba(255,255,255,0.1); border-radius:4px; cursor:pointer; font-size:1.1rem; line-height:1; padding:2px 6px; color: ${isFav ? '#fbbf24' : 'rgba(255,255,255,0.4)'}; text-shadow: 0 2px 4px rgba(0,0,0,0.8);">★</button>
                        </div>
                        <div class="card-img-container">
                            ${bgHtml}
                            ${carouselBtns}
                        </div>
                        <div class="card-banner">
                            <h3>${escHtml(model.name)}</h3>
                            <div class="card-meta-row">
                                <span>${escHtml(creatorName)}</span>
                                <span>⬇ ${dl}</span>
                            </div>
                        </div>
                    </div>
                `);
            });

            grid.innerHTML = htmlParts.join('');
        }

        async function toggleFavorite(modelId) {
            const m = activeModels[modelId];
            if(!m) return;
            if(!window.appFavorites) window.appFavorites = {};
            if(window.appFavorites[modelId]) {
                delete window.appFavorites[modelId];
                try {
                    await fetch('/api/favorites/remove', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ model_id: modelId })
                    });
                } catch(e) { console.warn('Failed to remove favorite:', e); }
            } else {
                window.appFavorites[modelId] = m;
                try {
                    await fetch('/api/favorites/add', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ model_id: modelId, data: m })
                    });
                } catch(e) { console.warn('Failed to add favorite:', e); }
            }
            // E-4 fix: Update star in-place instead of rebuilding entire grid (preserves scroll)
            const card = document.querySelector(`.card[onclick*="openLightbox(${modelId})"]`);
            if (card) {
                const starBtn = card.querySelector('.fav-btn');
                if (starBtn) {
                    starBtn.style.color = window.appFavorites[modelId] ? '#fbbf24' : 'rgba(255,255,255,0.4)';
                }
            }
        }

        function cycleImage(modelId, step) {
            const m = activeModels[modelId];
            if(!m) return;
            const imgs = m.modelVersions[0].images;
            if(!imgs || imgs.length === 0) return;
            
            let current = window.cardState[modelId] || 0;
            current += step;
            if(current < 0) current = imgs.length - 1;
            if(current >= imgs.length) current = 0;
            
            window.cardState[modelId] = current;
            const target = imgs[current];
            const el = document.getElementById('card-media-' + modelId);
            if(el) {
                const parent = el.parentElement;
                let bgHtml = '';
                if(target.type === "video") {
                    bgHtml = `<video class="card-img" id="card-media-${modelId}" src="${target.url}" autoplay loop muted playsinline></video>`;
                } else {
                    bgHtml = `<img class="card-img" id="card-media-${modelId}" src="${target.url}">`;
                }
                el.outerHTML = bgHtml;
            }
        }

        function openLightbox(modelId, localFile = null, localCategory = null) {
            window.isVaultMode = !!localFile;
            window.currentVaultFilename = localFile;
            window.currentVaultCategory = localCategory;
            
            const m = activeModels[modelId];
            if(!m) return;
            currentModalModel = m;
            
            document.getElementById('lb-title').innerText = m.name;
            document.getElementById('lb-creator').innerText = `by ${m.creator ? m.creator.username : 'Unknown'}`;
            document.getElementById('lb-civitai-link').href = `https://civitai.com/models/${m.id}`;
            
            // Populate versions
            const select = document.getElementById('lb-version-select');
            select.innerHTML = '';
            let firstNonEA = -1;
            m.modelVersions.forEach((v, index) => {
                const opt = document.createElement('option');
                opt.value = index;
                const ea = isVersionEarlyAccess(v);
                opt.innerText = ea ? `⏳ ${v.name} (${v.baseModel}) — EARLY ACCESS` : `${v.name} (${v.baseModel})`;
                if(ea) opt.style.color = '#fbbf24';
                select.appendChild(opt);
                if(!ea && firstNonEA === -1) firstNonEA = index;
            });
            // Auto-select first non-early-access version if available
            if(firstNonEA > 0) select.value = firstNonEA;
            
            // Load Tags
            renderLightboxTags(m.tags || []);
            
            // Show new tag input only in Vault mode
            document.getElementById('lb-tagging-controls').style.display = window.isVaultMode ? 'block' : 'none';

            document.getElementById('lightbox').style.display = 'flex';
            
            // BUG-3 fix: Explicitly trigger version rendering (onchange doesn't fire from JS)
            updateLightboxVersion();
        }

        function renderLightboxTags(tagsObjList) {
            const tagsCont = document.getElementById('lb-tags-container');
            tagsCont.innerHTML = '';
            tagsObjList.forEach(t => {
                const tagName = typeof t === 'string' ? t : t.name;
                tagsCont.innerHTML += `
                    <span class="badge" style="background:var(--surface-hover); display:flex; align-items:center; gap:5px;">
                        ${escHtml(tagName)}
                        ${window.isVaultMode ? `<button onclick="removeVaultTag('${escHtml(tagName)}')" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:0.8rem; padding:0; margin-left:4px;">&times;</button>` : ''}
                    </span>
                `;
            });
        }

        async function addVaultTag(tagName) {
            const tag = tagName.trim();
            if(!tag || !window.currentVaultFilename) return;
            document.getElementById('lb-new-tag').value = '';
            
            try {
                const res = await fetch('/api/vault/tag/add', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({filename: window.currentVaultFilename, category: window.currentVaultCategory, tag: tag})
                });
                const data = await res.json();
                if(data.status === 'success') {
                    if(!currentModalModel.tags) currentModalModel.tags = [];
                    // Avoid dupes locally
                    if(!currentModalModel.tags.find(t => (t.name === tag || t === tag))) {
                        currentModalModel.tags.push({name: tag});
                        renderLightboxTags(currentModalModel.tags);
                        loadVaultTags(); // refresh filter list
                    }
                } else alert(data.message);
            } catch(e) {}
        }

        async function removeVaultTag(tagName) {
            if(!window.currentVaultFilename) return;
            try {
                const res = await fetch('/api/vault/tag/remove', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({filename: window.currentVaultFilename, category: window.currentVaultCategory, tag: tagName})
                });
                const data = await res.json();
                if(data.status === 'success') {
                    if(currentModalModel.tags) {
                        currentModalModel.tags = currentModalModel.tags.filter(t => t.name !== tagName && t !== tagName);
                        renderLightboxTags(currentModalModel.tags);
                    }
                } else alert(data.message);
            } catch(e) {}
            updateLightboxVersion();
        }

        window.lbImageIndex = 0;

        function updateLightboxVersion() {
            const index = document.getElementById('lb-version-select').value;
            currentModalVersion = currentModalModel.modelVersions[index];
            window.lbImageIndex = 0; // reset index for new version
            
            const v = currentModalVersion;
            const trigCont = document.getElementById('lb-trigger-container');
            const trig = document.getElementById('lb-triggers');
            if(v.trainedWords && v.trainedWords.length > 0) {
                trigCont.style.display = 'block';
                trig.innerText = v.trainedWords.join(", ");
            } else {
                trigCont.style.display = 'none';
            }
            
            // Download UI Binding
            let mainFile = (v.files && v.files.length > 0) ? (v.files.find(f => f.primary) || v.files[0]) : null;
            const btn = document.getElementById('lb-download-btn');
            const meta = document.getElementById('lb-download-meta');
            
            if(mainFile) {
                const mb = (mainFile.sizeKB / 1024).toFixed(1);
                btn.innerText = `Download ${mainFile.name}`;
                meta.innerText = `${mainFile.type} Format • ${mb} MB`;
                btn.disabled = false;
            } else {
                btn.innerText = window.isVaultMode ? "Already Installed" : "No Files Available";
                meta.innerText = "";
                btn.disabled = true;
            }

            renderLightboxImage();
        }

        function cycleLightboxImage(step) {
            const v = currentModalVersion;
            if(!v || !v.images || v.images.length === 0) return;
            window.lbImageIndex += step;
            if(window.lbImageIndex < 0) window.lbImageIndex = v.images.length - 1;
            if(window.lbImageIndex >= v.images.length) window.lbImageIndex = 0;
            renderLightboxImage();
        }

        function renderLightboxImage() {
            const v = currentModalVersion;
            if(v && v.images && v.images.length > 0) {
                const img = v.images[window.lbImageIndex];
                const wrap = document.getElementById('lb-gallery-wrapper');
                if(img.type === "video") {
                    wrap.innerHTML = `<video style="max-width:100%; max-height:100%; object-fit:contain;" src="${img.url}" autoplay loop muted playsinline></video>`;
                } else {
                    wrap.innerHTML = `<img style="max-width:100%; max-height:100%; object-fit:contain;" src="${img.url}">`;
                }

                // Metadata injection
                const metaCont = document.getElementById('lb-meta-container');
                const metaDiv = document.getElementById('lb-metadata');
                if(img.meta && Object.keys(img.meta).length > 0) {
                    metaCont.style.display = 'block';
                    let h = '';
                    if(img.meta.prompt) h += `<div style="margin-bottom:8px;"><strong>Prompt:</strong> ${escHtml(img.meta.prompt)}</div>`;
                    if(img.meta.negativePrompt) h += `<div style="margin-bottom:8px;"><strong>Negative:</strong> ${escHtml(img.meta.negativePrompt)}</div>`;
                    let pills = '';
                    if(img.meta.sampler) pills += `<span class="meta-pill">Sampler: ${img.meta.sampler}</span>`;
                    if(img.meta.cfgScale) pills += `<span class="meta-pill">CFG: ${img.meta.cfgScale}</span>`;
                    if(img.meta.steps) pills += `<span class="meta-pill">Steps: ${img.meta.steps}</span>`;
                    if(img.meta.seed) pills += `<span class="meta-pill">Seed: ${img.meta.seed}</span>`;
                    if(pills) h += `<div style="margin-top:10px;">${pills}</div>`;
                    metaDiv.innerHTML = h || 'No render metrics attached.';
                } else {
                    metaCont.style.display = 'none';
                }
            } else {
                document.getElementById('lb-gallery-wrapper').innerHTML = '';
            }

            const trigCont = document.getElementById('lb-trigger-container');
            const trig = document.getElementById('lb-triggers');
            if(v.trainedWords && v.trainedWords.length > 0) {
                trigCont.style.display = 'block';
                trig.innerText = v.trainedWords.join(", ");
            } else {
                trigCont.style.display = 'none';
            }
            
            // Early Access warning banner
            const eaWarning = document.getElementById('lb-ea-warning');
            if(eaWarning) {
                eaWarning.style.display = isVersionEarlyAccess(v) ? 'block' : 'none';
            }

            // Download UI Binding
            let mainFile = (v.files && v.files.length > 0) ? (v.files.find(f => f.primary) || v.files[0]) : null;
            const btnStandard = document.getElementById('lb-actions-standard');
            const btnVault = document.getElementById('lb-actions-vault');
            const btnDl = document.getElementById('lb-download-btn');
            const meta = document.getElementById('lb-download-meta');
            
            if(window.isVaultMode) {
                btnStandard.style.display = 'none';
                btnVault.style.display = 'flex';
                // Show Hash button only for unhashed models (no file_hash = no CivitAI metadata)
                const hashBtn = document.getElementById('lb-hash-btn');
                if(hashBtn) {
                    const model = window.currentModalModel;
                    const isUnhashed = model && !model.file_hash;
                    hashBtn.style.display = isUnhashed ? 'inline-flex' : 'none';
                    hashBtn.style.alignItems = 'center';
                    hashBtn.style.gap = '6px';
                }
            } else {
                btnStandard.style.display = 'block';
                btnVault.style.display = 'none';
                if(mainFile) {
                    const mb = (mainFile.sizeKB / 1024).toFixed(1);
                    btnDl.innerText = `Download ${mainFile.name}`;
                    meta.innerText = `${mainFile.type} Format • ${mb} MB`;
                    btnDl.disabled = false;
                } else {
                    btnDl.innerText = "No Files Available";
                    meta.innerText = "";
                    btnDl.disabled = true;
                }
            }
        }
        
        function closeLightbox() {
            document.getElementById('lightbox').style.display = 'none';
        }

        // Keyboard navigation for lightbox
        document.addEventListener('keydown', (e) => {
            const lb = document.getElementById('lightbox');
            if(!lb || lb.style.display !== 'flex') return;
            if(e.key === 'Escape') { closeLightbox(); e.preventDefault(); }
            else if(e.key === 'ArrowLeft') { cycleLightboxImage(-1); e.preventDefault(); }
            else if(e.key === 'ArrowRight') { cycleLightboxImage(1); e.preventDefault(); }
        });

        async function executeDownload() {
            const m = currentModalModel;
            const v = currentModalVersion;
            const mainFile = v.files.find(f => f.primary) || v.files[0];
            
            if(!mainFile) return;

            // Mapping Model Type to Vault Tier
            let tier = "misc";
            const lowerName = (mainFile.name || "").toLowerCase();
            const isFlux = (v.baseModel && v.baseModel.includes("Flux"));

            if(isFlux) {
                // Intelligent routing for FLUX components
                if(m.type === "LORA" || lowerName.includes("lora")) tier = "loras";
                else if(m.type === "VAE" || lowerName.includes("vae")) tier = "vaes";
                else if(lowerName.includes("clip") || lowerName.includes("t5")) tier = "clip";
                else tier = "unet"; // Default FLUX checks/UNETs to unet folder
            } else {
                const typeMap = {
                    "Checkpoint": "checkpoints",
                    "LORA": "loras",
                    "LoCon": "loras",
                    "LyCORIS": "loras",
                    "DoRA": "doras",
                    "TextualInversion": "embeddings",
                    "Hypernetwork": "hypernetworks",
                    "AestheticGradient": "aesthetic_gradients",
                    "Controlnet": "controlnet",
                    "Upscaler": "upscaler",
                    "MotionModule": "motion",
                    "VAE": "vaes",
                    "Poses": "poses",
                    "Wildcards": "wildcards",
                    "Workflows": "workflows",
                    "Detection": "detection",
                    "Other": "misc",
                    "Text Encoder": "clip"
                };
                tier = typeMap[m.type] || "misc";
            }

            const destFolder = `Global_Vault/${tier}`;
            // E-6 fix: Read source from model instead of dropdown (survives tab switch)
            const source = m._source || document.getElementById('ex-source').value;
            let dlUrl = mainFile.downloadUrl;
            if (source === 'civitai') {
                dlUrl += "?type=Model&format=SafeTensor";
            }
            
            closeLightbox();
            
            try {
                const res = await fetch('/api/download', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        url: dlUrl,
                        filename: mainFile.name,
                        model_name: m.name,
                        dest_folder: destFolder,
                        api_key: localStorage.getItem('civitai_api_key') || ""
                    })
                });
                const response = await res.json();
                if(response.status !== 'success') {
                    alert("Download rejected: " + response.message);
                }
            } catch(e) {
                alert("Server request failed");
            }
        }

        async function executeVaultRepair() {
            if(!confirm(`Refresh metadata and preview image for ${window.currentVaultFilename}?`)) return;
            try {
                // Send both filename (always available) and file_hash (when metadata exists)
                const payload = { filename: window.currentVaultFilename };
                if(currentModalModel && currentModalModel.modelVersions && currentModalModel.modelVersions[0]) {
                    const ver = currentModalModel.modelVersions[0];
                    if(ver.files && ver.files[0] && ver.files[0].hashes && ver.files[0].hashes.SHA256) {
                        payload.file_hash = ver.files[0].hashes.SHA256;
                    }
                }
                const res = await fetch('/api/vault/repair', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const response = await res.json();
                if(response.status === 'success') {
                    closeLightbox();
                    loadModels();
                } else alert("Repair failed: " + (response.message || "Unknown error"));
            } catch(e) { alert("Failed to repair model"); }
        }

        async function hashSingleVaultModel() {
            const model = window.currentModalModel;
            if(!model || !model.id) { showToast('No model ID available.'); return; }

            const hashBtn = document.getElementById('lb-hash-btn');
            if(hashBtn) {
                hashBtn.disabled = true;
                hashBtn.textContent = '⏳ Hashing...';
            }

            try {
                // Start background hash for this specific model by DB id
                const res = await fetch('/api/vault/hash_single', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ model_id: model.id })
                });
                const data = await res.json();
                if(data.error) {
                    showToast('Hash failed: ' + data.error);
                    if(hashBtn) { hashBtn.disabled = false; hashBtn.innerHTML = 'Hash 🔑'; }
                    return;
                }

                // Poll scan_progress until no longer active
                const pollInterval = setInterval(async () => {
                    try {
                        const pr = await fetch('/api/vault/scan_progress');
                        const progress = await pr.json();
                        if(!progress.active) {
                            clearInterval(pollInterval);
                            showToast('✅ Hash complete! Metadata updated.');
                            // Refresh vault grid and hide hash button
                            loadModels(false);
                            closeLightbox();
                        } else if(hashBtn) {
                            const pct = progress.percent || 0;
                            hashBtn.textContent = `⏳ ${pct}%`;
                        }
                    } catch(e) {
                        clearInterval(pollInterval);
                    }
                }, 1500);

                // Safety timeout: stop polling after 5 minutes
                setTimeout(() => {
                    clearInterval(pollInterval);
                    if(hashBtn) { hashBtn.disabled = false; hashBtn.innerHTML = 'Hash 🔑'; }
                }, 5 * 60 * 1000);

            } catch(e) {
                showToast('Failed to start hash: ' + e.message);
                if(hashBtn) { hashBtn.disabled = false; hashBtn.innerHTML = 'Hash 🔑'; }
            }
        }

        async function executeVaultOpenFolder() {
            if(!window.currentVaultCategory) return;
            try {
                await fetch('/api/open_folder', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({category: window.currentVaultCategory})
                });
            } catch(e) {}
        }
        
        async function executeVaultDelete() {
            if(!confirm(`Permanently delete ${window.currentVaultFilename}?`)) return;
            try {
                const res = await fetch('/api/delete_model', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({filename: window.currentVaultFilename, category: window.currentVaultCategory})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    closeLightbox();
                    loadModels();
                } else alert(response.message);
            } catch(e) { alert("Failed to delete"); }
        }

        async function executeVaultRedownload() {
            if(!confirm(`Redownload ${window.currentVaultFilename}? This will delete the local file and recreate it.`)) return;
            document.getElementById('lightbox').style.pointerEvents = 'none';
            document.getElementById('lightbox').style.opacity = '0.5';
            
            try {
                await fetch('/api/delete_model', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({filename: window.currentVaultFilename, category: window.currentVaultCategory})
                });
                document.getElementById('lightbox').style.pointerEvents = 'auto';
                document.getElementById('lightbox').style.opacity = '1';
                executeDownload();
            } catch(e) { 
                document.getElementById('lightbox').style.pointerEvents = 'auto';
                document.getElementById('lightbox').style.opacity = '1';
            }
        }

        /* --- Local Vault & App Store --- */
        async function loadModels(append = false) {
            if (window._semanticSearchActive) return; // Prevent pagination interference during search
            try {
                if(!append) {
                    vaultOffset = 0;
                    document.getElementById('models-grid').innerHTML = '<div class="empty-state">Loading your library...</div>';
                }
                
                const res = await fetch(`/api/models?limit=${vaultLimit}&offset=${vaultOffset}`);
                const data = await res.json();
                
                renderVaultGrid(data.models || [], append, data.total);
                
                // Also update the tags dropdown
                if(!append) {
                    await loadVaultTags();
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function loadVaultTags() {
            try {
                const res = await fetch('/api/vault/tags');
                const data = await res.json();
                const select = document.getElementById('vault-tag-filter');
                const curVal = select.value;
                select.innerHTML = '<option value="">All Collections / Tags</option>';
                if(data.tags) {
                    data.tags.forEach(tag => {
                        const opt = document.createElement('option');
                        opt.value = tag.name;
                        opt.innerText = tag.name;
                        select.appendChild(opt);
                    });
                }
                select.value = curVal; // Restore selection if any
            } catch(e) {}
        }

        function renderVaultGrid(models, append, total = 0) {
            const grid = document.getElementById('models-grid');
            const loadMoreBtn = document.getElementById('vault-load-more-container');
            
            if(!append) grid.innerHTML = '';
            
            if(!models || models.length === 0) {
                if(!append) grid.innerHTML = '<div class="empty-state">No models found in the database. Run the Vault Crawler!</div>';
                loadMoreBtn.style.display = 'none';
                return;
            }

            const htmlParts = [];

            models.forEach(m => {
                // Determine model object (from standard or search API)
                const isSearchRes = (m.model !== undefined && m.score !== undefined);
                const item = isSearchRes ? m.model : m;
                
                // Generate a vibrant, unique gradient fallback based on the filename hash
                const _hashCode = (s) => { let h = 0; for(let i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i) | 0; return Math.abs(h); };
                const _fhash = _hashCode(item.filename || 'model');
                const _hue1 = _fhash % 360;
                const _hue2 = (_fhash * 137) % 360;
                const _noPreviewSvg = "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="hsl(${_hue1},70%,35%)"/><stop offset="100%" stop-color="hsl(${_hue2},60%,25%)"/></linearGradient></defs><rect fill="url(#g)" width="200" height="200"/><text fill="rgba(255,255,255,0.5)" x="100" y="90" font-family="sans-serif" font-size="32" text-anchor="middle" dominant-baseline="middle">📦</text><text fill="rgba(255,255,255,0.35)" x="100" y="130" font-family="sans-serif" font-size="11" text-anchor="middle" dominant-baseline="middle">${(item.filename || 'Model').substring(0,20)}</text></svg>`);
                const imgSrc = (item.thumbnail_path && item.thumbnail_path.length > 0) ? '/' + item.thumbnail_path.replace(/\\/g, '/') : _noPreviewSvg;
                const displayName = item.metadata?.model?.name || item.filename;
                const isFlux = (item.metadata?.baseModel && item.metadata.baseModel.includes("Flux"));
                // Compile tags for dataset attribute
                const tagsList = ((item.tags && item.tags.map(t=>t.name)) || []).join(',');
                
                // Detect if the first preview image is actually a video (from CivitAI metadata)
                let isVideoPreview = false;
                let videoSrc = '';
                if(item.metadata && item.metadata.images && item.metadata.images[0]) {
                    const firstImg = item.metadata.images[0];
                    if(firstImg.type === "video" && firstImg.url) {
                        isVideoPreview = true;
                        videoSrc = firstImg.url;  // Use remote CivitAI video URL
                    }
                }
                // Also detect by file extension on the local thumbnail
                if(!isVideoPreview && imgSrc) {
                    const ext = imgSrc.split('.').pop().split('?')[0].toLowerCase();
                    if(['mp4','webm','ogv','mov'].includes(ext)) {
                        isVideoPreview = true;
                        videoSrc = imgSrc;
                    }
                }

                let clickStr = '';
                if(!item.metadata) item.metadata = {};
                if(!item.metadata.modelId) item.metadata.modelId = 'local_' + Math.floor(Math.random() * 1000000);
                
                // Ensure metadata has images/files arrays even if empty
                if(!item.metadata.images) item.metadata.images = [];
                if(!item.metadata.files) item.metadata.files = [];
                
                // If metadata has no images but we have a local thumbnail, inject it
                if(item.metadata.images.length === 0 && item.thumbnail_path) {
                    item.metadata.images = [{ url: '/' + item.thumbnail_path.replace(/\\/g, '/'), type: 'image', meta: {} }];
                }
                
                const fakeParent = {
                    id: item.metadata.modelId,
                    name: item.metadata.model ? item.metadata.model.name : item.filename,
                    type: item.metadata.model ? item.metadata.model.type : "Unknown",
                    creator: { username: "Local Vault" },
                    tags: item.tags || [],
                    modelVersions: [ item.metadata ]
                };
                activeModels[fakeParent.id] = fakeParent;
                window.cardState[fakeParent.id] = 0;
                clickStr = `onclick="openLightbox('${fakeParent.id}', '${item.filename}', '${item.vault_category}')" style="cursor:pointer;"`;
                
                // Render video or image preview based on media type
                // Videos use the remote CivitAI URL; images use the local cached thumbnail
                const mediaHtml = isVideoPreview
                    ? `<video class="card-img" src="${videoSrc}" autoplay loop muted playsinline></video>`
                    : `<img class="card-img" src="${imgSrc}" onerror="this.onerror=null;this.src='${_noPreviewSvg}'">`;

                htmlParts.push(`
                    <div class="card" data-category="${item.vault_category}" data-tags="${tagsList}" data-name="${displayName.toLowerCase()}" data-filename="${item.filename}" ${clickStr}>
                        <input type="checkbox" class="vault-select-checkbox" data-filename="${item.filename}" data-category="${item.vault_category}" onclick="event.stopPropagation(); updateVaultSelection();">
                        <div class="card-img-container" style="padding-top:100%;">
                            ${mediaHtml}
                            <div style="position:absolute; top:10px; right:10px; display:flex; gap:5px; z-index:2; flex-wrap:wrap;">
                                ${item.update_available === 1 ? '<span class="badge" style="background:#10b981; color:#fff; border:none; font-weight:bold; padding:4px 8px; font-size:0.75rem;">🔄 UPDATE</span>' : ''}
                                ${isFlux ? '<span class="badge" style="background:#fbbf24; color:#000; border:none; font-weight:bold; padding:4px 8px; font-size:0.75rem;">FLUX</span>' : ''}
                                <span class="badge" style="background:var(--primary); padding:4px 8px; font-size:0.75rem;">${item.vault_category}</span>
                            </div>
                        </div>
                        <div class="card-banner" style="position:relative; background:var(--surface);">
                            <h3>${escHtml(displayName)}</h3>
                            <div class="card-meta-row" style="color:var(--text-muted);">
                                <span>${escHtml(item.filename)}</span>
                                ${isSearchRes ? `<span style="color: #4ade80;">Score: ${(m.score * 100).toFixed(0)}</span>` : ''}
                            </div>
                        </div>
                    </div>
                `);
            });

            if (append) {
                grid.insertAdjacentHTML('beforeend', htmlParts.join(''));
            } else {
                grid.innerHTML = htmlParts.join('');
            }

            if(!window._semanticSearchActive) {
                vaultOffset += models.length;
                if(vaultOffset < total) {
                    loadMoreBtn.style.display = 'block';
                    // Phase 5: IntersectionObserver for infinite scroll
                    if(window._vaultScrollObserver) window._vaultScrollObserver.disconnect();
                    window._vaultScrollObserver = new IntersectionObserver((entries) => {
                        if(entries[0].isIntersecting) {
                            window._vaultScrollObserver.disconnect();
                            loadModels(true);
                        }
                    }, { rootMargin: '400px' });
                    window._vaultScrollObserver.observe(loadMoreBtn);
                } else {
                    loadMoreBtn.style.display = 'none';
                    if(window._vaultScrollObserver) window._vaultScrollObserver.disconnect();
                }
            }
        }

