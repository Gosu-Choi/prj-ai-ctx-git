"""Adit MCP extension for ctxgit.

Unlike the other extensions, this one does not implement tools itself. The Adit
MCP servers already exist inside the Rdod-Corporation repos, so this extension's
job is only to *offer* them to the chat agent on both providers.

That is why it declares `mcp_servers()` (external processes) instead of
`MCP_TOOLS` (ctxgit-hosted). The server list lives in `servers.json` so adding a
newly built Adit MCP later is a data change, not a code change.

Secrets stay in this directory's own `.env`, matching the other extensions —
`servers.json` only ever names an environment variable, never a value.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# --- Extension metadata (surfaced in the sidebar registry) -------------------
ID = "adit"
NAME = "Adit MCP"
ICON = "\U0001F517"  # 🔗
DESCRIPTION = "Adit 사내 MCP 서버 모음 — 콘솔 데이터 조회, 애널리틱스, A/B Lab."

_DIR = Path(__file__).resolve().parent
ENV_PATH = _DIR / ".env"
SERVERS_PATH = _DIR / "servers.json"

# Extensions own their secrets, so this extension's .env wins over any value
# inherited from the shell — the agent must not pick up a stray token.
_ENV_FIRST = True


def _read_env_file() -> dict[str, str]:
    """Parse this extension's own .env (``KEY=value``), ignoring comments."""
    values: dict[str, str] = {}
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _lookup(name: str) -> str:
    env = _read_env_file()
    if _ENV_FIRST and env.get(name):
        return env[name]
    return os.environ.get(name) or env.get(name) or ""


def _load_config() -> dict[str, Any]:
    try:
        data = json.loads(SERVERS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve(value: str) -> str:
    """Expand a single ``${VAR}`` reference; empty string when unresolved."""
    text = str(value or "")
    if not (text.startswith("${") and text.endswith("}")):
        return text
    return _lookup(text[2:-1])


def _entries() -> list[dict[str, Any]]:
    config = _load_config()
    raw = config.get("servers")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _root_for(entry: dict[str, Any], config: dict[str, Any]) -> Path:
    base = str(entry.get("root") or config.get("aditRoot") or "").strip()
    return Path(base).expanduser() if base else _DIR


def server_status() -> list[dict[str, Any]]:
    """Every declared server with why it is (or is not) currently offered.

    Surfaced verbatim by `ctxgit provider status`, so a missing token reads as a
    named missing token rather than a silently absent tool.
    """
    config = _load_config()
    rows: list[dict[str, Any]] = []
    for entry in _entries():
        server_id = str(entry.get("id") or "").strip()
        if not server_id:
            continue
        enabled = entry.get("enabled") is not False
        missing = [
            name for name in (entry.get("requires") or [])
            if not _lookup(str(name))
        ]
        # A remote entry has a url instead of a local checkout to run.
        url = str(entry.get("url") or "").strip()
        cwd = "" if url else str(_root_for(entry, config) / str(entry.get("cwd") or ""))
        if not enabled:
            reason = "disabled in servers.json"
        elif missing:
            reason = f"missing env: {', '.join(missing)}"
        elif not url and not Path(cwd).exists():
            reason = f"path not found: {cwd}"
        else:
            reason = ""
        rows.append({
            "id": server_id,
            "label": str(entry.get("label") or server_id),
            "ready": not reason,
            "reason": reason,
            "cwd": cwd,
            "url": url,
        })
    return rows


def mcp_servers() -> dict[str, dict[str, Any]]:
    """Ready-to-spawn specs, keyed by the name the agent will see.

    A server whose token or checkout is missing is skipped rather than offered
    broken: a half-configured Adit setup should still hand over the servers that
    do work.
    """
    config = _load_config()
    specs: dict[str, dict[str, Any]] = {}
    ready = {row["id"] for row in server_status() if row["ready"]}
    for entry in _entries():
        server_id = str(entry.get("id") or "").strip()
        if server_id not in ready:
            continue
        url = str(entry.get("url") or "").strip()
        if url:
            # Remote MCP: the provider CLI owns the OAuth token, so ctxgit passes
            # the endpoint and nothing else. No credential ever reaches a spec.
            specs[server_id] = {"url": url}
            continue
        root = _root_for(entry, config)
        env: dict[str, str] = {}
        for name, value in (entry.get("env") or {}).items():
            resolved = _resolve(str(value))
            if resolved:
                env[str(name)] = resolved
        specs[server_id] = {
            "command": str(entry.get("command") or ""),
            "args": [str(a) for a in (entry.get("args") or [])],
            "cwd": str(root / str(entry.get("cwd") or "")),
            "env": env,
        }
    return specs


def configured() -> bool:
    """Configured once at least one declared server can actually be spawned."""
    return bool(mcp_servers())


# This extension hosts no tools of its own; the Adit servers declare theirs.
MCP_TOOLS: list[dict[str, Any]] = []


def mcp_call(_key: str, name: str, _arguments: dict[str, Any]) -> Any:
    raise RuntimeError(
        f"{NAME} proxies external MCP servers and hosts no tools of its own "
        f"(got {name!r})."
    )


def read_key() -> str:
    return ""
