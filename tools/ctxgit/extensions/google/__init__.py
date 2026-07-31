"""Google (Gmail + Drive) extension — native, read-only, via the standard REST APIs.

Self-contained stdio MCP extension (ctxgit spawns it, like Instagram). Its OAuth
credentials live in this directory's own .env
(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN), obtained once
via `ctxgit google-auth`.

READ-ONLY by construction: only find/read tools are implemented, so nothing can
send mail or modify Drive — independent of the granted scopes.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# --- Extension metadata ------------------------------------------------------
ID = "google"
NAME = "Google (Gmail + Drive)"
ICON = "\U0001F4E7"  # 📧
DESCRIPTION = "Find and read your Gmail and Drive — read-only."

_DIR = Path(__file__).resolve().parent
ENV_PATH = _DIR / ".env"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"

_token_cache: dict[str, Any] = {"token": "", "exp": 0.0}


# --- Configuration (this extension's own .env) -------------------------------
def _read_env() -> dict[str, str]:
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


def write_credentials(client_id: str, client_secret: str, refresh_token: str) -> None:
    ENV_PATH.write_text(
        "# Google (Gmail + Drive) OAuth credentials — read-only. Do not commit.\n"
        f"GOOGLE_CLIENT_ID={client_id}\n"
        f"GOOGLE_CLIENT_SECRET={client_secret}\n"
        f"GOOGLE_REFRESH_TOKEN={refresh_token}\n",
        encoding="utf-8",
    )


def configured() -> bool:
    env = _read_env()
    return bool(env.get("GOOGLE_CLIENT_ID") and env.get("GOOGLE_CLIENT_SECRET") and env.get("GOOGLE_REFRESH_TOKEN"))


def read_key() -> str:
    # Unused: this extension manages its own OAuth token internally.
    return ""


# --- OAuth: refresh token -> access token ------------------------------------
def _access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] - 60 > now:
        return str(_token_cache["token"])
    env = _read_env()
    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN") if not env.get(k)]
    if missing:
        raise ValueError(f"Google is not configured (run `ctxgit google-auth`); missing {', '.join(missing)}")
    data = urllib.parse.urlencode(
        {
            "client_id": env["GOOGLE_CLIENT_ID"],
            "client_secret": env["GOOGLE_CLIENT_SECRET"],
            "refresh_token": env["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data, method="POST"), timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else str(exc)
        raise ValueError(f"Google token refresh failed ({exc.code}): {detail}") from exc
    token = payload.get("access_token")
    if not token:
        raise ValueError("Google token refresh returned no access_token")
    _token_cache["token"] = token
    _token_cache["exp"] = now + float(payload.get("expires_in", 3600))
    return str(token)


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    """Exchange an authorization code for a refresh token (used by `ctxgit google-auth`)."""
    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data, method="POST"), timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    refresh = payload.get("refresh_token")
    if not refresh:
        raise ValueError("No refresh_token returned. Re-run with a fresh consent (prompt=consent, access_type=offline).")
    return str(refresh)


def auth_url(client_id: str, redirect_uri: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )


# --- REST helpers ------------------------------------------------------------
def _api_get(url: str) -> dict[str, Any]:
    token = _access_token()
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else str(exc)
        raise ValueError(f"Google API error {exc.code}: {detail}") from exc


def _api_get_raw(url: str) -> str:
    token = _access_token()
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else str(exc)
        raise ValueError(f"Google API error {exc.code}: {detail}") from exc


# Google-native docs must be exported; pick a text-ish format per source type.
_GOOGLE_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _header(headers: list[dict[str, Any]], name: str) -> str:
    for h in headers or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def _decode_body(payload: dict[str, Any]) -> str:
    """Extract the text/plain body from a Gmail message payload."""
    def walk(part: dict[str, Any]) -> str:
        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            text = walk(sub)
            if text:
                return text
        # Fallback: any body data (e.g. text/html) if no plain part found.
        if data and mime.startswith("text/"):
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        return ""

    return walk(payload or {})


# --- Tool implementations (read-only) ----------------------------------------
def gmail_search(query: str, count: int = 10) -> list[dict[str, Any]]:
    count = max(1, min(int(count or 10), 20))
    q = urllib.parse.quote(query or "")
    listing = _api_get(f"{GMAIL_BASE}/messages?maxResults={count}&q={q}")
    out: list[dict[str, Any]] = []
    for item in (listing.get("messages") or [])[:count]:
        mid = item.get("id")
        if not mid:
            continue
        msg = _api_get(f"{GMAIL_BASE}/messages/{mid}?format=metadata"
                       "&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        headers = (msg.get("payload") or {}).get("headers", [])
        out.append(
            {
                "id": mid,
                "threadId": msg.get("threadId", ""),
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
            }
        )
    return out


def gmail_get_message(message_id: str) -> dict[str, Any]:
    if not str(message_id or "").strip():
        raise ValueError("id is required")
    msg = _api_get(f"{GMAIL_BASE}/messages/{message_id}?format=full")
    payload = msg.get("payload") or {}
    headers = payload.get("headers", [])
    return {
        "id": msg.get("id", ""),
        "threadId": msg.get("threadId", ""),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"),
        "body": _decode_body(payload)[:8000],
    }


def gmail_list_labels() -> list[str]:
    data = _api_get(f"{GMAIL_BASE}/labels")
    return [str(label.get("name", "")) for label in (data.get("labels") or []) if label.get("name")]


def drive_search(query: str = "", count: int = 10, filter_expr: str = "") -> list[dict[str, Any]]:
    count = max(1, min(int(count or 10), 20))
    clauses = []
    keyword = (query or "").strip()
    if keyword:
        clauses.append(f"fullText contains '{keyword.replace(chr(39), ' ')}'")
    structured = (filter_expr or "").strip()
    if structured:
        clauses.append(f"({structured})")
    if not clauses:
        raise ValueError("provide a `query` keyword and/or a `filter` expression")
    clauses.append("trashed = false")
    params = urllib.parse.urlencode(
        {
            "q": " and ".join(clauses),
            "pageSize": count,
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink,driveId,owners(displayName))",
            "orderBy": "modifiedTime desc",
            # Include Shared Drives (Team Drives), not just My Drive.
            "corpora": "allDrives",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        }
    )
    data = _api_get(f"{DRIVE_BASE}/files?{params}")
    out = []
    for f in data.get("files") or []:
        out.append(
            {
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "mimeType": f.get("mimeType", ""),
                "modifiedTime": f.get("modifiedTime", ""),
                "link": f.get("webViewLink", ""),
                "sharedDrive": bool(f.get("driveId")),
            }
        )
    return out


def drive_read_file(file_id: str) -> dict[str, Any]:
    if not str(file_id or "").strip():
        raise ValueError("id is required")
    # supportsAllDrives=true is required to read files that live in a Shared Drive.
    meta = _api_get(f"{DRIVE_BASE}/files/{file_id}?fields=id,name,mimeType&supportsAllDrives=true")
    mime = meta.get("mimeType", "")
    if mime.startswith("application/vnd.google-apps."):
        export_mime = _GOOGLE_EXPORT_MIME.get(mime, "text/plain")
        params = urllib.parse.urlencode({"mimeType": export_mime, "supportsAllDrives": "true"})
        content = _api_get_raw(f"{DRIVE_BASE}/files/{file_id}/export?{params}")
    else:
        content = _api_get_raw(f"{DRIVE_BASE}/files/{file_id}?alt=media&supportsAllDrives=true")
    return {"id": meta.get("id", ""), "name": meta.get("name", ""), "mimeType": mime, "content": content[:12000]}


# --- MCP tool schemas + dispatch ---------------------------------------------
MCP_TOOLS = [
    {
        "name": "gmail_search",
        "description": "Search your Gmail. Returns matching messages (id, from, subject, date, snippet). "
        "Use Gmail search syntax in `query` (e.g. 'from:foo subject:bar newer_than:30d').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "count": {"type": "integer", "description": "Max messages (1-20, default 10)"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "gmail_get_message",
        "description": "Read one Gmail message by id (from gmail_search). Returns headers and the plain-text body.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Gmail message id"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "gmail_list_labels",
        "description": "List the names of your Gmail labels.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "drive_search",
        "description": (
            "Search Google Drive, including Shared Drives. `query` = plain keywords matched as "
            "full text. `filter` = optional Google Drive v3 query for structured filtering, e.g. "
            "\"name contains 'report'\", \"mimeType = 'application/pdf'\", "
            "\"modifiedTime > '2026-01-01'\", \"'FOLDER_ID' in parents\", \"sharedWithMe = true\"; "
            "combine terms with 'and'/'or'. Provide `query`, `filter`, or both. Each result is "
            "flagged with sharedDrive."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Full-text keywords (optional)"},
                "filter": {"type": "string", "description": "Drive v3 structured query (optional)"},
                "count": {"type": "integer", "description": "Max files (1-20, default 10)"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "drive_read_file",
        "description": "Read a Drive file's content by id (from drive_search). Google Docs are exported as text.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Drive file id"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def mcp_call(key: str, name: str, arguments: dict[str, Any]) -> Any:
    if name == "gmail_search":
        return gmail_search(arguments.get("query", ""), arguments.get("count", 10))
    if name == "gmail_get_message":
        return gmail_get_message(arguments.get("id", ""))
    if name == "gmail_list_labels":
        return gmail_list_labels()
    if name == "drive_search":
        return drive_search(
            arguments.get("query", ""),
            arguments.get("count", 10),
            arguments.get("filter", ""),
        )
    if name == "drive_read_file":
        return drive_read_file(arguments.get("id", ""))
    raise ValueError(f"Unknown tool: {name}")
