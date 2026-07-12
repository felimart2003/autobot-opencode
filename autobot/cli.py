"""Command-line interface: --list, --dry-run, --doctor, single run, --watch."""

from __future__ import annotations

import argparse
import atexit
import datetime as dt
import os
import subprocess
import sys
import time

from . import __version__
from .backends import BACKENDS, EFFORT_CHOICES
from .config import SCRIPT_DIR, cfg, load_env
from .notion import (
    MARK_DONE, MARK_FAILED, MARK_RUNNING, add_comment, fetch_page_text,
    fetch_pending_projects, notion_request, rich_text_to_plain, set_title,
)
from .runner import resolve, run_project

LOCK_FILE = SCRIPT_DIR / ".autobot.lock"


# ------------------------------ single instance ------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True  # can't check -> assume alive, safer to block than double-run


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except OSError:
        pass


def acquire_lock() -> None:
    """Refuse to start a second instance — only one autobot ever runs projects
    at a time, even if the script is started twice."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid and _pid_alive(pid):
            sys.exit(
                f"Another autobot is already running (PID {pid}). If that process "
                f"actually died without cleaning up, delete {LOCK_FILE} and retry."
            )
        # stale lock left by a crashed/killed run; safe to reclaim
    LOCK_FILE.write_text(str(os.getpid()))
    atexit.register(_release_lock)


# --------------------------------- commands ----------------------------------

def run_one(args: argparse.Namespace) -> str:
    """Run the next pending project. Returns "ok", "failed", "limit", or "empty"."""
    projects = fetch_pending_projects()
    if args.project:
        projects = [p for p in projects if args.project.lower() in p["title"].lower()]
    if not projects:
        print("No pending projects in Notion.")
        return "empty"

    project = projects[0]
    print(f"\n=== {project['title']} ===")
    prompt = fetch_page_text(project["id"]).strip()
    if not prompt:
        print("  Page is empty - marking failed.")
        set_title(project["id"], f"{MARK_FAILED} {project['title']}", project["title_prop"])
        add_comment(project["id"], "autobot: page has no content to use as a prompt.")
        return "failed"

    if args.dry_run:
        backend, model, effort = resolve(project, args)
        print(f"  would run: backend={backend.name} "
              f"model={model or '(backend default)'} effort={effort}")
        print(f"--- prompt ---\n{prompt}\n--- end (dry run, nothing executed) ---")
        return "ok"

    set_title(project["id"], f"{MARK_RUNNING} {project['title']}", project["title_prop"])
    started = time.time()
    try:
        status, output, reset_epoch = run_project(project, prompt, args)
    except BaseException:
        # un-mark so the project can be retried
        set_title(project["id"], project["title"], project["title_prop"])
        raise

    minutes = (time.time() - started) / 60
    tail = output.strip()[-1500:]
    if status == "ok":
        set_title(project["id"], f"{MARK_DONE} {project['title']}", project["title_prop"])
        add_comment(project["id"], f"autobot: completed in {minutes:.0f} min.\n\n{tail}")
        print(f"  done in {minutes:.0f} min")
    elif status == "limit":
        # back to pending; --watch retries after the reset
        set_title(project["id"], project["title"], project["title_prop"])
        when = (
            dt.datetime.fromtimestamp(reset_epoch).strftime("%H:%M") if reset_epoch else "unknown"
        )
        print(f"  usage limit hit; resets at {when}")
        args._reset_epoch = reset_epoch
    else:
        set_title(project["id"], f"{MARK_FAILED} {project['title']}", project["title_prop"])
        add_comment(project["id"], f"autobot: FAILED after {minutes:.0f} min.\n\n{tail}")
        print(f"  FAILED after {minutes:.0f} min (see log)")
    return status


def watch(args: argparse.Namespace) -> None:
    poll = int(cfg("AUTOBOT_POLL_MIN")) * 60
    limit_retry = int(cfg("AUTOBOT_LIMIT_RETRY_MIN")) * 60
    runs = 0
    while True:
        status = run_one(args)
        if status in ("ok", "failed"):
            runs += 1
            if args.max_runs and runs >= args.max_runs:
                print(f"Reached --max-runs {args.max_runs}, stopping.")
                return
            continue
        if status == "limit":
            reset = getattr(args, "_reset_epoch", None)
            sleep_s = max(
                120,
                min((reset - time.time()) + 120 if reset else limit_retry, 6 * 3600),
            )
            print(f"Sleeping {sleep_s / 60:.0f} min until tokens reset...")
            time.sleep(sleep_s)
            continue
        # empty queue
        print(f"Checking again in {poll // 60} min (Ctrl+C to stop).")
        time.sleep(poll)


def list_projects(args: argparse.Namespace) -> None:
    print(f"Workspaces dir  : {cfg('AUTOBOT_WORKSPACES')}")
    print(f"Default backend : {cfg('AUTOBOT_BACKEND')}  "
          f"(model: {cfg('AUTOBOT_MODEL') or 'backend default'}, "
          f"effort: {cfg('AUTOBOT_EFFORT')})")
    print()
    projects = fetch_pending_projects()
    if not projects:
        print("No pending projects.")
        return
    print(f"{len(projects)} pending project(s), in run order:")
    for i, p in enumerate(projects, 1):
        extras = ", ".join(
            f"{k}={v}" for k, v in
            [("backend", p["backend"]), ("model", p["model"]),
             ("effort", p["effort"]), ("priority", p["priority"])]
            if v is not None
        )
        print(f"  {i}. {p['title']}" + (f"  ({extras})" if extras else ""))


def doctor() -> None:
    """Check Notion access and every backend; exit 1 if the default backend or
    Notion is broken (missing optional backends are just warnings)."""
    ok = True
    default_backend = cfg("AUTOBOT_BACKEND").lower()
    print(f"autobot {__version__} on Python {sys.version.split()[0]} ({sys.platform})")
    print(f"config dir      : {SCRIPT_DIR}")
    print(f"workspaces dir  : {cfg('AUTOBOT_WORKSPACES')}")
    print(f"default backend : {default_backend}  "
          f"(model: {cfg('AUTOBOT_MODEL') or 'backend default'}, "
          f"effort: {cfg('AUTOBOT_EFFORT')})")
    print()

    if os.environ.get("NOTION_TOKEN"):
        print("[OK] NOTION_TOKEN is set")
        try:
            db = notion_request("GET", f"/databases/{cfg('NOTION_DATABASE_ID')}")
            name = rich_text_to_plain(db.get("title", [])) or cfg("NOTION_DATABASE_ID")
            print(f'[OK] Notion database reachable: "{name}"')
        except Exception as e:
            print(f"[!!] Notion database not reachable: {e}")
            ok = False
    else:
        print("[!!] NOTION_TOKEN is not set (put it in .env - see .env.example)")
        ok = False

    for name, backend in BACKENDS.items():
        good, message = backend.doctor()
        tag = "[OK]" if good else ("[!!]" if name == default_backend else "[--]")
        print(f"{tag} backend {name:<9}: {message}")
        if not good and name == default_backend:
            ok = False

    print()
    print("All good - try: python -m autobot --list" if ok else
          "Fix the [!!] lines above, then re-run --doctor.")
    sys.exit(0 if ok else 1)


def main() -> None:
    # Keep emoji status markers printable even when output is piped/redirected
    # (Windows consoles otherwise fall back to a legacy codepage).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    load_env()
    parser = argparse.ArgumentParser(
        prog="autobot",
        description="Run coding agents (Claude Code / OpenCode / any CLI) on "
                    "projects queued in a Notion database.",
    )
    parser.add_argument("--backend", choices=sorted(BACKENDS),
                        help="agent to use (overrides Notion + default)")
    parser.add_argument("--model",
                        help="model (claude: opus|sonnet|haiku|fable; opencode: "
                             "provider/model, e.g. zai-coding-plan/glm-4.6)")
    parser.add_argument("--effort", choices=EFFORT_CHOICES,
                        help="effort/thinking level (overrides Notion + default)")
    parser.add_argument("--permission-mode", default=cfg("AUTOBOT_PERMISSION_MODE"),
                        help="Claude Code permission mode (default: %(default)s)")
    parser.add_argument("--project", help="run the project whose title contains this text")
    parser.add_argument("--list", action="store_true", help="list pending projects and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would run (backend/model/effort + prompt), change nothing")
    parser.add_argument("--doctor", action="store_true",
                        help="check Notion access and backend installs, then exit")
    parser.add_argument("--watch", action="store_true",
                        help="keep running projects; sleep through token resets")
    parser.add_argument("--max-runs", type=int, default=0,
                        help="in --watch mode, stop after N completed/failed runs")
    parser.add_argument("--version", action="version", version=f"autobot {__version__}")
    args = parser.parse_args()

    try:
        if args.doctor:
            doctor()
        elif args.list:
            list_projects(args)
        elif args.watch:
            acquire_lock()
            try:
                watch(args)
            except KeyboardInterrupt:
                print("\nStopped.")
        else:
            if not args.dry_run:
                acquire_lock()
            run_one(args)
    except RuntimeError as e:
        sys.exit(f"error: {e}")
