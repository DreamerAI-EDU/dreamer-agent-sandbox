# Prompt overrides (P1)

Drop-in replacements for the DeepTutor engine's own prompt files, mounted
read-only over the image (see `deeptutor/docker-compose.yml`):

| override | engine path |
|---|---|
| `en/agentic_chat.yaml` | `/app/deeptutor/agents/chat/prompts/en/agentic_chat.yaml` |
| `zh/agentic_chat.yaml` | `/app/deeptutor/agents/chat/prompts/zh/agentic_chat.yaml` |
| `en/chat_agent.yaml`   | `/app/deeptutor/agents/chat/prompts/en/chat_agent.yaml` |
| `zh/chat_agent.yaml`   | `/app/deeptutor/agents/chat/prompts/zh/chat_agent.yaml` |

Provenance: base = engine image `hkuds/deeptutor:v1.5.8` prompt files, verbatim
except the identity lines. When the engine image is bumped, re-diff these
against the new image before rolling forward (a stale override silently wins).

Not covered here: `book` / `notebook` / `visualize` / `memory` stage prompts
still say "DeepTutor" internally — no student-facing self-identification, so
left untouched (backlog).
