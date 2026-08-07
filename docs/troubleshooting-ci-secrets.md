# CI Secrets Troubleshooting

## Symptom

CI passes green, `trial_run.py` reports 6/6, but OpenRouter shows $0 usage and runtime is abnormally fast (~0.3s). The LLM is never called — stubs are used instead.

## Root Causes (in order of likelihood)

### 1. Secret name contains hyphens

GitHub Secrets names only allow `[a-z][A-Z][0-9]_`. Hyphens (`-`) are **not allowed**.

```yaml
# Wrong — GitHub silently rejects or ignores
OPENROUTER_API_KEY: ${{ secrets.hermes-phase2-trial }}

# Correct
OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

### 2. Secret value copied from OpenRouter UI is masked

OpenRouter only shows the full key **at creation time**. The key list displays `sk-or-v1-4fe...cb6` — clicking "Copy" may copy the masked string or nothing.

**Fix**: Copy the full key from your local `.env` file instead.

### 3. Secret exists in Environment but not Repository

Workflow YAML must declare `environment:` to access environment-level secrets.

```yaml
# If OPENROUTER_API_KEY is under "Production" environment secrets:
jobs:
  trial:
    runs-on: ubuntu-latest
    environment: Production  # ← Required
```

**Fix**: Move the secret from Environment secrets to **Repository secrets**, or add `environment:` to the job.

### 4. Secret was never created

The workflow runs (GitHub doesn't fail on missing secrets) but the env var is empty. Go to:
```
Settings → Secrets and variables → Actions → Repository secrets
```
Create or update `OPENROUTER_API_KEY` with the value from `.env`.

## Debug Recipe

Add a temporary step before `Run trial`:

```yaml
- name: Debug - check key presence
  run: |
    if [ -n "$OPENROUTER_API_KEY" ]; then
      echo "OPENROUTER_API_KEY is SET (length: ${#OPENROUTER_API_KEY})"
      echo "First 8 chars: ${OPENROUTER_API_KEY:0:8}"
    else
      echo "OPENROUTER_API_KEY is EMPTY"
    fi
  env:
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

Expected output when correct:
```
OPENROUTER_API_KEY is SET (length: 73)
First 8 chars: sk-or-v1
```

Remove this step after resolution.

## Resolution History

| Date | Attempt | Symptom | Root Cause | Fix |
|------|---------|---------|------------|-----|
| 2026-07-26 | 1 | EMPTY | Secret name `hermes-phase2-trial` invalid (hyphens) | Renamed to `OPENROUTER_API_KEY` |
| 2026-07-26 | 2 | EMPTY | Copied masked key from OpenRouter UI | Copied full key from `.env` |
| 2026-07-26 | 3 | EMPTY | Secret was never actually created in Repository | Created `OPENROUTER_API_KEY` with `.env` value |
| 2026-07-28 | 4 | $0.003 ✓ | — | — |
