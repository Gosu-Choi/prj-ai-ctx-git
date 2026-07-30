"""Instagram extension for ctxgit (Rocket API).

An optional, non-fundamental add-on. Self-contained and deliberately independent
of ctxgit.py: its Rocket API key lives in this directory's own ``.env``
(``ROCKETAPI_KEY``), separate from the ctxgit project environment.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# --- Extension metadata (surfaced in the sidebar registry) -------------------
ID = "instagram"
NAME = "Instagram"
ICON = "\U0001F4F8"  # 📸
DESCRIPTION = "View a public profile and its recent posts (Rocket API)."

_DIR = Path(__file__).resolve().parent
ENV_PATH = _DIR / ".env"
API_BASE = "https://v1.rocketapi.io"
IMAGE_HOSTS = ("cdninstagram.com", "fbcdn.net")


# --- Configuration (this extension's own .env) -------------------------------
def read_key() -> str:
    """Read ROCKETAPI_KEY from this extension's own .env file."""
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "ROCKETAPI_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def configured() -> bool:
    return bool(read_key())


# --- Rocket API client -------------------------------------------------------
def api_post(key: str, path: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    """POST to Rocket API and return the parsed JSON body. Raises ValueError on failure."""
    if not key:
        raise ValueError("Rocket API key is not configured (set ROCKETAPI_KEY in the extension's .env)")
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_BASE + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Token {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else str(exc)
        raise ValueError(f"Rocket API error {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001 - surface network failures to the UI
        raise ValueError(f"Rocket API request failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Rocket API returned invalid JSON") from exc


# --- Defensive response parsers ---------------------------------------------
def _first_dict_with(obj: Any, *keys: str) -> dict[str, Any] | None:
    """Depth-first search for the first dict containing any of ``keys``."""
    if isinstance(obj, dict):
        if any(k in obj for k in keys):
            return obj
        for value in obj.values():
            found = _first_dict_with(value, *keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first_dict_with(value, *keys)
            if found is not None:
                return found
    return None


def profile_from_response(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a get_web_profile_info response into a flat profile dict."""
    user = _first_dict_with(data, "edge_followed_by", "biography") or {}

    def count(node: Any) -> int:
        return int(node.get("count", 0)) if isinstance(node, dict) else int(node or 0)

    return {
        "id": str(user.get("id") or user.get("pk") or ""),
        "username": user.get("username") or "",
        "full_name": user.get("full_name") or "",
        "biography": user.get("biography") or "",
        "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        "is_verified": bool(user.get("is_verified")),
        "is_private": bool(user.get("is_private")),
        "followers": count(user.get("edge_followed_by") or user.get("follower_count")),
        "following": count(user.get("edge_follow") or user.get("following_count")),
        "posts": count(user.get("edge_owner_to_timeline_media") or user.get("media_count")),
        "external_url": user.get("external_url") or "",
    }


def _media_thumbnail(item: dict[str, Any]) -> str:
    versions = item.get("image_versions2")
    if isinstance(versions, dict):
        cands = versions.get("candidates")
        if isinstance(cands, list) and cands and isinstance(cands[0], dict):
            return str(cands[0].get("url") or "")
    return str(item.get("thumbnail_url") or item.get("display_url") or "")


def media_from_response(data: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """Normalize a get_media response into a list of post thumbnails."""
    items = None
    node = _first_dict_with(data, "items")
    if isinstance(node, dict) and isinstance(node.get("items"), list):
        items = node["items"]
    if items is None:
        edges_node = _first_dict_with(data, "edges")
        if isinstance(edges_node, dict) and isinstance(edges_node.get("edges"), list):
            items = [e.get("node", {}) for e in edges_node["edges"] if isinstance(e, dict)]
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in items[: max(0, limit)]:
        if not isinstance(raw, dict):
            continue
        item = raw.get("media") if isinstance(raw.get("media"), dict) else raw
        caption = item.get("caption")
        caption_text = caption.get("text") if isinstance(caption, dict) else (caption or "")
        code = item.get("code") or item.get("shortcode") or ""
        out.append(
            {
                "id": str(item.get("id") or item.get("pk") or ""),
                "shortcode": code,
                "permalink": f"https://www.instagram.com/p/{code}/" if code else "",
                "thumbnail_url": _media_thumbnail(item),
                "caption": str(caption_text or "")[:280],
                "like_count": int(item.get("like_count") or 0),
                "comment_count": int(item.get("comment_count") or 0),
                "is_video": int(item.get("media_type") or 0) == 2 or bool(item.get("is_video")),
            }
        )
    return out


def is_image_url(url: str) -> bool:
    """Restrict the image proxy to Instagram CDN hosts (SSRF guard)."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS)


# --- High-level fetch helpers used by the HTTP endpoints ----------------------
def profile(key: str, username: str) -> dict[str, Any]:
    username = str(username or "").strip().lstrip("@")
    if not username:
        raise ValueError("username is required")
    return profile_from_response(api_post(key, "/instagram/user/get_web_profile_info", {"username": username}))


def media(key: str, user_id: str, count: int = 12) -> list[dict[str, Any]]:
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("id is required")
    try:
        count = int(count or 12)
    except (TypeError, ValueError):
        count = 12
    count = max(1, min(count, 24))
    return media_from_response(api_post(key, "/instagram/user/get_media", {"id": user_id, "count": count}), limit=count)


# --- MCP tools the chat agents can call mid-conversation ----------------------
MCP_TOOLS = [
    {
        "name": "get_instagram_profile",
        "description": (
            "Fetch a public Instagram profile by username via Rocket API. Returns JSON with "
            "id, username, full_name, biography, followers, following, posts, is_verified, "
            "is_private, external_url. Use the returned `id` to then call get_instagram_media."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Instagram username without the @"},
            },
            "required": ["username"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_instagram_media",
        "description": (
            "Fetch recent posts for an Instagram numeric user id (obtained from "
            "get_instagram_profile) via Rocket API. Returns a JSON array of posts with "
            "shortcode, permalink, caption, like_count, comment_count, is_video."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Instagram numeric user id"},
                "count": {"type": "integer", "description": "Number of posts (1-24, default 12)"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def mcp_call(key: str, name: str, arguments: dict[str, Any]) -> Any:
    if name == "get_instagram_profile":
        return profile(key, arguments.get("username"))
    if name == "get_instagram_media":
        return media(key, arguments.get("id"), arguments.get("count") or 12)
    raise ValueError(f"Unknown tool: {name}")
