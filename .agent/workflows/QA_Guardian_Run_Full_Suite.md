---
description: "Executes the full automated regression testing suite for backend and frontend."
---

# Run Full Test Suite

This workflow executes every integrated automated unit, integration, and smoke test under the Generative AI Manager repository.

// turbo-all
1. Navigate to the project root directory.
2. Ensure you are using the correct OS environment python binary `python`.
3. Execute the standard `pytest` suite for the quickest log results.
```powershell
python -m pytest .tests/ --cov=.backend/ --cov-report=term-missing
```
4. If the `pytest` runner fails to be discovered, gracefully fallback to the built-in isolated runner:
```powershell
python .tests/run_tests.py
```
5. If the tests fail, automatically invoke the QA Guardian workflow logic to analyze traces and resolve failures.
