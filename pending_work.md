# Generative AI Manager — Pending Work & Future Roadmap
> Last updated: 2026-03-28 (after Sprint 9 completion)

## Status: All 9 Sprints Complete ✅

The core development cycle (Sprints 1–9) is finished. Sprint 9 added Inference Studio power-ups and Dashboard intelligence. Below are areas for future enhancement, polish, and hardening.

---

## 🔴 High Priority — Pre-Release Polish

### E2E Test Suite Stabilization ✅ (Fixed 2026-03-27)
- ~~Playwright E2E tests were scaffolded in Sprint 4 but have had intermittent flakiness~~
- ~~Strict mode selector violations need resolution~~
- Three failures fixed: `exact=True` for Global Vault click, Settings tab navigation instead of defunct modal, theme DOM application
- Video forensic tracing was added but needs validation on CI
- **Remaining:** Monitor CI runs to confirm green across all 6 matrix jobs (3 OS × 2 Python versions)

### Cross-Platform Verification
- All code uses `os.name` / `platform.system()` branching but has only been tested on Windows
- macOS (Intel + Apple Silicon) and Linux (x86_64 + arm64) need verification
- Portable Python (`python-build-standalone`) binaries need platform-specific testing
- **Action:** Boot the manager on macOS/Linux and verify symlink, process management, and venv creation

### Performance Audit ✅ (Sprint 9)
- ~~`handle_server_status()` now walks `Global_Vault/` on every call for vault size~~ — Fixed with 60-second TTL cache
- Dashboard polling is 3 seconds; consider reducing for non-dashboard tabs

---

## 🟡 Medium Priority — Feature Enhancement

### Vault Import from Backup ✅ (Sprint 9)
- ~~Export works (Sprint 8) but there's no corresponding **import** endpoint~~ — Done
- ~~Need `POST /api/vault/import` that reads a `vault_manifest.json` and restores metadata~~ — Done
- Optional: re-download missing files from CivitAI using stored model IDs

### Command Palette Expansion (Complete ✅ Sprint 10)
- ~~Current: 12 commands (navigation + vault actions)~~ — Expanded to 16
- ~~Add: model search command (type model name → jump to vault card)~~ — Done
- ~~Add: recent generations quick-access~~ — Done
- ~~Add: theme toggle command~~ — Done

### Dashboard Enhancements (Complete ✅ Sprint 10)
- ~~Add a "Recent Activity" feed (last 5 generations, last 5 downloads)~~ — Done
- ~~Add vault category distribution chart (pie/donut chart via SVG)~~ — Done
- ~~Add disk space warning when vault exceeds configurable threshold~~ — Done

### Inference Studio Upgrades (Complete ✅ Sprint 10)
- ~~Batch generation (queue multiple prompts)~~ — Done
- Image-to-image mode (denoising_strength parameter) — Already supported via drag-drop
- ~~Prompt token counter~~ — Done
- ~~A/B comparison view (side-by-side generation results)~~ — Done

### Gallery Improvements (Complete ✅ Sprint 10)
- ~~Rating system with star display in grid cards~~ — Done
- ~~Tag filtering in gallery view~~ — Done
- Export gallery as PDF/HTML report — Deferred to future polish phase

---

## 🟢 Low Priority — Nice-to-Have

### Theming System (Partially Complete ✅)
- Settings theme dropdown now applies `data-theme` attribute to `<body>` on save and load
- Dark, Light, and Glass themes have CSS variable definitions
- **Remaining:** Add accent color customization

### Notifications
- Web Push notifications for completed downloads/generations
- Desktop notification API integration

### Multi-Language Support (i18n)
- Framework was scaffolded in Sprint 4 but no translations were added
- Need translation JSON files for at least: English, Japanese, Chinese, Spanish

### Documentation
- User-facing README with screenshots and setup guide
- API documentation (OpenAPI/Swagger spec generation)
- Video walkthrough / tutorial

---

## 📊 Current Codebase Metrics

| File | Lines | Purpose |
|------|-------|---------|
| `index.html` | ~4,800 | Monolithic frontend (9 tabs, 15+ modals, donut chart, batch queue) |
| `server.py` | ~1,700 | HTTP server + 44 API endpoints |
| `metadata_db.py` | ~485 | SQLite ORM layer |
| `installer_engine.py` | ~290 | App installer + extension clone tracker |
| `vault_crawler.py` | ~200 | Background file indexer |
| `civitai_client.py` | ~150 | CivitAI API scraper |
| `download_engine.py` | ~120 | Chunked file downloader |
| `test_sprint9.py` | ~285 | Latest unit tests (31 tests) |
| **Total backend** | **~3,800** | Python |
| **Total frontend** | **~4,800** | HTML/CSS/JS |

## Test Coverage

| Sprint | Tests Added | Cumulative |
|--------|-------------|------------|
| 7 | 20 (prompts, bulk ops) | 20 |
| 8 | 24 (clone tracker, export, dashboard, HTML) | 44 |
| E2E fix | 5 existing tests stabilized | 49 |
| 9 | 31 (vault import, activity, distribution, batch, tokens, HTML) | 80 |
| **10** | **18 (gallery tags, ratings, disk warning, ab comparison, routing)** | **98 total (85 unit + 13 E2E/components, all passing)** |
