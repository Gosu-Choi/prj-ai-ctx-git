---
summary: "Transparent git/markdown context branching for parallel AI conversations"
title: "ctxgit"
---

# ctxgit

`ctxgit` adds a visible context layer for parallel AI conversations. It does
not depend on opaque chat/session internals. The command is global, but the
state is project-scoped: each project directory owns its own `.git`, `.ctxgit/`,
and `contexts/`.

The model is:

- Branches are directories under `contexts/branches/<id>/`.
- Guiding knowledge lives in `contexts/knowledge/*.md`, switched on per branch.
- Conversation history is append-only `history.jsonl`.
- Compressed human-editable state lives in report-form `context.md`.
- Research outputs become markdown reports under `research/`.
- Optional AI-generated per-turn markdown outputs live under `artifacts/`.
- Conceptual merges are generated as comparative reports under `contexts/views/`.
- Git records every change.

OpenCode is the preferred research runtime. `ctxgit research --provider
opencode` shells out to `opencode run --agent research`, so the agentic research
surface stays explicit and scriptable. Brave LLM Context is available as a
direct retrieval backend when deterministic source capture matters more than
agentic synthesis.

```bash
cd /path/to/your/project
ctxgit init
ctxgit branch AItrust --title "AI trust"
ctxgit branch AIdiscipline --title "AI discipline"
ctxgit merge-view AItrust AIdiscipline --name trust-discipline
ctxgit research AItrust "AI trust calibration" --provider opencode
```

`ctxgit init` creates the project-local ctxgit files and initializes Git if the
directory is not already a repository.

On Windows, install the command wrapper from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

Then open a new PowerShell window and use `ctxgit` normally.

## Chat Interface

`ctxgit serve` starts a local browser interface for reading and appending
branch conversations:

```bash
ctxgit serve --port 8765
```

The chat timeline is loaded from `history.jsonl`; appending from the browser
writes another JSONL record. Those files are normal Git-tracked files, so
status, diff, log, and snapshot all work on the conversation history.

The browser UI has a `Project` panel. `Open` switches to an existing ctxgit
project. `Init/Open` creates `.ctxgit/`, `contexts/`, and `.git` in the selected
directory if needed, then switches the UI to that project.

The primary chat provider is OpenAI Codex through the local `codex` CLI. This
uses the Codex OAuth login already stored on the machine:

```bash
codex login status
codex login --device-auth
ctxgit provider status
ctxgit chat AItrust "Continue this research branch."
```

A chat turn may create multiple markdown artifacts in
`contexts/branches/<branch>/artifacts/`; it is not forced to create an artifact
on every turn.

## Guiding Knowledge

`contexts/knowledge/*.md` holds project-wide knowledge documents. Each branch
chooses which of them apply through the topbar `Guiding` button, stored as
`guiding` in `branch.json`. Selected documents are injected verbatim into that
branch's chat, info-chat, and sequence-room prompts, so they are always in
effect rather than being files the model may or may not open.

Entries are added only on request: the `Knowledging` item in a chat message's
`...` menu opens a modal where you say what should be remembered, and the
configured LLM appends one distilled Markdown section to the chosen document.

## Report Shape

The markdown files are intentionally report-shaped so they can be reviewed,
diffed, cited, and updated over time:

- Executive Summary
- Research Question
- Scope or Method
- Key Findings
- Evidence Ledger
- Source Map
- Analysis
- Uncertainties or Open Questions
- Decisions And Assumptions
- Next Actions
- Change Log
