#!/usr/bin/env python3
"""Coding bake-off: real tasks from a repo's git history, one throwaway worktree per (task, contestant).

Each task resets the target repo to the parent of a real commit, drops in that commit's test files, gives the
model the task, then restores the test files and runs the judge commands. PASS means every judge command exits 0.

    python3 bakeoff.py validate                 # each task must fail at the parent and pass at the commit
    python3 bakeoff.py run [--tasks t1,..] [--contestants opus,..]
    python3 bakeoff.py report                   # results table from runs/*.json

Worktrees live under bakeoff/work/ (keep this folder under a "personal" or "open" rule in model-policy.json,
or outside routes are refused) and are removed after judging. Diffs are kept in runs/.
"""
import argparse, json, os, re, shlex, shutil, subprocess, sys, threading, time
from pathlib import Path
CLUPAI_HOME = os.path.expanduser(os.environ.get('CLUPAI_HOME') or (
    '~/clupai' if os.path.isdir(os.path.expanduser('~/clupai'))
    else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))  # where this repo is installed

HERE = Path(__file__).resolve().parent
# BAKEOFF_TASKS picks the task file (default tasks.json, round 1); each file has one repo and its own runs dir
TASKS_FILE = HERE / os.environ.get('BAKEOFF_TASKS', 'tasks.json')
CFG = json.loads(TASKS_FILE.read_text())
REPO = Path(os.path.expanduser(CFG['repo']))
WORK, RUNS = HERE / 'work', HERE / CFG.get('runs', 'runs')
SO = os.path.join(CLUPAI_HOME, 'scripts/second_opinion.py')
TIMEOUT = int(os.environ.get('BAKEOFF_TIMEOUT_MIN', '45')) * 60
KIMI_BUDGET = 15.0   # USD, the owner's cap for the whole bake-off
KIMI_FLOOR = 0.40    # stop starting kimi runs below this balance

