# Token economy

**Opus 5.5 low does the work, Opus 5.5 high writes what people read and judges, Sonnet or Haiku 5.5 low code where a test decides, Codex reviews every change, and context stays under ~200k.**

The enforced version is the `token-economy` skill (`skills/_core/token-economy/SKILL.md`). This page is the why.
Figures come from the [bake-off](bake-off.md) (10 real app tasks, 17 known review bugs) and the 17 Sep [routing benchmark](routing.md).

## Which Claude model for which job

| Work | Model, effort | Evidence |
|---|---|---|
| Default: audits, fixes, research, internal notes | Opus 5.5, **low** | 29 Sep: 10/10 coding tasks for $8.22, half of Opus 5.5 high, same code quality |
| Text a person reads, reviews, final judging | Opus 5.5, **high** | Drafts score 8-9/10; finds 9-10 of 17 review bugs. At low effort it invented cause-and-effect links in a mentor update (29 Sep) |
| Coding a test or script decides | Sonnet 5.5, **low** | 29 Sep: 10/10 for $4.78 (58% of Opus 5.5 low), as clean. Not for reviews (6 of 17 bugs at high effort) or prose |
| Short, tightly briefed coding a test decides; cheap extra review passes; any folder | Haiku 5.5, **low** (reviews at high) | 10 Oct: 10/10 for $1.44; reviews 5-9 of 17 for ~$0.20 per 5. Price goes up 5x past a 100k-token prompt, and it is slow on long tasks (30 min where Sonnet took 8). Not a main reviewer |
| Hardest coding only | Fable 5.1 | Clean code (28, behind GPT-6.1 Sol's 19 and Sonnet 5.5 low's 27; lower is cleaner), but 2-3x the cost and a weaker reviewer than Opus 5.5 |
| One-line lookups | inline, no agent | Every agent pays setup tokens first (estimate: 30-50k) |

Don't use for subagents: Opus at xhigh or max, Sonnet 5.5 high (costs as much as Opus 5.5 low, slower, no better code), Opus 4.8, Haiku 4.5, Sonnet 5.

## Mixing Claude models (10-11 Oct)

**Every setup passed 10/10, so mixing models bought no extra passes. One cheap model alone is the default.**

| Setup | Use? | Measured |
|---|---|---|
| Sonnet 5.5 low alone (Haiku 5.5 low for short jobs) | **Default** | $4.78, 32 min; Haiku $1.44, 58 min |
| Opus lead directing Haiku or Sonnet subagents | Only when speed matters | Fastest, 26-30 min, $4.89-7.65; quality no better |
| Opus plans, a cheaper model codes | **Don't** | +$8-12 for no gain; 92% of "Opus plans, Haiku codes" ($12.44) was Opus |
| Cheaper model with an Opus advisor | Only without a reminder to consult it | The reminder makes Haiku consult Opus on most turns: $3.10 becomes $12.84 |
| Opus lead with Haiku or Sonnet sub-reviewers | **Don't** | 7-8 of 17 bugs for $5.39-8.79; Opus 5.5 high alone finds 9-10 for $4.35 |
| Cheap model works, Opus reviews | **Don't** | $0.78 vs $0.33 for Opus low alone, same score (17 Sep) |

## Other measured rules

| Rule | Evidence |
|---|---|
| Always pass `model` and `effort` to subagents | They inherit session effort; xhigh costs 2.7x ($0.90 vs $0.33) with no meaningful gain |
| Pass `model` per agent when a lead picks agents | 10 Oct: an agent defined as Haiku ran on Sonnet because the lead chose the model |
| Strip the effort-gate line from headless output you parse | Sonnet 5.5 low and Haiku 5.5 sometimes echo it into answers |
| Codex reviews every code change, on the diff (since 21 Oct) | It costs almost no Claude usage. `second_opinion.py --review` puts the diff in the prompt: in Sep, 302 Codex reviews through MCP used 267M input tokens (median 553k each) |
| Review on Codex's out-of-quota days | Grok 4.7 on personal folders; an Opus 5.5 high subagent on confidential ones |
| Reset context near 200k | A call at 600-900k costs about 3x a call at 200k (estimate: $0.38 vs $0.13) |
| Auto-compact at 250k in every account | In the week to 23 Sep, 59% of Claude spend was on calls past 200k; with auto-compact on, it was 10-14% in the four weeks to 24 Oct |
| `/compact` and `/clear` + handoff cost the same | $0.81 vs $0.69 at 563k; pick the handoff if another session continues |
| Don't switch effort mid-session on Opus | It drops the prompt cache: the next call re-reads everything at full price |
| Keep agents short; split past ~100 steps | 10 long agents were 71% of past Opus usage |
| Keep installed skills small | The skill listing cost tokens in every agent (estimate: ~7.5k before cleanup) |
| Recall memories per prompt, don't preload | `memory_recall.py` keeps `MEMORY.md` to pinned notes only |

