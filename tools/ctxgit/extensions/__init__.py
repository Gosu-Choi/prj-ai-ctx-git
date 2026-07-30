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

from . import instagram

# Ordered registry of available extensions (module objects).
_REGISTRY: dict[str, Any] = {
    instagram.ID: instagram,
}


def all_extensions() -> list[Any]:
    return list(_REGISTRY.values())


def get_extension(ext_id: str) -> Any | None:
    return _REGISTRY.get(ext_id)


def metadata(ext: Any) -> dict[str, Any]:
    return {
        "id": ext.ID,
        "name": ext.NAME,
        "icon": ext.ICON,
        "description": ext.DESCRIPTION,
        "configured": ext.configured(),
    }


def mcp_tool_names(ext: Any) -> tuple[str, ...]:
    return tuple(f"mcp__{ext.ID}__{tool['name']}" for tool in ext.MCP_TOOLS)


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
