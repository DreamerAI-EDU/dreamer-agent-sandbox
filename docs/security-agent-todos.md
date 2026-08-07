# Phase 3 — Security Agent TODOs

## 🔧 Fix: retry count should only increment on actual LLM regeneration
- **Bug**: `SecurityGate.audit_artifacts()` calls `self.auditor.record_retry()` inside the audit loop,
  which means every `audit_artifacts()` call burns a retry — including fix_hint generation and re-checks.
- **Expected behavior**: `record_retry()` should only be called when the orchestrator *actually* sends
  the fix_hint to the LLM for code regeneration. Audit and hint generation are read-only and should
  not consume the retry budget.
- **Impact**: Currently trial_c_pipeline_integration() works around this by calling audit_artifacts()
  to simulate exhaustion, but in production this would exhaust retries on re-checks before the LLM
  ever gets a chance to fix the code.
- **Fix plan**:
  1. Remove `record_retry()` from `audit_artifacts()`
  2. Add explicit `commit_retry(task_id, finding)` method to `SecurityGate`
  3. Caller (orchestrator / trial) calls `commit_retry()` only after LLM regeneration is triggered
  4. Update trial_c_pipeline_integration() to use `commit_retry()` explicitly
- **Recorded**: 2026-08-02 —验收通过时发现
