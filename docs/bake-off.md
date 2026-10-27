# Model bake-off (Sep-Oct 2026)

**Opus 5.5 is the main worker (low effort) and the Claude reviewer and writer (high effort). Sonnet 5.5 low and Haiku 5.5 low are the cheap Claude coders when a test decides. Codex (GPT-6 Astra) reviews every change; GPT-6.1 Sol codes when Claude quota is tight. DeepSeek V4 Flash is the bulk worker. Mixing Claude models bought no extra passes.**

All work came from the git history of a production React Native + Firebase app. The runner is in `bakeoff/`.

## Who does what now (27 Oct 2026)

| Model | Route | Role | Why |
|---|---|---|---|
| Opus 5.5 | Claude Code | **Main worker** (low); text people read, reviews, final judging (high) | 10/10 at low for $8.22; 9-10 of 17 review bugs at high; invents links in prose at low |
| Sonnet 5.5 | Claude Code | Coding a test decides (low) | 10/10 for $4.78, clean code; 6 of 17 in review at high effort, so not a reviewer |
| Haiku 5.5 | Claude Code | Short coding a test decides (low); cheap extra review passes; any folder | 10/10 for $1.44; slow on long tasks |
| Fable 5.1 | Claude Code | Hardest coding tasks only | Clean code, but a weaker and ~2.7x costlier reviewer than Opus 5.5, and last in research writing |
| Opus 5 | Claude Code | Fallback if 5.5 is unavailable | 10/10, $20.60 |
| GPT-6 Astra | `codex` | **Reviews every code change** (since 21 Oct) | Fastest coder; found 1 bug no one else did; costs almost no Claude usage |
| GPT-6.1 Sol | `codex:gpt-6.1-sol` | Coder when Claude quota is tight (personal and open folders), then a review pass | 10/10, cleanest code measured (19); 3 of 17 in review, so not a reviewer |
| DeepSeek V4 Flash | `dsh:deepseek-flash` | Bulk worker and reviewer; always followed by a review; never factual prose | 10/10 for ~$1.50; 9 of 17 review bugs; answered wrong instead of "don't know" 96.5% of the time on a public hallucination test |
| Grok 4.7 | `grok:grok-4.7` | Extra reviewer on personal folders; stands in when Codex is out | 7 of 17 in review; 10/10 coding on the plan quota |
| Gemini 3.8 Flash | `agy:<model>` | Free quick drafts and reads | 9/10, plan quota; 5 of 17 in review |
| GLM-5.3, Grok 4.6, Qwen 3.8 Max, MiniMax M3 | `opencode:openrouter/...` | Second opinions; writing second drafts | See the full results |
| Kimi K3 | `kimi:kimi-k3` | Backup if DeepSeek is down | 10/10 but slowest, ~$14.70 |
| Gemini 4 Argon | on Vertex | Tested 14 Oct, not routed | Top-tier reviewer, but twice Opus 5.5 high's price per review |

Reviewers: **DeepSeek Flash + Opus 5.5 + Astra** (Grok 4.7 as well on personal folders).

## What was tested

| Test | What |
|---|---|
| Coding | 10 real tasks from git history: 6 short, 4 long (one touched 20 files). Each was checked to fail before the real commit and pass after it. |
| Review | 5 real changes whose tests passed, containing 17 bugs a later review caught. Graded blind. |
| Code quality | Astra reviewed each model's passing code on the 2 long backend tasks, blind. Defects weighted by severity; lower is better; one run each, so noisy. |

## Full results

Most rows are the 22 Sep run; dated rows were added later.

