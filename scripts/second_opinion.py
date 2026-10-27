#!/usr/bin/env python3
"""Ask a non-Claude model, falling back down a ladder when one is out of quota or fails.

Usage:
  second_opinion.py PROMPT_FILE [--cwd DIR] [--network] [--confidential] [--write] [--ladder NAME,NAME,...] [--timeout SECS]
                    [--review [--base BASE]] [--codex-effort low|medium|high|xhigh]

  --review        code review of the git diff in --cwd: the uncommitted changes (plus BASE...HEAD with --base) go
                  into the prompt with a brief that keeps the reviewer on it, and PROMPT_FILE adds what to focus
                  on ('-' or an empty file for none). Much cheaper than letting a reviewer explore the repo.
  --codex-effort  reasoning effort for codex without --write (default medium). Read-only codex runs are lean: no
                  user config (plugins, MCP servers, hooks), only auth and the model from ~/.codex/config.toml.

Prints the model's final answer on stdout. Prints one JSON line on stderr per attempt:
{"provider":..., "model":..., "ok":..., "secs":..., "usage":..., "quota":..., "error":...}

Ladder entries (default order is LADDER below, from the 22 Sep 2026 app bake-off):
  codex                         Codex CLI, your ChatGPT plan
  codex:<model>                 same, with a set model (codex:gpt-6.1-sol = coding on the Codex plan)
  agy:<model>                   Google Antigravity CLI, e.g. agy:gemini-3.8-flash-medium
  dsh:<model>                   DeepSeek's own CLI on the direct API (own key), e.g. dsh:deepseek-flash, dsh:deepseek-v4-pro
  kimi:<model>                  Kimi Code CLI on the Moonshot platform API (own key, keychain kimi-api), e.g. kimi:kimi-k3
  grok:<model>                  Grok Build CLI on your Grok plan (grok login), e.g. grok:grok-4.7, grok:grok-4.7-build-fast
  opencode:<provider/model>     OpenCode on OpenRouter, e.g. opencode:openrouter/z-ai/glm-5.3 (GLM, Grok, Qwen, MiniMax;
                                DeepSeek goes through dsh and Kimi through kimi; OpenCode Go was dropped 22 Sep 2026)

Safety (agy, dsh, kimi, grok, opencode run inside a macOS sandbox-exec profile; codex uses its own -s sandbox):
  reads           the sandbox denies reading $HOME, /Users, /Volumes and the world temp dirs, then re-allows only
                  the repo under review (plus its git top and common dir), this run's private scratch dir, the CLI's
                  own state dir, and the shared agent layer read-only ($CLUPAI_HOME, the skills/commands dirs). So a
                  reviewer cannot read your keys, ssh, keychain files, auto-memory, other projects or the rest of the
                  vault. It also blocks the keychain/pasteboard/open/launchctl binaries, Apple events, and the unix
                  sockets for ssh-agent, the terminal and docker — the side channels a file-read wall alone leaves open.
  env             the child gets a PATH with no $HOME entries and ONLY its own route's API key; every other secret
                  (other routes' keys, the Claude messaging token, ssh/kitty/atuin vars) is stripped, and
                  GIT_CONFIG_GLOBAL=/dev/null so git never reads ~/.gitconfig.
  writes          --write lets the model edit files inside --cwd only (use a disposable worktree). Without it no route
                  may write to your files: writes are denied under $HOME and --cwd, leaving only the state dir and
                  scratch. dsh, kimi, grok and agy run their tools without asking (dsh is forced danger-full-access
                  because its own per-command sandbox-exec cannot nest in ours), so this sandbox is their sole guard.
  codex           runs read-only (or in an empty temp dir when --network is set, with /tmp excluded); it is NOT wrapped
                  in the read sandbox above, as it is the only route allowed on confidential folders and must not break.
  policy          read from model-policy.json by --cwd: confidential = codex only, open = + dsh, kimi, opencode,
                  personal = + agy (Gemini), grok (Grok Build on a consumer plan). Override with --policy or --confidential.
"""
import argparse, glob, json, os, re, shutil, signal, subprocess, sys, tempfile, time
CLUPAI_HOME = os.path.expanduser(os.environ.get('CLUPAI_HOME') or (
    '~/clupai' if os.path.isdir(os.path.expanduser('~/clupai'))
    else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))  # where this repo is installed

CODEX_EFFORT = 'medium'
REVIEW_BRIEF = '''You are reviewing a code change. The diff is below. Report only real defects: bugs, security holes,
data loss, race conditions, broken error handling, and behaviour that contradicts the stated intent. No style notes,
no praise, no summary of the change. Read other files only to confirm or rule out a suspected defect, and keep it
to the files the diff touches or calls. For each finding give: file:line, what goes wrong (concrete input or
state -> wrong result), severity (high/medium/low), and the fix in one line. If you find nothing, say "No defects found."
'''
MAX_DIFF = 80000

