# 🛡️ Anti-Gravity Guardian Workflow Execution (Sequence)

This sequence diagram details the real-time interaction between the guardians when a user introduces a code change. It highlights the primary "Happy Path" along with conditional escalations.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor U as User / Developer
    participant AG as Architecture Guardian
    participant API as API Contract Librarian
    participant QA as QA Guardian + Safe Test Runner
    participant RHD as Runtime Health Doctor
    participant EHD as Ecosystem Health Dashboard

    U->>AG: File Save / Commit (Initiate Change)
    activate AG
    
    %% Phase 1: Architecture & API Boundaries
    Note over AG,API: 1. Design & Boundary Validation
    AG->>API: Request boundary & payload validation
    activate API
    
    alt Payload Drift Detected
        API-->>AG: Error: JSON Mismatch Detected
        AG-->>U: ⛔ BLOCK: API Contract Violation
    else Contracts Valid
        API-->>AG: OK: Boundaries Maintained
    end
    deactivate API

    AG->>AG: Analyze structural impact & zero-dependency rule
    
    alt Architectural Violation
        AG-->>U: ⛔ BLOCK: Structural/Dependency Hazard
    else Architecture Clean
        AG->>QA: Approve & Trigger Test Lifecycle
    end
    deactivate AG

    %% Phase 2: Testing & Timeout Protection
    activate QA
    Note over QA: 2. Execution & Timeout Protection
    QA->>QA: Wrap tests in OS-level Timeout Envelope
    
    alt Cosmetic / Minor Fail
        QA->>QA: Apply Self-Healing (DOM/Locators)
        QA->>QA: Re-run updated tests
    else Timeout / Structural Deadlock
        QA-->>AG: ESCALATE: Deadlock/Structural Breakage
        activate AG
        AG-->>U: ⛔ BLOCK: Escalated Testing Failure
        deactivate AG
    else All Tests Pass
        QA->>RHD: Request Infrastructure Pre-flight Sweep
    end
    deactivate QA

    %% Phase 3: Runtime Sweeps
    activate RHD
    Note over RHD: 3. Pre-Flight Infrastructure Sweeps
    RHD->>RHD: Scan for DB Locks / Zombie ComfyUI Processes
    
    alt Infra Defect Found
        RHD-->>U: ⛔ BLOCK: Infrastructure Broken (e.g., Zombie Engine)
    else Health OK
        RHD-->>U: ✅ DEPLOYMENT SUCCESS (Ready)
    end
    
    %% Phase 4: Observability
    RHD->>EHD: Push Final Telemetry & Telemetry Logs
    deactivate RHD
    
    Note over U,EHD: 4. Ecosystem Observability
    activate EHD
    U->>EHD: Invokes /health_dashboard
    EHD-->>U: Serves Consolidated System Overview
    deactivate EHD
```

## Flow Explanation

1. **Initiation & Validation**: 
   The sequence begins when the developer saves a file. The **Architecture Guardian** catches the event and immediately queries the **API Contract Librarian**. If the librarian detects any drift between the frontend components and backend routers, it throws a JSON Mismatch error, allowing the Architecture Guardian to block the commit. If approved, the Architecture Guardian runs its own internal checks for anti-gravity/zero-dependency violations.
   
2. **Safe Execution**: 
   Passing the structural checks, the baton is handed to the **QA Guardian**. This guardian immediately wraps its test executions within the **Safe Test Runner** timeout envelope. If the test fails on a purely cosmetic issue, it enters a self-healing inner loop. If it encounters a timeout or structural deadlock, it will *not* attempt to self-heal; instead, it escalates backward to the Architecture Guardian, dropping a block on the user.

3. **Runtime Sweep**: 
   Assuming a perfect test pass, the **Runtime Health Doctor** executes a live sweep of the OS infrastructure. It looks for silent killers like locked SQLite databases or orphaned `python-build-standalone` instances that tests wouldn't natively catch.

4. **Telemetry Sync**: 
   Upon completion (whether successful or blocked), the current infrastructure footprint logs are funneled into the **Ecosystem Health Dashboard**, which the User pulls on-demand with `/health_dashboard`.
