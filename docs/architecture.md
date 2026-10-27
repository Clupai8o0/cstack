# Architecture

**One folder holds the rules, hooks, skills and mods. Every agent links to it. Hooks coordinate sessions through small JSON files, which a GUI can read too.**

## Layout at runtime

```mermaid
flowchart LR
  subgraph home["$CLUPAI_HOME (this repo)"]
    R[rules/CLAUDE.md]
    D[agents/*/DELTA.md]
    H[hooks/*.py]
    S[skills/_core/*]
    M[mods/*]
    P[model-policy.json<br/>guardrails.json]
  end
  SY[scripts/sync-agents.py]
  R --> SY
  D --> SY
  S --> SY
  M --> SY
  SY -->|AGENTS.md, skills, hooks| CX[Codex]
  SY --> OC[OpenCode plugin]
  SY --> DS[dsh]
  SY --> KM[kimi]
  SY -->|DELTA.md, config hooks| GK[grok]
  R -->|symlink via install.sh| CC[Claude Code accounts]
  SY -->|"--ui: CLAUDE_CODE_PLUGIN_DIRS, statusline, reset and alert hooks"| CC
  H -.hooks.-> CC
  H -.agent_hook.py.-> CX & OC & DS & KM & GK
  SO[scripts/second_opinion.py] -->|policy check, sandbox, fallback| CX & DS & KM & OC & GK
  P --> SO
  ST[(shared state JSON)]
  H --> ST
  MC[MonoCode fork] -->|"claims.py list --json, stacks.py list --json"| ST
  MC -->|location.json| AL[hooks/alerts.py]
```

## Shared state

| File | Written by | Holds |
|---|---|---|
| `<git common dir>/claude-claims.json` | `claims.py` | who is editing which file, status notes |
| `<git common dir>/claude-claims-history.jsonl` | `claims.py` | every note, release and session end, with times and files edited |
| `~/.local/state/claude-claims/` | `claims.py`, `queues.py`, `stacks.py` | queue lines, per-session index, guardrail acks, stack leases (`stacks.json`), reaper log |
| `$CLUPAI_HOME/guardrails.json` | `guardrails.py learn` | warn/stop/queue/deny rules learned from failures |
| `$CLUPAI_HOME/model-policy.json` | you | which outside models may see which folders |
| `$CLUPAI_HOME/stacks.json`, `alerts.json` | you (optional) | stack definitions; alert settings that override the defaults |
| `~/.claude*/projects/*/memory/` | Claude Code | memories; `memory_recall.py` reads all accounts |
| `<config dir>/sessions/` | Claude Code, `session_mirror.py` | live sessions; copied across accounts so `SendMessage` reaches them |
| `~/.local/state/claude-alerts/` | `alerts.py` | open alerts, the off switch, a log |
| `~/.local/state/claude-reset/` | `reset.py` | queued context resets and their log |
| `~/.local/state/monocode-fork/location.json` | the MonoCode fork, every minute while it runs | whether alerts may ring at the current place; `alerts.py` reads it |

## Hooks

| Hook | Event | What it does |
|---|---|---|
| `claims.py` | PreToolUse, SessionStart, UserPromptSubmit, SessionEnd, PostToolUseFailure | Claims files per session; blocks same-worktree edits; runs guardrails and queues; nags for a status note; suggests a guardrail after a risky command fails |
| `queues.py` | called by guardrails, or by hand | One session at a time on a shared target such as a staging deploy |
| `guardrails.py` | called by `claims.py pretool` | Checks each command and edit against learned rules |
| `memory_guard.py` | PreToolUse, SessionStart | Blocks new agents and heavy commands when RAM or swap is low |
| `memory_recall.py` | SessionStart, UserPromptSubmit | Adds only the memories that match this prompt |
| `effort_gate.py` | UserPromptSubmit | Makes the model state the effort a task needs; early on, asks you to change it |
| `reset.py` | Stop, SessionStart (clear, compact) | Types a `/clear` or `/compact` the agent asked for into its kitty window, then loads the handoff |
| `alerts.py` | Stop, Notification, UserPromptSubmit, PostToolUse, SessionEnd | Done and needs-you sounds and notifications; types `/remote-control` after 5 min on an unanswered question |
| `stacks.py` | by hand; launchd `reap` every 10 min | Leases shared Docker stacks and devices; the reaper stops what nobody leases |
| `session_mirror.py` | launchd every 15 s | Copies session entries between Claude accounts |
| `agent_hook.py` | every event, non-Claude agents | Adapter so Codex, OpenCode, dsh, kimi and Grok Build run the same hooks |
| `codex_hook.py` | Codex | Thin shim to `agent_hook.py` |

