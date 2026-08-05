# prj-ai-ctx-git

An experiment in parallel AI conversations backed by plain markdown and Git.

Before changing history, internal Git refs, Fork, Cut, Merge, or message
revision behavior, read [`MAJOR_DESIGN_CONSIDERATIONS.md`](MAJOR_DESIGN_CONSIDERATIONS.md).

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
ctxgit merge AItrust AIdiscipline --name integrated-research
```

`ctxgit init` creates `.ctxgit/`, `.ctxgit/git/`, and `contexts/`. It does not
create a root `.git/` repository by default. Use `ctxgit init --git` only when
you also want the project folder itself to become a normal Git repository.

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

## Local Server Scripts

The repository includes double-click launchers at the repository root. By
default they start the server with no project selected; open or initialize a
project from the browser UI. Set `CTXGIT_ROOT` in this repository's local
`.env` file only when you want the launchers to open one fixed project
automatically. The default server URL is `http://127.0.0.1:8766/`.

Root launchers:

- `start-ctxgit-windows.cmd`
- `stop-ctxgit-windows.cmd`
- `start-ctxgit-macos.command`
- `stop-ctxgit-macos.command`

On macOS, if Finder refuses to run the `.command` files, set the executable bit
once:

```bash
chmod +x start-ctxgit-macos.command stop-ctxgit-macos.command
```

Windows PowerShell:

```powershell
.\scripts\windows\start-ctxgit.ps1
.\scripts\windows\start-ctxgit.ps1 "C:\path\to\your\project"
.\scripts\windows\stop-ctxgit.ps1
```

macOS:

```bash
bash scripts/macos/start-ctxgit.sh
bash scripts/macos/start-ctxgit.sh "/path/to/your/project"
bash scripts/macos/stop-ctxgit.sh
```

Optional `.env` defaults:

```dotenv
# Leave CTXGIT_ROOT unset to start with no project selected.
# CTXGIT_ROOT=/absolute/path/to/your/ctxgit/project
CTXGIT_HOST=127.0.0.1
CTXGIT_PORT=8766
```

## Research

Hybrid research is the default:

```bash
ctxgit research AItrust \
  "current research on AI trust calibration"
```

Hybrid research collects sources before synthesis. It uses Brave Web Search and
Brave LLM Context when `BRAVE_API_KEY` is set, and also queries scholarly
indexes such as Semantic Scholar, Crossref, and arXiv to avoid relying on a
single search surface. The final note is synthesized from collected source
records and includes coverage and hallucination-check sections instead of
forcing a rigid report template.

For hallucination control, ctxgit stores the collected source records in the
note, fetches readable excerpts from a bounded number of URLs, warns when source
coverage is thin, and refuses to synthesize claims if zero sources were
collected.

Set `BRAVE_API_KEY` either in the shell environment or in the ctxgit repository
`.env` file:

```dotenv
BRAVE_API_KEY=...
```

The repository includes `.env.example`; copy it to `.env` and fill the key.
`.env` is ignored by Git. A project-local `.ctxgit/.env` can still override the
shared repository value when needed.

Direct Brave retrieval is still available:

```bash
export BRAVE_API_KEY=...
ctxgit research AItrust \
  "AI trust calibration literature" \
  --provider brave \
  --freshness py
```

The project-level OpenCode research agent lives at
`.opencode/agents/research.md` and is used for synthesis in hybrid mode.

## Source Files

Branch-local source files live under `contexts/branches/<branch>/sources/`.
Chat turns automatically try to ingest readable source files from that folder
before calling the model. Text-like files are copied/extracted directly; PDFs
are extracted when `pypdf`, `PyPDF2`, or `pdftotext` is available, otherwise the
file is recorded with `needs-extractor` status so the missing capability is
visible.

You can also ingest a file explicitly:

```bash
ctxgit ingest initial ./paper.pdf
```

## Agent Memory

Project-level agent instructions and memory live under `contexts/`:

- `contexts/AGENTS.md`
- `contexts/USER.md`
- `contexts/MEMORY.md`
- `contexts/agents/`

These files are global to the opened project. They are not branch-local and are
not copied or merged when ctxgit branches are merged.

## Guiding Knowledge

Guiding knowledge is durable knowledge a branch should already have before the
first message of a turn, without depending on the model choosing to read a file.

Documents live under `contexts/knowledge/*.md` and are shared across the whole
project. Which of them apply is decided **per branch**: the topbar `Guiding`
button lists every knowledge document and toggles each one on or off for the
open branch. The selection is stored as `guiding` in that branch's `branch.json`.

Every document a branch has switched on is inserted verbatim into that branch's
prompts, in the same layer as `AGENTS.md`, for chat turns, info-chat turns, and
sequence-room agent turns. It is prompt injection, not a tool call, so a guiding
document is guaranteed to be in effect rather than merely available to read.
Documents removed from disk drop out of a branch's selection silently instead of
breaking its prompts.

