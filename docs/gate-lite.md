# Gate-Lite Setup

Human gate for Phase 1 → Phase 2 transition. No frontend, no Marvis UI.
Two layers: **GitHub branch protection** + **OpenRouter spend cap**.

---

## 1. GitHub Branch Protection

Go to repo → Settings → Rules → Rulesets → New branch ruleset:

| Setting | Value |
|---------|-------|
| Ruleset name | `main-protection` |
| Enforcement status | Active |
| Target branches | `refs/heads/main` |
| Require a pull request before merging | ✅ On |
| Required approvals | **1** |
| Dismiss stale reviews | ✅ On |
| Require status checks to pass | ✅ On |
| Status checks | `trial` (from ci.yml) |
| Block force pushes | ✅ On |

---

## 2. OpenRouter Sub-Key

1. Go to [openrouter.ai/keys](https://openrouter.ai/keys)
2. Create a new key: name it `dreamer-agent-sandbox-p1`
3. Set **Credit Limit**: `$5.00` (hard cap for Phase 1 safety)
4. Store as GitHub secret: Settings → Secrets and variables → Actions → New repository secret

| Secret name | Value |
|-------------|-------|
| `OPENROUTER_API_KEY` | (paste the sub-key) |

---

## 3. Usage in Codex CLI

When Phase 1 → `#1 Real Codex CLI`, reference the secret:

```python
api_key = os.environ["OPENROUTER_API_KEY"]
```

---

## Exit Criteria

- [ ] CI passes on every push to `feature/*`
- [ ] PR to `main` requires 1 reviewer approval + CI green
- [ ] OpenRouter sub-key active with ≤ $5 spend
- [ ] Zero manual code edits needed to pass the gate
