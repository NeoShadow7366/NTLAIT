           SPRINT 7 — PROMPT LIBRARY
        ═══════════════════════════════════════════════ */
        function togglePromptLibrary() {
            const panel = document.getElementById('prompt-lib-panel');
            panel.classList.toggle('open');
            if(panel.classList.contains('open')) loadPromptLibrary();
        }
        async function loadPromptLibrary(search) {
            const list = document.getElementById('prompt-lib-list');
            list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:20px;">Loading...</div>';
            try {
                let url = '/api/prompts';
                if(search) url += '?search=' + encodeURIComponent(search);
                const res = await fetch(url);
                const data = await res.json();
                if(!data.prompts || data.prompts.length === 0) {
                    list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:40px 0;">No saved prompts yet.</div>';
                    return;
                }
                list.innerHTML = data.prompts.map(p => `
                    <div class="prompt-card">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                            <strong style="font-size:0.95rem;">${p.title}</strong>
                            <div style="display:flex;gap:6px;flex-shrink:0;">
                                <button onclick="event.stopPropagation(); loadPromptToStudio(${p.id})" title="Load into Studio" style="background:var(--primary);color:#fff;border:none;padding:4px 10px;border-radius:5px;font-size:0.8rem;cursor:pointer;font-weight:600;">⚡ Load</button>
                                <button onclick="event.stopPropagation(); deletePrompt(${p.id})" title="Delete" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:1rem;">🗑</button>
                            </div>
                        </div>
                        <div style="font-size:0.82rem; color:var(--text-muted); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${(p.prompt || '').substring(0,120)}${p.prompt?.length > 120 ? '...' : ''}</div>
                        ${p.model ? `<div style="font-size:0.75rem; color:#60a5fa; margin-top:6px;">🎨 ${p.model}</div>` : ''}
                    </div>
                `).join('');
            } catch(e) {
                list.innerHTML = '<div style="text-align:center; color:#ef4444; padding:20px;">Error loading prompts.</div>';
            }
        }
        let _promptSearchTimer = null;
        function searchPromptLibrary(q) {
            clearTimeout(_promptSearchTimer);
            _promptSearchTimer = setTimeout(() => loadPromptLibrary(q || undefined), 300);
        }
        function openSavePromptDialog() {
            const title = prompt('💾 Save Prompt\n\nEnter a title for this prompt:');
            if(!title || !title.trim()) return;
            const promptVal = document.getElementById('inf-prompt')?.value || '';
            const negVal = document.getElementById('inf-negative')?.value || '';
            const modelVal = document.getElementById('inf-model')?.value || '';
            fetch('/api/prompts/save', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ title: title.trim(), prompt: promptVal, negative: negVal, model: modelVal })
            }).then(r => r.json()).then(data => {
                if(data.status === 'success') {
                    showSettingsToast('✅ Prompt saved to library!');
                    if(document.getElementById('prompt-lib-panel').classList.contains('open')) loadPromptLibrary();
                } else {
                    alert('Failed: ' + (data.message || 'Unknown error'));
                }
            }).catch(e => alert('Error saving prompt: ' + e.message));
        }
        async function loadPromptToStudio(promptId) {
            try {
                const res = await fetch('/api/prompts');
                const data = await res.json();
                const p = (data.prompts || []).find(x => x.id === promptId);
                if(!p) return;
                const promptEl = document.getElementById('inf-prompt');
                const negEl = document.getElementById('inf-negative');
                const modelEl = document.getElementById('inf-model');
                if(promptEl) promptEl.value = p.prompt || '';
                if(negEl) negEl.value = p.negative || '';
                if(modelEl && p.model) {
                    // Try to select the model
                    for(let opt of modelEl.options) {
                        if(opt.value === p.model || opt.text === p.model) { modelEl.value = opt.value; break; }
                    }
                }
                showSettingsToast('⚡ Prompt loaded into Studio');
                togglePromptLibrary();
                switchTab('inference');
            } catch(e) { alert('Error loading prompt: ' + e.message); }
        }
        async function deletePrompt(id) {
            if(!confirm('Delete this saved prompt?')) return;
            try {
                const res = await fetch('/api/prompts/delete', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id })
                });
                const data = await res.json();
                if(data.status === 'success') loadPromptLibrary();
            } catch(e) { alert('Error: ' + e.message); }
        }
        // ═══ Server-Sent Events (SSE) Client ══════════════════════════
        // Replaces multiple setInterval polling loops with a single
        // persistent connection. Events are dispatched to handler functions
        // that may be defined in any module.
        (function initSSE() {
            if (typeof EventSource === 'undefined') {
                console.warn('SSE not supported in this browser, falling back to polling');
                return;
            }

            let sse = null;
            let retryCount = 0;

            function connect() {
                sse = new EventSource('/api/events');

                sse.onopen = () => {
                    retryCount = 0;
                    console.log('[SSE] Connected to event stream');
                };

                // Download progress events
                sse.addEventListener('download_progress', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        if (typeof window._onSSEDownloadProgress === 'function') {
                            window._onSSEDownloadProgress(data);
                        }
                    } catch (err) { console.debug('[SSE] download_progress parse error', err); }
                });

                // Install progress events
                sse.addEventListener('install_progress', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        if (typeof window._onSSEInstallProgress === 'function') {
                            window._onSSEInstallProgress(data);
                        }
                    } catch (err) { console.debug('[SSE] install_progress parse error', err); }
                });

                // Server status events
                sse.addEventListener('server_status', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        if (typeof window._onSSEServerStatus === 'function') {
                            window._onSSEServerStatus(data);
                        }
                    } catch (err) { console.debug('[SSE] server_status parse error', err); }
                });

                // Batch queue events
                sse.addEventListener('batch_update', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        if (typeof window._onSSEBatchUpdate === 'function') {
                            window._onSSEBatchUpdate(data);
                        }
                    } catch (err) { console.debug('[SSE] batch_update parse error', err); }
                });

                // Vault crawler events
                sse.addEventListener('vault_crawl', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        if (typeof window._onSSEVaultCrawl === 'function') {
                            window._onSSEVaultCrawl(data);
                        }
                    } catch (err) { console.debug('[SSE] vault_crawl parse error', err); }
                });

                sse.onerror = () => {
                    // EventSource auto-reconnects, but log for debugging
                    retryCount++;
                    if (retryCount <= 3) {
                        console.debug('[SSE] Connection error, auto-reconnecting...');
                    }
                };
            }

            // Connect after DOM is ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', connect);
            } else {
                connect();
            }

            // Expose for debugging
            window._sseConnection = { getState: () => sse ? sse.readyState : -1 };
        })();

        // Init
        loadExplorer();
        loadSettings();