Nothing is captured automatically. To store something, open the `...` menu on a
chat message and choose `Knowledging`. The modal asks which document to append
to (or creates a new one) and what should be remembered; the configured LLM then
distills one Markdown section from that message and your instruction, and
appends it to the document. Knowledge documents are append-only through this
flow — editing or reorganizing what is already stored is done in the files
themselves, and every append is recorded as a ctxgit turn commit. `.ctxgit/` is reserved
for tool configuration and metadata; AI prompts are built from `contexts/` so
the operational context is visible and Git-reviewable.

On first `ctxgit init`, ctxgit also looks for an existing workspace context
folder in the project root, such as `workspace/`, `openclaw-workspace/`, or
`.openclaw/workspace/`. If it finds OpenClaw-style memory files like
`MEMORY.md`, `AGENTS.md`, `SOUL.md`, `DREAMS.md`, or `memory/*.md`, it imports a
reviewable digest into `contexts/imports/workspace-summary.md` and seeds the
`initial` branch with a system history entry that points to that summary.
Top-level uppercase OpenClaw files such as `AGENTS.md`, `USER.md`, `MEMORY.md`,
`SOUL.md`, `TOOLS.md`, and `DREAMS.md` are also copied verbatim into
`contexts/imports/workspace-files/`; `AGENTS.md`, `USER.md`, and `MEMORY.md` are
appended into the matching ctxgit global files, while the others are appended
under `contexts/MEMORY.md` with provenance-only source headers. Runtime prompts
use the copied files under `contexts/`; deleting the original workspace does
not remove the imported AI context.

If the workspace lives somewhere else or the project is already initialized,
import it explicitly:

```bash
ctxgit import-workspace C:\Users\work\Desktop\openclaw\workspace
```

You can also combine this with first initialization:

```bash
ctxgit init --import-workspace C:\Users\work\Desktop\openclaw\workspace
```

## Branch Merge

`ctxgit merge` creates a new ctxgit branch from two or more source branches:

```bash
ctxgit merge AItrust AIdiscipline --name integrated-research
```

The merged branch starts with a summarized system history entry. Source branch
histories are archived under
`contexts/branches/<merged>/archives/<source>/history.jsonl` and can be viewed
from the UI's Archives tab.

## Chat Interface

Run the local viewer:

```bash
ctxgit serve
```

For local-only use on your own machine, skip signup/login:

```bash
ctxgit serve --no-auth
```

The web interface requires login. On a fresh server, the first signup creates
the admin account; after that, signup is closed by default. Set
`CTXGIT_ALLOW_SIGNUP=1` only if you intentionally want additional open
registrations. Behind HTTPS, set `CTXGIT_COOKIE_SECURE=1` unless your reverse
proxy sends `X-Forwarded-Proto: https`.

The UI has a `Project` panel. Open an already initialized project, or choose a
directory and press `Init/Open` to create that project's `.ctxgit/`, `contexts/`,
and `.git` if needed. The UI then shows that project's branches as chat
timelines backed by `contexts/branches/<branch>/history.jsonl`, the branch
report from `context.md`, and Git status/log/diff for those files. Appending a
message in the UI writes to the selected project's `history.jsonl`, so each
project keeps its own version-managed conversation history.

The file browser uploads folders by sending files in small chunks rather than
posting one huge base64 payload. This avoids common reverse-proxy and
Cloudflare `413 Payload Too Large` failures for large folders.

The primary `Send` button calls the configured LLM provider. The default
provider is OpenAI Codex through the local `codex` CLI, using its existing
ChatGPT OAuth login. ctxgit runs Codex with `--sandbox workspace-write` by
default, so chat turns can edit files inside the opened project workspace
without asking for per-edit approval. If a turn needs to write outside the
opened project, the assistant must request approval first; approving it reruns
that turn with only the approved external directory added through Codex
`--add-dir`.

On Windows, ctxgit first tries `codex` from PATH and then falls back to the
Codex binary bundled with the VS Code/Cursor ChatGPT extension. If your setup is
elsewhere, set `CTXGIT_CODEX_BIN` in this repository's `.env` file to the full
path of `codex.exe`.

```bash
codex login status
codex login --device-auth
ctxgit provider status
ctxgit chat AItrust "What should I investigate next?"
```

One chat turn always records the user message and assistant reply in
`history.jsonl`. It may also create zero, one, or many markdown artifacts under
`contexts/branches/<branch>/artifacts/`.

The UI `Research` button runs the hybrid research pipeline for the selected
branch and writes the request plus result pointer into `history.jsonl`. The
research report itself is saved under `contexts/branches/<branch>/research/`.

Long histories are not truncated to a fixed message count. ctxgit keeps raw
history append-only and, once a branch grows past the compaction threshold,
uses the configured LLM to write reviewable summaries under
`contexts/branches/<branch>/compactions/`. If AI compaction is unavailable,
ctxgit writes an explicit extractive fallback summary and marks it as fallback.
Future chat and research prompts include project memory, branch context,
source-file extracts, compactions, and the most relevant raw history selected
within the configured context budget.

## Report Shape

Branch contexts are meant to read like managed research reports, not loose chat
notes. The default branch report has these sections:

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

Research notes are flexible. They should use headings that fit the request,
especially for literature review work where the important unit is often paper
coverage, argument mapping, and claim support rather than a fixed RQ template.
