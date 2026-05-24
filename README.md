# prj-ai-ctx-git

An experiment in parallel AI conversations backed by plain markdown and Git.

The core idea is simple:

- use `ctxgit` as a global tool, but keep data inside each selected project
- initialize each project with its own `.git`, `.ctxgit/`, and `contexts/`
- keep each conversation or research thread as a branch under that project's `contexts/branches/`
- externalize compact state into editable report-form `context.md` files
- append raw-ish conversation turns to `history.jsonl`
- store optional AI-generated per-turn artifacts under `artifacts/`
- generate conceptual merge views under `contexts/views/`
- use Git as the history, diff, and rollback layer

OpenCode is the preferred agent host for research because it is terminal-first,
scriptable, supports custom agents, and can expose web search/fetch without
bringing in a full messaging gateway. OpenClaw and agent skills are useful
references, not runtime dependencies.

## Quick Start

This workspace installs a small wrapper at `bin/ctxgit`. On this machine it is
also linked from `/opt/homebrew/bin/ctxgit`, so the command can be used like
`git`:

```bash
cd /path/to/your/project
ctxgit init
ctxgit branch AItrust --title "AI trust"
ctxgit branch AIdiscipline --title "AI discipline"
ctxgit append AItrust --role user "What makes an AI trustworthy?"
ctxgit merge-view AItrust AIdiscipline --name trust-discipline
```

`ctxgit init` creates `.ctxgit/` and `contexts/`; it also runs `git init` when
the project is not already a Git repository. Use `ctxgit init --no-git` if you
only want the ctxgit files.

## Windows Install

Clone this tool repo, then run the installer from PowerShell:

```powershell
git clone <this-repo-url> prj-ai-ctx-git
cd prj-ai-ctx-git
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

Open a new PowerShell window and check:

```powershell
ctxgit --help
ctxgit provider status
```

The installer adds this repo's `bin\` folder to the user `PATH`. Windows uses
`bin\ctxgit.cmd`, which calls Python through `py -3` or `python`.

## Research

OpenCode-backed agentic research:

```bash
ctxgit research AItrust \
  "current research on AI trust calibration" \
  --provider opencode
```

Direct Brave LLM Context retrieval:

```bash
export BRAVE_API_KEY=...
ctxgit research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

The project-level OpenCode research agent lives at
`.opencode/agents/research.md`.

## Chat Interface

Run the local viewer:

```bash
ctxgit serve
```

The UI has a `Project` panel. Open an already initialized project, or choose a
directory and press `Init/Open` to create that project's `.ctxgit/`, `contexts/`,
and `.git` if needed. The UI then shows that project's branches as chat
timelines backed by `contexts/branches/<branch>/history.jsonl`, the branch
report from `context.md`, and Git status/log/diff for those files. Appending a
message in the UI writes to the selected project's `history.jsonl`, so each
project keeps its own version-managed conversation history.

The primary `Send` button calls the configured LLM provider. The default
provider is OpenAI Codex through the local `codex` CLI, using its existing
ChatGPT OAuth login:

```bash
codex login status
codex login --device-auth
ctxgit provider status
ctxgit chat AItrust "What should I investigate next?"
```

One chat turn always records the user message and assistant reply in
`history.jsonl`. It may also create zero, one, or many markdown artifacts under
`contexts/branches/<branch>/artifacts/`.

## Report Shape

Branch contexts and research notes are meant to read like managed research
reports, not loose chat notes. The default sections are:

- Executive Summary
- Research Question
- Scope
- Key Findings
- Evidence Ledger
- Analysis
- Open Questions
- Decisions And Assumptions
- Source Map
- Next Actions
- Change Log
