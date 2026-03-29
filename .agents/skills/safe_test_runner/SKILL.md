---
name: Safe Test Runner
description: Executes the QA Guardian test suite within a secure OS-level timeout envelope to prevent orphaned pipelines and infinite deadlocks.
---

# 🛡️ Safe Test Runner

## Purpose
Provide a single, resilient command to execute the QA Guardian test suite with built-in OS-level timeout protection. This ensures that even if a test suite permanently deadlocks (e.g., hanging server socket, orphaned Popen), the pipeline will automatically sever the execution, freeing up system resources and preventing infinite hangs.

## Core Responsibilities
- **Timeout Execution**: Run `python -m pytest .tests/` wrapped inside a PowerShell job with a strict 60-second timeout.
- **Auto-Termination**: Automatically terminate and kill the job sequence if it exceeds the designated timeout limit.
- **Result Triaging**: Parse the terminal output and gracefully expose the final condition (Passed / Failed / Timed Out).
- **Dashboard Logging**: Pass the execution state directly into the `/health_dashboard` report cycle.

## Integration & Triggers
- **Manual Trigger**: `/run_safe_tests` or "Run tests safely".
- **QA Guardian Hook**: Acts alongside the QA Guardian Agent as its shielded execution chamber.
- **Automatic Health Check**: Immediately triggers the Ecosystem Health Dashboard (`/health_dashboard`) upon completion to log updated status.

## Output Format
Always present a concise Markdown summary displaying:
1. **Execution Verdict**: 🟢 Passed / 🔴 Failed / 🔴 Timed Out
2. **Metrics Summary**: Number of tests passed/failed/skipped.
3. **Timeout Warning**: Prominent `> [!CRITICAL]` alert if the 60-second threshold triggered a force-kill.
4. **Health Link**: Immediate rendering of `/health_dashboard`.

## Tools & Permissions
- Allowed to execute the protected PowerShell pipeline constraint:
  `Start-Job -ScriptBlock { python -m pytest .tests/ -v -s --lf } | Wait-Job -Timeout 60 | Receive-Job`
- Read-only access to `.tests/` directory and `metadata.sqlite` file.
- **NO DIRECT CODE CHANGES**: This agent is strictly an execution wrapper; test mutations must be handled by the QA Guardian or Architecture Guardian.
