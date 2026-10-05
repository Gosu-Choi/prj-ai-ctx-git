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
ctxgit import-workspace /path/to/openclaw/workspace
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

Use the default hybrid research pipeline:

```bash
ctxgit research AItrust \
  "current research on AI trust calibration"
```

Hybrid mode collects source records first, then asks the OpenCode research
agent to synthesize only from those records. If `BRAVE_API_KEY` is available it
uses Brave Web Search and Brave LLM Context; it also queries scholarly indexes
such as Semantic Scholar, Crossref, and arXiv.
It stores collected source records, fetches readable excerpts from a bounded
number of URLs, warns on thin coverage, and skips synthesis when zero sources
were collected.

`BRAVE_API_KEY` can be set in the shell environment or in the ctxgit repository
`.env` file:

```dotenv
BRAVE_API_KEY=...
```

The repository includes `.env.example`; copy it to `.env` and fill the key.
`.env` is ignored by Git. A project-local `.ctxgit/.env` can still override the
shared repository value when needed.

Or call Brave directly:

```bash
export BRAVE_API_KEY=...
ctxgit research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

Both modes write markdown notes to
`contexts/branches/<branch>/research/`.

## Guiding Knowledge

Knowledge documents live under `contexts/knowledge/*.md` and are shared across
the project. Each branch switches individual documents on from the topbar
`Guiding` button; the selection is stored as `guiding` in that branch's
`branch.json`. Switched-on documents are injected verbatim into that branch's
prompts, so the agent starts every turn already knowing them.

They go in three places, because one was not enough to make them stick. In the
prompt body the text runs on from the end of the user's own message with no tag
or heading between them: placed anywhere else it reads as reference material the
user happened to paste, and continuing their sentence it reads as part of what is
being asked. The provider's system prompt carries a second copy, and a short
reminder after the message says that it outranks the branch's earlier prose.
History compaction gets them too — a compaction is re-injected into every later
prompt, so one written without them contradicts them from then on.

## Templates

Guiding decides how a branch writes. Templates decide what it builds with.

A template is a package rather than a document — a deck system's stylesheets,
starter files, and build scripts — so it lives in `contexts/templates/<id>/v<N>/`
with a `template.json` naming it and pointing at its entry document. Versions sit
side by side and a branch pins the one it selected, so shipping v2 never rewrites
finished work.

Branches switch templates on from the topbar `Template` button, stored as
`templates` in `branch.json`, independently of `guiding`. Only the manifest and
the entry document are injected; the package itself stays on disk for the agent to
open. That is the difference from guiding knowledge, which is small enough to go
in whole.

Storing knowledge is always explicit: `Knowledging` in a chat message's `...`
menu opens a modal, and the configured LLM appends one distilled section to the
document you pick.

## Git Snapshots

```bash
ctxgit snapshot -m "ctxgit: update AI trust contexts"
```

## Chat Interface

```bash
ctxgit serve
```

For local-only use on your own machine, run without the login gate:

```bash
ctxgit serve --no-auth
```

The web interface uses local accounts by default. The first signup creates the
admin account, then signup closes unless `CTXGIT_ALLOW_SIGNUP=1` is set. User
records are stored outside project snapshots in `.ctxgit/auth.json`; sessions
use an HttpOnly cookie. Set `CTXGIT_COOKIE_SECURE=1` when serving through HTTPS
unless the reverse proxy sends `X-Forwarded-Proto: https`.

Open the printed local URL to view branch reports, chat histories, research
notes, and Git status in one place. The `Project` panel can open another
initialized project or initialize a new directory, so one long-running UI can
move between project workspaces without storing their contexts in this tool
repo.

Folder uploads are chunked from the browser. ctxgit sends each file in small
pieces and records one upload turn after the selected files finish, which keeps
large folder uploads below reverse-proxy and Cloudflare request-size limits.

`Send` calls the configured LLM provider. The default is the local `codex` CLI
using OpenAI Codex / ChatGPT OAuth. ctxgit uses `--sandbox workspace-write` by
default, which lets the model edit files inside the opened project workspace
without per-edit approval. Outside-workspace writes are handled as explicit
approval requests; approving one reruns the turn with only that external
directory added through Codex `--add-dir`. `Append only` writes a user message
without asking the model.

Web jobs use the Codex app-server protocol, so BTW messages steer the active
Codex turn just as streamed stdin does on Claude. Direct one-shot commands keep
`codex exec` as a fallback. App-server thread IDs are saved per branch and mode,
so the next Codex turn resumes its native session; ctxgit's branch history also
brings in any intervening Claude turns after a provider switch.

On the Claude provider the model list is Claude Code's tier aliases — `fable`,
`opus`, `sonnet`, `haiku`, plus the `[1m]` variants that ask for the 1M-token
context window (those need an account entitled to it). The team pipeline reads a
role's declared tier as relative to that choice: roles asking for the frontier
tier run on whatever is selected, so picking Fable reaches them, while cheaper
roles stay cheap and no role outruns a deliberately cheaper selection.

```bash
ctxgit provider status
ctxgit chat AItrust "What should we research next?"
```
