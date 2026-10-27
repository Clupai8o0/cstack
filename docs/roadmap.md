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

Done in the 27 Oct refresh: alerts and reset hooks in the settings example, a devices example for simulators, private folder names scrubbed from exported docstrings, and the sandbox now re-allows `$CLUPAI_HOME` itself.
