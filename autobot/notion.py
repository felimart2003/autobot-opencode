"""Notion API client (stdlib urllib only) and the project-queue schema.

Queue contract, shared with autoclaude so both can point at the same database:
  - each database page is one project; the page CONTENT is the prompt
  - status lives in the title: no marker = pending, 🔄 running, ✅ done, ❌ failed
  - optional columns per row: Backend (select), Model (select or text),
    Effort (select; legacy name "Thinking" also read), Priority (number, lower = sooner)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from .config import SCRIPT_DIR, cfg

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

MARK_DONE, MARK_RUNNING, MARK_FAILED = "✅", "\U0001f504", "❌"  # ✅ 🔄 ❌
ALL_MARKS = (MARK_DONE, MARK_RUNNING, MARK_FAILED)


def notion_request(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit(
            "NOTION_TOKEN is not set.\n"
            "Create an internal integration at https://www.notion.so/profile/integrations,\n"
            "share the projects database with it (page ••• menu > Connections),\n"
            f"then put NOTION_TOKEN=... in {SCRIPT_DIR / '.env'}"
        )
    req = urllib.request.Request(
        f"{NOTION_API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"Notion API {method} {path} -> {e.code}: {detail}") from e


def rich_text_to_plain(rich: list) -> str:
    return "".join(part.get("plain_text", "") for part in rich)


def _prop_value(props: dict, *names: str):
    """First usable value among the named properties (select, text, or number)."""
    for name in names:
        p = props.get(name)
        if not p:
            continue
        ptype = p.get("type")
        value = None
        if ptype == "select":
            value = (p.get("select") or {}).get("name")
        elif ptype == "rich_text":
            value = rich_text_to_plain(p.get("rich_text", [])).strip() or None
        elif ptype == "number":
            value = p.get("number")
        if value not in (None, "", "default"):
            return value
    return None


def fetch_pending_projects() -> list[dict]:
    """All DB pages without a status marker, sorted by Priority (blank last) then created time."""
    pages, cursor = [], None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{cfg('NOTION_DATABASE_ID')}/query", body)
        pages.extend(data.get("results", []))
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break

    projects = []
    for page in pages:
        props = page["properties"]
        title_name, title_prop = next(
            ((k, p) for k, p in props.items() if p["type"] == "title"), (None, None)
        )
        title = rich_text_to_plain(title_prop["title"]) if title_prop else ""
        if not title or any(m in title for m in ALL_MARKS):
            continue
        projects.append(
            {
                "id": page["id"],
                "title": title.strip(),
                "title_prop": title_name or "Name",
                "backend": _prop_value(props, "Backend", "Agent", "Runner"),
                "model": _prop_value(props, "Model"),
                "effort": _prop_value(props, "Effort", "Thinking"),
                "priority": props.get("Priority", {}).get("number"),
                "created": page.get("created_time", ""),
            }
        )
    projects.sort(key=lambda p: (p["priority"] is None, p["priority"] or 0, p["created"]))
    return projects


def fetch_page_text(block_id: str, depth: int = 0) -> str:
    """Concatenate the plain text of a page's blocks (recursing into nested blocks)."""
    if depth > 3:
        return ""
    lines, cursor = [], None
    while True:
        path = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        data = notion_request("GET", path)
        for block in data.get("results", []):
            btype = block["type"]
            payload = block.get(btype, {})
            text = rich_text_to_plain(payload.get("rich_text", []))
            prefix = {
                "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
                "bulleted_list_item": "- ", "numbered_list_item": "- ",
                "to_do": "- [ ] ", "quote": "> ",
            }.get(btype, "")
            if btype == "code":
                lines.append(f"```\n{text}\n```")
            elif text:
                lines.append(prefix + text)
            if block.get("has_children") and btype not in ("child_page", "child_database"):
                child = fetch_page_text(block["id"], depth + 1)
                if child:
                    lines.append(child)
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break
    return "\n".join(lines)


def set_title(page_id: str, title: str, prop: str = "Name") -> None:
    notion_request(
        "PATCH",
        f"/pages/{page_id}",
        {"properties": {prop: {"title": [{"text": {"content": title}}]}}},
    )


def add_comment(page_id: str, text: str) -> None:
    try:
        notion_request(
            "POST",
            "/comments",
            {"parent": {"page_id": page_id}, "rich_text": [{"text": {"content": text[:1900]}}]},
        )
    except Exception as e:  # comments are best-effort; never fail the run over them
        print(f"  (could not post Notion comment: {e})")