## Effort gate

`hooks/effort_gate.py` makes every substantive reply start with `Effort: <now> now, <needed> needed (<reason>)`.

| When | What Claude does |
|---|---|
| Early in a session, and the gap matters | Stops and asks for `/effort <needed>`; switching is cheap while context is small |
| Later in a session | Notes it and carries on; switching would drop the prompt cache |
| Headless runs | Never stops |

Effort is the user's call. Agents get their own `effort` per call.

## Start a session

1. Open it in the project folder, so its `CLAUDE.md`, skills and model policy load.
2. One session per task.
3. Write the first prompt with this template:

```text
Goal: <one sentence>
Done when: <tests pass / page shows X / numbers match Y>
Scope: <dirs or files>. Don't touch: <dirs, branches, deploys>
Context: read <AGENTS.md / handoff.md> first, nothing else up front
Run it: workers claude-opus-5-5 low (claude-sonnet-5-5 low where tests decide), final check opus-5-5 high or Codex, max 4 agents at once
Finish with the recap. No questions mid-work; put decisions in the recap checklist.
```

4. Anything touching several files starts in plan mode.
5. Finish cleanly: handoff to `<project>/.claude/handoff.md`, lessons to the project `CLAUDE.md`, then exit.

## Choose the mode

| Situation | Main session | Workers | Checked by |
|---|---|---|---|
| Quick question or small edit | normal effort, no agents | none | you |
| Normal feature or bug | high effort | Opus 5.5 low, pinned | tests, then a Codex review of the diff |
| Coding a test decides | high effort | Sonnet 5.5 low (Haiku 5.5 low for short jobs) | tests, then a Codex review of the diff |
| Big audit, migration, wide sweep | workflow | Opus 5.5 low, pinned per stage | Opus 5.5 high or Codex |
| Text someone else reads | Opus 5.5 high writes it | none | Codex or a second Opus pass |

## Unclear scope

1. Scope at `/effort xhigh` in its own short session. Write the result to a file.
2. `/clear`, `/effort high`, and execute from that file with Opus 5.5 low workers.

## Mixed-model flow (open and personal projects only)

1. Claude (Opus 5.5 high) writes the spec and acceptance tests into the repo.
2. Make a disposable worktree: `git worktree add ../wt-<task> -b <task>`.
3. Delegate: `second_opinion.py spec.md --cwd ../wt-<task> --write --ladder dsh:deepseek-flash`
   (or `--ladder codex:gpt-6.1-sol` when Claude quota is tight and Codex has room).
4. Claude runs the tests, reads the diff, fixes small things, merges. Then a review pass.
5. Only worth it when the spec is clear and the change is big. For small edits, start-up and review cost as much as doing it.

## Context size

**Most spend goes on calls with a huge context, so cap it.** Every call re-reads the whole context.

| Measure | How |
|---|---|
| Auto-compact at 250k, not near 1M | `sync-agents.py --ui` sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW=250000` for every account; `/autocompact` changes one session |
| Reset yourself at a break point | Write `<project>/.claude/handoff.md`, then `hooks/reset.py request clear` (or `request compact --focus "..."`). The Stop hook types the command when the turn ends and the fresh context gets the handoff |
| When to reset | Instructions are in a plan or handoff and context is over ~100k; a milestone is done and it is over ~150k; or after the 2nd compaction (each compaction keeps about half the detail of the one before) |
| Never reset | With background tasks or agents running, a queue turn held, a result the user still has to read, from a subagent, or mid-debug before findings are written down |
| Check it weekly | `scripts/usage_report.py` prints the share of spend past 200k; `--write` keeps one row per week |

`reset.py` only works in kitty (it types into the window with kitty remote control). It refuses without a fresh
handoff and past 3 resets an hour; `reset.py off` turns it off everywhere.

## Other hygiene

- Point at files and logs instead of pasting them.
- Browser work: use page text or the accessibility tree; screenshots only as evidence.
- Close idle sessions: `memory_guard.py close-idle 6`.