# contestant -> (lane, kind, model). One lane runs its jobs one at a time, so balance diffs are per run.
CONTESTANTS = {
    'opus':    ('claude', 'claude', 'claude-opus-5'),
    'opus55':  ('claude', 'claude', 'claude-opus-5-5'),   # released 2026-09-23
    'fable':   ('claude', 'claude', 'claude-fable-5-1'),
    'astra':   ('codex', 'codex', 'gpt-6-astra'),
    'sol':     ('codex-sol', 'codex', 'gpt-6-sol'),     # released 2026-09-22; own lanes so they run side by side
    'luna':    ('codex-luna', 'codex', 'gpt-6-luna'),
    'kimi':    ('kimi', 'so', 'kimi:kimi-k3'),
    'ds-flash': ('dsh', 'so', 'dsh:deepseek-flash'),
    'ds-pro':  ('dsh', 'so', 'dsh:deepseek-v4-pro'),
    'glm':     ('go', 'so', 'opencode:opencode-go/glm-5.3'),
    'grok':    ('go', 'so', 'opencode:opencode-go/grok-4.6'),
    'minimax': ('go', 'so', 'opencode:opencode-go/minimax-m3'),
    # the same three through OpenRouter, after the Go account ran out of funds (22 Sep)
    'glm-or':  ('or', 'so', 'opencode:openrouter/z-ai/glm-5.3'),
    'grok-or': ('or', 'so', 'opencode:openrouter/x-ai/grok-4.6'),
    'minimax-or': ('or', 'so', 'opencode:openrouter/minimax/minimax-m3'),
    'gemini':  ('agy', 'so', 'agy:gemini-3.8-flash-high'),   # Antigravity CLI, plan quota
    # newer OpenRouter models, 22 Sep; own lane so they run beside the GLM/Grok/MiniMax round 2
    'ds41-or': ('or2', 'so', 'opencode:openrouter/deepseek/deepseek-v4.1-flash'),
    'mimo-or': ('or2', 'so', 'opencode:openrouter/xiaomi/mimo-v2.6-pro'),
    'hy4-or': ('or2', 'so', 'opencode:openrouter/tencent/hy4-preview'),
    'grok47-or': ('or2', 'so', 'opencode:openrouter/x-ai/grok-4.7'),
    'qwenmax-or': ('or2', 'so', 'opencode:openrouter/qwen/qwen3.8-max-0902'),
    'fugu-or': ('or2', 'so', 'opencode:openrouter/sakana/fugu-max'),
    'glmflash-or': ('or2', 'so', 'opencode:openrouter/z-ai/glm-5.3-flash'),
    # cheap screening round, 29 Sep: 2 short tasks + 1 review case before paying for a full run
    'qwenflash-or': ('or2', 'so', 'opencode:openrouter/qwen/qwen3.8-flash'),
    'mimoflash-or': ('or2', 'so', 'opencode:openrouter/xiaomi/mimo-v2.6-flash'),
    'inkling-or': ('or2', 'so', 'opencode:openrouter/thinkingmachines/inkling'),
    'grok-build': ('grok', 'so', 'grok:grok-4.7'),  # Grok Build CLI on the Grok plan quota, 22 Sep
    'muse-or': ('or3', 'so', 'opencode:openrouter/meta/muse-spark-1.3'),  # needs the account's 18+ confirmation
    # Sonnet 5.5 check, 29 Sep; optional 4th field is the Claude effort (default high); own lanes so they run side by side
    'sonnet55': ('claude-s55', 'claude', 'claude-sonnet-5-5'),
    'sonnet55-low': ('claude-s55l', 'claude', 'claude-sonnet-5-5', 'low'),
    'opus55-low': ('claude-o55l', 'claude', 'claude-opus-5-5', 'low'),
    # Haiku 5.5 check, 10 Oct
    'haiku55-low': ('claude-h55l', 'claude', 'claude-haiku-5-5', 'low'),
    'haiku55': ('claude-h55', 'claude', 'claude-haiku-5-5'),
    # multi-model workflows, 10 Oct. 'plan': planner model+effort writes a plan (no edits), executor model+effort implements it.
    # 'orch': one Claude session that delegates the coding to subagents pinned to the listed models.
    'p-opus-haiku': ('claude-pOH', 'plan', 'claude-opus-5-5', 'high', 'claude-haiku-5-5', 'low'),
    'p-opus-sonnet': ('claude-pOS', 'plan', 'claude-opus-5-5', 'high', 'claude-sonnet-5-5', 'low'),
    'p-sonnet-haiku': ('claude-pSH', 'plan', 'claude-sonnet-5-5', 'high', 'claude-haiku-5-5', 'low'),
    'o-opus-haiku': ('claude-oOH', 'orch', 'claude-opus-5-5', 'low', ['haiku']),
    'o-opus-sonnet': ('claude-oOS', 'orch', 'claude-opus-5-5', 'low', ['sonnet']),
    'o-opus-both': ('claude-oOB', 'orch', 'claude-opus-5-5', 'low', ['haiku', 'sonnet']),
    # 'adv': executor model+effort with Claude Code's advisor (advisorModel); last field = remind it to consult the advisor
    'a-haiku-opus': ('claude-aHO', 'adv', 'claude-haiku-5-5', 'low', 'opus', True),
    'a-haiku-opus-norem': ('claude-aHOn', 'adv', 'claude-haiku-5-5', 'low', 'opus', False),
    'a-sonnet-opus': ('claude-aSO', 'adv', 'claude-sonnet-5-5', 'low', 'opus', True),
    'sol61': ('codex-sol61', 'codex', 'gpt-6.1-sol'),
    # GLM-5.3 from Z.ai's own API, through Claude Code's Anthropic-compatible endpoint (key: keychain zai-api)
    'glm-zai': ('zai', 'zai', 'glm-5.3', 'high'),   # released 29 Sep (DevDay)
    # Gemini 4 Argon on Vertex (owner-only lane: your GCP project, gcloud account in BAKEOFF_VERTEX_ACCOUNT, your own opencode-vertex.json), OpenCode agent loop, 14 Oct
    'argon': ('vertex', 'so', 'opencode:vertex/gemini-4-argon'),
    # Meta Muse Code CLI (~/.local/bin/muse) on the Muse subscription, reasoning high, 27 Oct (owner-only lane)
    'muse': ('muse', 'muse', 'muse-wonder-full-1.0'),
}
MUSE = os.path.expanduser('~/.local/bin/muse')
MUSE_NETFAIL = 'network connection could not be opened'


def muse_exec(prompt_file, cwd, model, effort='high', extra='', timeout=None):
    """One headless Muse Code run. Returns (exit, answer, usage) from its JSONL events."""
    cmd = (f'"{MUSE}" exec --json --yolo --model {model} --reasoning-effort {effort} --workspace "{cwd}" '
           f'--disable-web-tools --disable-request-user-input --prompt-file "{prompt_file}" {extra}')
    code, out = sh(cmd, cwd=cwd, timeout=timeout or TIMEOUT)
    answer, usage = None, {}
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get('payload') or {}
        if d.get('payload_type') == 'run.terminal.completed' or p.get('kind') == 'run_terminal':
            answer = (answer or '') + (p.get('text') or '') + (f' [terminal={p.get("terminal")} {p.get("reason")}]'
                                                              if p.get('terminal') != 'completed' else '')
        if d.get('payload_type') == 'run.usage':
            usage = p
    return code, answer if answer is not None else out[-3000:], usage
