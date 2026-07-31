"""Google Workspace extension for ctxgit (Gmail + Drive via official remote MCP).

Unlike the Instagram extension (a stdio MCP server ctxgit spawns), this is a
*remote* extension: the user registers Google's official remote MCP servers in
their own Codex/Claude CLI config (with OAuth), and ctxgit only wires the
consumption side — auto-approving the tool calls (Codex) and allow-listing the
tools (Claude) when this extension is enabled.

There is no key file here; auth lives in the CLI's own OAuth token store.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

# --- Extension metadata ------------------------------------------------------
ID = "google-workspace"
NAME = "Google Workspace"
ICON = "\U0001F4E7"  # 📧
DESCRIPTION = "Read Gmail and Drive via Google's official remote MCP (OAuth)."
KIND = "remote"

# The MCP server names the user is expected to register in their CLI config.
MCP_SERVERS = ("gmail", "drive")

# Official Google-managed remote MCP endpoints (for the setup UI).
SERVER_ENDPOINTS = {
    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
    "drive": "https://drivemcp.googleapis.com/mcp/v1",
}

_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
_CLAUDE_CONFIG = Path.home() / ".claude.json"


def _codex_servers() -> set[str]:
    try:
        data = tomllib.loads(_CODEX_CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    servers = data.get("mcp_servers")
    return set(servers.keys()) if isinstance(servers, dict) else set()


def _claude_servers() -> set[str]:
    """Best-effort scan of ~/.claude.json for registered MCP server names."""
    try:
        data = json.loads(_CLAUDE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    names: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            servers = node.get("mcpServers")
            if isinstance(servers, dict):
                names.update(servers.keys())
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(data)
    return names


def server_status() -> dict[str, bool]:
    """Which of this extension's servers are registered in either CLI's config."""
    registered = _codex_servers() | _claude_servers()
    return {server: server in registered for server in MCP_SERVERS}


def codex_configured_servers() -> list[str]:
    """Servers registered specifically in the Codex config (drives approval wiring)."""
    present = _codex_servers()
    return [server for server in MCP_SERVERS if server in present]


def configured() -> bool:
    """Considered configured once at least one of its servers is registered."""
    return any(server_status().values())
