# MonoCode

**MonoCode is a desktop GUI for coding agents; a personal fork of it reads this layer's claims, stacks, alerts and close lines, so the shared state is visible without a terminal.**

## Upstream MonoCode

- A GUI for the agent CLIs you already have: each tab is a session, the composer is the input, split panes show sessions side by side.
- It runs the installed CLIs on their own logins and sells no tokens ([upstream](https://github.com/hardbeat920/monocode), MIT).
- From this layer it runs Claude Code, Codex, Grok Build, OpenCode and Antigravity (`agy`); the fork adds dsh. kimi has no provider.

## The fork

[Clupai8o0/monocode](https://github.com/Clupai8o0/monocode), branch `mine`. Fork features live in `src/fork/*` and `src-tauri/src/fork_*.rs`, one row each in [`fork/README.md`](https://github.com/Clupai8o0/monocode/blob/mine/fork/README.md).

| Step | What happens |
|---|---|
| Build | Node.js 20+ and stable Rust; `npm install && npm run tauri dev` for a dev run, `update.sh` for the installed app |
| Launch | `monocode [dir]` (`fork/monocode`, symlinked into `~/.local/bin`): swaps in a staged build if the app is closed, opens it, starts `fork/update.sh` in the background |
| Update | `update.sh` merges `upstream/main` into `mine` in a private worktree, then runs `tsc`, `npm test` and `tauri build` |
| Repair | On a merge conflict or broken build, one Claude Sonnet agent at low effort fixes it in that worktree; if it fails, `mine` stays put and a notification says so |
| Stage | The new `.app` is staged in `~/.local/state/monocode-fork/` and swapped into `/Applications` on the next open or after quit |
| Safety | Skips when the checkout is not on `mine` or has uncommitted edits; `mine` only moves forward; settings and sessions survive every swap |

`monocode dir` puts the folder path on the clipboard, because MonoCode has no CLI or URL hook to open a folder.

## Fork feature and what it reads from this layer

| Fork feature | Reads or follows |
|---|---|
| Who's editing what | `claims.py list --json DIR` (read-only): a tag on file tabs and Explorer rows naming the session editing that file; orange Claude, blue Codex, dashed for another worktree |
| Stacks panel | `stacks.py list --json`: footer "Stacks · N up" with who holds each stack; Stop runs `stacks.py stop NAME` (a person's choice; there is no Start) |
| Close badges | The last `Close:` line of a session's reply (the `on-the-go` output style ends with one): Safe, Handover or Not safe; one button archives every safe session that is not open, pinned or busy |
| Peer message cards | `<cross-session-message>` from another Claude Code session (`SendMessage`) shows as a card instead of being dropped |
| Message badges | Per-session counts of messages received and sent; a "Messages" footer pane lists them all |
| Needs-you counts | Badge and window title show how many agents wait on you; a question or approval left 5 min alerts once more, the same delay as `alerts.py` |
| Ring at my places | Sounds play only at saved places; the fork writes `~/.local/state/monocode-fork/location.json`, and `alerts.py` goes silent when it says `ring=false` (rings as usual when the file is missing or stale) |
| Handoff indicator | A project tag when `.claude/handoff.md` exists |
| Status line | Runs your Claude Code `statusLine.command`; `ui/statusline.py` answers the composer layout with plain JSON (account, compactions, compact point) |
| Side checklist | Rebuilds the `side-checklist` mod's `checklist` tool calls into a sidebar |
| DeepSeek provider | Runs `dsh --profile acp` as a MonoCode agent; models and effort come from dsh |
| Codex integration | Codex sessions keep peer-message cards, send receipts and artifact links ([`fork/CODEX.md`](https://github.com/Clupai8o0/monocode/blob/mine/fork/CODEX.md)) |
| Chrome for Claude | Interactive Claude sessions get `--chrome`, so the Claude in Chrome tools load |
| Auto-update | The installed app runs `monocode --update` at launch and `monocode --after-quit PID` at quit, so a Dock open updates too |
| Remote agent | A provider that runs Claude Code on a home-lab Linux machine over Tailscale SSH, in the same `$HOME`-relative folder |

## Other fork features

| Feature | What it does |
|---|---|
| File previews | PDF, CSV/TSV/XLSX, SVG, notebooks, HTML, LaTeX (via MacTeX) and Office files (via LibreOffice) |
| Workspace windows | Named OS windows, each with its own layout; one session never opens in two windows |
| Projects sidebar and notifications | One project list with running/needs-you/done counts; one bell for completions, questions and approvals |
| Usage footer | Claude and Codex plan balances in the footer |
| Hidden features | Inbox, Notes, Automations and some providers are hidden, not deleted, so upstream merges stay clean |

Every row, with its files: [`fork/README.md`](https://github.com/Clupai8o0/monocode/blob/mine/fork/README.md).

## Limits

- macOS first: ring at my places needs Location Services, banners and Dock bounce use macOS, and the updater uses `ditto` and `/Applications`.
- LaTeX preview needs MacTeX; Office preview needs LibreOffice.
- dsh sandboxes itself and asks no edit approvals, so Supervised and Plan modes are not enforced for it.
- The remote agent edits the remote machine's copy; sync with git.
- The handoff tag reads local folders only; the Stacks panel hides when `stacks.py` is missing.
- The fork looks for `claims.py` and `stacks.py` at a fixed path in the owner's home folder, not `$CLUPAI_HOME`. Elsewhere the claims tags and Stacks panel stay hidden, with no error, until that path reads `$CLUPAI_HOME` (see [roadmap](roadmap.md)).
- Codex keeps its own agent tree; the fork shows cross-session messages in Codex but adds no Claude-style transport.
