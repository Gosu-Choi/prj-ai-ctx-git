# ctxgit

`ctxgit` is a small transparent context layer for parallel AI conversations.
It keeps conversation branches, notes, research, and conceptual merge views as
plain files under `contexts/` so Git can manage the history.

It is intentionally separate from chat-agent session internals. OpenCode can be
used as a research backend through `opencode run --agent research`, while the
conversation state remains markdown and JSONL.

## Quick Start

```bash
python3 tools/ctxgit/ctxgit.py init
python3 tools/ctxgit/ctxgit.py branch AItrust --title "AI trust"
python3 tools/ctxgit/ctxgit.py branch AIdiscipline --title "AI discipline"
python3 tools/ctxgit/ctxgit.py append AItrust --role user "What makes an AI trustworthy?"
python3 tools/ctxgit/ctxgit.py append AIdiscipline --role user "How should I discipline AI usage?"
python3 tools/ctxgit/ctxgit.py merge-view AItrust AIdiscipline --name trust-discipline
```

## Research

Use OpenCode as the default research backend:

```bash
python3 tools/ctxgit/ctxgit.py research AItrust \
  "current research on AI trust calibration" \
  --provider opencode
```

Or call Brave LLM Context directly:

```bash
export BRAVE_API_KEY=...
python3 tools/ctxgit/ctxgit.py research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

Both modes write markdown notes to
`contexts/branches/<branch>/research/`.

## Git Snapshots

```bash
python3 tools/ctxgit/ctxgit.py snapshot -m "ctxgit: update AI trust contexts"
```
