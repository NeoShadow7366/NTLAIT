# ADR-004: Test Infrastructure Hardening

**Title:** Preventing Hanging Tests in Subprocess-Heavy Monolith
**Status:** Approved
**Date:** 2026-03-28

## Context
The QA Guardian automated test suite experienced a critical 22+ minute deadlock. Root cause analysis identified multiple flaws in the test infrastructure:
1. `ThreadingHTTPServer` uses `daemon_threads = False` by default, meaning any stuck HTTP request prevents the test process from exiting.
2. `urllib.request.urlopen()` calls lacked explicit timeout constraints, causing the test runner to hang indefinitely if the server deadlocked.
3. Thread `join()` and `while` loop operations lacked timeout bounds.
4. End-to-End or API tests could spawn real or mocked Python subprocesses in `server.py` that outlived the test suite, causing zombie processes.

Because this project strictly adheres to a zero-dependency, anti-gravity model, we cannot rely on tools like `pytest-timeout` to forcefully kill hanging tests. We must build resilience into our standard library usage.

## Decision
We will enforce rigid bounds and explicit teardown across the test suite using only the Python standard library:
1. **Daemonized Request Handlers:** The `IsolatedServerThread` must explicitly set `self.server.daemon_threads = True`.
2. **Explicit Network Timeouts:** All `urllib.request.urlopen()` calls within `.tests/` must provide a strict `timeout` parameter (e.g., 5.0 seconds).
3. **Bounded Synchronization:** Thread synchronizations (`.join()`, `.wait()`) must define a maximum wait time to prevent infinite stalls.
4. **Mandatory Subprocess Registry Cleanup:** `conftest.py` and `test_base.py` teardown blocks must actively sweep the `server.running_processes` registry and execute `.terminate()` on any lingering subprocesses.

## Rationale
Relying on implicit timeouts and non-daemonized threads introduces high fragility when testing complex infrastructure like a local HTTP server that manages subprocesses. Enforcing explicit timeouts guarantees that tests fail fast, preserving developer momentum. Daemonizing the server threads guarantees the Python process shuts down when the main PyTest thread concludes.

## Consequences
- **Positive:** Eliminates infinite deadlocks during automated testing. Test failures will raise `TimeoutError` or `socket.timeout`, providing immediate feedback. Leaves no zombie `Popen` tasks behind on system.
- **Negative:** Minor boilerplate increase in test API requests (enforcing the timeout argument).
- **Coupling Note:** Directly iterating `server.running_processes` in teardown tightly couples the test suite to `server.py`'s internal state mechanism, but this is an acceptable and pragmatic compromise for a monolithic zero-dependency architecture.