# the cm account (~/.claude-alt) was removed 24 Sep; Claude runs go on cx unless told otherwise
# main by default (owner, 10 Oct): cx is only upgraded when needed, so it runs out fast. 'main' = the default login
CLAUDE_DIR = os.path.expanduser(os.environ.get('BAKEOFF_CLAUDE_DIR', 'main'))
OR_FLOOR = 1.50  # stop starting OpenRouter runs below this many dollars of credit
LOCK = threading.Lock()
if os.environ.get('BAKEOFF_NODE_BIN'):   # e.g. a pinned Node version's bin dir
    os.environ['PATH'] = os.environ['BAKEOFF_NODE_BIN'] + ':' + os.environ['PATH']
BASELINE = HERE / CFG.get('baseline', 'baseline.json')   # scraper test files that already fail at each task's commit
REGRESS = 'REGRESS'            # judge entry: every scraper test file; only files that pass at the commit count
REGRESS_JEST = 'REGRESS_JEST'  # same for the app's jest suites in __tests__
MODES = {REGRESS: {'root': 'scrapers', 'dirs': ['lib', 'test']}, REGRESS_JEST: {'root': '', 'dirs': ['__tests__']}}


def regress_failures(wt, ref, mode):
    """Every test file tracked at ref (the tree the run started from), plus any on disk, run and failing ones returned.
    Names are relative to the mode's root. A tracked file a contestant deleted, or a symlinked test, counts as failing."""
    m = MODES[mode]
    root = wt / m['root'] if m['root'] else wt
    prefix = m['root'] + '/' if m['root'] else ''
    r = git('ls-tree', '-r', '--name-only', ref, *[prefix + d for d in m['dirs']])  # asked of the source repo, not the worktree
    if r.returncode:
        raise RuntimeError(f'ls-tree {ref} failed: {r.stderr}')
    files = {p[len(prefix):] for p in r.stdout.split() if p.endswith('.test.js') and p[len(prefix):].count('/') == 1}
    files |= {str(p.relative_to(root)) for d in m['dirs'] for p in (root / d).glob('*.test.js')}
    bad, run = [], []
    for f in sorted(files):
        if (root / f).is_symlink():
            bad.append(f'SYMLINK:{f}')  # never run a linked test; never excused
        elif not (root / f).is_file():
            bad.append(f'MISSING:{f}')  # never excused by the baseline
        else:
            run.append(f)
    env = dict(os.environ, NODE_ENV='test', FIRESTORE_EMULATOR_HOST='')
    if mode == REGRESS:
        for f in run:
            code, out = sh(f'node {shlex.quote(f)}', cwd=root, timeout=300, env=env)
            if code:
                bad.append(f)
    elif run:
        report = wt.parent / f'{wt.name}.jest.json'
        sh(f'npx jest --ci --json --outputFile={shlex.quote(str(report))} ' + ' '.join(shlex.quote(f) for f in run),
           cwd=root, timeout=1200, env=env)
        try:
            results = json.loads(report.read_text())['testResults']
            passed = {str(Path(t['name']).resolve().relative_to(root.resolve())) for t in results if t['status'] == 'passed'}
        except (OSError, ValueError, KeyError):
            passed = set()
        report.unlink(missing_ok=True)
        bad += [f for f in run if f not in passed]  # a suite jest never reported counts as failing
    return bad


def sh(cmd, cwd=None, timeout=600, env=None, stdin=None):
    """Run a shell string in its own process group; return (code, output)."""
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, env=env, text=True, start_new_session=True,
                         stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(stdin, timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, 9)
        out, _ = p.communicate()
        return 124, (out or '') + '\n[timeout]'


def start_of(task):
    """The commit a contestant starts from: the task commit's parent, or `start` for a task spanning several commits."""
    return task.get('start') or f'{task["commit"]}^'


def git(*args, cwd=REPO):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)


def keychain(name):
    return subprocess.run(['security', 'find-generic-password', '-s', name, '-w'],
                          capture_output=True, text=True).stdout.strip()


def kimi_balance():
    out = subprocess.run(['curl', '-s', '-H', f'Authorization: Bearer {keychain("kimi-api")}',
                          '/'.join(['https://api.moonshot.ai/v1', 'users', 'me', 'balance'])], capture_output=True, text=True).stdout
    return float(json.loads(out)['data']['available_balance'])


def deepseek_balance():
    out = subprocess.run(['curl', '-s', '-H', f'Authorization: Bearer {keychain("deepseek-api")}',
                          'https://api.deepseek.com/user/balance'], capture_output=True, text=True).stdout
    return float(json.loads(out)['balance_infos'][0]['total_balance'])


def openrouter_balance():
    key = os.environ.get('OPENROUTER_API_KEY', '')
    out = subprocess.run(['curl', '-s', '-H', f'Authorization: Bearer {key}', 'https://openrouter.ai/api/v1/credits'],
                         capture_output=True, text=True).stdout
    d = json.loads(out)['data']
    return round(float(d['total_credits']) - float(d['total_usage']), 4)


