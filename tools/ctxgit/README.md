# ctxgit

`ctxgit` is a small transparent context layer for parallel AI conversations.
It is used as a global command, while each selected project keeps its own
`.git`, `.ctxgit/`, and `contexts/` directories. Conversation branches, notes,
research, and conceptual merge views are plain files under that project's
`contexts/` so Git can manage the history.
Those markdown files are report-shaped by default: branch contexts carry an
executive summary, research question, findings table, evidence ledger, source
map, analysis, decisions, next actions, and change log.

It is intentionally separate from chat-agent session internals. OpenCode can be
used as a research backend through `opencode run --agent research`, while the
conversation state remains markdown and JSONL.

## Quick Start

Use the `ctxgit` wrapper from `bin/ctxgit`. On this machine it is symlinked into
`/opt/homebrew/bin`, so it is available on `PATH`.

```bash
cd /path/to/your/project
ctxgit init
ctxgit branch AItrust --title "AI trust"
ctxgit branch AIdiscipline --title "AI discipline"
ctxgit append AItrust --role user "What makes an AI trustworthy?"
ctxgit append AIdiscipline --role user "How should I discipline AI usage?"
ctxgit merge-view AItrust AIdiscipline --name trust-discipline
```

`ctxgit init` runs `git init` by default when the directory is not already a Git
repository. Pass `--no-git` to skip that.

## Windows

From PowerShell:

```powershell
git clone <this-repo-url> prj-ai-ctx-git
cd prj-ai-ctx-git
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

Open a new PowerShell window:

```powershell
ctxgit --help
```

The installer adds `bin\` to the user `PATH`; `bin\ctxgit.cmd` runs the Python
CLI with `py -3` or `python`.

## Research

Use OpenCode as the default research backend:

```bash
ctxgit research AItrust \
  "current research on AI trust calibration" \
  --provider opencode
```

Or call Brave LLM Context directly:

```bash
export BRAVE_API_KEY=...
ctxgit research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

Both modes write markdown notes to
`contexts/branches/<branch>/research/`.

## Git Snapshots

```bash
ctxgit snapshot -m "ctxgit: update AI trust contexts"
```

## Chat Interface

```bash
ctxgit serve
```

Open the printed local URL to view branch reports, chat histories, research
notes, and Git status in one place. The `Project` panel can open another
initialized project or initialize a new directory, so one long-running UI can
move between project workspaces without storing their contexts in this tool
repo.

`Send` calls the configured LLM provider. The default is the local `codex` CLI
using OpenAI Codex / ChatGPT OAuth. `Append only` writes a user message without
asking the model.

```bash
ctxgit provider status
ctxgit chat AItrust "What should we research next?"
```
