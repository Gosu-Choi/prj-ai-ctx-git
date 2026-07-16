"""Subagent library: OMC's vendored agent prompts + project overrides.

The vendored prompts under `agents/*.md` come from oh-my-claudecode (MIT) so the
delegated roles behave the way OMC's do. See ORCHESTRATION_NOTICE.md.

A project can add or override any role by dropping a markdown file with the same
frontmatter shape into `contexts/subagents/`. (That is deliberately not
`contexts/agents/`, which already holds ctxgit's own research/merge prompts.)

Note: OMC prompts occasionally reference tools from its own runtime (for example
`lsp_diagnostics_directory` or `TodoWrite`). Those simply do not exist in a ctxgit
session; the agent works with the tools it is actually granted below.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

#: Read-only tools every subagent may use.
BASE_READ_TOOLS = ["Read", "Glob", "Grep"]
#: Added when the session is writable.
WRITE_TOOLS = ["Edit", "Write", "Bash"]
#: Added when web search is enabled.
WEB_TOOLS = ["WebSearch", "WebFetch"]

VENDORED_AGENTS_DIR = Path(__file__).resolve().parent / "agents"
#: Project-level subagent overrides. Not `contexts/agents/`, which ctxgit already
#: uses for its own research/merge prompts.
PROJECT_AGENTS_RELPATH = ("contexts", "subagents")


def subagent_tool_pool(*, writable: bool, web_search: bool) -> list[str]:
    """Tools a subagent may draw from.

    Task is deliberately excluded: per OMC's worker contract a delegated worker
    does the work directly and never spawns further subagents.
    """
    tools = list(BASE_READ_TOOLS)
    if writable:
        tools.extend(WRITE_TOOLS)
    if web_search:
        tools.extend(WEB_TOOLS)
    return tools


def parse_agent_markdown(text: str) -> tuple[dict[str, str], str]:
    """Split an agent file into (frontmatter, body).

    Frontmatter is the leading `---` delimited block; everything after it is the
    agent's system prompt.
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta: dict[str, str] = {}
            for line in parts[1].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
            return meta, parts[2].strip()
    return {}, text.strip()


def _split_tool_list(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\s]+", raw or "") if item.strip()]


def _entry_from_markdown(
    path: Path,
    text: str,
    *,
    pool: list[str],
) -> Optional[tuple[str, dict[str, Any]]]:
    meta, body = parse_agent_markdown(text)
    name = str(meta.get("name") or path.stem).strip()
    if not name or not body:
        return None

    disallowed = set(_split_tool_list(meta.get("disallowedTools", "")))
    allowed = _split_tool_list(meta.get("tools", ""))
    if allowed:
        # An explicit `tools:` list wins, but still cannot exceed the pool.
        tools = [item for item in allowed if item in pool]
    else:
        tools = [item for item in pool if item not in disallowed]

    entry: dict[str, Any] = {
        "description": str(meta.get("description") or f"Subagent {name}."),
        "prompt": body,
        "tools": tools,
    }
    model = str(meta.get("model") or "").strip()
    if model:
        entry["model"] = model
    return name, entry


def _load_agent_dir(directory: Path, *, pool: list[str]) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _entry_from_markdown(path, text, pool=pool)
        if parsed is None:
            continue
        name, entry = parsed
        result[name] = entry
    return result


def load_vendored_agents(*, pool: list[str]) -> dict[str, dict[str, Any]]:
    """OMC's agent roster shipped with ctxgit."""
    return _load_agent_dir(VENDORED_AGENTS_DIR, pool=pool)


def load_project_agents(root: Path, *, pool: list[str]) -> dict[str, dict[str, Any]]:
    """Project-defined agents from contexts/subagents/, overriding vendored ones by name."""
    return _load_agent_dir(root.joinpath(*PROJECT_AGENTS_RELPATH), pool=pool)


def build_subagents(
    root: Path,
    *,
    writable: bool,
    web_search: bool = True,
) -> dict[str, dict[str, Any]]:
    pool = subagent_tool_pool(writable=writable, web_search=web_search)
    agents = load_vendored_agents(pool=pool)
    agents.update(load_project_agents(root, pool=pool))
    # A role with no usable tools (e.g. a writer role in a read-only session)
    # cannot do anything useful, so drop it rather than offer a dead role.
    return {name: entry for name, entry in agents.items() if entry.get("tools")}


def build_subagents_json(
    root: Path,
    *,
    writable: bool,
    web_search: bool = True,
) -> str:
    """Value for `claude --agents`."""
    agents = build_subagents(root, writable=writable, web_search=web_search)
    return json.dumps(agents, ensure_ascii=False, separators=(",", ":"))