`install.sh --settings` merges the Claude hook rows from `examples/claude-settings.example.json`. `sync-agents.py --ui`
adds the `reset.py` and `alerts.py` rows too, and never removes or reorders existing ones.

## Mods

- A mod is a Claude Code plugin (pane, band, tool, slash command) in `mods/<name>/` with a `.claude-plugin/plugin.json`.
- `sync-agents.py --ui` lists every mod folder in `CLAUDE_CODE_PLUGIN_DIRS` in each Claude account's `settings.json`
  env, so it loads in every session. A folder holding an `OPT-IN` file is left out; with no mods left the key is removed.
- `side-checklist` is the one shipped: a pane the model fills through its `checklist` tool and you tick off.

## Readers of the shared state

The [MonoCode fork](monocode.md) shows this state in a desktop GUI. Its only writes are `location.json` and a Stop you click.

| It reads | For |
|---|---|
| `claims.py list --json DIR` | a tag on each file another session is editing |
| `stacks.py list --json` | a stacks panel with who holds each stack; its Stop button runs `stacks.py stop NAME` |
| the `Close:` line at the end of a reply (on-the-go output style) | Safe, Handover or Not safe badges |

It writes `location.json`, and `alerts.py` goes silent when that file says `ring=false`.

## Design choices

- **Symlinks, not copies.** One edit reaches every agent. `sync-agents.py --check` shows drift.
- **Fail open.** A broken hook never blocks work, except a deliberate deny. `claims.py closeout` is the exception
  the other way: when it cannot check, it does not report clear.
- **Files, not a server.** State is JSON with file locks. Nothing to run or keep alive.
- **Read-only JSON for other tools.** `claims.py list --json` takes no lock and writes nothing back, so a GUI polling
  it cannot block an edit.
- **Missing signal means the old behaviour.** With MonoCode closed (no `location.json`, or one older than 10 min),
  alerts ring as usual.
- **Never type into a dialog.** `alerts.py` types `/remote-control` only at an empty input box; for a permission
  prompt or dialog it alerts again instead.
- **Policy by folder.** The script decides which outside models are allowed from `--cwd`, not the caller.
- **Reviews see the diff.** `second_opinion.py --review` puts the git diff in the prompt with a findings-only brief,
  so the reviewer does not explore the repo.
- **Grok Build reads Claude's files itself.** It loads `~/.claude/CLAUDE.md` and skills through its Claude compatibility, so
  it gets only `agents/grok/DELTA.md` (linked as `~/.grok/rules/`) and a hooks block in `~/.grok/config.toml`.
- **Opt out a folder with `.sync-agents-skip`.** `sync-agents.py --repos` links `AGENTS.md` to each repo's `CLAUDE.md`;
  a folder with this empty file is skipped. `rules/` carries one because its `CLAUDE.md` is a template, not a briefing.
- **Public-copy safety.** Claude settings changes (statusline, theme, env, reset and alert hooks) need `--ui`, repo
  links need `--repos`, and backups are timestamped.
- **macOS first.** The sandbox for outside CLIs uses `sandbox-exec`, `memory_guard.py` reads macOS memory stats, and
  `alerts.py` uses macOS sounds and kitty notifications (osascript outside kitty).
