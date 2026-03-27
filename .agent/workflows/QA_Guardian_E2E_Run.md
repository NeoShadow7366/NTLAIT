---
description: "Executes the interactive JavaScript WET tests via headless Chromium."
---

# QA Guardian - E2E WET Tests

This workflow uses Pytest + Playwright to spin up a headless Chromium instance, interactively simulating clicks, drag-and-drops, modal popups, and theme switches without exposing users to bloated node dependencies.

// turbo-all
1. Navigate to the project root directory.
2. Ensure you have the required dev-only QA dependencies installed:
```powershell
python -m pip install -r requirements-qa.txt
python -m playwright install chromium
```
3. Execute the dedicated E2E file passing the base_url automatically bound by our `conftest.py`:
```powershell
python -m pytest .tests/test_frontend_e2e.py -v
```
4. If failures occur, read the traceback to ensure UI selectors within `main.js` match the assertions tested in `test_frontend_e2e.py`.
