           DRAG-AND-DROP IMPORT ENGINE
        ═══════════════════════════════════════════════ */
        let _pendingImportFiles = [];
        let _activeImportId = null;

        function handleVaultFileDrop(event) {
            const files = Array.from(event.dataTransfer.files).filter(f =>
                /\.(safetensors|ckpt|pt|pth|bin|sft|gguf)$/i.test(f.name)
            );
            if(!files.length) return;
            openImportDialog(files);
        }

        function handleVaultFileInput(fileList) {
            const files = Array.from(fileList).filter(f =>
                /\.(safetensors|ckpt|pt|pth|bin|sft|gguf)$/i.test(f.name)
            );
            if(!files.length) return;
            openImportDialog(files);
        }

        function openImportDialog(files) {
            _pendingImportFiles = files;
            window._importDone = false;
            document.getElementById('import-filename').innerText = files.map(f => f.name).join(', ');
            document.getElementById('import-bar').style.width = '0%';
            document.getElementById('import-status-msg').innerText = 'Select a category, then click Start Import.';
            document.getElementById('import-cat-row').style.display = 'block';
            document.getElementById('import-start-btn').style.display = 'inline-block';
            document.getElementById('import-progress-modal').style.display = 'flex';
        }

        async function commitImport() {
            if(!_pendingImportFiles.length) return;
            const category = document.getElementById('import-category').value;
            const apiKey = localStorage.getItem('civitai_api_key') || '';
            
            document.getElementById('import-start-btn').style.display = 'none';
            document.getElementById('import-cat-row').style.display = 'none';
            document.getElementById('import-status-msg').innerText = 'Starting import...';

            // For browser file drops we pass the full path via a special header
            // The file object has a .path property on desktop Electron/webview;
            // for standard browsers we use the file name and rely on a temp-upload approach.
            // Here we send the file.path (works when running locally on the same machine).
            const file = _pendingImportFiles[0]; // Process one at a time
            const filePath = file.path || file.name;

            try {
                const res = await fetch('/api/import', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: filePath, category, api_key: apiKey })
                });
                const data = await res.json();
                if(data.import_id) {
                    _activeImportId = data.import_id;
                    pollImport(_activeImportId);
                } else {
                    document.getElementById('import-status-msg').innerText = '❌ ' + (data.message || 'Unknown error');
                }
            } catch(e) {
                document.getElementById('import-status-msg').innerText = '❌ Network error: ' + e.message;
            }
        }

        function pollImport(importId) {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/import/status?id=${importId}`);
                    const data = await res.json();
                    
                    document.getElementById('import-bar').style.width = (data.progress || 0) + '%';
                    document.getElementById('import-status-msg').innerText = data.message || '...';

                    if(data.status === 'done') {
                        clearInterval(interval);
                        window._importDone = true;
                        document.getElementById('import-progress-modal').style.display = 'none';
                        showDependencyResolver(data);
                    } else if(data.status === 'error') {
                        clearInterval(interval);
                        window._importDone = true;
                        document.getElementById('import-status-msg').innerText = '❌ ' + data.message;
                        document.getElementById('import-start-btn').style.display = 'inline-block';
                        document.getElementById('import-start-btn').innerText = 'Close';
                        document.getElementById('import-start-btn').onclick = () => 
                            document.getElementById('import-progress-modal').style.display = 'none';
                    }
                } catch(e) {
                    clearInterval(interval);
                }
            }, 1000);
        }

        function showDependencyResolver(importData) {
            const modelName = importData.metadata?.model?.name || importData.filename || 'Model';
            document.getElementById('dep-model-name').innerText = `"${modelName}" has been imported successfully.`;
            
            const depList = document.getElementById('dep-list');
            const deps = importData.deps || [];
            
            if(!deps.length) {
                depList.innerHTML = '<div style="color:var(--text-muted);font-size:0.9rem;">No dependencies detected. You\'re all set!</div>';
            } else {
                depList.innerHTML = deps.map((dep, i) => `
                    <div style="background:var(--bg-color); border:1px solid var(--border); border-radius:10px; padding:14px; display:flex; align-items:center; gap:12px;">
                        <div style="flex:1;">
                            <div style="font-weight:600; font-size:0.9rem;">${escHtml(dep.name)}</div>
                            <div style="color:var(--text-muted); font-size:0.8rem;">${escHtml(dep.type)}</div>
                        </div>
                        ${dep.civitai_url ? `<a href="${escHtml(dep.civitai_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--primary);font-size:0.8rem;text-decoration:none;font-weight:600;">View →</a>` : ''}
                        <button onclick="quickDownloadDep('${escHtml(String(dep.civitai_id || ''))}')" style="background:var(--primary);color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600;">Install</button>
                    </div>
                `).join('');
            }
            document.getElementById('dep-resolver-modal').style.display = 'flex';
        }

        async function quickDownloadDep(civitaiModelId) {
            if(!civitaiModelId) return;
            // Open the lightbox for this dep so user can pick version
            window.open(`https://civitai.com/models/${civitaiModelId}`, '_blank');
        }

        /* ═══════════════════════════════════════════════
           VAULT CLIENT-SIDE FILTERING
        ═══════════════════════════════════════════════ */
        let _allVaultModels = [];

        function filterVaultGrid(query) {
            // V-4 fix: Reset semantic search flag when using standard filters
            window._semanticSearchActive = false;
            const cat = document.getElementById('vault-cat-filter').value.toLowerCase();
            const tag = document.getElementById('vault-tag-filter').value.toLowerCase();
            const q = (query || '').toLowerCase();
            const grid = document.getElementById('models-grid');
            
            Array.from(grid.children).forEach(card => {
                // V-1 fix: data-name is already lowercase from renderVaultGrid, skip redundant toLowerCase
                const cardCat = card.dataset.category || '';
                const cardName = card.dataset.name || '';
                const cardTags = card.dataset.tags || '';
                const matchesCat = !cat || cardCat === cat;
                const matchesTag = !tag || cardTags.includes(tag);
                // Local filter acts only on name if not performing semantic search
                const matchesQ = !q || cardName.includes(q);
                card.style.display = (matchesCat && matchesTag && matchesQ) ? '' : 'none';
            });
        }

        async function filterVaultByTag(tag) {
            filterVaultGrid(document.getElementById('vault-search').value);
        }

        async function searchVaultModels(query) {
            if(!query.trim()) {
                window._semanticSearchActive = false;
                loadModels(false);
                return;
            }
            window._semanticSearchActive = true;
            document.getElementById('models-grid').innerHTML = '<div class="empty-state">Searching vault via Semantic Embeddings...</div>';
            try {
                const res = await fetch(`/api/vault/search?query=${encodeURIComponent(query)}&limit=40`);
                const data = await res.json();
                renderVaultGrid(data.models || [], false);
                document.getElementById('vault-load-more-container').style.display = 'none'; // Disable pagination for semantic search for now
            } catch(e) {
                console.error("Semantic search failed:", e);
                document.getElementById('models-grid').innerHTML = '<div class="empty-state">Semantic search failed or indexing in progress.</div>';
            }
        }


        // ── SSE Consumer: Vault Crawler Progress ──────────────────────────
        window._onSSEVaultCrawl = function(data) {
            if (!data) return;
            if (data.status === 'started') {
                showToast('🔍 Vault indexing started...');
            } else if (data.status === 'completed') {
                showToast(`✅ Vault indexing complete — ${data.indexed || 0} models indexed`);
                // Refresh the vault grid to show newly indexed models
                if (typeof loadModels === 'function') loadModels();
            } else if (data.status === 'progress') {
                console.debug(`[Vault Crawl] ${data.phase || 'Scanning'}: ${data.current || 0}/${data.total || '?'}`);
            }
        };

        /* ═══════════════════════════════════════════════
