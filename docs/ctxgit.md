---
summary: "Transparent git/markdown context branching for parallel AI conversations"
title: "ctxgit"
---

# ctxgit

`ctxgit` adds a visible context layer for parallel AI conversations. It does
not depend on opaque chat/session internals.

The model is:

- Branches are directories under `contexts/branches/<id>/`.
- Conversation history is append-only `history.jsonl`.
- Compressed human-editable state lives in `context.md`.
- Research outputs become markdown notes under `research/`.
- Conceptual merges are generated files under `contexts/views/`.
- Git records every change.

OpenCode is the preferred research runtime. `ctxgit research --provider
opencode` shells out to `opencode run --agent research`, so the agentic research
surface stays explicit and scriptable. Brave LLM Context is available as a
direct retrieval backend when deterministic source capture matters more than
agentic synthesis.

```bash
python3 tools/ctxgit/ctxgit.py init
python3 tools/ctxgit/ctxgit.py branch AItrust --title "AI trust"
python3 tools/ctxgit/ctxgit.py branch AIdiscipline --title "AI discipline"
python3 tools/ctxgit/ctxgit.py merge-view AItrust AIdiscipline --name trust-discipline
python3 tools/ctxgit/ctxgit.py research AItrust "AI trust calibration" --provider opencode
```