def make_worktree(task, name, ref):
    wt = WORK / name
    if wt.exists():
        drop_worktree(wt)
    r = git('worktree', 'add', '--detach', str(wt), ref)
    if r.returncode:
        raise RuntimeError(r.stderr)
    for link in CFG['links']:
        if (wt / link).parent.is_dir() and (REPO / link).exists():
            (wt / link).symlink_to(REPO / link)
    return wt


def put_tests(task, wt):
    """Write the task commit's version of every test file into the worktree."""
    for path in task['tests']:
        r = git('show', f'{task["commit"]}:{path}')
        if r.returncode:
            raise RuntimeError(f'{path} is not in {task["commit"]}')
        blob = r.stdout
        target = wt / path
        for part in [target, *target.parents]:
            if part == wt:
                break
            if part.is_symlink():  # never write through a link a contestant made
                raise RuntimeError(f'refusing to restore {path}: {part} is a symlink')
        (wt / path).parent.mkdir(parents=True, exist_ok=True)
        (wt / path).write_text(blob)


def drop_worktree(wt):
    for link in CFG['links']:
        if (wt / link).is_symlink():
            (wt / link).unlink()
    git('worktree', 'remove', '--force', str(wt))
    shutil.rmtree(wt, ignore_errors=True)
    git('worktree', 'prune')


def judge(task, wt, baseline=None, start_ref=None):
    res = []
    start_ref = start_ref or start_of(task)
    for cmd in task['judge']:
        t0 = time.time()
        if cmd in MODES:
            m = MODES[cmd]
            prefix = m['root'] + '/' if m['root'] else ''
            # put back every other tracked test, so an edited or emptied one cannot hide a regression
            start = git('rev-parse', start_ref).stdout.strip()  # the tree the contestant started from; its HEAD is mutable
            others = [p for p in git('ls-tree', '-r', '--name-only', start, *[prefix + d for d in m['dirs']]).stdout.split()
                      if p.endswith('.test.js') and p not in task['tests']]
            if not start or (others and git('checkout', start, '--', *others, cwd=wt).returncode):
                res.append({'cmd': cmd, 'ok': False, 'secs': 0, 'tail': 'could not restore tracked tests'})
                continue
            bad = regress_failures(wt, start, cmd)
            tracked = {p[len(prefix):] for p in git('ls-tree', '-r', '--name-only', start, *([m['root']] if m['root'] else [])).stdout.split()}
            # a known failure is excused only for a file that was already in the tree the contestant started from
            known = set((baseline if baseline is not None else load_baseline()).get(task['id'], [])) & tracked
            new = [f for f in bad if f not in known]
            res.append({'cmd': cmd, 'ok': not new, 'secs': round(time.time() - t0), 'failing': bad, 'tail': f'new failures: {new}'})
            continue
        code, out = sh(cmd, cwd=wt, timeout=600, env=dict(os.environ, FIRESTORE_EMULATOR_HOST=''))
        res.append({'cmd': cmd, 'ok': code == 0, 'secs': round(time.time() - t0), 'tail': out[-600:]})
    return res


def load_baseline():
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {}


def prompt_for(task):
    shown = [{REGRESS: 'cd scrapers && npm test   (files that already fail before your change may keep failing)',
              REGRESS_JEST: 'npx jest   (the whole app suite; suites that already fail before your change may keep failing)'}.get(c, c)
             for c in task['judge']]
    checks = '\n'.join(f'    {c}' for c in shown)
    tests = ', '.join(task['tests'])
    intro = CFG.get('intro', 'the target repo (set intro in the tasks file)')
    return f"""You are in a disposable git worktree of {intro}. node_modules are already installed.

TASK
{task['task']}

These files are already updated in the tree and define the expected behaviour: {tests}
Do NOT edit them; change source code only.

Run these checks yourself (from the worktree root) and keep working until they all pass:
{checks}

Rules: do not commit, push or deploy; do not install packages or use the network; stay inside this folder; work alone
(no subagents, no other models, no MCP tools). This is a headless one-shot run: nobody will answer questions, so never
stop to ask. When done, reply with a short summary of what you changed.
"""


PLAN_STEP = """

PLANNING STEP ONLY. You are the planner. Another engineer (a cheaper model) will implement this from your plan, with no
other context. Read the code and the test files now and write a concrete implementation plan: the files and functions to
change, the exact behaviour each must have, the edge cases the tests check, and the order to work in. You may run the
checks to see what fails. Do NOT edit or create any files. Reply with only the plan."""

EXEC_STEP = """

PLAN FROM THE PLANNER (a senior engineer who read the code). Follow it, but trust the code and the tests if they disagree:
"""

ADV_REMIND = ('\n\nYou have an advisor (a stronger model). Consult it after you have read the relevant code and before you '
              'start editing, and once more before you declare the task done.')

