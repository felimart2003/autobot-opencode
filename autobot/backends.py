"""Agent backends: how to launch each coding agent and recognize its limit messages.

A backend answers three questions:
  1. command()      — what process do we run for this (model, effort, prompt)?
  2. wrap_prompt()  — how does the effort level reach the agent (native flag vs.
                      an instruction prepended to the prompt)?
  3. detect_limit() — did the output say we hit a usage/rate limit, and when
                      does it reset?

Prompts are delivered two ways:
  - claude reads the full prompt on stdin (native `claude -p` behavior).
  - opencode/custom get the full prompt written to AUTOBOT_PROMPT.md in the
    workspace, plus a one-line pointer message as the CLI argument. This avoids
    Windows command-line length limits and the .cmd-shim newline mangling that
    breaks multi-line arguments to npm-installed CLIs.
"""

from __future__ import annotations

import datetime as dt
import glob
import os
import re
import shlex
import shutil
from pathlib import Path

from .config import cfg

# Valid values for the effort/thinking level. "default" means "don't steer it".
EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max", "ultracode"}
EFFORT_CHOICES = ["default", "low", "medium", "high", "xhigh", "max", "ultracode"]

PROMPT_FILE_NAME = "AUTOBOT_PROMPT.md"

# ASCII on purpose: this string travels through npm .cmd shims on Windows.
POINTER_PROMPT = (
    f"Read the file {PROMPT_FILE_NAME} in the current directory. It contains your "
    "full task specification. Complete that task end to end, working in the "
    "current directory."
)

# For backends without a native effort flag, the level becomes an instruction
# prepended to the prompt.
EFFORT_PREAMBLE = {
    "low": "Effort level: LOW. Keep reasoning brief and build the simplest "
           "implementation that fully works.",
    "medium": "Effort level: MEDIUM. Think through the design briefly before "
              "implementing; don't gold-plate.",
    "high": "Effort level: HIGH. Plan before coding, consider edge cases, and "
            "verify the result actually runs before finishing.",
    "xhigh": "Effort level: VERY HIGH. Plan thoroughly, handle edge cases, test "
             "everything, and double-check your work before finishing.",
    "max": "Effort level: MAXIMUM. Design first, implement carefully, test end "
           "to end, then review your own work and fix everything you find "
           "before finishing.",
    "ultracode": "Effort level: MAXIMUM. Design first, implement carefully, test "
                 "end to end, then review your own work and fix everything you "
                 "find. Iterate until the result is genuinely production quality.",
}

# Claude Code's usage-limit message, e.g.:
#   "You've hit your session limit · resets 3:45pm"
#   "You've hit your weekly limit · resets Mon 12:00am"
CLAUDE_LIMIT_RE = re.compile(
    r"You'?ve hit your (?:session|weekly|Opus) limit.*?resets\s+([A-Za-z0-9:, ]+)",
    re.IGNORECASE,
)

# Provider-agnostic limit phrases (Z.AI quota windows, OpenRouter 429s, empty
# MiniMax/Moonshot credit balances, ...). Only checked against the TAIL of the
# output so a transcript that merely talks about rate limiting mid-run doesn't
# false-positive.
GENERIC_LIMIT_RE = re.compile(
    r"rate.?limit|too many requests|\b429\b|quota (?:exceeded|reached)|"
    r"usage limit|insufficient (?:credits?|balance|quota)|resource.?exhausted|"
    r"limit (?:reached|exceeded)",
    re.IGNORECASE,
)
GENERIC_LIMIT_TAIL = 3000

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_reset_time(text: str) -> float | None:
    """Turn a reset description ('3:45pm' or 'Mon 12:00am') into a future Unix
    timestamp (assumes local time). None if unparseable — callers fall back to
    a fixed retry interval."""
    m = re.search(r"(?:([A-Za-z]{3})[a-z]*\s+)?(\d{1,2}):(\d{2})\s*([ap]m)", text, re.IGNORECASE)
    if not m:
        return None
    wd_str, hh, mm, ampm = m.groups()
    hh, mm = int(hh), int(mm)
    if ampm.lower() == "pm" and hh != 12:
        hh += 12
    if ampm.lower() == "am" and hh == 12:
        hh = 0
    now = dt.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if wd_str:
        want = _WEEKDAYS.get(wd_str.lower()[:3])
        if want is None:
            return None
        target += dt.timedelta(days=(want - now.weekday()) % 7)
        if target <= now:
            target += dt.timedelta(days=7)
    elif target <= now:
        target += dt.timedelta(days=1)
    return target.timestamp()


