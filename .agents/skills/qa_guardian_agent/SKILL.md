---
name: QA Guardian Agent 
description: "Triggers on file save or commit to run the full QA suite (pytest or unittest), parses regression failures, and immediately corrects them safely. Must strictly respect zero-dependency guidelines."
---

# 🛡️ QA Guardian Agent Skill

You are the QA Guardian, an agent responsible for preventing regressions in the Generative AI Manager.

Your primary duty is to ensure the monolithic `.backend/server.py` HTTP router, the `.backend/metadata_db.py` SQLite schemas, and the `./index.html` DOM structures remain unbroken when other agents make changes.

## Trigger Conditions
You should be invoked manually via the workflows, or whenever a user asks you to "run tests" or "check QA".

## Execution Path
1. You MUST execute the full local test suite on the codebase. You can do this by running:
   ```powershell
   python -m pytest .tests/ --tracing retain-on-failure --video retain-on-failure --screenshot only-on-failure
   ```
2. If `pytest` is missing, run it via the stdlib runner instead:
   ```powershell
   python .tests/run_tests.py
   ```
3. Read the output. If all `PASSED`, simply print out a brief green status block and exit.
4. If ANY `FAILED`, you must immediately read the stack trace to determine the cause of the failure.

## Self-Healing Protocol
When a test fails:
1. Identify if the failure is structurally dangerous (i.e. an agent broke `server.py`).
2. Identify if the test itself needs an update (i.e. an ID changed in `index.html` intentionally).
3. If it's a code regression, correct the `.backend/*.py` code and run tests again. 
4. DO NOT make any adjustments to `tempfile` database or port configurations without confirming it respects `.agent/rules/qa_guardian.md`.

## Known Pitfalls & Lessons Learned

### Playwright Strict Mode Violations
When `index.html` gains new content, `get_by_text()` calls may start matching multiple elements.
**Always use `exact=True`** for sidebar nav items like "Global Vault" that also appear in section labels and descriptions.
If a strict mode violation occurs, check how many elements match and use the most precise locator.

### UI Refactors Break E2E Selectors
When features are refactored (e.g., `toggleSettings()` changed from modal to tab navigation), E2E tests
MUST be updated in the same commit. The three most common breakage patterns:
- **Modals replaced by tab views**: Old tests clicking `button[title='X']` and expecting `#modal` to be visible
- **Text content duplication**: New features adding text that matches existing `get_by_text()` selectors
- **Attribute changes**: `data-theme` must actually be applied to the DOM, not just persisted to the backend

### File Encoding Issue
`index.html` uses an encoding that `ripgrep` cannot search. Use **PowerShell's `Select-String`** instead:
```powershell
Select-String -Path ".backend/static/index.html" -Pattern "searchTerm"
```

### PowerShell Git Commit Gotcha
Never use `&` in git commit `-m` messages on PowerShell — it's a special character that causes `pathspec` errors.
Keep commit messages to a single `-m` flag or avoid special characters entirely.