ORCH_RULE = ('work alone (no subagents, no other models, no MCP tools)',
             'no MCP tools. You are the lead: plan, check and verify, but delegate the code editing to your coder '
             'subagent(s) ({names}). When you call one, pass its model and effort exactly as listed ({calls}); this '
             'experiment fixes the models, so do not pick others')


ZAI_PRICE = {'in': 1.40, 'cached': 0.26, 'out': 4.40}   # $ per M tokens, docs.z.ai pricing, 10 Oct 2026


def vertex_env():
    """OpenCode env for the Vertex provider in opencode-vertex.json: a fresh 1-hour token per run (runs are < 45 min)."""
    tok = subprocess.run(['gcloud', 'auth', 'print-access-token', '--account=' + os.environ.get('BAKEOFF_VERTEX_ACCOUNT', '')],
                         capture_output=True, text=True, check=True).stdout.strip()
    return dict(os.environ, VERTEX_TOKEN=tok, OPENCODE_CONFIG=str(HERE / 'opencode-vertex.json'))


def zai_env():
    d = WORK / 'zai-claude-config'   # its own config dir, so no Claude login gets mixed in
    d.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('ANTHROPIC_') and k != 'CLAUDE_CONFIG_DIR'}
    env.update(CLAUDE_CONFIG_DIR=str(d), ANTHROPIC_BASE_URL='https://api.z.ai/api/anthropic',
               ANTHROPIC_AUTH_TOKEN=keychain('zai-api'), API_TIMEOUT_MS='3000000',
               ANTHROPIC_DEFAULT_OPUS_MODEL='glm-5.3', ANTHROPIC_DEFAULT_SONNET_MODEL='glm-5.3',
               ANTHROPIC_DEFAULT_HAIKU_MODEL='glm-5.3-flash')
    return env


def claude_session(task, wt, model, effort, prompt, flags, env=None):
    """One headless Claude run with the session-limit retry. Returns the parsed JSON (or {'result': raw tail})."""
    if env is None:
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CONFIG_DIR'}
        if CLAUDE_DIR != 'main':
            env['CLAUDE_CONFIG_DIR'] = CLAUDE_DIR
    cmd = (f'claude -p --model {model} --effort {effort} --output-format json --permission-mode bypassPermissions '
           f'--strict-mcp-config --max-budget-usd 25 {flags}')
    for _ in range(6):
        code, out = sh(cmd, cwd=wt, timeout=TIMEOUT, env=env, stdin=prompt)
        if 'hit your session limit' not in out and 'usage limit' not in out.lower():
            break
        with LOCK:
            print(f'{time.strftime("%H:%M:%S")} {task["id"]} {model}: Claude session limit, retrying in 30 min', flush=True)
        git('checkout', '--', '.', cwd=wt)
        git('clean', '-fdq', '-e', 'node_modules', cwd=wt)
        put_tests(task, wt)
        time.sleep(1800)
    try:
        return json.loads(out[out.index('{'):])
    except ValueError:
        return {'result': out[-800:] or '[timeout]'}


def run_workflow(name, task, wt, prompt):
    lane, kind, *cfg = CONTESTANTS[name]
    info = {'cost_note': 'API-equivalent from Claude Code, all models summed'}
    if kind == 'plan':
        pm, pe, em, ee = cfg
        p = claude_session(task, wt, pm, pe, prompt + PLAN_STEP,
                           '--disallowedTools "Agent Edit Write NotebookEdit MultiEdit"')
        git('checkout', '--', '.', cwd=wt)   # a planner must not leave edits behind
        git('clean', '-fdq', '-e', 'node_modules', cwd=wt)
        put_tests(task, wt)
        plan = str(p.get('result') or '')
        e = claude_session(task, wt, em, ee, prompt + EXEC_STEP + plan, '--disallowedTools Agent')
        parts = {'plan': p, 'exec': e}
        info['plan_chars'] = len(plan)
    elif kind == 'zai':
        m, e = cfg
        z = claude_session(task, wt, m, e, prompt, '--disallowedTools Agent', env=zai_env())
        cost = 0.0
        for u in (z.get('modelUsage') or {}).values():
            cost += ((u.get('inputTokens') or 0) + (u.get('cacheCreationInputTokens') or 0)) * ZAI_PRICE['in'] / 1e6
            cost += (u.get('cacheReadInputTokens') or 0) * ZAI_PRICE['cached'] / 1e6
            cost += (u.get('outputTokens') or 0) * ZAI_PRICE['out'] / 1e6
        z['total_cost_usd'] = cost   # Claude Code would price the tokens at Anthropic rates
        parts = {'exec': z}
        info['cost_note'] = 'Z.ai list price from token counts'
    elif kind == 'adv':
        em, ee, adv, remind = cfg
        a = claude_session(task, wt, em, ee, prompt + (ADV_REMIND if remind else ''),
                           "--disallowedTools Agent --settings " + shlex.quote(json.dumps({'advisorModel': adv})))
        parts = {'exec': a}
    else:
        om, oe, subs = cfg
        agents = {f'coder-{m}': {'description': f'Coder on {m}: implements the changes the lead describes.',
                                 'prompt': 'You are a coder working for a lead engineer. Implement exactly what you are '
                                           'asked in this worktree, run the checks you are given, and report back briefly.',
                                 'model': m, 'effort': 'low'} for m in subs}
        names = ', '.join(agents)
        calls = '; '.join(f'coder-{m}: model "{m}", effort "low"' for m in subs)
        old, new = ORCH_RULE
        pat = r'\s+'.join(map(re.escape, old.split()))   # the rule wraps across lines in the prompt
        lead = re.sub(pat, new.format(names=names, calls=calls), prompt)
        assert lead != prompt
        o = claude_session(task, wt, om, oe, lead,
                           "--agents " + shlex.quote(json.dumps(agents)))
        parts = {'orch': o}
    info['cost_usd'] = round(sum(x.get('total_cost_usd') or 0 for x in parts.values()), 4) or None
    info['turns'] = sum(x.get('num_turns') or 0 for x in parts.values()) or None
    info['by_model'] = {}
    for x in parts.values():
        for m, u in (x.get('modelUsage') or {}).items():
            info['by_model'][m] = round(info['by_model'].get(m, 0) + (u.get('costUSD') or 0), 4)
    info['answer'] = str(list(parts.values())[-1].get('result'))[-800:]
    return info


