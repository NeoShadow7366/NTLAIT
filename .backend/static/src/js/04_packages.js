        async function loadPackages() {
            try {
                const res = await fetch('/api/packages');
                const data = await res.json();
                const grid = document.getElementById('packages-grid');
                grid.innerHTML = '';
                
                window.activePackages = data.packages || [];
                
                if(!data.packages || data.packages.length === 0) {
                    grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;">No packages installed yet. Visit the App Store!</div>';
                    return;
                }

                data.packages.forEach(p => {
                    let runBtns = p.is_running ? `
                        <button onclick="stopPackage('${p.id}')" style="background: #f59e0b; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">Stop Process</button>
                        <button onclick="restartPackage('${p.id}')" style="background: var(--primary); color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">Restart Engine</button>
                    ` : `
                        <button onclick="launchPackage('${p.id}')" style="background: var(--primary); color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">Launch UI</button>
                    `;
                    
                    const statusDot = p.is_running ? `<div class="progress-pulsing" style="width:10px; height:10px; border-radius:50%; background:#10b981; display:inline-block; margin-left:8px;" title="Running"></div>` : '';

                    grid.innerHTML += `
                        <div class="std-card" id="pkg-card-${p.id}">
                            <h3 class="card-title" style="display:flex; align-items:center;">${p.name}${statusDot}</h3>
                            <div style="display:flex; gap:8px; align-items:center; margin-top:4px; flex-wrap:wrap;">
                                ${p.installed_version ? `<span style="font-size:0.72rem; background:var(--primary); color:white; padding:2px 8px; border-radius:8px; font-weight:600;">${p.installed_version}</span>` : ''}
                                ${p.disk_size_mb != null ? `<span style="font-size:0.7rem; color:var(--text-muted);">💾 ${p.disk_size_mb >= 1024 ? (p.disk_size_mb / 1024).toFixed(1) + ' GB' : p.disk_size_mb + ' MB'}</span>` : ''}
                                ${p.installed_at ? `<span style="font-size:0.7rem; color:var(--text-muted);">· ${new Date(p.installed_at).toLocaleDateString()}</span>` : ''}
                            </div>
                            <div id="pkg-status-${p.id}" style="display:none; margin-top:8px; font-size:0.78rem; color: #a78bfa; font-weight:600;"></div>
                            <div style="margin-top: 15px; display:flex; gap:10px; flex-wrap:wrap;">
                                ${runBtns}
                                <button onclick="openLogTerminal('${p.id}', '${p.name}')" style="background: var(--surface-hover); color: white; border: 1px solid var(--border); padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">⌨️ Terminal</button>
                                <button onclick="openExtensions('${p.id}', '${p.name}')" style="background: #8b5cf6; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">Plugins</button>
                                <button onclick="repairDependencies('${p.id}')" style="background: #a78bfa; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;" title="Fix missing Python packages (PyTorch CUDA, etc.)">💊 Fix Deps</button>
                                <button onclick="repairPackage('${p.id}')" style="background: #f59e0b; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;" title="Re-download source code">🔧 Repair</button>
                                <button onclick="uninstallPackage('${p.id}')" style="background: #ef4444; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;" title="Uninstall">Uninstall</button>
                            </div>
                        </div>
                    `;
                });
                
                // Refresh recipes UI to accurately reflect newly installed/uninstalled packages
                loadRecipes();
            } catch (e) {
                console.error(e);
            }
        }

        async function loadRecipes() {
            try {
                const res = await fetch('/api/recipes');
                const data = await res.json();
                const grid = document.getElementById('recipes-grid');
                grid.innerHTML = '';
                
                if(!data.recipes || data.recipes.length === 0) {
                    grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;">No recipes found in .backend/recipes/</div>';
                    return;
                }
                window.activePackages = window.activePackages || [];

                data.recipes.forEach(r => {
                    const isInstalled = window.activePackages.some(p => p.id === r.app_id);
                    const btnHtml = isInstalled 
                        ? `<button disabled style="background: var(--surface); color: var(--text-muted); border: 1px solid var(--border); padding: 8px 15px; border-radius: 6px; cursor: not-allowed; font-weight: 600;">✅ Installed</button>`
                        : `<button id="install-btn-${r.app_id}" onclick="installRecipe('${r.id}', '${r.app_id}')" style="background: #10b981; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">Install Sandbox</button>`;

                    const repoShort = r.repository ? r.repository.replace('https://github.com/', '').replace('.git', '') : '';

                    grid.innerHTML += `
                        <div class="std-card" id="recipe-card-${r.app_id}">
                            <h3 class="card-title" style="display:flex; align-items:center; gap:10px;">
                                ${r.name}
                                ${isInstalled ? `<span style="font-size:0.7rem; background: #10b981; color:white; padding:2px 6px; border-radius:8px; font-weight: bold;">INSTALLED</span>` : ''}
                            </h3>
                            ${repoShort ? `<p class="subtitle" style="font-size: 0.78rem; margin-bottom:4px; color:var(--text-muted);"><span style="opacity:0.6;">📦</span> ${repoShort}</p>` : ''}
                            <p class="subtitle" style="font-size: 0.82rem; margin-bottom: 15px;">${r.description || 'Isolated sandbox with auto-linked Global Vault models.'}</p>
                            <div id="install-progress-${r.app_id}" style="display:none; margin-bottom:12px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                    <span id="install-phase-${r.app_id}" style="font-size:0.8rem; color: #a78bfa; font-weight:600;">Starting...</span>
                                    <span id="install-pct-${r.app_id}" style="font-size:0.75rem; color: var(--text-muted);">0%</span>
                                </div>
                                <div style="width:100%; height:6px; background: var(--border); border-radius:3px; overflow:hidden;">
                                    <div id="install-bar-${r.app_id}" style="height:100%; width:0%; background: linear-gradient(90deg, #10b981, #34d399); border-radius:3px; transition: width 0.4s ease;"></div>
                                </div>
                                <div id="install-log-${r.app_id}" style="font-size:0.7rem; color: var(--text-muted); margin-top:6px; font-family:monospace; background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:6px 8px; max-height:100px; overflow-y:auto; white-space:pre-wrap; line-height:1.4;"></div>
                            </div>
                            <div style="display:flex; gap:10px;">
                                ${btnHtml}
                                <button onclick="openLogTerminal('${r.id}', '${r.name}')" style="background: var(--surface-hover); color: white; border: 1px solid var(--border); padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 600;">⌨️ View Log</button>
                            </div>
                        </div>
                    `;
                });
            } catch (e) {
                console.error(e);
            }
        }

        let _installPollIntervals = {};

        async function installRecipe(recipeId, appId) {
            const btn = document.getElementById(`install-btn-${appId}`);
            if(btn) { btn.innerText = "Starting..."; btn.disabled = true; }
            const progressEl = document.getElementById(`install-progress-${appId}`);
            if(progressEl) progressEl.style.display = 'block';
            try {
                const res = await fetch('/api/install', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({recipe_id: recipeId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    if(btn) btn.innerText = "Installing...";
                    startInstallPoll(appId);
                } else {
                    if(btn) { btn.innerText = "Error"; btn.disabled = false; }
                    if(progressEl) progressEl.style.display = 'none';
                    alert(response.message);
                }
            } catch(e) {
                alert("Failed to contact server");
                if(btn) { btn.innerText = "Install Sandbox"; btn.disabled = false; }
                if(progressEl) progressEl.style.display = 'none';
            }
        }

        function startInstallPoll(appId) {
            if(_installPollIntervals[appId]) clearInterval(_installPollIntervals[appId]);
            _installPollIntervals[appId] = setInterval(async () => {
                try {
                    const res = await fetch('/api/install/status');
                    const data = await res.json();
                    const job = data.jobs?.[appId];
                    if(!job) return;
                    const phaseEl = document.getElementById(`install-phase-${appId}`);
                    const pctEl = document.getElementById(`install-pct-${appId}`);
                    const barEl = document.getElementById(`install-bar-${appId}`);
                    const logEl = document.getElementById(`install-log-${appId}`);
                    const btn = document.getElementById(`install-btn-${appId}`);
                    if(phaseEl) phaseEl.innerText = job.phase || 'Working...';
                    if(pctEl) pctEl.innerText = `${job.percent || 0}%`;
                    if(barEl) barEl.style.width = `${job.percent || 0}%`;
                    if(logEl && job.log?.length) {
                        logEl.innerText = job.log.join('\n');
                        logEl.scrollTop = logEl.scrollHeight;
                    }
                    if(job.status === 'completed') {
                        clearInterval(_installPollIntervals[appId]);
                        delete _installPollIntervals[appId];
                        if(barEl) barEl.style.background = 'linear-gradient(90deg, #10b981, #22c55e)';
                        if(phaseEl) { phaseEl.innerText = 'Installation Complete'; phaseEl.style.color = '#4ade80'; }
                        if(btn) { btn.innerText = 'Installed'; btn.style.background = 'var(--surface)'; btn.style.color = 'var(--text-muted)'; }
                        setTimeout(() => { loadRecipes(); if(typeof loadPackages === 'function') loadPackages(); }, 2000);
                    } else if(job.status === 'failed') {
                        clearInterval(_installPollIntervals[appId]);
                        delete _installPollIntervals[appId];
                        if(barEl) barEl.style.background = '#ef4444';
                        if(phaseEl) { phaseEl.innerText = 'Installation Failed'; phaseEl.style.color = '#ef4444'; }
                        if(btn) { btn.innerText = 'Retry Install'; btn.disabled = false; btn.style.background = '#ef4444'; }
                    }
                } catch(e) {
                    console.error("Install poll error:", e);
                }
            }, 2000);
        }
        async function launchPackage(packageId) {
            const btn = event.currentTarget;
            btn.innerText = "Launching...";
            btn.disabled = true;
            try {
                const res = await fetch('/api/launch', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    if(response.already_running && response.url) {
                        window.open(response.url, '_blank');
                        loadPackages();
                        return;
                    }
                    // Show warm-up status on the card
                    const statusEl = document.getElementById(`pkg-status-${packageId}`);
                    if(statusEl) {
                        statusEl.style.display = 'block';
                        statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#a78bfa; margin-right:6px;"></span>Initializing engine...';
                    }
                    btn.innerText = "Starting...";
                    // Connectivity poll: wait for the engine to actually respond
                    if(response.url) {
                        let attempts = 0;
                        const maxAttempts = 60; // 60 × 2s = 2 minutes max
                        const pollId = setInterval(async () => {
                            attempts++;
                            if(statusEl) statusEl.innerHTML = `<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#a78bfa; margin-right:6px;"></span>Warming up engine... (${attempts}s)`;
                            try {
                                const probe = await fetch(response.url, {mode: 'no-cors', signal: AbortSignal.timeout(2000)});
                                // If we get here without error, the engine is listening
                                clearInterval(pollId);
                                if(statusEl) { statusEl.innerHTML = '✅ Engine ready!'; setTimeout(() => { statusEl.style.display = 'none'; }, 2000); }
                                window.open(response.url, '_blank');
                                loadPackages();
                            } catch(_) {
                                if(attempts >= maxAttempts) {
                                    clearInterval(pollId);
                                    if(statusEl) { statusEl.innerHTML = '⚠️ Engine may still be loading. <a href="' + response.url + '" target="_blank" style="color:#a78bfa;">Open manually →</a>'; }
                                    loadPackages();
                                }
                            }
                        }, 2000);
                    }
                    loadPackages();
                } else {
                    // Check if server says we need a repair
                    if(response.needs_repair) {
                        const statusEl = document.getElementById(`pkg-status-${packageId}`);
                        if(statusEl) {
                            statusEl.style.display = 'block';
                            statusEl.innerHTML = '⚠️ Source code missing. <a href="#" onclick="repairPackage(\'' + packageId + '\'); return false;" style="color:#f59e0b; text-decoration:underline;">Click here to repair</a>';
                        }
                        btn.innerText = 'Launch UI'; btn.disabled = false;
                    } else {
                        alert(response.message); btn.innerText = 'Launch UI'; btn.disabled = false;
                    }
                }
            } catch(e) { alert("Failed to contact server"); btn.innerText = 'Launch UI'; btn.disabled = false; }
        }

        async function repairPackage(packageId) {
            if(!confirm(`Repair ${packageId}?\n\nThis will re-download the source code. Your venv and models are preserved.`)) return;
            const statusEl = document.getElementById(`pkg-status-${packageId}`);
            if(statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#f59e0b; margin-right:6px;"></span>Starting repair...';
            }
            try {
                const res = await fetch('/api/repair', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    // Check if it was an instant git checkout repair (no background process)
                    if(response.message && response.message.includes('restored from git')) {
                        if(statusEl) statusEl.innerHTML = '✅ ' + response.message;
                        setTimeout(loadPackages, 1500);
                        return;
                    }
                    // Full re-install: poll install_jobs.json for progress
                    if(statusEl) statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#f59e0b; margin-right:6px;"></span>Re-downloading source code...';
                    const repairPoll = setInterval(async () => {
                        try {
                            const sr = await fetch('/api/install/status');
                            const sd = await sr.json();
                            const job = sd.jobs?.[packageId];
                            if(!job) return;
                            if(statusEl) {
                                const pct = job.percent || 0;
                                const phase = job.phase || 'Working...';
                                const logLine = job.log?.length ? job.log[job.log.length - 1] : '';
                                statusEl.innerHTML = `<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#f59e0b; margin-right:6px;"></span>${phase} (${pct}%)<br><span style="font-size:0.7rem; color:var(--text-muted); font-weight:normal;">${logLine}</span>`;
                            }
                            if(job.status === 'completed') {
                                clearInterval(repairPoll);
                                if(statusEl) { statusEl.innerHTML = '✅ Repair complete!'; }
                                setTimeout(loadPackages, 2000);
                            } else if(job.status === 'failed') {
                                clearInterval(repairPoll);
                                if(statusEl) { statusEl.innerHTML = '❌ Repair failed: ' + (job.phase || 'Unknown error'); }
                            }
                        } catch(_) {}
                    }, 2000);
                } else {
                    if(statusEl) statusEl.innerHTML = '❌ ' + response.message;
                }
            } catch(e) {
                alert('Failed to contact server');
                if(statusEl) statusEl.style.display = 'none';
            }
        }

        async function repairDependencies(packageId) {
            if(!confirm(`Fix dependencies for ${packageId}?\n\nThis will:\n• Bootstrap pip if missing\n• Install CUDA PyTorch\n• Install all requirements\n\nThis may take 10-15 minutes for large packages.`)) return;
            const statusEl = document.getElementById(`pkg-status-${packageId}`);
            if(statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#a78bfa; margin-right:6px;"></span>Starting dependency repair...';
            }
            try {
                const res = await fetch('/api/repair_dependency', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    if(statusEl) statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#a78bfa; margin-right:6px;"></span>' + response.message;
                    // Progress now tracked via install_jobs.json → SSE install_progress events
                    showToast('Dependency repair started — progress shown on card');
                } else {
                    if(statusEl) statusEl.innerHTML = '❌ ' + response.message;
                }
            } catch(e) {
                alert('Failed to contact server');
                if(statusEl) statusEl.style.display = 'none';
            }
        }

        async function stopPackage(packageId) {
            const btn = event.currentTarget;
            const originalText = btn.innerText;
            btn.innerText = "Stopping...";
            btn.disabled = true;
            try {
                const res = await fetch('/api/stop', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                await res.json();
                loadPackages();
            } catch(e) {
                alert("Failed to contact server");
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }
        
        async function restartPackage(packageId) {
            const btn = event.currentTarget;
            btn.innerText = "Restarting...";
            btn.disabled = true;
            const statusEl = document.getElementById(`pkg-status-${packageId}`);
            if(statusEl) { statusEl.style.display = 'block'; statusEl.innerText = 'Stopping engine...'; }
            try {
                const res = await fetch('/api/restart', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    if(statusEl) statusEl.innerText = '✅ Restarted successfully';
                    setTimeout(() => { if(statusEl) statusEl.style.display = 'none'; loadPackages(); }, 2000);
                } else {
                    if(statusEl) statusEl.innerText = '⚠️ ' + (response.message || 'Restart failed');
                    loadPackages();
                }
            } catch(e) {
                alert("Failed to restart!");
                btn.innerText = 'Restart Engine';
                btn.disabled = false;
                if(statusEl) statusEl.style.display = 'none';
            }
        }

        async function uninstallPackage(packageId) {
            if(!confirm("Are you sure you want to permanently delete " + packageId + "?\n\nNote: Your Global Vault models are safe and will NOT be deleted.")) return;
            const btn = event.currentTarget;
            btn.innerText = "Removing...";
            btn.disabled = true;
            btn.style.opacity = '0.7';
            // Show inline deletion status on card
            const statusEl = document.getElementById(`pkg-status-${packageId}`);
            if(statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = '<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#ef4444; margin-right:6px;"></span>Removing files...';
            }
            try {
                const res = await fetch('/api/uninstall', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: packageId})
                });
                const response = await res.json();
                if(response.status === 'success') {
                    if(statusEl) statusEl.innerHTML = '✅ Uninstalled!';
                    setTimeout(loadPackages, 800);
                } else {
                    alert(response.message);
                    btn.innerText = "Error";
                    if(statusEl) statusEl.style.display = 'none';
                }
            } catch(e) {
                alert("Failed to contact server");
                btn.innerText = 'Uninstall';
                btn.disabled = false;
                btn.style.opacity = '1';
                if(statusEl) statusEl.style.display = 'none';
            }
        }

        /* ═══════════════════════════════════════════════
           TERMINAL WEB VIEWER
        ═══════════════════════════════════════════════ */
        let terminalInterval = null;
        
        function openLogTerminal(packageId, packageName) {
            document.getElementById('terminal-modal').style.display = 'flex';
            document.getElementById('term-pkg-name').innerText = packageName;
            const termOut = document.getElementById('term-output');
            termOut.innerText = "Connecting to log stream...";
            
            terminalInterval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/logs?package_id=${packageId}`);
                    const data = await res.json();
                    
                    const isScrolledToBottom = termOut.scrollHeight - termOut.clientHeight <= termOut.scrollTop + 50;
                    termOut.innerText = data.logs || "--- Empty Log ---";
                    if(isScrolledToBottom) {
                        termOut.scrollTop = termOut.scrollHeight;
                    }
                } catch(e) {}
            }, 1000);
        }
        
        function closeTerminal() {
            document.getElementById('terminal-modal').style.display = 'none';
            if(terminalInterval) clearInterval(terminalInterval);
        }

        /* ═══════════════════════════════════════════════
           VAULT HEALTH & UPDATES
        ═══════════════════════════════════════════════ */
        async function triggerUpdatesCheck() {
            try {
                const res = await fetch('/api/vault/updates', { method: 'POST', body: '{}' });
                const data = await res.json();
                if(data.status === 'success') {
                    alert("Update checker started in the background. It will poll CivitAI for new versions of your models. Check the terminal for progress.");
                } else alert(data.message);
            } catch(e) { alert("Failed to start update check."); }
        }

        async function triggerUnmanagedImport() {
            try {
                const payload = {api_key: document.getElementById('set-api-key')?.value || ''};
                const res = await fetch('/api/vault/import_scan', { method: 'POST', body: JSON.stringify(payload), headers: {'Content-Type': 'application/json'} });
                const data = await res.json();
                alert(data.message || "Import scan started.");
            } catch(e) { alert("Failed to start import scan."); }
        }

        async function triggerExternalImport() {
            const extPath = prompt('Enter the absolute path to your external Models folder (e.g. C:\\Users\\Name\\AppData\\Roaming\\StabilityMatrix\\Models).\n\nA zero-byte directory link will be created inside Global_Vault to native scan these models.');
            if(!extPath || !extPath.trim()) return;
            
            try {
                showSettingsToast('🔗 Linking external folder...');
                const res = await fetch('/api/import/external', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: extPath.trim() })
                });
                const data = await res.json();
                if(data.status === 'success') {
                    showSettingsToast('✅ Successfully linked folder! Scanning will begin automatically.');
                    // Trigger a scan immediately
                    await fetch('/api/vault/import_scan', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
                } else {
                    alert("Link failed: " + data.message);
                }
            } catch(e) { alert("Connection Error during linking."); }
        }

        async function triggerHealthCheck() {
            try {
                const res = await fetch('/api/vault/health_check', { method: 'POST', body: '{}' });
                const data = await res.json();
                if(data.status === 'success') {
                    alert("Health Scan Complete:\n" + data.message);
                } else alert(data.message);
            } catch(e) { alert("Failed to run health check."); }
        }

        /* NOTE: loadSettings/saveSettings/triggerSystemUpdate defined in the Settings Panel section below */

        /* ═══════════════════════════════════════════════
           RECIPE / EXTENSION MANAGEMENT JS
        ═══════════════════════════════════════════════ */
        async function submitNewRecipe() {
            const app_id = document.getElementById('recipe-id').value;
            const name = document.getElementById('recipe-name').value;
            if(!app_id || !name) return alert("App ID and Name required.");
            
            const symlink_targets = Array.from(document.querySelectorAll('.recipe-symlink-cb:checked')).map(cb => cb.value);
            
            const payload = {
                app_id, name,
                repository: document.getElementById('recipe-repo').value,
                launch: document.getElementById('recipe-launch').value,
                pip_packages: (document.getElementById('recipe-pip').value || '').split(',').map(s=>s.trim()).filter(Boolean),
                symlink_targets,
                platform_flags: (document.getElementById('recipe-platform-flags') || {}).value || '',
                requirements_file: 'requirements.txt'
            };
            
            try {
                const res = await fetch('/api/recipes/build', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if(data.status === 'success') {
                    document.getElementById('recipe-modal').style.display = 'none';
                    loadRecipes();
                    showSettingsToast('✅ Recipe saved: ' + (data.recipe_id || ''));
                } else alert(data.message);
            } catch(e) { alert("Error building recipe"); }
        }

        let currentExtPkg = null;
        async function openExtensions(pkgId, pkgName) {
            currentExtPkg = pkgId;
            document.getElementById('ext-pkg-name').innerText = pkgName;
            document.getElementById('ext-repo-url').value = '';
            document.getElementById('ext-list').innerHTML = '<div style="color:var(--text-muted);padding:10px;">Loading extensions...</div>';
            document.getElementById('extensions-modal').style.display = 'flex';
            
            try {
                const res = await fetch('/api/extensions?package_id=' + pkgId);
                const data = await res.json();
                if(data.status === 'success') {
                    const list = document.getElementById('ext-list');
                    if(data.extensions.length === 0) list.innerHTML = '<div style="color:var(--text-muted);padding:10px;">No custom nodes/extensions found.</div>';
                    else {
                        list.innerHTML = data.extensions.map(e => `
                            <div style="display:flex; justify-content:space-between; align-items:center; background:var(--surface); padding:10px; border-radius:6px; border:1px solid var(--border);">
                                <span style="font-size:0.9rem;">${e.name}</span>
                                <button onclick="removeExtension('${pkgId}', '${e.name}')" style="background:none; border:none; color:#ef4444; cursor:pointer;" title="Remove">🗑</button>
                            </div>
                        `).join('');
                    }
                }
            } catch(e) {}
        }

        let _currentExtJobId = null;
        let _extPollInterval = null;

        async function installExtension() {
            if(!currentExtPkg) return;
            const repo = document.getElementById('ext-repo-url').value;
            if(!repo) return;

            const cloneBtn = document.getElementById('ext-clone-btn');
            cloneBtn.disabled = true;
            cloneBtn.innerText = 'Starting...';

            try {
                const res = await fetch('/api/extensions/install', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: currentExtPkg, repo_url: repo})
                });
                const data = await res.json();
                if(data.status === 'success' && data.job_id) {
                    _currentExtJobId = data.job_id;
                    document.getElementById('ext-repo-url').value = '';

                    // Show progress container
                    const container = document.getElementById('ext-progress-container');
                    container.style.display = 'block';
                    document.getElementById('ext-progress-bar').style.width = '0%';
                    document.getElementById('ext-progress-text').innerText = 'Starting clone...';
                    document.getElementById('ext-log-output').innerText = '';

                    // Start polling
                    _extPollInterval = setInterval(() => pollExtensionProgress(_currentExtJobId), 1000);
                } else {
                    alert(data.message || 'Failed to start clone');
                    cloneBtn.disabled = false;
                    cloneBtn.innerText = 'Clone Repo';
                }
            } catch(e) {
                alert('Error installing extension');
                cloneBtn.disabled = false;
                cloneBtn.innerText = 'Clone Repo';
            }
        }

        async function pollExtensionProgress(jobId) {
            try {
                const res = await fetch(`/api/extensions/status?job_id=${jobId}`);
                const data = await res.json();

                document.getElementById('ext-progress-text').innerText = data.progress_text || 'Working...';
                document.getElementById('ext-progress-bar').style.width = (data.percent || 0) + '%';

                if(data.log_lines && data.log_lines.length > 0) {
                    const logEl = document.getElementById('ext-log-output');
                    logEl.innerText = data.log_lines.join('\n');
                    logEl.scrollTop = logEl.scrollHeight;
                }

                if(data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
                    clearInterval(_extPollInterval);
                    _extPollInterval = null;

                    const cloneBtn = document.getElementById('ext-clone-btn');
                    cloneBtn.disabled = false;
                    cloneBtn.innerText = 'Clone Repo';

                    if(data.status === 'completed') {
                        document.getElementById('ext-progress-text').innerText = '✅ Clone completed!';
                        document.getElementById('ext-progress-bar').style.width = '100%';
                        setTimeout(() => {
                            document.getElementById('ext-progress-container').style.display = 'none';
                            openExtensions(currentExtPkg, document.getElementById('ext-pkg-name').innerText);
                        }, 2000);
                    } else if(data.status === 'cancelled') {
                        document.getElementById('ext-progress-text').innerText = '❌ Cancelled';
                        setTimeout(() => {
                            document.getElementById('ext-progress-container').style.display = 'none';
                        }, 2000);
                    } else {
                        document.getElementById('ext-progress-text').innerText = '❌ ' + (data.progress_text || 'Clone failed');
                        document.getElementById('ext-progress-bar').style.width = '0%';
                    }
                }
            } catch(e) {
                console.error('Failed to poll extension progress:', e);
            }
        }

        async function cancelExtensionClone() {
            if(!_currentExtJobId) return;
            try {
                await fetch('/api/extensions/cancel', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({job_id: _currentExtJobId})
                });
            } catch(e) { console.error('Cancel failed:', e); }
        }

        async function removeExtension(pkgId, extName) {
            if(!confirm(`Remove ${extName}?`)) return;
            try {
                const res = await fetch('/api/extensions/remove', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({package_id: pkgId, ext_name: extName})
                });
                if((await res.json()).status === 'success') {
                    openExtensions(pkgId, document.getElementById('ext-pkg-name').innerText);
                }
            } catch(e) { alert("Error removing extension"); }
        }

        // ── SSE Consumer: Install Progress ──────────────────────────
        window._onSSEInstallProgress = function(data) {
            // data is the full install_jobs.json content keyed by appId
            if (!data || typeof data !== 'object') return;
            for (const [appId, job] of Object.entries(data)) {
                const phaseEl = document.getElementById(`install-phase-${appId}`);
                const pctEl = document.getElementById(`install-pct-${appId}`);
                const barEl = document.getElementById(`install-bar-${appId}`);
                const logEl = document.getElementById(`install-log-${appId}`);
                const btn = document.getElementById(`install-btn-${appId}`);
                const progressEl = document.getElementById(`install-progress-${appId}`);

                // Make progress section visible if it exists
                if (progressEl) progressEl.style.display = 'block';

                if (phaseEl) phaseEl.innerText = job.phase || 'Working...';
                if (pctEl) pctEl.innerText = `${job.percent || 0}%`;
                if (barEl) barEl.style.width = `${job.percent || 0}%`;
                if (logEl && job.log?.length) {
                    logEl.innerText = job.log.join('\n');
                    logEl.scrollTop = logEl.scrollHeight;
                }

                if (job.status === 'completed') {
                    if (barEl) barEl.style.background = 'linear-gradient(90deg, #10b981, #22c55e)';
                    if (phaseEl) { phaseEl.innerText = 'Installation Complete'; phaseEl.style.color = '#4ade80'; }
                    if (btn) { btn.innerText = 'Installed'; btn.style.background = 'var(--surface)'; btn.style.color = 'var(--text-muted)'; }
                    // Clean up any active polling interval for this app
                    if (_installPollIntervals[appId]) { clearInterval(_installPollIntervals[appId]); delete _installPollIntervals[appId]; }
                    setTimeout(() => { loadRecipes(); loadPackages(); }, 2000);
                } else if (job.status === 'failed') {
                    if (barEl) barEl.style.background = '#ef4444';
                    if (phaseEl) { phaseEl.innerText = 'Installation Failed'; phaseEl.style.color = '#ef4444'; }
                    if (btn) { btn.innerText = 'Retry Install'; btn.disabled = false; btn.style.background = '#ef4444'; }
                    if (_installPollIntervals[appId]) { clearInterval(_installPollIntervals[appId]); delete _installPollIntervals[appId]; }
                }

                // Also update repair status if visible on package card
                const statusEl = document.getElementById(`pkg-status-${appId}`);
                if (statusEl && statusEl.style.display === 'block') {
                    const pct = job.percent || 0;
                    const phase = job.phase || 'Working...';
                    if (job.status === 'completed') {
                        statusEl.innerHTML = '✅ Repair complete!';
                        setTimeout(loadPackages, 2000);
                    } else if (job.status === 'failed') {
                        statusEl.innerHTML = '❌ Repair failed: ' + (job.phase || 'Unknown error');
                    } else {
                        statusEl.innerHTML = `<span class="progress-pulsing" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#f59e0b; margin-right:6px;"></span>${phase} (${pct}%)`;
                    }
                }
            }
        };

