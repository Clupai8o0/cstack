# Global agent rules (template)

This file is the global `CLAUDE.md` for every Claude Code account on this machine, and the base of the
`AGENTS.md` that `scripts/sync-agents.py` generates for Codex, OpenCode, dsh, kimi and Grok Build.
Its home is `$CLUPAI_HOME/rules/CLAUDE.md`. `~/.claude/CLAUDE.md` is a symlink to it. Edit it here.

Lines marked **Example:** are one person's setup. Replace them with yours or delete them.
The last section, "Owner preferences", is taste, not system: edit it freely.

## Many sessions, one brain

Several agent sessions often run on the same projects at the same time. They share auto-memory (`hooks/memory_recall.py` links a second account's memory folders to
the main account's at session start, merging their files), but NOT per-account skills or settings, and outside
models have no auto-memory. Anything they all need must be written somewhere they can all read.

**Example:** two Claude Code accounts on one Mac: `claude` (main, `~/.claude`) and `cx` (second login,
`~/.claude-exec`, the only second-account folder the scripts support), plus Codex, OpenCode, dsh, kimi and
Grok Build (`grok`, plan quota, personal folders only).

- **Durable learnings never live only in auto-memory.** Write them where the next session will read them:
  - about one project: that project's `CLAUDE.md` (or a doc it links to)
  - about how you work, tools, or more than one project: your shared notes folder, linked from an index
- **Handoffs between sessions go in the project**, e.g. `<project>/.claude/handoff.md`, not in chat and not
  in account memory. Read it at the start of work on that project.
- **Skills:**
  - core skills, installed in every account: `$CLUPAI_HOME/skills/_core/`, symlinked in
  - everything else: your library `$CLUPAI_HOME/skills/<category>/`, loaded on demand with the `vault-skills` skill
    (index: `$CLUPAI_HOME/skills/INDEX.md`; this repo ships `_core` and `production-ready`, the rest of the library is yours to add)
  - skills one project uses often: symlink into `<project>/.claude/skills/`
  - never install a skill into one account's skills folder directly
  - **Load skills yourself, before the user asks.** At the start of any task, check `INDEX.md` for a fitting skill
    (UI and design, charts, docs, decks, debugging, launch audits ...), read it, and put the skill paths in every
    subagent brief.
- **Scope tools to where they are used.** Skills, MCP servers, connectors and API keys go in the smallest place
  that works (project, core, or library). Follow the `tool-scoping` skill.
- **Memory:** a hook blocks new agents, workflows and heavy commands when the machine is out of memory.
  `python3 $CLUPAI_HOME/hooks/memory_guard.py list` shows every open session; `close-idle 6` closes idle ones.

## Shared stacks, simulators and dev servers

- Docker stacks and dev servers are shared and leased. Start a project's stack with
  `python3 $CLUPAI_HOME/hooks/stacks.py up NAME "why"`: it reuses the stack if another session has it up.
  Never start a second copy (e.g. a second Firebase emulator set). Run `stacks.py down NAME` when done.
- `stacks.py list` shows stacks and leases; `stacks.py add` registers a new one in `$CLUPAI_HOME/stacks.json`.
- A lease lasts while your agent process runs. Stopping keeps data.
- A launchd reaper (every 10 min) stops stacks `up` started once nobody has leased them for 45 min, other
  containers after 12 h, and kills dev servers (metro, ng serve, emulators, vite ...) left behind by finished sessions.
- iOS simulators and Android emulators work the same way: `stacks.py up ios|android "why"` boots one shared,
  headless device. Never boot your own. Use `android-lite` (test image, half the RAM) by default; `android` only
  when you need screenshots or Play services.

## Parallel sessions on one repo

- A hook claims each file a session edits, in `<git common dir>/claude-claims.json` (shared by all worktrees and
  all accounts). It blocks editing a file another live session is editing in the same worktree, and warns when it
  is being edited in another worktree.
- Before starting, run `python3 $CLUPAI_HOME/hooks/claims.py list` and avoid claimed files.
- Keep a status note with `claims.py note "doing now; done/tried: ..."` (run inside the repo). A hook reminds you
  after 3 turns with edits and no note.
- Every note is kept with its exact time and the files edited. Before starting something, check
  `claims.py history --grep WORD` for whether it was already done or tried.
- Claims drop when the session ends, or with `claims.py release`.
- On overlap, talk to the other session directly: the name in `claims.py list` is its `SendMessage` address.
  `ListAgents` shows who is reachable in every account: `hooks/session_mirror.py` (launchd, every 15 s) copies
  each session's entry into the other accounts, so a new session shows up within 15 s.
- Send one handoff (done, branch, files, tests, what is left). The session with less done hands over, releases,
  and stops or moves on. If you can't agree in two messages, or the other session is not reachable, tell the user.
- Bash `sed -i` / `perl -i` on plain paths is tracked. Other Bash writes (scripts, redirects, heredocs) are not,
  so use Edit/Write for repo files when others are running.

## Shared deploys, merges and learned guardrails

- `queues.py` gives one session at a time a turn on a shared target (`myapp:deploy-staging`):
  `join NAME "what"`, then `wait NAME` as a background task so you are woken on your turn, then
  `done NAME "result"`. Guardrails queue matching commands on their own; a blocked session is already in line.
- `guardrails.py` rules (`$CLUPAI_HOME/guardrails.json`) warn, STOP, queue or deny commands and file edits.
  Before executing a plan in a project, run `guardrails.py list --dir <project>` and say which could apply.
- On STOP: check the edge case. If it applies, fix it or tell the user in one line what could break and what you
  recommend. If it doesn't, `guardrails.py ack ID "what you checked"` and retry. Never work around it.
- After a failure another session could repeat, add a rule:
  `guardrails.py learn --action stop --match '^...' --dir <project> --why "could break: ...; instead: ..."`.
  Retire rules that turn out wrong.

## Session alerts

- `hooks/alerts.py` plays a soft sound and posts a kitty notification when a session finishes a turn, and a louder
  one when it needs the user (permission prompt, dialog, reply ending on a question).
- A question left unanswered for 5 min gets `/remote-control` typed at its empty input box, so it reaches the
  phone app. Prompts and dialogs only re-alert.
- `alerts.py status|off|on|test`. Settings: `$CLUPAI_HOME/alerts.json` (optional).

## Say whether the session can be closed

When a piece of work ends, run `claims.py closeout` (lists the claims, notes and queue places this session still
holds) and end the reply with one close line:

- `Safe to close: nothing left to do.` Only when there are no follow-ups and closeout says clear.
- `Safe to close, handover ready: <path>` when there are follow-ups. First write them to
  `<project>/.claude/handoff.md` (what is done, what is left in order, branch, commands, open risks, which
  guardrails apply), finish or leave every queue place, then `claims.py note "handed over: <path>"` and
  `claims.py release`, and run closeout again.
- `Not safe to close: <reason>` when background work is running, a queue turn is held mid-action, or you are
  waiting on the user. Say what would make it safe.

## One layer for every agent

- Shared files (this file, output styles, core skills, agents) live in `$CLUPAI_HOME` and are symlinked into every
  config dir. Change the shared copy, never a per-account copy.
- Codex, OpenCode, dsh and kimi each get a generated `AGENTS.md` (this file plus `agents/<agent>/DELTA.md`), the
  same skills and commands by symlink, and hooks through `hooks/agent_hook.py --agent <name>`, which calls the same
  claims, queues, guardrails, memory-guard and memory-recall scripts. Their sessions show in `claims.py list` and
  can block or be blocked by a Claude session on the same file.
- Grok Build reads this file through its Claude compatibility and gets only its delta, as
  `~/.grok/rules/shared-agent-layer.md`. Its Claude-compat hooks are off, so its session and prompt context arrive
  with its first tool call.
- dsh's hooks only fire when it may write (`second_opinion.py --write`); read-only runs skip them, which is harmless.
- With `--repos`, every repo with a `CLAUDE.md` gets a git-ignored `AGENTS.md` symlink to it, at the repo's git
  top level. A folder holding an empty `.sync-agents-skip` file is skipped.
- After changing this file, a core skill, a command or any agent's hook config, run
  `python3 $CLUPAI_HOME/scripts/sync-agents.py` (`--check` first).
- **Codex will not run a changed `hooks.json` until you launch `codex` once interactively and approve it;
  until then `codex exec` hangs.**
- **Memory is recalled, not preloaded.** `MEMORY.md` holds only pinned memories (type `feedback` or `user`, or a
  line marked `(pinned)`). `hooks/memory_recall.py` folds the rest out at session start and, on each prompt, adds
  the few memories that match it, ranked by keywords and `[[links]]`, from every account's memory for this folder
  and the folders above it. The full list is in `MEMORY.full.md`. Search with `memory_recall.py search WORDS`;
  `memory_recall.py share --check` shows any second-account folder not linked yet. Link related memories with
  `[[name]]`: a linked memory is recalled alongside its match. Outside models only get memories from folders
  `model-policy.json` lets them see.

## Claude Code mods

- Mods (function-hook plugins: panes, bands, tools) live in `$CLUPAI_HOME/mods/<name>/`.
- Every folder there loads in every Claude account through `CLAUDE_CODE_PLUGIN_DIRS`, which
  `sync-agents.py --only ui` writes. Rerun it after adding one.
- A folder with an `OPT-IN` file is skipped and loads only on request (`claude --plugin-dir <path>`).
- `side-checklist` loads by default: a pane beside the session. When you give the user steps to carry out, also put
  them on it with its `checklist` tool, and tick them off as they are done.

## Token economy

Before spawning any subagent or workflow, follow the `token-economy` skill. Short form, measured Sep to Oct 2026:

- Default worker: **Opus 5.5 at low effort** (`claude-opus-5-5`). Always pass `model` AND `effort`, or subagents
  inherit the session effort (xhigh under ultracode: 2.7x cost, no gain).
- Any text a person reads, reviews and final judging: Opus 5.5 at high effort. At low effort it invents
  cause-and-effect links in prose.
- **Sonnet 5.5 at low effort** (`claude-sonnet-5-5`) for coding where a test or script decides pass/fail:
  10/10 tasks at 58% of Opus 5.5 low's cost. Never for reviews or prose.
- **Haiku 5.5 at low effort** (`claude-haiku-5-5`) for short, tightly briefed coding a test decides, and cheap
  extra review passes, on any folder. Price goes up 5x past a 100k-token prompt, and it is slow on long tasks.
  Not a main reviewer.
- One cheap model alone is the default. Mixing Claude models (Opus directing or advising cheaper ones) bought no
  extra passes; use Opus directing Haiku or Sonnet subagents only when speed matters.
- "Cheap model executes, Opus reviews" costs more than Opus low alone. Don't.
- Codex for independent verification: same quality, almost no Claude usage.
- **Reset context near 200k tokens**, with `/clear` plus a handoff or with `/compact`. They cost about the same,
  but every call at 600-900k costs about 3x a call at 200k. Prefer the handoff when another session may continue.
  `sync-agents.py` sets every account to auto-compact at 250k (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`).
  Weekly spend: `python3 $CLUPAI_HOME/scripts/usage_report.py`.
- **Reset your own context at a good break point** (Claude Code in kitty only). Each compact keeps only about half
  the detail of the one before, and rule-following drops past ~500k. Claude cannot run `/clear` itself, so
  `hooks/reset.py` types it into your kitty window when your turn ends. `reset.py context` shows your size.
  - When: only while working on your own through a long task, not mid-conversation. The instructions are written
    into a plan or handoff and context is over ~100k; a milestone is done and context is over ~150k; or after the
    2nd compaction.
  - How: write `<project>/.claude/handoff.md` (done, what is left in order, decisions, files, commands, open
    risks), run `python3 $CLUPAI_HOME/hooks/reset.py request clear`, and end the turn with a one-line reply (the
    screen is wiped). Use `request compact --focus "..."` when recent detail matters more than a clean start.
    The fresh context gets the handoff and a "continue" prompt. A reset drops your claims and status note.
  - Never: with background tasks or agents running, a queue turn held, or a question or result the user still has
    to read; from a subagent; mid-debug before the findings are written down. It refuses outside kitty, without a
    fresh handoff, and past 3 resets an hour. `reset.py cancel|off|status`.
- **Effort gate:** a hook makes every substantive reply start with `Effort: <now> now, <needed> needed (...)`.
  Early in a session, Claude stops and asks for `/effort <needed>` when the gap matters; later it only notes it.
- **Effort is set by the user, not by Claude.** Changing it mid-session on Opus drops the prompt cache (the next
  call re-reads everything at full price), so suggest switching only right after a `/clear`. Agents get their own
  `effort`.

## Outside models

Policy by folder lives in `$CLUPAI_HOME/model-policy.json`. Unlisted folders are confidential.

| Policy | Example folders | Allowed outside Claude |
|---|---|---|
| confidential | client work, private notes, anything unlisted | Codex only |
| open | open-source repos | Codex, DeepSeek (`dsh`), Kimi (`kimi`), OpenCode on OpenRouter (GLM, Qwen, Grok, MiniMax) |
| personal | your own side projects and coursework | the above, plus Gemini (`agy`, plan quota) and Grok Build (`grok`, plan quota) |

Who does what (from a bake-off on a production React Native + Firebase app; full table in the `token-economy` skill):

| Model | Role |
|---|---|
| **Opus 5.5** | Main worker and final reviewer (high effort); replaced Fable 5.1 as reviewer: more bugs found at ~37% of the cost |
| **Fable 5.1** | Only the hardest coding tasks |
| **Sonnet 5.5 / Haiku 5.5**, low | Coding where a test decides (see Token economy) |
| **DeepSeek V4 Flash** (`dsh:deepseek-flash`) | Default bulk worker, always followed by a review pass; also a reviewer. Never for factual prose: it made up an answer instead of saying "don't know" 96.5% of the time on a hallucination test |
| **GPT-6 Astra** (`codex`) | Reviewer |
| **GPT-6.1 Sol** (`codex:gpt-6.1-sol`) | Coder on personal and open folders when Claude quota is tight; cleanest code measured; not a reviewer |
| **Grok 4.7** (`grok:grok-4.7`) | Reviewer on personal folders; stand-in when Codex is out |
| **Gemini 3.8 Flash** (`agy`) | Free quick drafts and reads |
| **Kimi K3** (`kimi:kimi-k3`) | Backup only, for when DeepSeek is down |

Reviewers are **DeepSeek Flash + Opus 5.5 + Astra** (Grok 4.7 on personal folders).
Dropped: DeepSeek V4 Pro, OpenCode Go and Zen (GLM, Grok, MiniMax go through OpenRouter for second opinions only).

Always call outside models through the script, so policy, sandbox and fallback apply:

```
python3 $CLUPAI_HOME/scripts/second_opinion.py PROMPT_FILE --cwd <project dir> [--network] [--write] [--ladder ...]
```

- Routes: `codex`, `dsh:<model>` (all DeepSeek calls: DeepSeek's own CLI and API), `kimi:<model>` (all Kimi calls),
  `opencode:openrouter/<vendor>/<model>` (Grok, GLM, Qwen, MiniMax only, never DeepSeek or Kimi), `agy:<model>`,
  `grok:<model>`.
- Don't call the raw CLIs on client or sensitive folders. `kimi -p` runs every tool without asking, so only ever
  call it through the script.
- Prefer CLIs over MCP servers for outside models: a CLI costs nothing until it is called.

## Code review

- **Always get a Codex review before calling any code change done, in every folder.** Review the diff, not the
  repo: `second_opinion.py - --cwd <repo> --review [--base BASE] --ladder codex` puts the git diff in the prompt
  with a findings-only brief (a focus file instead of `-` is optional). Fold in anything it confirms, on top of
  your own tests and checks, and say in the handoff that Codex reviewed it.
  - Every change: `--ladder codex` (medium effort). Use `--codex-effort high` for client deliverables and risky
    changes: auth, security, database rules, payments, migrations or deletes, concurrency, a diff over ~300 lines.
  - Also, on open and personal folders: `dsh:deepseek-flash`, plus `grok:grok-4.7` on personal ones, as extra passes.
  - Codex out of quota (it says so, not a guess): Grok 4.7 on personal folders; on confidential ones an Opus 5.5
    review subagent at high effort. Tell the user Codex was out. Database rules changes still need DeepSeek Flash
    and your own check.
- The Codex MCP tools (`mcp__codex__codex`, `mcp__codex__codex-reply`) can be allowed in `settings.json` and used
  without asking, but prefer `second_opinion.py --review` for reviews: it skips Codex's plugins and MCP servers and
  keeps the reviewer on the diff.

## Environment (example, replace with yours)

- **Example:** terminal is kitty; `ui/palette.py` reads its accent colour so the statusline matches.
- **Example:** `ls` is aliased to eza only at an interactive terminal, so scripts use `command ls`.
- **Example:** macOS gates some writes (LaunchServices, app icons, `/Applications`) on the terminal app hosting the
  shell, not the target app. Run those from the terminal that should own the permission, or they silently no-op.
- **Example:** peer machines over Tailscale run Claude Code unattended. When this machine is short on memory or
  quota, or a job is long, hand work over to one (read-only unless you allow writes) and read its log back. Keep
  client work on the main machine.

## Owner preferences (edit to taste)

- **Never use dividers.** No horizontal or vertical separator rules, ornamental hairlines or divider borders in
  interfaces, graphics, videos or review artifacts. Separate content with space, typography and composition.
  This overrides skill advice to use dividers.
- **K&R brace style** in every language that has braces. The opening brace goes on the same line as its
  statement, with one space before it; function *definitions* take the brace on their own line. `else`, `catch`
  and `do`/`while`'s `while` sit on the closing brace's line. Always brace a control statement's body, even one
  line. Where a file, repo or ecosystem already runs a different style, match the file. Never reformat as a side
  effect of an unrelated edit.
- **Short documents for review.** Anything the user has to read (reports, plans, summaries, audit write-ups) must
  be short. Main idea only.
  - Lead with the answer in one line. Conclusion first, never reasoning first.
  - Assume the reader does not know the subject. Plain language; gloss the jargon or drop it.
  - One sentence per point. If a point needs a paragraph, it needs a better sentence.
  - Tables and lists over prose. Cut citations down to the one that proves the point.
  - Detail is available on request. Offer it; do not pre-emptively include it.
  - Depth in the underlying work is still expected. Just do not make the user read it.
