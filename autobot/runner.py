"""Run one project through its backend inside a per-project workspace folder."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path

from .backends import PROMPT_FILE_NAME, Backend, get_backend
from .config import SCRIPT_DIR, cfg


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return slug[:60] or "project"


def resolve(project: dict, args) -> tuple[Backend, str | None, str]:
    """(backend, model, effort) with priority: command line > Notion row > .env default."""
    backend_name = args.backend or project.get("backend") or cfg("AUTOBOT_BACKEND")
    backend = get_backend(backend_name)
    model = args.model or project.get("model") or cfg("AUTOBOT_MODEL") or None
    effort = (args.effort or project.get("effort") or cfg("AUTOBOT_EFFORT") or "default").lower()
    return backend, model, effort


def build_full_prompt(project: dict, prompt: str, workspace: Path) -> str:
    return (
        f"You are working autonomously in the project folder {workspace} (your current "
        "directory). Build the project described below. Create all files here, keep the "
        "code runnable, and finish with a README.md explaining how to run it. When done, "
        "print a short summary of what you built.\n\n"
        f"# Project: {project['title']}\n\n{prompt}"
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the agent and everything it spawned. On Windows, npm .cmd shims mean
    the direct child is cmd.exe while the real agent (node) is a grandchild, so
    a plain kill() would orphan it — taskkill /T takes the whole tree."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.kill()


def run_project(project: dict, prompt: str, args) -> tuple[str, str, float | None]:
    """Run the project. Returns (status, output, limit_reset_epoch) where status
    is one of "ok", "failed", "limit"."""
    backend, model, effort = resolve(project, args)

    workspace = Path(cfg("AUTOBOT_WORKSPACES")) / slugify(project["title"])
    workspace.mkdir(parents=True, exist_ok=True)
    log_dir = SCRIPT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(project['title'])}.log"

    full_prompt = backend.wrap_prompt(build_full_prompt(project, prompt, workspace), effort)
    prompt_file = None
    if backend.uses_prompt_file:
        prompt_file = workspace / PROMPT_FILE_NAME
        prompt_file.write_text(full_prompt, encoding="utf-8")

    cmd, stdin_text = backend.command(
        model=model, effort=effort, prompt=full_prompt, prompt_file=prompt_file,
        permission_mode=args.permission_mode, workspace=workspace,
    )

    print(f"  backend={backend.name} model={model or '(backend default)'} effort={effort}")
    print(f"  workspace={workspace}")
    print(f"  log: {log_file}")

    timeout = int(cfg("AUTOBOT_TIMEOUT_MIN")) * 60
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=workspace,
        env=os.environ.copy(),
    )
    try:
        out, err = proc.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=15)
        except Exception:
            out, err = "", ""
        log_file.write_text(
            f"$ {' '.join(cmd)}\n\nTIMED OUT after {timeout // 60} min\n\n"
            f"=== PARTIAL OUTPUT ===\n{out or ''}\n{err or ''}",
            encoding="utf-8",
        )
        return "failed", f"Timed out after {timeout // 60} minutes.", None

    output = (out or "") + (f"\n--- stderr ---\n{err}" if err else "")
    log_file.write_text(
        f"$ {' '.join(cmd)}\n\n{full_prompt}\n\n=== OUTPUT ===\n{output}",
        encoding="utf-8",
    )

    hit, reset_epoch = backend.detect_limit(output)
    if hit:
        return "limit", output, reset_epoch
    if proc.returncode != 0:
        return "failed", output, None
    return "ok", output, None