class Backend:
    name = ""
    uses_prompt_file = False  # True: write prompt to AUTOBOT_PROMPT.md in the workspace

    def wrap_prompt(self, prompt: str, effort: str) -> str:
        pre = EFFORT_PREAMBLE.get(effort)
        return f"{pre}\n\n{prompt}" if pre else prompt

    def command(self, *, model: str | None, effort: str, prompt: str,
                prompt_file: Path | None, permission_mode: str,
                workspace: Path) -> tuple[list[str], str | None]:
        """Return (argv, stdin_text_or_None)."""
        raise NotImplementedError

    def detect_limit(self, output: str) -> tuple[bool, float | None]:
        """Return (limit_was_hit, reset_epoch_or_None)."""
        m = CLAUDE_LIMIT_RE.search(output)
        if m:
            return True, parse_reset_time(m.group(1))
        if GENERIC_LIMIT_RE.search(output[-GENERIC_LIMIT_TAIL:]):
            return True, None
        return False, None

    def find_binary(self) -> str:
        raise NotImplementedError

    def doctor(self) -> tuple[bool, str]:
        try:
            return True, self.find_binary()
        except RuntimeError as e:
            return False, str(e).splitlines()[0]


class ClaudeBackend(Backend):
    """Claude Code CLI. Effort is native (--effort), prompt goes in on stdin."""

    name = "claude"

    def wrap_prompt(self, prompt: str, effort: str) -> str:
        return prompt  # effort handled natively by --effort

    def find_binary(self) -> str:
        if os.environ.get("CLAUDE_BIN"):
            return os.environ["CLAUDE_BIN"]
        on_path = shutil.which("claude")
        if on_path:
            return on_path
        # CLI bundled with the Claude desktop app (versioned folders)
        bundled = sorted(
            glob.glob(os.path.expandvars(r"%APPDATA%\Claude\claude-code\*\claude.exe"))
        )
        if bundled:
            return bundled[-1]
        raise RuntimeError(
            "Could not find the claude CLI. Install it (npm install -g "
            "@anthropic-ai/claude-code) or set CLAUDE_BIN in .env."
        )

    def command(self, *, model, effort, prompt, prompt_file, permission_mode, workspace):
        cmd = [self.find_binary(), "-p", "--permission-mode", permission_mode]
        if model:
            cmd += ["--model", model]
        if effort in EFFORT_LEVELS:
            cmd += ["--effort", effort]
        return cmd, prompt

    def detect_limit(self, output):
        m = CLAUDE_LIMIT_RE.search(output)
        if m:
            return True, parse_reset_time(m.group(1))
        return False, None