def run_contestant(name, task, wt, prompt_file):
    lane, kind, model, *rest = CONTESTANTS[name]
    effort = rest[0] if rest else 'high'
    prompt = prompt_file.read_text()
    info = {'turns': None, 'cost_usd': None, 'tokens': None, 'cost_note': ''}
    if kind in ('plan', 'orch', 'adv', 'zai'):
        info.update(run_workflow(name, task, wt, prompt))
        code = 0
    elif kind == 'claude':
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CONFIG_DIR'}
        if CLAUDE_DIR != 'main':  # main's login lives under the default dir, which breaks if named explicitly
            env['CLAUDE_CONFIG_DIR'] = CLAUDE_DIR
        cmd = (f'claude -p --model {model} --effort {effort} --output-format json --permission-mode bypassPermissions '
               f'--strict-mcp-config --disallowedTools Agent --max-budget-usd 25')
        for _ in range(6):  # a Claude session limit is not the model failing: wait for the reset and retry
            code, out = sh(cmd, cwd=wt, timeout=TIMEOUT, env=env, stdin=prompt)
            if 'hit your session limit' not in out and 'usage limit' not in out.lower():
                break
            with LOCK:
                print(f'{time.strftime("%H:%M:%S")} {task["id"]} {name}: Claude session limit, retrying in 30 min', flush=True)
            git('checkout', '--', '.', cwd=wt)
            git('clean', '-fdq', '-e', 'node_modules', cwd=wt)
            put_tests(task, wt)
            time.sleep(1800)
        try:
            d = json.loads(out[out.index('{'):])
            info.update(turns=d.get('num_turns'), cost_usd=d.get('total_cost_usd'), answer=str(d.get('result'))[-800:],
                        tokens=d.get('usage'), cost_note='API-equivalent from Claude Code')
        except ValueError:
            info['answer'] = out[-800:]
    elif kind == 'codex':
        last = wt.parent / f'{wt.name}.last.txt'
        cmd = (f'codex exec --json --skip-git-repo-check -m {model} -c model_reasoning_effort=high -s workspace-write -C "{wt}" -o "{last}" -')
        code, out = sh(cmd, cwd=wt, timeout=TIMEOUT, stdin=prompt)
        tok, turns = {'input': 0, 'cached': 0, 'output': 0}, 0
        for line in out.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('type') == 'turn.completed':
                u = d.get('usage') or {}
                tok['input'] += u.get('input_tokens', 0)
                tok['cached'] += u.get('cached_input_tokens', 0)
                tok['output'] += u.get('output_tokens', 0)
            if d.get('type') == 'item.completed' and (d.get('item') or {}).get('type') in ('command_execution', 'file_change'):
                turns += 1
        info.update(turns=turns, tokens=tok, cost_note='ChatGPT plan; tokens only',
                    answer=last.read_text()[-800:] if last.exists() else out[-800:])
        last.unlink(missing_ok=True)
    elif kind == 'muse':
        for netfails in range(4):  # Meta's transport drops (27 Oct) are not the model failing: reset, wait, retry
            code, answer, u = muse_exec(prompt_file, wt, model, effort)
            if MUSE_NETFAIL not in str(answer) or netfails == 3:
                break
            with LOCK:
                print(f'{time.strftime("%H:%M:%S")} {task["id"]} {name}: Muse network drop, retrying in 5 min', flush=True)
            git('checkout', '--', '.', cwd=wt)
            git('clean', '-fdq', '-e', 'node_modules', cwd=wt)
            put_tests(task, wt)
            time.sleep(300)
        m = (u.get('models') or [{}])[0]
        info.update(turns=u.get('calls'), answer=str(answer)[-800:], quota=u.get('allowance'), netfails=netfails,
                    tokens={k: m.get(k) for k in ('input_tokens', 'cached_tokens', 'output_tokens', 'reasoning_tokens')},
                    cost_note='Muse subscription; tokens and allowance only')
    else:
        before ={'kimi': kimi_balance, 'dsh': deepseek_balance, 'or': openrouter_balance}.get(lane, lambda: None)()
        cmd = f'python3 "{SO}" "{prompt_file}" --cwd "{wt}" --write --ladder {model} --timeout {TIMEOUT}'
        code, out = sh(cmd, cwd=wt, timeout=TIMEOUT + 120, env=vertex_env() if lane == 'vertex' else None)
        attempts = [json.loads(l) for l in out.splitlines() if l.startswith('{"provider"')]
        a = attempts[-1] if attempts else {}
        info.update(tokens=a.get('usage'), answer=out[-800:], route_ok=a.get('ok'), quota=a.get('quota'),
                    route_error=a.get('error'))
        if lane == 'or':
            info.update(bal_before=before, cost_usd=(a.get('usage') or {}).get('cost'),
                        cost_note='OpenCode-reported cost; OpenRouter credit diff in report')
        elif lane in ('kimi', 'dsh'):
            # the balance updates minutes late, so cost = this run's starting balance minus the next run's
            # (or the lane's end balance); `report` fills it in from bal_before
            info.update(bal_before=before, cost_note=f'{lane} balance diff to the next run in the lane')
        elif lane == 'vertex':
            info.update(cost_usd=(a.get('usage') or {}).get('cost'),
                        cost_note='OpenCode cost at Vertex on-demand list price $4/$20 per 1M (GCP credits)')
        elif lane == 'grok':
            u = a.get('usage') or {}
            info.update(cost_usd=u.get('cost'), turns=u.get('turns'),
                        cost_note='Grok Build notional API price; billed to the Grok plan quota')
        else:
            info.update(cost_usd=(a.get('usage') or {}).get('cost'), cost_note='OpenCode Go reported cost')
    info['exit'] = code
    return info


