           SPRINT 9 — Batch Generation Queue
        ═════════════════════════════════════════════ */

        let _batchPollInterval = null;

        function getInferencePayload() {
            // IS-05: Delegate to unified payload builder, then apply wildcard resolution
            const payload = buildGenerationPayload();
            payload.prompt = resolveWildcards(payload.prompt);
            payload.negative_prompt = resolveWildcards(payload.negative_prompt || '');
            return payload;
        }

        async function addToBatchQueue() {
            const payload = getInferencePayload();
            if(!payload.prompt.trim()) {
                showToast('Enter a prompt before adding to queue.'); return;
            }
            try {
                const res = await fetch('/api/generate/batch', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ payload })
                });
                const data = await res.json();
                if(data.status === 'success') {
                    showToast(`Added to queue (${data.queue_length} total)`);
                    refreshBatchPanel();
                    if(!_batchPollInterval) {
                        _batchPollInterval = setInterval(refreshBatchPanel, 2000);
                    }
                } else {
                    showToast('Queue error: ' + (data.message || 'Unknown'));
                }
            } catch(e) {
                showToast('Failed to add to queue: ' + e.message);
            }
        }

        async function refreshBatchPanel() {
            try {
                const res = await fetch('/api/generate/queue');
                const data = await res.json();
                const queue = data.queue || [];

                const countEl = document.getElementById('inf-batch-count');
                if(countEl) countEl.innerText = queue.length;

                const listEl = document.getElementById('batch-list');
                if(!listEl) return;

                if(queue.length === 0) {
                    listEl.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:20px; font-size:0.85rem;">Queue is empty</div>';
                    if(_batchPollInterval) { clearInterval(_batchPollInterval); _batchPollInterval = null; }
                    return;
                }

                listEl.innerHTML = queue.map(j => `
                    <div class="batch-item">
                        <div class="batch-status ${j.status}"></div>
                        <div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#e2e8f0;">${j.prompt || '(no prompt)'}</div>
                        <span style="color:var(--text-muted); font-size:0.75rem; flex-shrink:0;">${j.status}</span>
                    </div>
                `).join('');

                // Stop polling if all done/failed
                const allFinished = queue.every(j => j.status === 'done' || j.status === 'failed');
                if(allFinished && _batchPollInterval) {
                    clearInterval(_batchPollInterval); _batchPollInterval = null;
                }
            } catch(e) {}
        }

        function toggleBatchPanel() {
            const panel = document.getElementById('batch-panel');
            if(!panel) return;
            panel.classList.toggle('open');
            if(panel.classList.contains('open')) refreshBatchPanel();
        }

        // ── SSE Consumer: Batch Updates ──────────────────────────
        window._onSSEBatchUpdate = function(data) {
            // Server pushed a batch job status change — refresh the panel UI
            refreshBatchPanel();
            // Show toast notification for completion
            if (data.status === 'done') {
                showToast('🎨 Batch job completed');
            } else if (data.status === 'failed') {
                showToast('❌ Batch job failed: ' + (data.error || 'Unknown error'));
            }

            // IS-06: Update XYZ/Seed Explorer grid cell if this job belongs to an active session
            if (window._xyzJobIds && data.id) {
                const idx = window._xyzJobIds.indexOf(data.id);
                if (idx !== -1 && window._xyzGridEl) {
                    const cell = window._xyzGridEl.querySelector(`[data-xyz-idx="${idx}"]`);
                    if (cell) {
                        if (data.status === 'done') {
                            cell.style.background = 'rgba(16, 185, 129, 0.15)';
                            cell.style.borderColor = '#10b981';
                            const label = cell.querySelector('.xyz-grid-label');
                            if (label) label.textContent = '✅ ' + label.textContent;
                        } else if (data.status === 'failed') {
                            cell.style.background = 'rgba(239, 68, 68, 0.15)';
                            cell.style.borderColor = '#ef4444';
                            const label = cell.querySelector('.xyz-grid-label');
                            if (label) label.textContent = '❌ ' + label.textContent;
                        }
                    }
                    // Check if all jobs are complete
                    const completedCount = window._xyzJobIds.filter((_, i) => {
                        const c = window._xyzGridEl.querySelector(`[data-xyz-idx="${i}"]`);
                        return c && (c.style.borderColor === 'rgb(16, 185, 129)' || c.style.borderColor === 'rgb(239, 68, 68)');
                    }).length;
                    if (completedCount >= window._xyzJobIds.length) {
                        const statusEl = document.getElementById('xyz-status');
                        if (statusEl) statusEl.textContent = '✅ All XYZ/Seed jobs completed!';
                        window._xyzJobIds = null;
                    }
                }
            }
        };

        /* ═════════════════════════════════════════════
           SPRINT 9 — Vault Import from Backup
        ═════════════════════════════════════════════ */

        async function handleVaultImportBackup(file) {
            if(!file) return;
            try {
                const text = await file.text();
                let parsed = JSON.parse(text);
                // Support both direct array manifests and {manifest: [...]} wrappers
                let manifest = Array.isArray(parsed) ? parsed : (parsed.manifest || []);

                if(!manifest.length) {
                    showToast('Invalid manifest: no model entries found.');
                    return;
                }

                const res = await fetch('/api/vault/import', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ manifest })
                });
                const data = await res.json();
                if(data.status === 'success') {
                    showToast(`Import complete: ${data.imported} imported, ${data.skipped} skipped.`);
                    loadModels();  // Refresh vault grid
                } else {
                    showToast('Import failed: ' + (data.message || 'Unknown error'));
                }
            } catch(e) {
                showToast('Import error: ' + e.message);
            }
            // Reset file input
            document.getElementById('vault-import-file').value = '';
        }
        
        /* ═══════════════════════════════════════════════