class OpenCodeBackend(Backend):
    """OpenCode CLI (https://opencode.ai). Model is provider/model — e.g.
    zai-coding-plan/glm-4.6, openrouter/moonshotai/kimi-k2 — see `opencode models`.
    Provider auth is OpenCode's own (`opencode auth login` or provider env vars)."""

    name = "opencode"
    uses_prompt_file = True

    def find_binary(self) -> str:
        if os.environ.get("OPENCODE_BIN"):
            return os.environ["OPENCODE_BIN"]
        on_path = shutil.which("opencode")
        if on_path:
            return on_path
        raise RuntimeError(
            "Could not find the opencode CLI. Install it (npm install -g opencode-ai,"
            " or see https://opencode.ai/docs) or set OPENCODE_BIN in .env."
        )

    def command(self, *, model, effort, prompt, prompt_file, permission_mode, workspace):
        cmd = [self.find_binary(), "run"]
        if model:
            if "/" in model:
                cmd += ["--model", model]
            else:
                # A claude-style name (fable/opus/...) from a shared Notion DB —
                # not valid for opencode, which needs provider/model.
                print(f"  (model '{model}' is not a provider/model id - "
                      "letting opencode use its default model)")
        extra = cfg("AUTOBOT_OPENCODE_ARGS")
        if extra:
            cmd += shlex.split(extra)
        cmd.append(POINTER_PROMPT)
        return cmd, None


class CustomBackend(Backend):
    """Any CLI, via the AUTOBOT_CUSTOM_CMD template (OpenClaw, aider, codex, ...).

    Placeholders, substituted per argv token (no shell quoting involved):
      {prompt_file}  path to AUTOBOT_PROMPT.md holding the full prompt
      {prompt}       full prompt text inline as one argument
      {stdin}        standalone token: removed, prompt is piped to stdin instead
      {model} {effort} {workspace}
    """

    name = "custom"
    uses_prompt_file = True

    def find_binary(self) -> str:
        template = cfg("AUTOBOT_CUSTOM_CMD")
        if not template:
            raise RuntimeError(
                "Backend 'custom' needs AUTOBOT_CUSTOM_CMD in .env - a command "
                "template such as: aider --yes-always --message-file {prompt_file}"
            )
        return shlex.split(template, posix=False)[0].strip('"')

    def command(self, *, model, effort, prompt, prompt_file, permission_mode, workspace):
        template = cfg("AUTOBOT_CUSTOM_CMD")
        self.find_binary()  # raises with guidance if template is unset
        if not any(p in template for p in ("{prompt}", "{prompt_file}", "{stdin}")):
            raise RuntimeError(
                "AUTOBOT_CUSTOM_CMD must contain {prompt}, {prompt_file} or {stdin} "
                "so the project prompt actually reaches the agent."
            )
        # posix=False keeps Windows paths (backslashes) intact; strip the quotes
        # shlex leaves on quoted tokens.
        tokens = [t.strip('"') for t in shlex.split(template, posix=False)]
        cmd: list[str] = []
        stdin_text: str | None = None
        for tok in tokens:
            if tok == "{stdin}":
                stdin_text = prompt
                continue
            cmd.append(
                tok.replace("{prompt_file}", str(prompt_file))
                   .replace("{prompt}", prompt)
                   .replace("{model}", model or "")
                   .replace("{effort}", effort)
                   .replace("{workspace}", str(workspace))
            )
        return cmd, stdin_text

    def doctor(self) -> tuple[bool, str]:
        try:
            binary = self.find_binary()
        except RuntimeError as e:
            return False, str(e).splitlines()[0]
        resolved = shutil.which(binary) or binary
        if shutil.which(binary) or Path(binary).exists():
            return True, f"{resolved}  (from AUTOBOT_CUSTOM_CMD)"
        return False, f"AUTOBOT_CUSTOM_CMD is set but '{binary}' was not found on PATH"


BACKENDS: dict[str, Backend] = {
    b.name: b for b in (ClaudeBackend(), OpenCodeBackend(), CustomBackend())
}
_ALIASES = {"claude-code": "claude", "claudecode": "claude", "cc": "claude", "oc": "opencode"}


def get_backend(name: str) -> Backend:
    key = _ALIASES.get(name.lower(), name.lower())
    backend = BACKENDS.get(key)
    if backend is None:
        raise RuntimeError(
            f"Unknown backend '{name}' (valid: {', '.join(BACKENDS)}; "
            "set it via --backend, the Notion Backend column, or AUTOBOT_BACKEND)"
        )
    return backend
