# Agents

**Six agent CLIs share one layer: the same rules, core skills and coordination hooks. Claude Code does the work, the others review, take bulk jobs, or stand in when a quota runs out.**

`scripts/sync-agents.py` wires every agent except Claude Code (which `install.sh` links). Run it with `--check` first.
Outside agents are called through `scripts/second_opinion.py`, which applies `model-policy.json`, the sandbox and the fallback ladder.

| Agent | Rules | Skills | Hooks | Used for | Quirks |
|---|---|---|---|---|---|
| **Claude Code** (`claude`, a second account `cx`) | `~/.claude/CLAUDE.md` symlinks to `rules/CLAUDE.md` | `~/.claude/skills/` links to `skills/_core/`; the library loads on demand | Native, in `settings.json` (`examples/claude-settings.example.json`) | Main worker (Opus 5.5 low); text people read, reviews and final judging (Opus 5.5 high); coding a test decides (Sonnet 5.5 low, or Haiku 5.5 low for short jobs); hardest coding (Fable 5.1) | Accounts share memory, not skills or settings. Mods in `mods/` load through `CLAUDE_CODE_PLUGIN_DIRS`, which `sync-agents.py --only ui` writes. Cross-account messaging needs `session_mirror.py` running. Self-reset (`reset.py`) works only in kitty. Every account auto-compacts at 250k |
| **Codex** (`codex`) | Generated `~/.codex/AGENTS.md` = `agents/codex/DELTA.md` + rules; also `~/AGENTS.md` | `~/.codex/skills/`, commands in `~/.codex/prompts/` | `~/.codex/hooks.json` -> `codex_hook.py` -> `agent_hook.py` | Reviews every code change, on the diff (`second_opinion.py --review`; GPT-6 Astra, medium effort, high for client work and risky changes); codes with GPT-6.1 Sol when Claude quota is tight; the only outside model allowed on confidential folders | **Won't run a changed `hooks.json` until you launch `codex` once interactively and approve it; until then `codex exec` hangs.** No `/effort`: use `model_reasoning_effort`. Writes no session registry, so `agent_hook.py` writes one for it. When it is out of quota, Grok 4.7 reviews on personal folders and an Opus 5.5 high subagent on confidential ones |
| **OpenCode** (`opencode`) | Generated `AGENTS.md` = `agents/opencode/DELTA.md` + rules | `~/.config/opencode/skills/`, `commands/` | Plugin `shared-agent-layer.js` | Second opinions and writing second drafts from GLM, Qwen, Grok or MiniMax on OpenRouter (or a local Qwen in LM Studio); open and personal folders | Never used for DeepSeek or Kimi (they have their own CLIs). A tool call the plugin blocks is a deny |
| **dsh** (DeepSeek's CLI) | Generated `AGENTS.md` = `agents/dsh/DELTA.md` + rules | `~/.dsh/skills/` | `agents/dsh/hooks.json`, inserted into each dsh profile | Default bulk worker and China worker (DeepSeek V4 Flash), always followed by a review; extra review pass on open and personal folders; cheap image input. Never for factual prose | **Hooks only fire when it may write (`second_opinion.py --write`).** In the read-only sandbox they are skipped, which is harmless since nothing is edited |
| **kimi** (Kimi Code CLI) | Generated `AGENTS.md` = `agents/kimi/DELTA.md` + rules | `~/.kimi-code/skills/` | Managed `[[hooks]]` block in `~/.kimi-code/config.toml` | Backup when DeepSeek is down (Kimi K3) | **`kimi -p` runs every tool without asking, so only call it through `second_opinion.py`.** Paid per call. It drops SessionStart output, so `agent_hook.py` resends that context later |
| **Grok Build** (`grok`) | Reads `~/.claude/CLAUDE.md` itself (Claude compatibility), plus `agents/grok/DELTA.md` linked as `~/.grok/rules/shared-agent-layer.md` | Reads `~/.claude/skills/` itself | Managed block in `~/.grok/config.toml` calling `agent_hook.py --agent grok` | Extra review pass on personal folders; stands in for Codex there when Codex is out of quota; plan quota | **Claude-compat hooks are off** (`[compat.claude] hooks = false`), or grok would run the Claude hooks as if it were Claude. It drops session and prompt hook output, so that context arrives with its first tool call. Personal folders only |

## Common to all

- **Claims, queues and guardrails are shared.** A session of any agent can block, or be blocked by, any other on the same file. `claims.py list` labels each one.
- **Memory is recalled, not written.** Outside agents get matching memories per prompt but keep none; durable findings go in the project's `CLAUDE.md`.
- **When an outside agent reviews, it reviews.** Findings only, no re-planning.
- **Policy by folder.** Confidential: Claude and Codex only. Open and personal: DeepSeek, Kimi, OpenCode too. Grok and Gemini (`agy`): personal only.
- **After changing rules, a core skill, a command or any hook config**, run `python3 scripts/sync-agents.py` (then approve Codex's hooks once).

## Routes that are not synced agents

`second_opinion.py` also offers these. `agy` gets no rules or hooks; `codex:<model>` is Codex with a set model, so Codex's rules and hooks apply.

| Route | What it is | Used for |
|---|---|---|
| `agy:<model>` | Google Antigravity CLI, e.g. `agy:gemini-3.8-flash-high` | Free quick drafts and reads on personal folders (Gemini 3.8 Flash). Not a fact-checker: reviewing a finished report, 0 of its 4 findings held (6 Oct) |
| `codex:gpt-6.1-sol` | The Codex CLI with the model set | Coding on personal and open folders when Claude quota is tight, in a worktree with `--write`, then a review pass. Not a reviewer (3 of 17 bugs) |

The Gemini CLI is deprecated and not used (14 Oct 2026).