def one(task, name):
    out_json = RUNS / f'{task["id"]}__{name}.json'
    if out_json.exists() and json.loads(out_json.read_text()).get('judged'):
        return
    if (HERE / f'PAUSE-{CONTESTANTS[name][0]}').exists():  # e.g. PAUSE-or: skip this lane, write nothing, run later
        return
    if CONTESTANTS[name][0] in ('or', 'or2', 'or3') and openrouter_balance() < OR_FLOOR:
        out_json.write_text(json.dumps({'task': task['id'], 'contestant': name, 'skipped': 'OpenRouter credit below floor'}))
        return
    if CONTESTANTS[name][0] == 'kimi':
        bal = kimi_balance()
        if bal < KIMI_FLOOR:
            out_json.write_text(json.dumps({'task': task['id'], 'contestant': name, 'skipped': f'kimi balance {bal}'}))
            return
    wt = make_worktree(task, f'{task["id"]}__{name}', start_of(task))
    try:
        put_tests(task, wt)
        pf = RUNS / f'{task["id"]}.prompt.txt'
        pf.write_text(prompt_for(task))
        t0 = time.time()
        info = run_contestant(name, task, wt, pf)
        info['started'] = t0
        wall = round(time.time() - t0)
        # did it touch the test files? record, then restore them before judging
        tampered = [p for p in task['tests'] if (wt / p).read_text() != git('show', f'{task["commit"]}:{p}').stdout]
        git('add', '-A', '--', '.', ':!node_modules', ':!scrapers/node_modules', cwd=wt)
        diff = git('diff', '--cached', start_of(task), '--', '.', *[f':(exclude){p}' for p in task['tests']], cwd=wt).stdout
        (RUNS / f'{task["id"]}__{name}.diff').write_text(diff)
        put_tests(task, wt)
        checks = judge(task, wt)
        rec = dict(task=task['id'], contestant=name, model=CONTESTANTS[name][2], wall_secs=wall,
                   passed=all(c['ok'] for c in checks), checks=checks, tampered_tests=tampered,
                   diff_lines=sum(1 for l in diff.splitlines() if l[:1] in '+-' and l[:3] not in ('+++', '---')),
                   rescues=0, judged=True, **info)
        out_json.write_text(json.dumps(rec, indent=1))
        with LOCK:
            print(f'{time.strftime("%H:%M:%S")} {task["id"]:18} {name:9} {"PASS" if rec["passed"] else "fail"} '
                  f'{wall}s cost={rec.get("cost_usd")} turns={rec.get("turns")}', flush=True)
    finally:
        drop_worktree(wt)


