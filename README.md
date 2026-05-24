# prj-ai-ctx-git

An experiment in parallel AI conversations backed by plain markdown and Git.

The core idea is simple:

- keep each conversation or research thread as a branch under `contexts/branches/`
- externalize compact state into editable `context.md` files
- append raw-ish conversation turns to `history.jsonl`
- generate conceptual merge views under `contexts/views/`
- use Git as the history, diff, and rollback layer

OpenCode is the preferred agent host for research because it is terminal-first,
scriptable, supports custom agents, and can expose web search/fetch without
bringing in a full messaging gateway. OpenClaw and agent skills are useful
references, not runtime dependencies.

## Quick Start

```bash
python3 tools/ctxgit/ctxgit.py init
python3 tools/ctxgit/ctxgit.py branch AItrust --title "AI trust"
python3 tools/ctxgit/ctxgit.py branch AIdiscipline --title "AI discipline"
python3 tools/ctxgit/ctxgit.py append AItrust --role user "What makes an AI trustworthy?"
python3 tools/ctxgit/ctxgit.py merge-view AItrust AIdiscipline --name trust-discipline
```

## Research

OpenCode-backed agentic research:

```bash
python3 tools/ctxgit/ctxgit.py research AItrust \
  "current research on AI trust calibration" \
  --provider opencode
```

Direct Brave LLM Context retrieval:

```bash
export BRAVE_API_KEY=...
python3 tools/ctxgit/ctxgit.py research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

The project-level OpenCode research agent lives at
`.opencode/agents/research.md`.
