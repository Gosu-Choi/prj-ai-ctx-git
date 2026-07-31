"""ctxgit extensions: optional, non-fundamental add-ons.

Each extension is a self-contained module under this package with its own
metadata, its own ``.env`` (secrets live next to the extension, not in the
project env), and optional MCP tools the chat agents can call.

This package is deliberately independent of ctxgit.py: ctxgit imports it, reads
the registry, and wires the HTTP endpoints / MCP servers. Enable/disable state
is owned by ctxgit (global settings), not stored here.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import google_workspace, instagram

# Ordered registry of available extensions (module objects).
_REGISTRY: dict[str, Any] = {
    instagram.ID: instagram,
    google_workspace.ID: google_workspace,
}


def all_extensions() -> list[Any]:
    return list(_REGISTRY.values())


def get_extension(ext_id: str) -> Any | None:
    return _REGISTRY.get(ext_id)


def extension_kind(ext: Any) -> str:
    """"stdio" (ctxgit spawns the MCP server) or "remote" (user-configured CLI MCP)."""
    return getattr(ext, "KIND", "stdio")


def stdio_extensions() -> list[Any]:
    return [ext for ext in _REGISTRY.values() if extension_kind(ext) == "stdio"]


def remote_extensions() -> list[Any]:
    return [ext for ext in _REGISTRY.values() if extension_kind(ext) == "remote"]


def metadata(ext: Any) -> dict[str, Any]:
    payload = {
        "id": ext.ID,
        "name": ext.NAME,
        "icon": ext.ICON,
        "description": ext.DESCRIPTION,
        "kind": extension_kind(ext),
        "configured": ext.configured(),
    }
    if extension_kind(ext) == "remote":
        # Per-server registration status, for the setup UI.
        payload["servers"] = ext.server_status() if hasattr(ext, "server_status") else {}
    return payload


def mcp_tool_names(ext: Any) -> tuple[str, ...]:
    """Fully-qualified tool names for a stdio extension (used in Claude allowlists)."""
    return tuple(f"mcp__{ext.ID}__{tool['name']}" for tool in ext.MCP_TOOLS)


def remote_allow_names(ext: Any) -> tuple[str, ...]:
    """Claude allowlist entries for a remote extension: mcp__<server> allows all its tools."""
    return tuple(f"mcp__{server}" for server in getattr(ext, "MCP_SERVERS", ()))


def run_mcp_server(ext: Any) -> int:
    """Minimal stdio MCP (JSON-RPC 2.0) server exposing one extension's tools.

    Spawned by the Claude/Codex CLI during a chat turn so the agent can use the
    extension on its own. Reads the key from the extension's own .env.
    """
    key = ext.read_key()

    def send(message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
            send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": requested,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": f"ctxgit-{ext.ID}", "version": "1.0.0"},
                },
            })
        elif method == "notifications/initialized":
            continue  # notification: no response expected
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": ext.MCP_TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                result = ext.mcp_call(key, str(name), arguments)
                send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
                })
            except Exception as exc:  # noqa: BLE001 - report failures back to the agent
                send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
                })
        elif msg_id is not None:
            send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })
    return 0