def lane_worker(jobs):
    lane = CONTESTANTS[jobs[0][1]][0]
    for task, name in jobs:
        try:
            one(task, name)
        except Exception as e:  # keep the lane going; the error is in the record
            (RUNS / f'{task["id"]}__{name}.json').write_text(json.dumps(
                {'task': task['id'], 'contestant': name, 'error': repr(e)[:1000]}))
            with LOCK:
                print(f'ERROR {task["id"]} {name}: {e!r}'[:300], flush=True)
    if lane in ('kimi', 'dsh', 'or'):
        time.sleep(240)
        bal = {'kimi': kimi_balance, 'dsh': deepseek_balance, 'or': openrouter_balance}[lane]()
        (RUNS / f'lane-{lane}-end.json').write_text(json.dumps({'balance': bal, 'at': time.time()}))


def cmd_run(a):
    tasks = [t for t in CFG['tasks'] if not a.tasks or t['id'].split('-')[0] in a.tasks.split(',')]
    names = a.contestants.split(',') if a.contestants else list(CONTESTANTS)
    lanes = {}
    for t in tasks:
        for n in names:
            lanes.setdefault(CONTESTANTS[n][0], []).append((t, n))
    threads = [threading.Thread(target=lane_worker, args=(jobs,)) for jobs in lanes.values()]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


def cmd_validate(a):
    for t in CFG['tasks']:
        if a.tasks and t['id'].split('-')[0] not in a.tasks.split(','):
            continue
        row = []
        for label, ref in (('commit', t['commit']), ('parent', start_of(t))):
            wt = make_worktree(t, f'validate-{t["id"]}-{label}', ref)
            try:
                put_tests(t, wt)
                mode = next((c for c in t['judge'] if c in MODES), None)
                if label == 'commit' and mode:
                    base = load_baseline()
                    base[t['id']] = regress_failures(wt, t['commit'], mode)
                    BASELINE.write_text(json.dumps(base, indent=1))
                res = judge(t, wt, start_ref=ref)
                row.append((label, [c['ok'] for c in res], res))
            finally:
                drop_worktree(wt)
        print(t['id'], ' '.join(f'{l}={oks}' for l, oks, _ in row), flush=True)
        for c in row[0][2]:
            if not c['ok']:
                print('   commit FAILS:', c['cmd'], '\n', c['tail'][-400:])


def fill_balance_costs(recs):
    """cost = balance before this run - balance before the next run of the same lane (or the lane's end balance)."""
    for lane in ('kimi', 'dsh', 'or'):
        runs = sorted((r for r in recs if r.get('bal_before') is not None and CONTESTANTS[r['contestant']][0] == lane),
                      key=lambda r: r['started'])
        end = RUNS / f'lane-{lane}-end.json'
        end_bal = json.loads(end.read_text())['balance'] if end.exists() else None
        for i, r in enumerate(runs):
            nxt = runs[i + 1]['bal_before'] if i + 1 < len(runs) else end_bal
            if nxt is not None and (r.get('cost_usd') is None or lane == 'or'):
                r['cost_usd'] = round(r['bal_before'] - nxt, 4)


def cmd_report(a):
    recs = [json.loads(p.read_text()) for p in sorted(RUNS.glob('*__*.json'))]
    fill_balance_costs(recs)
    names = list(CONTESTANTS)
    tasks = [t['id'] for t in CFG['tasks']]
    by = {(r['task'], r['contestant']): r for r in recs}
    print('| contestant | ' + ' | '.join(tasks) + ' | passed | cost $ | wall min |')
    print('|' + '---|' * (len(tasks) + 4))
    for n in names:
        cells, npass, cost, wall = [], 0, 0.0, 0
        for t in tasks:
            r = by.get((t, n))
            if not r:
                cells.append('-')
            elif 'skipped' in r or 'error' in r:
                cells.append('skip' if 'skipped' in r else 'err')
            else:
                npass += r['passed']
                cost += r.get('cost_usd') or 0
                wall += r['wall_secs']
                cells.append(('PASS' if r['passed'] else 'fail') + ('*' if r['tampered_tests'] else ''))
        print(f'| {n} | ' + ' | '.join(cells) + f' | {npass}/{len(tasks)} | {cost:.2f} | {wall / 60:.0f} |')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['validate', 'run', 'report'])
    ap.add_argument('--tasks')
    ap.add_argument('--contestants')
    a = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)
    {'validate': cmd_validate, 'run': cmd_run, 'report': cmd_report}[a.cmd](a)


if __name__ == '__main__':
    main()