LADDER = ['codex', 'dsh:deepseek-flash', 'agy:gemini-3.8-flash-high', 'kimi:kimi-k3']  # app bake-off, 22 Sep 2026
# OpenCode's own privacy policy allows using prompts to improve its services, several upstream
# providers may train on inputs, and Antigravity's free tier trains on inputs.
POLICY_FILE = os.path.join(CLUPAI_HOME, 'model-policy.json')
RANK = {'confidential': 0, 'open': 1, 'personal': 2}
MAX_ROUTES = {'confidential': {'codex'}, 'open': {'codex', 'dsh', 'kimi', 'opencode'},
              'personal': {'codex', 'dsh', 'kimi', 'opencode', 'agy', 'grok'}}


def _ancestors(path):
    path = os.path.abspath(path)
    while True:
        yield path
        parent = os.path.dirname(path)
        if parent == path:
            return
        path = parent


def _policy_of_one(path, rules):
    """Most specific rule whose folder is the same directory (by file identity, so case and symlinks can't dodge it)."""
    best, best_len = 'confidential', -1
    for rule in rules:
        root = os.path.expanduser(str(rule.get('path', '')))
        if not root or not os.path.isdir(root):
            continue
        for anc in _ancestors(path):
            try:
                if os.path.exists(anc) and os.path.samefile(anc, root):
                    if len(os.path.abspath(root)) > best_len:
                        best, best_len = str(rule.get('policy')), len(os.path.abspath(root))
                    break
            except OSError:
                continue
    return best if best in RANK else 'confidential'


def policy_for(path):
    """Strictest policy of the path as given and as resolved. Unlisted, unknown or unreadable means confidential."""
    try:
        cfg = json.load(open(POLICY_FILE))
        rules = [r for r in cfg.get('rules', []) if isinstance(r, dict)]
    except (OSError, ValueError, AttributeError):
        return 'confidential', MAX_ROUTES['confidential']
    lexical = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    candidates = [_policy_of_one(lexical, rules), _policy_of_one(os.path.realpath(lexical), rules)]
    policy = min(candidates, key=lambda x: RANK[x])
    configured = set((cfg.get('routes') or {}).get(policy, []))
    return policy, (configured & MAX_ROUTES[policy]) or MAX_ROUTES['confidential']


QUOTA = re.compile(r'usage limit|rate.?limit|quota|429|exceeded|insufficient|out of credits|resource.?exhausted|try again later', re.I)
HOME = os.path.realpath(os.path.expanduser('~'))
LOCALE_RE = re.compile(r'^[A-Za-z0-9_.@=-]+$')  # a plain locale token like en_US.UTF-8 or de_DE@euro, nothing else
# Roots whose contents an outside reviewer must never read. Both the plain and the /System/Volumes/Data firmlink
# form of each are listed, because a canonicalised path can arrive by either name. Re-allowing any of these, or any
# ANCESTOR of one, would reopen everything beneath it — an over-broad allow — so _safe() rejects exactly those.
DENY_SUBPATHS = [HOME, '/Users', '/System/Volumes/Data/Users', '/Volumes',
                 '/private/tmp', '/private/var/tmp', os.path.realpath(os.environ.get('TMPDIR', '/tmp'))]
_DENY_CANON = {os.path.realpath(p) for p in DENY_SUBPATHS} | {HOME, '/Users', '/Volumes'}
# Where each CLI keeps its own state. It must stay WRITABLE (the CLI saves sessions, caches, logs there) and
# READABLE (it reads them back) inside the sandbox. Keep these narrow: a read allow here is a hole in the read
# wall below, so never list a shared dir like bare ~/.cache or ~/.config — name the CLI's own subdir. If a CLI
# errors for want of a path, that is visible and fixable; a too-broad allow leaks silently, which is the worse failure.
STATE_DIRS = {
    'opencode': ['.local/share/opencode', '.local/state/opencode', '.cache/opencode', '.config/opencode'],
    'agy': ['.gemini'],
    'dsh': ['.dsh', '.cache/dsh', '.cache/deepseek'],
    'kimi': ['.kimi-code'],
    'grok': ['.grok'],
}
# Read-only paths every route needs so the shared agent layer (agent_hook.py and the rules/skills it loads) still
# works inside the read wall. These are the operating layer — rules, hook scripts, skills, config — not client
# data; the confidential parts of the vault (notes, usage, other projects) stay denied because only these subpaths
# are re-allowed. Auto-memory under ~/.claude/projects is deliberately NOT here: a reviewer has no need of it, and
# memory_recall just fails open (no context) when it cannot read it.
READ_EXTRA = [
    CLUPAI_HOME,  # hooks, rules, model-policy/guardrails/queues json
    os.path.join(CLUPAI_HOME, 'skills', '_core'),     # core skills the CLIs symlink in
    '~/.agents/skills', '~/.claude/skills', '~/.claude/commands',   # more symlinked skills/commands
]  # NOT ~/.config/git: it can hold a credential helper or insteadOf tokens; child_env disables git global/system config
# Binaries that read secrets or reach the user's session, and the Apple-event channel to drive other apps. A read
# sandbox that still let the model shell out to the keychain or the pasteboard would not have closed the hole.
HARDEN_BINS = ['/usr/bin/security', '/usr/bin/osascript', '/usr/bin/open', '/bin/launchctl', '/usr/bin/crontab',
               '/usr/bin/at', '/usr/bin/pbpaste', '/usr/bin/pbcopy', '/usr/sbin/screencapture']