| Model | Coding | Review (of 17 bugs) | Code quality (lower is better) | Cost for 10 tasks | Role |
|---|---|---|---|---|---|
| **Opus 5.5** high (23 Sep) | 10/10 | **10 / 9** (2 runs) | 31 | $16.12 | **Reviewer, writer, judge** |
| **Opus 5.5** low (29 Sep) | 10/10 | not run | 32 | $8.22 | **Main worker** |
| Sonnet 5.5 low (29 Sep) | 10/10 | not run (6 at high) | 27 | $4.78 | Coding a test decides |
| Haiku 5.5 low (10 Oct) | 10/10 | not run (5-6 at high) | 36 | **$1.44** | Short coding a test decides |
| Opus 5 | 10/10 | not run | 32 | $20.60 | Fallback (main worker until 23 Sep) |
| Fable 5.1 | 10/10 | 6 | 28 | $26.95 | Hardest coding only (final reviewer until 23 Sep) |
| GPT-6 Astra (via Codex) | 10/10, fastest | 5 (1 no one else found) | judge | plan quota | **Reviewer** |
| GPT-6.1 Sol (via Codex, 11 Oct) | 10/10 | 3 / 3 | **19** | plan quota | Coder when Claude quota is tight |
| GPT-6 Sol (via Codex, 29 Sep) | 10/10 | 5 | 29 | plan quota | Replaced by 6.1 on 11 Oct |
| GPT-6 Luna (via Codex, 29 Sep) | 10/10 | 3 | 41 | plan quota | Not used |
| DeepSeek V4 Flash | 10/10 | **9** | 43 | **~$1.50** | **Bulk worker, reviewer** |
| Gemini 4 Argon (on Vertex, 14 Oct) | 10/10 | **10 / 8** | not run | $16.77 | Tested, not routed |
| Gemini 3.8 Flash (High) | 9/10 | 5 | 35 | $0 (plan quota) | Free drafts and reads |
| Grok 4.7 (OpenRouter) | 6/6 short only | 7 | not run | $4.06 for 6 short | Found nothing the others missed |
| Grok 4.7 (Grok Build CLI) | 10/10 | 2 of 3 on case 1 (only case run) | not run | Grok plan quota (~77% of a week's allowance) | Extra reviewer; personal folders only |
| GLM-5.3 | 9/10 | 8 / 5 (11 Oct) | not run | ~$24 | Second opinions; slow and costly on long tasks |
| Kimi K3 | 10/10, slowest | 4 | 45 | ~$14.70 | Backup only |
| DeepSeek V4 Pro | 7/10 | not run | not run | ~$1.50 | Dropped: its CLI stopped partway twice |
| Grok 4.6 | 9/9 | not run | not run | ~$9 | Second opinions |
| MiniMax M3 | 7/9 | not run | not run | ~$4 | Second opinions |

## Opus 5.5 vs Fable 5.1 as reviewer (23 Sep)

**Opus 5.5 at high effort replaced Fable 5.1 as reviewer.** Same 5 review cases, both at high effort, 2 runs each.
All 20 answers were re-graded blind by an Opus 5.5 subagent and by Grok 4.7 (Codex was out of quota). Both graders agree.

| | Opus 5.5 | Fable 5.1 |
|---|---|---|
| Bugs found, run 1 / run 2 (Opus grader) | **10 / 9** | 6 / 4 |
| Same, Grok grader | **9 / 8** | 6 / 4 |
| False alarms | 0 | 0 |
| Cost per 5 reviews | **~$4.35** | ~$11.80 |
| Time per 5 reviews | **~12 min** | ~19 min |
| Bugs it found that the other missed (both runs) | 4-5 | **0** |

- Opus 5.5's code quality was judged on 29 Sep: 31 (Fable 28, Opus 5 32).
- Opus 5.5 took about 30% more wall time than Opus 5 on the coding tasks.

## Sonnet 5.5 (29 Sep)

**Sonnet 5.5 low is a good cheap coder when tests decide. It is not a reviewer, and at low effort neither it nor Opus 5.5 should write text people read.**

| Setup | Coding | Cost | Time | Code quality | Review (of 17, 2 runs) | Writing /10 |
|---|---|---|---|---|---|---|
| Sonnet 5.5 low | 10/10 | **$4.78** | **32 min** | **27** | not run | 3-6 (invents links) |
| Sonnet 5.5 high | 10/10 | $8.04 | 57 min | 37 | 6 / 6-7 | 6-8 |
| Opus 5.5 low | 10/10 | $8.22 | 35 min | 32 | not run | 2-6 (invents links) |
| Opus 5.5 high | 10/10 | $16.12 | 78 min | 31 | **10 / 9** | **8-9** |

- Opus 5.5 low wrote "so I broke the work into smaller pieces" with nothing in the facts to back it.
- Sonnet 5.5 low once printed the effort-gate hook line into a headless answer. Opus never did.

## GPT-6 Sol and Luna (29 Sep)

**Sol codes well on the Codex plan but reviews only at Astra's level. Luna leaves DeepSeek-level defects.** Both ran through Codex at high effort, so no cash cost.

| Model | Coding | Time | Code quality | Review (of 17) |
|---|---|---|---|---|
| GPT-6 Sol | 10/10 | 41 min | 29 | 5 |
| GPT-6 Luna | 10/10 | 52 min | 41 | 3 |
| GPT-6 Astra, for comparison | 10/10 | 45 min | judge | 5 |

- Astra judging OpenAI's own models may be kind to them.
- Sol was added to routing as the coder when Claude quota is tight (29 Sep).
- Cheap OpenRouter screens ($0.33 total): MiMo V2.6 Flash passed 2/2 short tasks and found 2 of 3 bugs on case 1; Qwen 3.8 Flash failed 1 of 2. No full runs bought.

## Research writing: Fable 5.1 vs Opus 5.5 (6 Oct)

**Opus 5.5 in Claude Code wrote the best report; Fable cost 1.75x as much and came last.** One ~10k-word research report with web research, same brief, max effort.
Judged blind by Codex and by Gemini 3.8 Flash on Vertex.

| Writer | Cost | Time | Codex judge | Gemini judge |
|---|---|---|---|---|
| Opus 5.5, Claude Code CLI | $17.48 | 82 min | 1st (clear) | 1st (narrow) |
| Opus 5.5, Messages API (own tool loop) | $13.19 | 30 min | 2nd | 2nd |
| Fable 5.1, Claude Code CLI | $30.68 | 63 min | 3rd (narrow) | 3rd (clear) |

- The API run was cheaper and faster but got a fact wrong that the CLI run had right.
- Judges preferred reports written by their own model family. Use judges from neither family.
- GPT-6 Astra wrote the same report at max ($6.36) and medium ($3.63) effort: judges from neither family put Opus 5.5 first; only GPT judges put Astra first.
- As a fact-checking reviewer of the finished report, Gemini 3.8 Flash had 0 of 4 findings hold (2 were invented); Codex had 6 of 7.

## Haiku 5.5, plus DeepSeek V4.1 Flash review (10 Oct)

**Haiku 5.5 low is the cheapest Claude coder (10/10 for $1.44) and reviews about as well as Sonnet 5.5 at a tenth of the cost. It is slow on long tasks and not a main reviewer.**

| Setup | Coding | Cost | Time | Code quality | Review (of 17, 2 runs) | Review cost per 5 |
|---|---|---|---|---|---|---|
| Haiku 5.5 low | 10/10 | **$1.44** | 59 min | 36 | not run | not run |
| Haiku 5.5 high | 10/10 (1 at the time limit) | $1.40 + 1 run unmetered | 76 min | 29 | 5-6 / 7-9 | **$0.18-0.27** |
| Sonnet 5.5 high | 10/10 | $8.04 | 57 min | 37 | 6 / 7 | $1.70-1.92 |
| Opus 5.5 high | 10/10 | $16.12 | 78 min | 31 | 10 / 9 | $4.35 |

- Review counts are two blind graders (Opus 5.5 high / DeepSeek Flash); DeepSeek grades 1-2 bugs more generously.
- No false alarms from Haiku. In one run it found 2 Firestore rules bugs most models miss.
- One long task took Haiku 30 min at low effort, where Sonnet low took 8.
- Haiku echoed the effort-gate line in 2 of 10 headless review answers.
- Where it fits: folders where DeepSeek is not allowed. Elsewhere DeepSeek Flash reviews better for the same money.
- DeepSeek V4.1 Flash (OpenRouter) found 2 bugs on cases 1-2, vs 3 for V4 Flash. No reason to switch.

## Workflows, GPT-6.1 Sol and GLM-5.3 reviews (10-11 Oct)

**Every setup passed 10/10, so mixing Claude models bought no extra passes. Sonnet 5.5 low alone is still the best value. GPT-6.1 Sol wrote the cleanest code yet.**

| Setup | Cost (10 tasks) | Time | Code quality |
|---|---|---|---|
| GPT-6.1 Sol (Codex) | plan quota | 46 min | **19** |
| Sonnet low + Opus advisor | $9.03 + 1 run unmetered | 95 min | 22 |
| Sonnet 5.5 low alone | $4.78 | 32 min | 27 |
| Opus plans, Haiku codes | $12.44 | 65 min | 27 |
| Opus directs Sonnet | $7.65 | 39 min | 31 |
| Opus plans, Sonnet codes | $16.38 | 69 min | 31 |
| Sonnet plans, Haiku codes | $4.90 | 111 min | 31 |
| Opus 5.5 low alone | $8.22 | 35 min | 32 |
| Opus directs Haiku | $4.89 | 30 min | 35 |
| Haiku low + Opus advisor, with reminder | $12.84 | 70 min | 35 |
| Haiku 5.5 low alone | **$1.44** | 58 min | 36 |
| Opus directs Sonnet + Haiku | $6.73 | **26 min** | 38 |
| Haiku low + Opus advisor, no reminder | $3.10 | 61 min | 42 |

- Opus as planner is the costly part: 92% of "Opus plans, Haiku codes" was Opus.
- A reminder to consult the advisor quadruples cost: Haiku then calls Opus on most turns.
- Given both, the Opus lead picked Sonnet: Haiku did $0.01 of the work.
- Opus directing a cheap coder is the fastest setup, at about Sonnet-low prices.

| Reviewer (of 17 bugs) | Run 1 / run 2 | Security bugs (of 11) | Cost per 5 | Time per 5 |
|---|---|---|---|---|
| Opus 5.5 high (23 Sep) | 10 / 9 | not counted | $4.35 | ~12 min |
| GLM-5.3 (OpenRouter) | 8 / 5, 1 false alarm each | 5 | ~$2.10 | 20-32 min |
| Opus lead + Haiku reviewers | 8 | 5 / 4 | $5.39 | 16 min |
| Opus lead + Sonnet reviewers | 7 | 4 | $8.79 | 13 min |
| Sonnet 5.5 high | 6 / 7 | 4-5 | $1.70-1.92 | 6 min |
| GPT-6.1 Sol | 3 / 3 | 2-3 | plan quota | 17 min |

- GLM-5.3 is inconsistent, slow, and found no more security bugs than Claude. Second opinions only.
- Opus leading sub-reviewers costs more than Opus alone and finds fewer bugs.
- GPT-6.1 Sol codes very well and reviews poorly, like GPT-6 Sol. It replaced GPT-6 Sol in routing on 11 Oct.

## Gemini 4 Argon (14 Oct)

**Argon is a top-tier reviewer and codes 10/10, but costs about Opus 5.5 high's price for coding and twice its price per review. Not routed.**
Ran on Vertex in the same OpenCode agent loop as the other outside models, thinking high, at list price.

| Test | Argon | For comparison |
|---|---|---|
| Coding | **10/10**, $16.77, 62 min | Opus 5.5 high $16.12, 78 min; Sonnet 5.5 low $4.78; DeepSeek Flash ~$1.50 |
| Review (of 17, 2 runs) | **10 / 8**, 0 false alarms, ~$9.50 per 5; 2 bugs no anchor model found | Same batch: Opus 5.5 high 9, DeepSeek Flash 10 |
| Writing (/10, three judges) | 5-9 | Opus 5.5 high 8-9 from all three |
| Wrong instead of "don't know" (AA-Omniscience, public) | 15% | Grok 4.7 29%, Astra 51%, Opus 5.5 59%, DeepSeek Flash 96.5% |

- Its drafts over-claimed: "I landed" and "Merged" for work a teammate merged.
- 1 of 11 review runs ended empty and was rerun.
- OpenCode's generic OpenAI-compatible adapter fails on Argon tool calls; use `@ai-sdk/google-vertex`.
- Every OpenCode call carries ~35-40k tokens of setup.
- In the Gemini app on a consumer plan, Argon found 7 of 17 and scored 5/10 on writing. The Pro limit hit after about 6 big prompts, then the app switched to Flash-Lite with no warning.

## Extra models via OpenRouter (first look only)

Credit ran out before the long tasks. Two review cases is a small sample.

| Model | Short tasks | Review bugs (cases 1-2) | Cost for 4 tasks | Time for 4 |
|---|---|---|---|---|
| Hunyuan 4 | 4/4 | 3 | $0.65 | 36 min |
| Qwen 3.8 Max | 4/4 | 3 | $1.90 | 42 min |
| Sakana Fugu Max | 4/4 | 1 | $1.47 | **12 min** |
| DeepSeek V4.1 Flash | 4/4 | tool error | $0.10 | 21 min |
| MiMo v2.6 Pro | 3/4 | 0 | $1.54 | 84 min |

- Costs are what OpenCode reports; the real OpenRouter charge was about 1.5-2x that.

## History: how roles changed

| Role | 22 Sep | Now (27 Oct) |
|---|---|---|
| Main worker | Opus 5 | Opus 5.5 low (23 Sep) |
| Final reviewer | Fable 5.1 | Opus 5.5 high (23 Sep) |
| Review trio | Astra + Fable + DeepSeek Flash | Astra + Opus 5.5 + DeepSeek Flash |
| Cheap Claude coder | Sonnet 5 | Sonnet 5.5 low (29 Sep), Haiku 5.5 low for short jobs (10 Oct) |
| Coder when Claude quota is tight | none | GPT-6 Sol (29 Sep), GPT-6.1 Sol (11 Oct) |
| Codex code review | independent reviewer | risky changes only (24 Sep), then every change (21 Oct) |

## Lessons

- The tasks were too easy to separate the top models on pass rate. Speed, cost and code quality were the real differences.
- Every model missed Firestore security-rules bugs: 4 of 5 known rules bugs went unfound. Rules still need a human.
- DeepSeek Flash passed the tests but left 34-54% more defects than Claude (43 vs 28-32). Always follow its code with a review pass.
- A newer model can beat an older, pricier one: Opus 5.5 out-reviewed Fable at 37% of the cost and out-wrote it at 57%.
- Low effort invents facts in prose, on Opus and Sonnet alike. Text people read gets high effort.
- Mixing Claude models (planners, directors, advisors, sub-reviewers) bought no extra passes; Opus planning or sub-reviewing only added cost.
- The cleanest coders (GPT-6.1 Sol, Sonnet 5.5) were weak reviewers. Pick reviewers on review results.
- Judges favour their own model family; use judges from neither family.
- Harness traps: the effort gate read the wrong config for Codex; paths starting with `_` broke git's exclude filter;
  a prepaid plan ran out in a day; runs that died on an empty balance (HTTP 402) were voided, not counted as fails;
  a broad `pkill` killed 3 runs, which were voided and rerun.

## Caveats

- One app, one owner, 10 tasks, each run once per model (most review checks from 23 Sep on ran twice). Treat the ranking as a starting point, then run your own (`bakeoff/`).
- Model names and prices are as of Sep-Oct 2026.
