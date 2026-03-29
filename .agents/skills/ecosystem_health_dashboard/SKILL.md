---
name: Ecosystem Health Dashboard
description: Provides a consolidated, read-only overview of the health and status of the entire guardian ecosystem and the monolith's infrastructure by aggregating read-only reports from existing guardians.
---

# 🛡️ Ecosystem Health Dashboard (Guardian Dashboard)

## Purpose
Provides a single, convenient command that gives a consolidated overview of the health and status of the entire guardian ecosystem and the monolith's infrastructure. It aggregates information from the existing guardians without duplicating their individual responsibilities, serving as a clean, convenient "at-a-glance" view.

## Core Responsibilities
- **Summary Generation**: Produce a quick, read-only summary incorporating data from all other guardians:
  - **Runtime Health Doctor**: Zombie processes, junctions, SQLite state, manifest integrity.
  - **Architecture Guardian**: High-level findings, zero-dependency compliance, major coupling risks.
  - **QA Guardian**: Recent automated test suite status, last run results, pending escalations.
  - **API Contract Librarian**: Last sync timestamp, open warnings, drift alerts.
- **Alert Triage**: Present findings in a clear, color-coded/emoji-based format (🟢 Green, 🟡 Yellow, 🔴 Red).
- **Action Items**: Highlight and prioritize any action items that require immediate human attention.
- **Conciseness**: Keep the report easily readable and actionable, ideally fitting within one screen.

## Integration & Triggers

### Triggers
- **Manual Trigger**: Invoked by the user via the slash command `/health_dashboard` or by asking "Show me the guardian dashboard".
- **Optional Automatic Trigger**: Can be run silently on server startup or after major phase changes (e.g., following the `/New_Phase_Start_With_Model_Router` workflow) to provide immediate context.

### Integration with Other Guardians
- Internally calls the other guardians (Runtime Health Doctor, Architecture Guardian, QA Guardian, API Contract Librarian) in strictly **read-only/summary mode** to gather fresh assessment data.

## Output Format
Always present the output in simple, clean Markdown. Ensure it includes:

1. **Summary Header**: An overall verdict of system health (e.g., "🟢 System Nominal", "🟡 Caution Advised", "🔴 Action Required").
2. **Guardian Status Sections**: Brief, bulleted points for each guardian with emoji indicators.
   - 🟢 **Green**: Healthy, no issues.
   - 🟡 **Yellow**: Warnings, minor drift, non-critical issues.
   - 🔴 **Red**: Critical failures, zombie processes, broken junctions, test failures.
3. **Prioritized Action Items**: A focused list of steps the user needs to take to restore complete health.
4. **Timestamp**: Include the current local date and time ("Last Updated").

## Tools & Permissions
- **Strictly Read-Only**: This skill has NO authority to modify code, install dependencies, or alter user data.
- **Invocation Rights**: Has permission to invoke other guardians' check abilities to gather necessary data for the summary.
- **No Mutation**: Must adhere flawlessly to the project's zero-dependency principles without executing write operations (except for optional, lightweight local logging if absolutely required for its own execution state).