# Keys each route legitimately needs; every other secret in the environment is stripped (see child_env).
ROUTE_KEYS = {'dsh': ['DEEPSEEK_API_KEY'], 'kimi': ['MOONSHOT_API_KEY'], 'opencode': ['OPENROUTER_API_KEY'],
              'agy': [], 'grok': []}  # agy/grok authenticate from files in their own state dir, not an env key


def _esc(s):
    """Escape a path for an SBPL double-quoted string. Without this a path holding a `"` or `\\` makes the profile
    fail to compile (sandbox-exec then refuses to run the CLI at all — it fails closed, but still breaks the run)."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _q(path):
    return '"' + _esc(os.path.realpath(os.path.expanduser(path))) + '"'


def _cf(path):
    """Canonical comparison key: realpath (resolve symlinks) then casefold. The Mac's default filesystem is
    case-insensitive, so /users/me and $HOME are the SAME directory; a plain string compare would miss
    that and let a differently-cased --cwd slip the home folder past the read wall (an over-broad allow)."""
    return os.path.realpath(os.path.expanduser(path)).casefold()


def _within(child, parent):
    """True if child is parent or lives under it, comparing canonical case-folded paths."""
    c, p = _cf(child), _cf(parent)
    return c == p or (c + os.sep).startswith(p + os.sep)


def _safe(path):
    """A path is safe to re-allow only if it is NOT the filesystem root, NOT one of the deny roots ($HOME, /Users,
    /Volumes, the temp dirs), and NOT an ancestor of any of them. Allowing a deny root or an ancestor of one would
    reopen everything beneath it — including $HOME — that the read wall just closed. Comparison is case-folded (see
    _cf). Paths UNDER a deny root (the repo, the CLI's own state dir) are fine: they are the intended holes."""
    p = _cf(path)
    if p == '/':
        return False
    return not any((_cf(d) + os.sep).startswith(p + os.sep) for d in _DENY_CANON)  # p == d or p is an ancestor of d


def _git(project, arg, env):
    """One `git -C project rev-parse <arg>`, returned as an absolute realpath, or None if git fails."""
    r = subprocess.run(['git', '-C', project, 'rev-parse', arg], capture_output=True, text=True, timeout=30, env=env)
    if r.returncode == 0 and r.stdout.strip():
        return os.path.realpath(os.path.join(project, r.stdout.strip()))
    return None


def _git_allow(project, env):
    """Git dirs OUTSIDE the project that genuinely belong to it and must be readable so git works in a worktree.
    Returns [] for a plain repo (its .git is inside the project, already covered by the project read-allow) and for
    anything we cannot rigorously tie back to this project. Every path git reports ultimately derives from files in
    the project's own .git, so a crafted .git / gitdir / commondir could aim them at ~/.ssh or an unrelated repo. The
    worktree pair is accepted only when the per-worktree dir sits at <common>/worktrees/<name> (so `common` is its
    structural parent, not an attacker-named commondir) AND its backlink is EXACTLY <project>/.git (not merely a path
    beneath the project). An attacker can only plant files inside the project, so they cannot forge a backlink file
    under a dir they do not own; the worst they can reach is a dir they already control, never the user's secrets."""
    gitdir, common = _git(project, '--absolute-git-dir', env), _git(project, '--git-common-dir', env)
    if not gitdir or not common:
        return []
    if _within(gitdir, project) and _within(common, project):
        return []                                            # plain repo — nothing external to add
    if _cf(os.path.dirname(os.path.dirname(gitdir))) != _cf(common):
        return []                                            # `common` is not this per-worktree dir's real parent
    try:
        with open(os.path.join(gitdir, 'gitdir')) as f:      # the per-worktree dir names its working tree's .git
            backlink = os.path.realpath(f.read().strip())
    except OSError:
        return []
    if _cf(backlink) != _cf(os.path.join(project, '.git')):
        return []                                            # backlink is not EXACTLY this project's .git
    return [gitdir, common]


def read_rules(kind, project, scratch):
    """Deny reads of the home folder and the world temp dirs, then re-allow only the repo under review, this run's
    scratch, the CLI's own state, and the shared agent layer. Firmlink and /Volumes paths are denied too because a
    canonicalised path can arrive by either name. The allow must name the SAME operations as the deny (file-read-data
    and file-read-xattr): a bare `allow file-read*` does not re-open an operation a specific deny closed. The scratch
    allow is re-opened AFTER the temp-dir deny (last matching rule wins) so the CLI can read back its own temp files —
    scratch sits under $TMPDIR, which is denied, so without this a reopen-by-path would hit EPERM."""
    allow = [project, scratch]
    # The project's own git dir and shared common dir, so git works in a worktree. git's reported paths are NOT
    # trusted blindly — a crafted .git gitfile/config could point them at ~/.ssh or an unrelated repo — so a git dir
    # is allowed only once _git_owns confirms it belongs to THIS project. Then its common dir is read wherever it
    # lives (fixes worktrees whose shared dir is elsewhere under $HOME). Everything still passes _safe below.
    gitenv = {k: v for k, v in os.environ.items()
              if k not in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_OBJECT_DIRECTORY')}  # no env redirect
    gitenv.update(GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null', GIT_CONFIG_NOSYSTEM='1')
    allow += _git_allow(project, gitenv)
    allow += [os.path.join(HOME, d) for d in STATE_DIRS[kind]] + [os.path.expanduser(p) for p in READ_EXTRA]
    allow = sorted({os.path.realpath(p) for p in allow if _safe(p)})
    rule = ('(deny file-read-data file-read-xattr ' + ' '.join(f'(subpath "{_esc(r)}")' for r in DENY_SUBPATHS) + ')'
            '(allow file-read-data file-read-xattr ' + ' '.join(f'(subpath "{_esc(a)}")' for a in allow) + ')')
    if kind == 'agy':  # agy's binary lives in ~/.local/bin, which is under the deny; let it be read and run
        rule += f'(allow file-read-data file-read-xattr process-exec (literal {_q("~/.local/bin/agy")}))'
    return rule


def harden_rules():
    """Block the side channels a read wall alone leaves open: the keychain and pasteboard binaries, Apple events to
    other apps, and the user's own unix sockets (ssh-agent, the kitty control socket, docker). Each socket filter is
    a separate term — several path-regex filters inside one `remote unix-socket` apply only the first."""
    lits = ' '.join(f'(literal "{b}")' for b in HARDEN_BINS)
    rule = (f'(deny process-exec file-read-data {lits} (regex #"/git-credential-osxkeychain$"))'
            '(deny appleevent-send)'
            f'(deny network-outbound (remote unix-socket (path-regex #"^{re.escape(HOME)}/"))'
            ' (remote unix-socket (path-regex #"^/private/tmp/"))'
            ' (remote unix-socket (path-regex #"^/private/var/tmp/"))'
            ' (remote unix-socket (path-regex #"^/private/var/run/com\\.apple\\.launchd\\.")))')
    return rule


def sandbox_profile(kind, project_dir, write, scratch):
    """Block writes everywhere, and reads outside the repo. Re-allow writes only to the CLI's own state, this run's
    scratch, /dev, and the project itself with --write; re-allow reads to the repo, scratch and the shared agent
    layer. `scratch` is required: it is the one writable temp dir, kept per run so a route can never reach another
    run's worktree under /tmp. Every sandboxed CLI (dsh always danger-full-access; kimi/grok/agy skip permission
    prompts; opencode too) runs tools without asking, so OUR sandbox is the sole write guard — a narrow deny that
    left /tmp or /Volumes writable would let a --write run escape --cwd, so the deny is whole-root for every kind."""
    project = os.path.realpath(project_dir)
    scratch = os.path.realpath(scratch)
    if not _safe(project):  # never re-allow writes/reads for the root or a protected root (e.g. --write --cwd /)
        raise SystemExit(f'refusing to sandbox an unsafe --cwd (root or a protected location): {project}')
    writes = [f'(subpath "{_esc(os.path.join(HOME, d))}")' for d in STATE_DIRS[kind]]
    writes += [f'(subpath "{_esc(scratch)}")', '(subpath "/dev")']
    if write:
        writes.append(f'(subpath "{_esc(project)}")')
    reads = read_rules(kind, project, scratch) + harden_rules()
    return (f'(version 1)(allow default)(deny file-write* (subpath "/"))'
            f'(allow file-write* {" ".join(writes)})' + reads)


def child_env(kind, scratch, extra=None):
    """A clean environment for the sandboxed CLI: a PATH with no $HOME entries (so a read-denied ~/.local/bin cannot
    shadow a system tool), only this route's own API key, and no inherited session tokens (Claude messaging, ssh,
    kitty, atuin, other routes' keys). The CLI authenticates from its own key or its state-dir files; the shared
    hooks re-derive what they need from the registry, not from these vars."""
    keep = ('HOME', 'USER', 'LOGNAME', 'SHELL', 'TERM', 'LANG', 'TZ',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS')
    env = {k: os.environ[k] for k in keep if k in os.environ}
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy'):
        v = os.environ.get(k)
        if v and '@' not in v:  # drop a proxy URL carrying user:pass@host — the model could just print it
            env[k] = v
    for k in ('LC_ALL', 'LC_CTYPE', 'LC_MESSAGES'):  # a fixed locale set, and only plain locale tokens, not arbitrary LC_*
        v = os.environ.get(k)
        if v and LOCALE_RE.match(v):
            env[k] = v
    env['PATH'] = '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    env['TMPDIR'] = os.path.realpath(scratch)
    env['GIT_CONFIG_GLOBAL'] = '/dev/null'  # never read ~/.gitconfig (it may carry credential helpers or tokens)
    env['GIT_CONFIG_SYSTEM'] = '/dev/null'  # nor the system gitconfig (/opt/homebrew/etc, /usr/local/etc)
    env['GIT_CONFIG_NOSYSTEM'] = '1'        # belt and suspenders: ignore system git config entirely
    for key in ROUTE_KEYS.get(kind, []):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env.update(extra or {})
    return env


def cli_bin(name):
    """Absolute path to a CLI, resolved against the caller's PATH. The sandboxed child runs with a PATH that has no
    $HOME entries (child_env), so a CLI living in ~/.local/bin or its own state dir must be invoked by full path."""
    return shutil.which(name) or name


def run(cmd, cwd=None, stdin_text=None, timeout=1200, env=None):
    """Run a command in its own process group so a timeout kills everything it spawned."""
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        raise
    return p.returncode, out, err


def kimi_usage(session):
    """Token totals for a kimi session, summed from the per-turn usage records in its wire logs."""
    tot = {'input': 0, 'output': 0, 'cache_read': 0}
    if not session:
        return tot
    for path in glob.glob(os.path.join(HOME, '.kimi-code', 'sessions', '*', session, 'agents', '*', 'wire.jsonl')):
        try:
            for line in open(path):
                if '"usage.record"' not in line:
                    continue
                d = json.loads(line)
                if d.get('usageScope', 'turn') != 'turn':
                    continue
                u = d.get('usage') or {}
                tot['input'] += u.get('inputOther', 0) + u.get('inputCacheCreation', 0)
                tot['output'] += u.get('output', 0)
                tot['cache_read'] += u.get('inputCacheRead', 0)
        except (OSError, ValueError):
            continue
    return tot


def codex_model():
    try:
        import tomllib                             # Python 3.11+
        with open(os.path.join(HOME, '.codex', 'config.toml'), 'rb') as f:
            return tomllib.load(f).get('model')
    except (ImportError, OSError, ValueError):
        return None


def review_prompt(cwd, base, focus):
    def git(*args, check=True):
        r = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True, errors='replace', timeout=60)
        if check and r.returncode != 0:
            raise SystemExit(f'git {" ".join(args)} failed: {r.stderr.strip()}')
        return r.stdout if r.returncode == 0 else None
    has_head = git('rev-parse', '--verify', '-q', 'HEAD', check=False) is not None
    local = git('diff', 'HEAD') if has_head else git('diff', '--cached')  # no commits yet: what is staged
    branch = git('diff', f'{base}...HEAD') if base else ''
    names = sorted(set((git('diff', '--name-only', 'HEAD') if has_head else git('diff', '--cached', '--name-only'))
                       .splitlines() + (git('diff', '--name-only', f'{base}...HEAD').splitlines() if base else [])))
    untracked = [f for f in git('ls-files', '-z', '--others', '--exclude-standard').split('\0') if f]
    diff = local + branch  # uncommitted work first: it is what a cut would otherwise lose
    if not diff.strip() and not untracked:
        raise SystemExit('--review: no changes to review')
    if len(diff) > MAX_DIFF:
        diff = (diff[:MAX_DIFF] + f'\n[diff cut at {MAX_DIFF} characters. Changed files, read any the diff above does '
                f'not cover: {", ".join(names[:200])}]\n')
    extra = f'\nNew untracked files (read them): {", ".join(untracked[:50])}\n' if untracked else ''
    return (REVIEW_BRIEF + (f'\nFocus: {focus.strip()}\n' if focus.strip() else '') + extra +
            f'\nRepository: {cwd}\n\n```diff\n{diff}```\n')


def attempt(entry, prompt, cwd, network, timeout, write):
    t0 = time.time()
    kind, _, model = entry.partition(':')
    usage, text, err, ok = {}, '', '', False
    if kind == 'codex':
        fd, last_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        scratch = None
        try:
            if write:
                sandbox, run_dir = 'workspace-write', cwd
            elif network:
                # Codex needs workspace-write for network access; point it at an empty temp dir so it
                # cannot modify the project. It can still read the project by absolute path.
                scratch = tempfile.mkdtemp(prefix='second-opinion-')
                sandbox, run_dir = 'workspace-write', scratch
                prompt = f'The project to look at is {cwd} (read it by absolute path; do not modify it).\n\n' + prompt
            else:
                sandbox, run_dir = 'read-only', cwd
            cmd = ['codex', 'exec', '--skip-git-repo-check', '-C', run_dir, '-o', last_path, '-s', sandbox]
            if not write:
                # lean: skip plugins, MCP servers and hooks (~7k tokens on every call); keep auth and the model
                cmd += ['--ignore-user-config', '-c', f'model_reasoning_effort={CODEX_EFFORT}']
            # codex:<model> picks the model (e.g. codex:gpt-6.1-sol for coding); plain codex keeps the config's model
            if model or (not write and codex_model()):
                cmd += ['-m', model or codex_model()]
            if network:
                cmd += ['-c', 'sandbox_workspace_write.network_access=true']
            if not write:
                # without --write, only the empty scratch dir may be written: no /tmp, no $TMPDIR
                cmd += ['-c', 'sandbox_workspace_write.exclude_slash_tmp=true', '-c', 'sandbox_workspace_write.exclude_tmpdir_env_var=true']
            cmd.append('-')  # prompt on stdin, so it can never be parsed as a flag
            code, out, stderr = run(cmd, stdin_text=prompt, timeout=timeout)
            text = open(last_path).read().strip()
        finally:
            os.remove(last_path)
            if scratch:
                subprocess.run(['rm', '-rf', scratch])
        ok = code == 0 and bool(text)
        m = re.search(r'tokens used\s+([\d,]+)', stderr)
        usage = {'total': int(m.group(1).replace(',', ''))} if m else {}
        err = '' if ok else (stderr + out)[-2000:]
    elif kind == 'agy':
        if network:
            return False, '', dict(provider=kind, model=model, ok=False, secs=0, usage={}, quota=False,
                                   error='skipped: agy cannot combine --network with its sandbox')
        # -p takes the prompt as a flag value, so a prompt starting with '--' stays a prompt.
        # No --sandbox: agy's own sandbox wraps each command in sandbox-exec, which cannot nest inside ours
        # (sandbox_apply: Operation not permitted), so its tools would all fail. Our sandbox is the sole guard.
        scratch = tempfile.mkdtemp(prefix='agy-')
        cmd = ['sandbox-exec', '-p', sandbox_profile('agy', cwd, write, scratch),
               cli_bin('agy'), '-p', prompt, '--model', model, '--output-format', 'json', '--add-dir', cwd,
               '--dangerously-skip-permissions']
        try:
            code, out, stderr = run(cmd, cwd=cwd, timeout=timeout, env=child_env('agy', scratch))
        finally:
            subprocess.run(['rm', '-rf', scratch])
        try:
            d = json.loads(out)
            text, usage = (d.get('response') or '').strip(), d.get('usage', {})
            ok = d.get('status') == 'SUCCESS' and bool(text)
        except ValueError:
            ok = False
        err = '' if ok else (stderr + out)[-2000:]
    elif kind == 'dsh':
        # dsh reads the key from DEEPSEEK_API_KEY; fall back to the keychain when the caller's shell
        # did not load ~/.zprofile. The model comes from DSH_MODEL, read by ~/.dsh/profiles/headless/cordis.patch.yml.
        # dsh enforces read-only AND workspace-write by wrapping each shell command in its own sandbox-exec, which
        # cannot nest inside ours (sandbox_apply: Operation not permitted) — so in read-only mode its shell/read
        # tools all fail and it cannot open a file to confirm a finding. Run it danger-full-access in both modes and
        # let OUR sandbox be the sole guard: it denies writes to the project and $HOME (re-allowing them only with
        # --write) and reads outside the repo, which holds whatever dsh's own mode would have.
        extra = dict(DSH_MODEL=model or 'deepseek-v4-pro', DSH_TELEMETRY_DISABLED='1',
                     DSH_PERMISSION_MODE='danger-full-access')
        if not os.environ.get('DEEPSEEK_API_KEY'):
            k = subprocess.run(['security', 'find-generic-password', '-s', 'deepseek-api', '-w'],
                               capture_output=True, text=True).stdout.strip()
            if k:
                extra['DEEPSEEK_API_KEY'] = k
        task = prompt if not prompt.lstrip().startswith('-') else 'Task:\n' + prompt  # never parsed as a flag
        scratch = tempfile.mkdtemp(prefix='dsh-')  # one private temp dir, never all of /tmp or another run's worktree
        cmd = ['sandbox-exec', '-p', sandbox_profile('dsh', cwd, write, scratch),
               cli_bin('dsh'), '--profile', 'headless', task]
        try:
            code, out, stderr = run(cmd, cwd=cwd, timeout=timeout, env=child_env('dsh', scratch, extra))
        finally:
            subprocess.run(['rm', '-rf', scratch])
        text = out.strip()
        ok = code == 0 and bool(text)
        err = '' if ok else (stderr + out)[-2000:]
    elif kind == 'kimi':
        # The config (~/.kimi-code/config.toml) reads the key from MOONSHOT_API_KEY; fall back to the
        # keychain when the caller's shell did not load ~/.zprofile. Prompt mode runs every tool without
        # asking (and refuses --auto), so the sandbox profile is the only write guard.
        # a private temp dir even with --write, so it cannot touch other runs' worktrees under /tmp
        scratch = tempfile.mkdtemp(prefix='kimi-')
        extra = {}
        if not os.environ.get('MOONSHOT_API_KEY'):
            k = subprocess.run(['security', 'find-generic-password', '-s', 'kimi-api', '-w'],
                               capture_output=True, text=True).stdout.strip()
            if k:
                extra['MOONSHOT_API_KEY'] = k
        task = prompt if not prompt.lstrip().startswith('-') else 'Task:\n' + prompt  # never parsed as a flag
        # --skills-dir: only the core and shared skills sync-agents.py links in, not the ~100 in ~/.agents/skills
        cmd = ['sandbox-exec', '-p', sandbox_profile('kimi', cwd, write, scratch), cli_bin('kimi'), '-p', task,
               '-m', model or 'kimi-k3', '--output-format', 'stream-json',
               '--skills-dir', os.path.join(HOME, '.kimi-code', 'skills')]
        try:
            code, out, stderr = run(cmd, cwd=cwd, timeout=timeout, env=child_env('kimi', scratch, extra))
        finally:
            subprocess.run(['rm', '-rf', scratch])
        session = None
        for line in out.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('role') == 'assistant' and isinstance(d.get('content'), str) and d['content'].strip():
                text = d['content'].strip()  # the last assistant message with text is the answer
            if d.get('type') == 'session.resume_hint':
                session = d.get('session_id')
        usage = kimi_usage(session)
        ok = code == 0 and bool(text)
        err = '' if ok else (stderr + out)[-2000:]
    elif kind == 'grok':
        # Headless grok needs --always-approve to use tools at all, so like kimi the sandbox is the only write
        # guard: everywhere is denied but ~/.grok, the project (only with --write) and a private scratch dir.
        # a private temp dir even with --write, so it cannot touch other runs' worktrees under /tmp
        scratch = tempfile.mkdtemp(prefix='grok-')
        task = prompt if not prompt.lstrip().startswith('-') else 'Task:\n' + prompt  # never parsed as a flag
        cmd = ['sandbox-exec', '-p', sandbox_profile('grok', cwd, write, scratch), cli_bin('grok'), '-p', task,
               '-m', model or 'grok-4.7', '--always-approve', '--output-format', 'json', '--cwd', cwd]
        try:
            code, out, stderr = run(cmd, cwd=cwd, timeout=timeout, env=child_env('grok', scratch))
        finally:
            subprocess.run(['rm', '-rf', scratch])
        try:
            d = json.loads(out)
            text = (d.get('text') or '').strip()
            u = d.get('usage') or {}
            usage = {'input': u.get('input_tokens', 0), 'output': u.get('output_tokens', 0),
                     'cache_read': u.get('cache_read_input_tokens', 0), 'turns': d.get('num_turns'),
                     'cost': d.get('total_cost_usd')}  # notional on the plan; it counts against the weekly pool
            ok = code == 0 and bool(text) and d.get('stopReason') != 'error'
        except ValueError:
            ok = False
        err = '' if ok else (stderr + out)[-2000:]
    elif kind == 'opencode':
        scratch = tempfile.mkdtemp(prefix='opencode-')
        cmd = ['sandbox-exec', '-p', sandbox_profile('opencode', cwd, write, scratch),
               cli_bin('opencode'), 'run', '--dir', cwd, '--format', 'json', '-m', model] + (['--auto'] if write else [])
        try:
            # cwd=cwd so the sandboxed process starts in a readable dir (a denied cwd crashes it at startup)
            code, out, stderr = run(cmd, cwd=cwd, stdin_text=prompt, timeout=timeout, env=child_env('opencode', scratch))
        finally:
            subprocess.run(['rm', '-rf', scratch])
        texts, last_msg, tot = {}, None, {'input': 0, 'output': 0, 'cache_read': 0, 'cost': 0.0}
        for line in out.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            part = d.get('part') or {}
            if d.get('type') == 'text':
                texts.setdefault(part.get('messageID'), []).append(part.get('text', ''))
                last_msg = part.get('messageID')
            if d.get('type') == 'step_finish':
                tk = part.get('tokens') or {}
                tot['input'] += tk.get('input', 0)
                tot['output'] += tk.get('output', 0)
                tot['cache_read'] += (tk.get('cache') or {}).get('read', 0)
                tot['cost'] += part.get('cost') or 0
            if d.get('type') == 'error':
                err += json.dumps(d)[:500]
        text, usage = ''.join(texts.get(last_msg, [])).strip(), tot
        ok = code == 0 and bool(text)
        err = '' if ok else (err + stderr)[-2000:]
    else:
        raise SystemExit(f'unknown ladder entry: {entry}')
    return ok, text, dict(provider=kind, model=model or 'default', ok=ok, secs=round(time.time() - t0),
                          usage=usage, quota=bool(QUOTA.search(err)), error=err[-300:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('prompt_file')
    ap.add_argument('--cwd', default=os.getcwd())
    ap.add_argument('--network', action='store_true', help='allow network, e.g. for gh')
    ap.add_argument('--ladder', default=','.join(LADDER))
    ap.add_argument('--timeout', type=int, default=1200)
    ap.add_argument('--policy', choices=['auto', 'confidential', 'open', 'personal'], default='auto',
                    help='auto reads model-policy.json for --cwd (default); unmatched folders are confidential')
    ap.add_argument('--confidential', action='store_true', help='same as --policy confidential')
    ap.add_argument('--write', action='store_true', help='allow edits inside --cwd only (use a disposable worktree)')
    ap.add_argument('--review', action='store_true', help='review the git diff in --cwd (uncommitted changes)')
    ap.add_argument('--base', default='', help='with --review: also review BASE...HEAD (the branch so far)')
    ap.add_argument('--codex-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    a = ap.parse_args()
    global CODEX_EFFORT
    CODEX_EFFORT = a.codex_effort
    prompt = '' if a.prompt_file == '-' else open(a.prompt_file).read()
    if a.base and not a.review:
        raise SystemExit('--base needs --review')
    if a.review:
        prompt = review_prompt(os.path.realpath(a.cwd), a.base, prompt)
    given_cwd = a.cwd
    cwd = os.path.realpath(given_cwd)
    if '"' in cwd or '\\' in cwd:  # would break out of the quoted paths in the sandbox profile
        raise SystemExit('--cwd must not contain a double quote or a backslash')
    if not _safe(cwd):  # the root, $HOME (any case, case-insensitive FS), /Users, /Volumes or a temp root — not a project
        raise SystemExit(f'--cwd must be a real project directory, not the root or a protected location: {cwd}')
    ladder = [e.strip() for e in a.ladder.split(',') if e.strip()]
    policy, allowed = policy_for(given_cwd)            # folder policy is the ceiling
    requested = 'confidential' if a.confidential else a.policy
    if requested != 'auto' and RANK[requested] < RANK[policy]:  # overrides may only restrict
        policy, allowed = requested, MAX_ROUTES[requested]
    ladder = [e for e in ladder if e.partition(':')[0] in allowed]
    print(json.dumps({'policy': policy, 'allowed_routes': sorted(allowed), 'ladder': ladder}), file=sys.stderr)
    for entry in ladder:
        try:
            ok, text, info = attempt(entry, prompt, cwd, a.network, a.timeout, a.write)
        except (subprocess.TimeoutExpired, OSError) as e:
            ok, text, info = False, '', dict(provider=entry, ok=False, error=str(e)[:300])
        print(json.dumps(info), file=sys.stderr)
        if ok:
            print(text)
            return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
