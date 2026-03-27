---
description: "Executes the static validation of the index.html monolithic structure via Python."
---

# Frontend Smoke Test

This workflow evaluates the `static/index.html` structure ensuring all critical identifiers, navigation objects, and data-binds act normally.

// turbo-all
1. Navigate to the project root directory.
2. Run only the specific frontend test file using Python.
```powershell
python -m unittest .tests/test_frontend_smoke.py
```
3. Report the result of the suite. Do not modify JS or HTML unless a critical typo caused the build to fail.
