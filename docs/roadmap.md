# Roadmap

**Next: give the files MonoCode reads a written contract, add CI for the hooks, and make the layer findable from anywhere through `$CLUPAI_HOME`.**

Ranked by value for effort (S = an hour or two, M = a day, L = several days). Suggested 27 Oct 2026.

| # | Change | Why | Size |
|---|---|---|---|
| 1 | `docs/interfaces.md`: a versioned contract for `claims.py list --json`, `stacks.py list --json`, the `Close:` line, `.claude/handoff.md` and the MonoCode location file | MonoCode parses these, and nothing says what shape they must keep | M |
| 2 | MonoCode finds `claims.py` and `stacks.py` through `$CLUPAI_HOME` | Today the fork uses a fixed path, so its claims tags and Stacks panel only work on one machine | S |
| 3 | CI: GitHub Actions on macOS and Ubuntu, Python 3.9 and 3.13, feeding sample hook JSON to every hook | Hooks run on every prompt and tool call; one bad edit can stall every session, and nothing checks them | M |
| 4 | `doctor` command: CLIs on PATH, platform, hooks wired, policy file valid | A missing piece now shows up later as a hook that silently does nothing | M |
| 5 | `export.py` warns when an exported file changed but the docs that describe it did not | Code refreshes on every export; the hand-written docs drift | S |
| 6 | Say "macOS first" up front, and give `memory_guard.py` a Linux memory signal | On Linux the memory guard does nothing and the sandboxed routes fail, without a word | M |
| 7 | Add a review case set made only of security-rules bugs to `bakeoff/` | Every model missed most of them, and reviews still go to those models | M |
| 8 | Publish a generic `peer` tool for handing jobs to other machines over Tailscale, with hosts in a config file | It saves Claude quota on long jobs, but the private version has its hosts built in | M |
| 9 | Fail-open timeouts on every hook lock (`memory_recall.py`, `alerts.py`, `session_mirror.py`) | A plain blocking lock can hold up a prompt until the hook is killed; `claims.py` already gives up after 3 s | S |
| 10 | `sync-agents.py --ui` honours `CLAUDE_DIRS` like `install.sh` | It writes only the two default account folders | S |
| 11 | Rules ask for a `Close:` prefix on the close line | MonoCode's close badges only read `Close:` lines, which only the on-the-go style writes | S |
| 12 | Ship `bakeoff/opencode-vertex.example.json` and pass its env through `second_opinion.py` | The Vertex lane in the bake-off cannot run from this repo | S |
| 13 | Offer MonoCode's file previews (PDF, tables, SVG, notebooks, LaTeX, Office, HTML) upstream; keep layer features as an optional integration | Less to merge on every upstream update | L |

## From the 27 Oct web sweep

**The most urgent: port the OpenCode plugin to v2, close guardrail gaps around wrapped commands, and deny reads of secret files.**

Six web researchers, then one pass that checked sources and the repo. Not yet tried hands-on.

| # | Change | Why | Size |
|---|---|---|---|
| 14 | Add a v2 entry to `agents/opencode/shared-agent-layer.js` and have `sync-agents.py --check` warn on OpenCode 2.x without it | OpenCode 2 ignores v1 plugins, so upgrading from 1.19.4 drops claims and guardrails ([docs](https://opencode.ai/v2/docs/build/plugins/migrate-v1/)) | M |
| 15 | `guardrails.py` looks inside `bash -c`, `sh -c`, `eval`, `timeout`, `nice`, `xargs`, `find -exec`, with a test table | A wrapped `git push` slips past a rule written for `git push` ([safety-net](https://github.com/kenryu42/claude-code-safety-net)) | M |
| 16 | Deny and STOP rules run in their own PreToolUse hook with `onFailure: "block"`; claims stay fail-open | A hook that crashes or times out lets the call through by default ([hooks](https://code.claude.com/docs/en/hooks)) | S |
| 17 | Settings example and sync add `permissions.deny` for reading `~/.ssh`, `~/.aws`, `**/.env*`, CLI key files; `enableAllProjectMcpServers: false` | The Read tool never reaches the hooks ([trailofbits](https://github.com/trailofbits/claude-code-config)) | S |
| 18 | `second_opinion.py` passes `--dangerously-bypass-hook-trust` to headless `codex exec` | A changed `hooks.json` can no longer hang a review run ([Codex hooks](https://learn.chatgpt.com/docs/hooks)) | S |
| 19 | Limit the "effort change drops the cache" rule to Opus 5 and older | 5.5 models and Fable 5.1 keep the cache on effort change ([caching](https://code.claude.com/docs/en/prompt-caching)) | S |
| 20 | Add `claude-sonnet-5-5` and `claude-haiku-5-5` to `PRICES` in `usage_report.py` | Spend on the default cheap workers is counted at Opus 5 rates | S |
| 21 | Clear `~/.agents/skills` (106 old folders) and link the core skills there | Codex, OpenCode and Kimi load it at every start, outside the vault library | S |
| 22 | Set `idleCompaction: false`, or a PreCompact(auto) hook that refreshes `.claude/handoff.md` first | Since v2.1.299 a session over 200k idle ~54 min compacts on its own | S |
| 23 | STOP `git checkout`, `switch`, `stash`, `reset --hard`, `clean` when another live session holds claims in the worktree | They rewrite other sessions' files without a claim check | M |
| 24 | Scan diffs for keys and PEM blocks before `second_opinion.py` sends them to a non-Codex route | A committed key would still reach DeepSeek, Kimi or OpenRouter | S |
| 25 | `claims.py guard-commit` as a git pre-commit hook | Stops `git add -A` committing another session's half-done work, for every CLI | S |
| 26 | `guardrails.py learn` needs one command that must match and one look-alike that must not; `check` re-runs them | Learned rules can over- or under-match unnoticed | S |
| 27 | `sync-agents.py --check` warns past ~28 KiB of Codex `AGENTS.md`; raise `project_doc_max_bytes` | It is 28.5 KB against Codex's 32 KiB cap, so project instructions may be cut | S |
| 28 | Show statusline `prompt_cache` fields; add cache hit ratio to `usage_report.py` | Makes the compact and reset rules measurable | S |

Skipped after checking: `--max-budget-usd` (already in the bake-off), rebuilding `reset.py` as a mod (unclear that mods can run `/clear`), the built-in Seatbelt sandbox (breaks docker for `stacks.py`), ccusage (borrow the idea instead).

Done in the 27 Oct refresh: alerts and reset hooks in the settings example, a devices example for simulators, private folder names scrubbed from exported docstrings, and the sandbox now re-allows `$CLUPAI_HOME` itself.
