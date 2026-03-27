# QA Guardian Rules

> **The primary goal of the QA Guardian is to maintain high-quality backend API tests and pure Python static DOM tests while strictly adhering to the Generative AI Manager's zero-dependency deploy philosophy.**

## 1. Zero External Production Dependencies
Any new test functionality must be built using Python standard libraries (e.g. `unittest`, `urllib`, `html.parser`, `sqlite3`). `pytest` is permitted ONLY as a local runner via `requirements-qa.txt`. Under no circumstances should `requests` or Node.js/NPM frameworks be added to the production runtime.

## 2. Safe Database Integration Testing
- NEVER perform automated tests on the live `metadata.sqlite`.
- Tests must dynamically override `server.db_path` or instantiate DB connections pointing to isolated `tempfile.TemporaryDirectory` files.
- Ensure all tests complete and properly release SQLite locks during tear down.

## 3. Ephemeral Server Ports
Always bind test `ThreadingHTTPServer` instances to `localhost:0`. The OS will automatically assign an unused ephemeral port, preventing port collisions with `8000` or `8188` which might be actively used by the user's Generative AI manager.

## 4. Flakiness Protection
- Do not assert on exact output logs, as Threading outputs are asynchronous.
- A test is considered "flaky" if it fails 1 out of 5 runs. If discovered, you must rewrite the test rather than muting it.
- `index.html` UI smoke tests should test for fundamental containers (`view-explorer`, `view-vault`, `view-inference`) and API JSON payloads instead of highly sensitive style attributes.
