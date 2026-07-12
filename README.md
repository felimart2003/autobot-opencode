# autobot-opencode

Queue coding projects in Notion, then let **any** autonomous coding agent build them —
Claude Code, [OpenCode](https://opencode.ai) (Z.AI GLM, Kimi, MiniMax, OpenRouter, …),
or any other CLI you can write as a one-line command template (OpenClaw, aider, codex, …).

It's the backend-agnostic successor to autoclaude and shares its queue contract, so both
can point at the **same** Notion database:

- Each page in the Notion **Claude Projects** database is one project; the page *content*
  is the prompt fed to the agent.
- Status lives in the title: no marker = pending, `🔄` = running, `✅` = done, `❌` = failed.
  Remove the emoji from a title to re-queue that project.
- `--watch` runs pending projects back-to-back, sleeps through usage-limit windows
  (Claude's 5-hour token resets, Z.AI quota windows, 429s, …), and polls for new projects.

Zero dependencies — Python 3.10+ stdlib only.

## Quick start

1. **Notion token** — create an internal integration at
   <https://www.notion.so/profile/integrations>, copy the secret, and share the projects
   database with it (database `•••` menu → **Connections**). Then
   `copy .env.example .env` and set `NOTION_TOKEN=...`.

   > Shortcut: if this folder sits inside an autoclaude checkout
   > (`autoclaude/workspaces/autobot-opencode`), autobot automatically borrows
   > `NOTION_TOKEN` from autoclaude's `.env` — zero setup.

2. **Install at least one backend** (see the table below). For OpenCode:
   `npm install -g opencode-ai`, then `opencode auth login` to connect a provider
   (Z.AI, OpenRouter, Moonshot, MiniMax, Anthropic, …).

3. **Check everything:**

   ```bat
   python -m autobot --doctor
   ```

4. **Run:**

   ```bat
   python -m autobot --list        :: show pending projects in run order
   python -m autobot --dry-run     :: show what would run (backend/model/effort + prompt)
   python -m autobot               :: run the next pending project once
   python -m autobot --watch       :: keep going: run projects back-to-back, sleep
                                   ::   through token/quota resets, poll for new work
   ```

   Or double-click `start_autobot.bat` (watch mode).

## Backends

| Backend | What it runs | Model format | Effort handling |
|---|---|---|---|
| `claude` | Claude Code CLI (`claude -p`) | `opus` `sonnet` `haiku` `fable` or a full model id | Native `--effort` flag (`low`…`ultracode`) |
| `opencode` | `opencode run` | `provider/model` — run `opencode models` for the list | Instruction prepended to the prompt |
| `custom` | Any CLI, via the `AUTOBOT_CUSTOM_CMD` template | whatever your tool takes (`{model}` placeholder) | Instruction prepended to the prompt |

### OpenCode model examples

```
zai-coding-plan/glm-4.6            Z.AI GLM coding plan (subscription quota)
openrouter/moonshotai/kimi-k2      Kimi K2 via OpenRouter
openrouter/minimax/minimax-m2      MiniMax via OpenRouter
anthropic/claude-sonnet-4-5        Anthropic API through OpenCode
```

Provider auth is OpenCode's own: `opencode auth login`, or put the provider API key
(`ZHIPUAI_API_KEY`, `OPENROUTER_API_KEY`, …) in `.env` — every key in `.env` is exported
to the agent subprocess.

### Custom backend (OpenClaw, aider, codex, anything)

Set a command template in `.env`. Placeholders: `{prompt_file}` (path to
`AUTOBOT_PROMPT.md` containing the full prompt), `{prompt}` (prompt inline as one
argument), `{stdin}` (standalone token: prompt is piped to stdin instead), `{model}`,
`{effort}`, `{workspace}`.

```ini
AUTOBOT_CUSTOM_CMD=aider --yes-always --message-file {prompt_file}
AUTOBOT_CUSTOM_CMD=codex exec --full-auto {prompt}
AUTOBOT_CUSTOM_CMD=openclaw agent --message {prompt}      ; check your openclaw version's flags
```

The command runs with the project workspace as its working directory. Long prompts are
always written to `AUTOBOT_PROMPT.md` in the workspace, so prefer `{prompt_file}` — it
sidesteps Windows command-line length limits and npm `.cmd`-shim newline mangling.

## Choosing backend, model, and effort

Priority order: **command line > Notion page property > `.env` default**.

- **Per project (in Notion):** add these columns to the database row —
  `Backend` (select: claude / opencode / custom), `Model` (select or text — for opencode
  use `provider/model`), `Effort` (select: low / medium / high / xhigh / max / ultracode;
  the legacy `Thinking` column is also read), `Priority` (number, lower = sooner).
- **Per run (command line):** `--backend opencode --model zai-coding-plan/glm-4.6 --effort high`
- **Default:** `AUTOBOT_BACKEND` / `AUTOBOT_MODEL` / `AUTOBOT_EFFORT` in `.env`.

For `claude`, effort maps to Claude Code's native `--effort` flag. For every other
backend the level becomes an explicit instruction prepended to the prompt (e.g. *"Effort
level: VERY HIGH. Plan thoroughly, handle edge cases, test everything…"*). If a provider
supports native reasoning-effort settings, configure them in the tool itself (e.g.
OpenCode's `opencode.json` model options) — autobot won't fight it.

Note for shared databases: if a row's `Model` is a claude-style name (like `fable`) but
the run uses the opencode backend, autobot ignores it and lets OpenCode use its own
default model instead of crashing on an invalid id.

## Token resets, limits, and failures

- **Claude Code:** when the output contains `You've hit your session limit · resets 3:45pm`
  (or the weekly/Opus variants), the project goes back to *pending* and `--watch` sleeps
  until that exact time (+2 min buffer).
- **Everything else:** rate-limit/quota phrases (`429`, `rate limit`, `quota exceeded`,
  `insufficient credits`, …) near the end of the output also re-queue the project, and
  `--watch` retries after `AUTOBOT_LIMIT_RETRY_MIN` (default 60 min) since those tools
  don't print a parseable reset time.
- A run that exceeds `AUTOBOT_TIMEOUT_MIN` (default 120) is killed — the **whole process
  tree**, including node grandchildren behind npm `.cmd` shims — and marked ❌ so one stuck
  run can't block the queue.
- Only one instance runs at a time (`.autobot.lock` with the live PID); a second launch
  exits immediately instead of racing the first.

## Where things go

- Code is written to `workspaces\<project-slug>\` (one folder per project) —
  configurable via `AUTOBOT_WORKSPACES`.
- Full transcripts go to `logs\`.
- A summary of each run is posted as a **comment on the Notion page**.

## Configuration reference

All set in `.env` (see `.env.example`) or left alone to use the built-in default from
`autobot/config.py`. To override a default, **uncomment the line** — a commented line is
ignored no matter what follows the `#`.

| Variable | Default | What it does |
|---|---|---|
| `NOTION_TOKEN` | *(required)* | Notion internal integration secret (auto-borrowed from autoclaude's `.env` when nested inside it). |
| `NOTION_DATABASE_ID` | `10aefa04…` | ID of the projects database. |
| `AUTOBOT_BACKEND` | `opencode` | Default backend: `claude` \| `opencode` \| `custom`. |
| `AUTOBOT_MODEL` | *(backend default)* | Default model when Notion row and `--model` don't set one. |
| `AUTOBOT_EFFORT` | `default` | Effort level: `default` `low` `medium` `high` `xhigh` `max` `ultracode`. |
| `AUTOBOT_PERMISSION_MODE` | `bypassPermissions` | Claude Code `--permission-mode`. |
| `AUTOBOT_TIMEOUT_MIN` | `120` | Max minutes per run before kill + ❌. |
| `AUTOBOT_POLL_MIN` | `30` | `--watch`: minutes between Notion checks while the queue is empty. |
| `AUTOBOT_LIMIT_RETRY_MIN` | `60` | `--watch`: retry delay after a limit with no parseable reset time. |
| `AUTOBOT_OPENCODE_ARGS` | *(empty)* | Extra args appended to `opencode run`. |
| `AUTOBOT_CUSTOM_CMD` | *(empty)* | Command template for the `custom` backend. |
| `AUTOBOT_WORKSPACES` | `<here>\workspaces` | Where project code is written. |
| `CLAUDE_BIN` / `OPENCODE_BIN` | auto-detected | Full binary paths, only if auto-detect fails. |

## Safety note

Agents run **unattended with permission prompts bypassed** (Claude Code
`bypassPermissions`; `opencode run` executes tools non-interactively) so they can install
packages, run commands, and write files inside the workspace. Only queue prompts you'd be
comfortable running yourself, and keep `AUTOBOT_WORKSPACES` pointed somewhere disposable.

## Run it automatically on login (optional)

```powershell
schtasks /Create /TN "autobot" /SC ONLOGON /TR "\"C:\path\to\autobot-opencode\start_autobot.bat\"" /F
```

## Monetization

Thinking about charging for this? See [MONETIZATION.md](MONETIZATION.md) for an honest
breakdown of the $1/month idea, the reverse-engineering question, and what actually
impresses hiring managers.
#   a u t o b o t - o p e n c o d e  
 