"""Defaults, .env loading, and cfg() lookup.

Change any value in DEFAULTS, OR set the same key in .env next to this package
(see .env.example) — .env always wins if both are set.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = PACKAGE_DIR.parent  # holds .env, logs/, workspaces/, .autobot.lock

DEFAULTS = {
    # Where each project's code gets written: <this>\<project-slug>\
    "AUTOBOT_WORKSPACES": str(SCRIPT_DIR / "workspaces"),

    # The Notion database that holds one page per project (page content = prompt).
    "NOTION_DATABASE_ID": "10aefa04a0d14dc4add853782342b841",  # "Claude Projects" DB

    # Which agent runs a project when neither --backend nor the Notion row's
    # Backend column says otherwise: claude | opencode | custom
    "AUTOBOT_BACKEND": "opencode",

    # Default model. Leave empty to let the backend use its own default
    # (Claude Code's session default / OpenCode's configured default model).
    #   claude:   opus | sonnet | haiku | fable | a full model id
    #   opencode: provider/model, e.g. zai-coding-plan/glm-4.6 (run `opencode models`)
    "AUTOBOT_MODEL": "",

    # Effort / thinking level: default | low | medium | high | xhigh | max | ultracode
    # claude gets it natively via --effort; every other backend gets it as an
    # instruction prepended to the prompt (see backends.EFFORT_PREAMBLE).
    "AUTOBOT_EFFORT": "default",

    # Claude Code only: --permission-mode. bypassPermissions lets it work fully
    # unattended; acceptEdits is more conservative but can stall on Bash steps.
    "AUTOBOT_PERMISSION_MODE": "bypassPermissions",

    # Hard ceiling on a SINGLE project run, in minutes. Past this the run is
    # killed (whole process tree) and the project is marked FAILED, so one
    # stuck run can't block the queue forever.
    "AUTOBOT_TIMEOUT_MIN": "120",

    # --watch mode only: minutes between Notion checks while the queue is empty.
    "AUTOBOT_POLL_MIN": "30",

    # --watch mode only: minutes to wait before retrying when a backend reports
    # a usage/rate limit but no exact reset time could be parsed from the message.
    # (When a reset time IS parseable — Claude Code prints one — autobot sleeps
    # until exactly then instead.)
    "AUTOBOT_LIMIT_RETRY_MIN": "60",

    # Extra arguments appended to `opencode run`, e.g. "--agent build".
    "AUTOBOT_OPENCODE_ARGS": "",

    # Command template for the "custom" backend (OpenClaw, aider, codex, ...).
    # Placeholders: {prompt_file} {prompt} {stdin} {model} {effort} {workspace}
    # Example: AUTOBOT_CUSTOM_CMD=aider --yes-always --message-file {prompt_file}
    "AUTOBOT_CUSTOM_CMD": "",
}

_loaded = False


def _read_env_file(path: Path, only_prefix: str | None = None) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if only_prefix and not key.startswith(only_prefix):
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def load_env() -> None:
    """Read .env next to this package into os.environ (no overwrite).

    Convenience fallback: when this folder lives inside an autoclaude checkout
    (autoclaude/workspaces/autobot-opencode) and no NOTION_TOKEN was found,
    borrow the NOTION_* settings from autoclaude's own .env two levels up, so
    the token never has to be copied around.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    _read_env_file(SCRIPT_DIR / ".env")
    if not os.environ.get("NOTION_TOKEN"):
        _read_env_file(SCRIPT_DIR.parent.parent / ".env", only_prefix="NOTION_")


def cfg(key: str) -> str:
    return os.environ.get(key) or DEFAULTS.get(key, "")
