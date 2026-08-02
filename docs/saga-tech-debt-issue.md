# Saga Compensation & Parallel Failure Recovery — Tech Debt

## Summary

The Hermes Scheduler currently executes parallel agent groups (PG) optimistically. If one agent in a parallel group fails while others succeed, the system has **no Saga compensation mechanism** — it cannot automatically roll back the successful agents' side effects, leaving the system in a partial state.

## Background

In Phase 1 MVP, this is acceptable because:
- Sandbox isolation limits side effects to sandbox directories
- Merge Arbiter catches incompatibilities between parallel outputs

However, when Phase 2 expands to:
- 9-agent matrices with shared resource locks
- Database writes by individual agents
- Real file system side effects outside sandboxes

...a single parallel failure will cause state corruption.

## Required Implementation

### 1. Saga Log (shared state)
- Persist a list of completed agent steps with their `task_id`, `resource_locks`, and `compensate_fn`
- Each agent registers its compensating action immediately after a successful step

### 2. Compensate Action per Agent
- BackendAgent: delete created files, release DB rows
- DatabaseAgent: DROP TABLE / DELETE rows within transaction boundary
- Future agents: implement `compensate()` method on Agent base class

### 3. Coordinator Logic
```python
if any task in PG failed:
    for task in PG that succeeded:
        execute task.compensate()
        release task.locks
    mark PG as ABORTED
    skip downstream PGs that depend on this PG
```

### 4. Merge Arbiter — should it participate?
- Question: if a PG fails, should the Merge Arbiter still run for the surviving outputs?
- Answer: No. If PG failed, all its outputs are discarded. Arbiter only runs when all PG tasks succeed.

## Estimated Effort

| Item | Hours | Notes |
|------|-------|-------|
| Saga log data structure | 2 | Shared state with atomic write |
| Agent base class `compensate()` | 1 | Interface only |
| Agent-specific compensation | 3 | 1h per existing agent |
| Coordinator error handler | 3 | Integration with HermesScheduler |
| Trial scenario (parallel failure) | 2 | Purposefully trigger failure |
| Testing | 2 | Unit + integration |

**Total: ~13 hours** (1.5-2 days)

## Related
- Blocks: #5 (9-agent matrix expansion)
- PR: Phase 2 proposal
- Doc: `docs/troubleshooting-ci-secrets.md`

## Labels
`tech-debt` `phase-3` `blocking-#5`
