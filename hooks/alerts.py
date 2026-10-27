#!/usr/bin/env python3
"""Sound and desktop alerts for Claude Code sessions (main and cx accounts), and a hand-off to Remote Control when
a question goes unanswered, so the session shows up in the Claude phone app.

  alerts.py done          Stop hook: "<project>: done" with a soft sound; "<project> needs you" if the reply ends
                          on a question
  alerts.py needs-you     Notification hook: a permission prompt, a question dialog, or idle on a question
  alerts.py clear WHY     UserPromptSubmit (prompt), PostToolUse (tool), SessionEnd (end): the wait is over.
                          A tool finishing does not clear a permission prompt or dialog in kitty (a parallel tool
                          can finish while it is still up); the waiter reads the screen for those instead
  alerts.py status        config, open alerts and the last log lines
  alerts.py off | on      kill switch for every session
  alerts.py test          plays both sounds and posts both notifications in this window
  alerts.py selftest      checks the wait / clear / escalate logic with a fake clock; types nothing
  alerts.py bg JSON       internal: the detached notifier and waiter for one alert

What fires when:
  done       the main agent's turn ends in an interactive session (not claude -p, not a subagent), unless the turn
             ended within `quick` s of the user's prompt or the user is looking at that kitty window right now
             (window focused and keyboard/mouse used in the last `present` s)
  needs you  a permission prompt or dialog (Notification hook), or a turn that ends on a question; same sound rule
             for the user looking at the window, but the wait is recorded either way
  escalate   still unanswered `delay` s later (300 by default): a question at the empty input box gets
             `/remote-control <project>` typed into its kitty window; anything else (permission prompt,
             AskUserQuestion dialog, a draft in the box, a window we cannot read) gets the sound and notification
             again instead, because keys typed there would answer the dialog. Once per alert; while the user is
             looking at the window the escalation waits `extend` s more, up to `give_up` s after the alert.
             Never typed when Remote Control may already be on in that process (typing it again disconnects).

Notifications go to kitty as OSC 99 written to the session's own tty (click one to jump to the window); outside
kitty, osascript. Sounds are macOS system sounds played with afplay. They follow MonoCode's "ring at my places" setting:
when ~/.local/state/monocode-fork/location.json (rewritten every minute while MonoCode runs) says ring=false, the
notification still shows but makes no sound. With MonoCode closed (file missing or older than `places_fresh` s) the
sound plays as before. Typing reuses reset.py's checked send-text
(never window creation).

Config: optional $CLUPAI_HOME/alerts.json with any of the DEFAULTS keys below; env CLAUDE_ALERTS_DELAY overrides
`delay`. State and log: ~/.local/state/claude-alerts (per machine, like reset.py's).
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), 'alerts.json')
STATE = os.path.expanduser('~/.local/state/claude-alerts')
KITTY = '/Applications/kitty.app/Contents/MacOS/kitty'
KITTEN = '/Applications/kitty.app/Contents/MacOS/kitten'
SOUNDS = '/System/Library/Sounds'
RESET_STATE = os.path.expanduser('~/.local/state/claude-reset')
LOCATION = os.path.expanduser('~/.local/state/monocode-fork/location.json')
DEFAULTS = {
    'delay': 300,            # seconds an alert may go unanswered before it escalates
    'done_sound': 'Glass',   # names of files in /System/Library/Sounds
    'needs_sound': 'Hero',
    'volume': 0.7,           # afplay -v
    'quick': 20,             # no done alert when the turn ended this soon after the prompt
    'present': 30,           # "looking at the window": it has focus and input came this recently
    'extend': 60,            # escalation waits this much more while the user is looking
    'give_up': 1800,         # ... but never past this many seconds after the alert
    'done': True,            # done alerts on/off
    'needs': True,           # needs-you alerts (and their escalation) on/off
    'remote_control': True,  # escalate a question to /remote-control; False = notify again instead
    'follow_places': True,   # silent away from MonoCode's saved places; False = always play sounds
    'places_fresh': 600,     # location.json older than this many seconds means MonoCode is closed: ring
}
CLOSE_LINE = re.compile(r'^\s*\**\s*(not )?safe to close\b', re.I)
WAITING = re.compile(r'waiting (on|for) (you|the user|your)|your (answer|call|decision|go|approval|reply|input)', re.I)


def p_off():
    return os.path.join(STATE, 'off')


def p_log():
    return os.path.join(STATE, 'log.jsonl')


def safe(s):
    return re.sub(r'[^A-Za-z0-9_-]', '', str(s or ''))[:80]


def pend_path(sid):
    return os.path.join(STATE, f'pending-{safe(sid)}.json')


def prompt_path(sid):
    return os.path.join(STATE, f'prompt-{safe(sid)}')


def rc_path(pid):
    return os.path.join(STATE, f'rc-{safe(pid)}')


def cfg():
    c = dict(DEFAULTS)
    try:
        user = json.load(open(CONFIG))
        c.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    try:
        c['delay'] = float(os.environ.get('CLAUDE_ALERTS_DELAY') or c['delay'])
    except ValueError:
        pass
    return c


def log(**row):
    try:
        os.makedirs(STATE, exist_ok=True)
        path = p_log()
        if os.path.exists(path) and os.path.getsize(path) > 512 << 10:   # keep the newer half
            lines = open(path).readlines()
            open(path, 'w').writelines(lines[len(lines) // 2:])
        row['at'] = time.time()
        with open(path, 'a') as f:
            f.write(json.dumps(row) + '\n')
    except OSError:
        pass


def read_json(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    os.makedirs(STATE, exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


class Lock:
    """One lock for every change to a pending alert, so a waiter's update cannot bring back an alert that a clear
    just removed."""
    def __enter__(self):
        import fcntl
        os.makedirs(STATE, exist_ok=True)
        self.f = open(os.path.join(STATE, '.lock'), 'a')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        self.f.close()


def update(sid, token, **fields):
    """Change a pending alert only while it is still the one this waiter owns. False when it was cleared or
    replaced."""
    with Lock():
        p = read_json(pend_path(sid))
        if not p or p.get('token') != token:
            return False
        p.update(fields)
        write_json(pend_path(sid), p)
        return True


def drop(sid, token):
    with Lock():
        p = read_json(pend_path(sid))
        if p and p.get('token') == token:
            remove(pend_path(sid))


# ---- reading replies ---------------------------------------------------------------------------------------------

def paragraphs(text):
    lines = (text or '').strip().splitlines()
    if lines and lines[0].startswith('Effort:'):   # the effort gate's first line
        lines = lines[1:]
    return [p.strip() for p in re.split(r'\n\s*\n', '\n'.join(lines)) if p.strip()]


def ends_with_q(line):
    return line.rstrip(' *_`)"\'').endswith('?')


def asks_user(text):
    """True when a reply ends by asking the user something: its last paragraph (not counting the close line) has a
    line ending in '?', or the close line says it is waiting on the user."""
    for p in reversed(paragraphs(text)):
        if CLOSE_LINE.match(p):
            if WAITING.search(p):
                return True
            continue
        return any(ends_with_q(l) for l in p.splitlines())
    return False


def clean(line, n=140):
    line = re.sub(r'[*_`#>]+', '', line).strip()
    return line[:n - 1] + '…' if len(line) > n else line


def question_line(text):
    for p in reversed(paragraphs(text)):
        if CLOSE_LINE.match(p):
            continue
        qs = [l for l in p.splitlines() if ends_with_q(l)]
        return clean(qs[-1] if qs else p.splitlines()[-1])
    return ''


def first_line(text):
    ps = paragraphs(text)
    return clean(ps[0].splitlines()[0]) if ps else ''


def tail_records(tp, size=256 << 10):
    try:
        with open(tp, 'rb') as f:
            end = f.seek(0, 2)
            f.seek(max(0, end - size))
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return []
    out = []
    for line in lines[1 if end > size else 0:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def last_state(tp):
    """('dialog', what) when the main agent's last tool call has no result yet (a permission prompt or an
    AskUserQuestion dialog is up), ('text', reply) when its last record is reply text, else (None, '')."""
    recs = [r for r in tail_records(tp) if r.get('type') in ('user', 'assistant') and not r.get('isSidechain')]
    answered = set()
    for r in recs:
        c = (r.get('message') or {}).get('content')
        if r['type'] == 'user' and isinstance(c, list):
            answered.update(b.get('tool_use_id') for b in c if isinstance(b, dict) and b.get('type') == 'tool_result')
    for r in reversed(recs):
        if r['type'] != 'assistant':
            continue
        blocks = [b for b in (r.get('message') or {}).get('content') or [] if isinstance(b, dict)]
        for b in blocks:
            if b.get('type') == 'tool_use' and b.get('id') not in answered:
                qs = (b.get('input') or {}).get('questions') if b.get('name') == 'AskUserQuestion' else None
                q = qs[0].get('question') if isinstance(qs, list) and qs and isinstance(qs[0], dict) else ''
                return 'dialog', clean(q or f'wants to use {b.get("name")}')
        text = '\n'.join(b.get('text', '') for b in blocks if b.get('type') == 'text').strip()
        if text:
            return 'text', text
        if blocks:
            return None, ''
    return None, ''


# ---- the hooks (fast: no subprocess, no kitty calls; the rest runs detached) --------------------------------------

def interactive():
    """A person's session in a terminal, not claude -p (sdk-cli) or another SDK caller."""
    return (os.environ.get('CLAUDE_CODE_ENTRYPOINT') == 'cli'
            and os.environ.get('CLAUDE_CODE_SESSION_ATTENDED', '1') != '0')


def session_ctx(data):
    listen = os.environ.get('KITTY_LISTEN_ON', '')
    cwd = data.get('cwd') or os.getcwd()
    try:
        pid = int(os.environ.get('CLAUDE_PID') or 0)
    except ValueError:
        pid = 0
    return dict(sid=str(data.get('session_id') or ''), cwd=cwd,
                project=os.path.basename((os.environ.get('CLAUDE_PROJECT_DIR') or cwd).rstrip('/')) or 'claude',
                listen=listen if listen.startswith('unix:') else '',
                window=re.sub(r'\D', '', os.environ.get('KITTY_WINDOW_ID', '')), pid=pid,
                transcript=data.get('transcript_path') or '',
                config_dir=os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude'))


def spawn(job):
    subprocess.Popen([sys.executable, os.path.abspath(__file__), 'bg', json.dumps(job)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def new_pending(ctx, kind, message, now, c):
    job = dict(ctx, kind=kind, message=clean(message, 200), at=now, due=now + float(c['delay']),
               token=f'{now:.6f}-{os.getpid()}')
    with Lock():
        write_json(pend_path(ctx['sid']), job)
    return job


def done(data):
    c = cfg()
    if os.path.exists(p_off()) or not interactive() or data.get('agent_id') or not data.get('session_id'):
        return
    ctx, now = session_ctx(data), time.time()
    with Lock():
        remove(pend_path(ctx['sid']))   # a turn that ended replaces any older wait in this session
    text = data.get('last_assistant_message')
    if text is None:
        kind, text = last_state(ctx['transcript'])
        text = text if kind == 'text' else ''
    try:
        quick = now - os.path.getmtime(prompt_path(ctx['sid'])) < float(c['quick'])
    except OSError:
        quick = False
    if c['needs'] and asks_user(text):
        job = new_pending(ctx, 'question', question_line(text), now, c)
        spawn(dict(job, alert=None if quick else 'needs', wait=True))
        log(event='question', sid=ctx['sid'], project=ctx['project'], quick=quick)
    elif c['done'] and not quick:
        spawn(dict(ctx, alert='done', message=first_line(text)))


def needs_you(data):
    c = cfg()
    if os.path.exists(p_off()) or not interactive() or not c['needs'] or not data.get('session_id'):
        return
    nt, msg = str(data.get('notification_type') or ''), str(data.get('message') or '').strip()
    if nt == 'auth_success':
        return
    ctx, now = session_ctx(data), time.time()
    p = read_json(pend_path(ctx['sid']))
    if nt == 'idle_prompt' or (not nt and 'waiting for your input' in msg.lower()):
        if p:
            return   # already alerted for this wait
        kind, detail = last_state(ctx['transcript'])
        if kind == 'dialog':
            message = detail
        elif kind == 'text' and asks_user(detail):
            kind, message = 'question', question_line(detail)
        else:
            return   # idle after a plain "done": the done alert already went
    else:
        kind = 'permission' if nt == 'permission_prompt' else 'dialog'
        if p and not p.get('escalated') and p.get('kind') == kind and now - p.get('at', 0) < 30:
            return
        message = msg or 'waiting for you'
    job = new_pending(ctx, kind, message, now, c)
    spawn(dict(job, alert='needs', wait=True))
    log(event='needs', kind=kind, nt=nt, sid=ctx['sid'], project=ctx['project'])


def clear(data, why):
    sid = data.get('session_id')
    if not sid:
        return
    if why == 'prompt':
        os.makedirs(STATE, exist_ok=True)
        with open(prompt_path(sid), 'w'):
            pass
    if why == 'end':
        remove(prompt_path(sid))
    if os.path.exists(pend_path(sid)):
        with Lock():
            p = read_json(pend_path(sid)) or {}
            if why == 'tool' and p.get('kind') != 'question' and p.get('listen') and p.get('window'):
                return   # a parallel tool finishing says nothing about the prompt; the waiter reads the screen
            remove(pend_path(sid))
        log(event='cleared', why=why, sid=str(sid))


# ---- the detached part -------------------------------------------------------------------------------------------

def run(args, timeout=5):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def ps(pid, field):
    r = run(['ps', '-o', f'{field}=', '-p', str(int(pid))]) if pid else None
    return r.stdout.decode(errors='replace').strip() if r and r.returncode == 0 else ''


def claude_tty(job):
    t = ps(job.get('pid'), 'tty')
    return f'/dev/{t}' if re.fullmatch(r'ttys?\d+', t) else ''


def hid_idle():
    r = run(['ioreg', '-c', 'IOHIDSystem', '-d', '4', '-k', 'HIDIdleTime'])
    m = re.search(rb'"HIDIdleTime" = (\d+)', r.stdout if r else b'')
    return int(m.group(1)) / 1e9 if m else 1e9


def looking(job, c):
    """The user has this session's kitty window focused and used the keyboard or mouse in the last `present` s."""
    if not (job.get('listen') and job.get('window')):
        return False
    r = run([KITTY, '@', '--to', job['listen'], 'ls', '--match', f'id:{job["window"]}'])
    try:
        wins = [w for o in json.loads(r.stdout) for t in o.get('tabs', []) for w in t.get('windows', [])]
    except (AttributeError, TypeError, ValueError):
        return False
    focused = any(str(w.get('id')) == str(job['window']) and w.get('is_focused') for w in wins)
    return focused and hid_idle() < float(c['present'])


def ring_here(c, now=None):
    """MonoCode's answer to "may alerts ring here?". Yes when it can't say: file missing, unreadable or stale."""
    if not c.get('follow_places'):
        return True
    try:
        d = json.load(open(LOCATION))
    except (OSError, ValueError):
        return True
    if not isinstance(d, dict):
        return True
    at = d.get('at')
    now = time.time() if now is None else now
    try:
        fresh = float(c['places_fresh'])
    except (TypeError, ValueError):
        fresh = DEFAULTS['places_fresh']
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 <= now - at <= fresh:
        return True
    return d.get('ring') is not False


def place_line(c):
    try:
        d = json.load(open(LOCATION))
    except (OSError, ValueError):
        d = None
    if not c.get('follow_places'):
        return 'sounds: always (follow_places off)'
    if not isinstance(d, dict):
        return 'sounds: on (MonoCode has not written location.json)'
    state = 'on' if ring_here(c) else 'silent'
    age = int(time.time() - d['at']) if isinstance(d.get('at'), (int, float)) else '?'
    return f'sounds: {state} (MonoCode says ring={d.get("ring")} place={d.get("place")} reason={d.get("reason")}, {age}s old)'


def sound(c, which):
    if not ring_here(c):
        return
    path = os.path.join(SOUNDS, f'{os.path.basename(str(c[which]))}.aiff')
    if os.path.exists(path):
        run(['afplay', '-v', str(c['volume']), path], timeout=15)


def notify(job, title, body, urgent):
    """kitty notification through the session's own tty (clicking it focuses the window), else osascript."""
    tty = claude_tty(job) if job.get('window') else ''
    if tty and os.path.exists(KITTEN):
        r = run([KITTEN, 'notify', '--only-print-escape-code', '-s', 'silent', '-a', 'Claude Code',
                 '-i', f'claude-{safe(job.get("sid"))[:12]}', '-u', 'critical' if urgent else 'normal',
                 title, body or ' '])
        if r and r.returncode == 0 and r.stdout.startswith(b'\x1b]99;'):
            if write_all(tty, r.stdout):
                return 'kitty'
    run(['osascript', '-e', 'on run argv', '-e', 'display notification (item 2 of argv) with title (item 1 of argv)',
         '-e', 'end run', title, body or ' '])
    return 'osascript'


def write_all(tty, data):
    """Write the whole escape code to the tty (a partial one would show up as garbage), giving up after 5 s."""
    import signal

    def timeout(*a):
        raise TimeoutError
    old = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(5)
    try:
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            return True
        finally:
            os.close(fd)
    except (OSError, TimeoutError):
        return False
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def alert(job, c, which, extra=''):
    p = job.get('project') or 'claude'
    title, body = {
        'done': (f'{p}: done', job.get('message') or ''),
        'needs': (f'{p} needs you', job.get('message') or ''),
        'again': (f'{p} still needs you', (job.get('message') or '') + extra),
        'rc': (f'{p}: sent to your phone', extra),
    }[which]
    how = notify(job, title, body, which != 'done')
    sound(c, 'done_sound' if which == 'done' else 'needs_sound')
    return how


def rc_active(job):
    """True when Remote Control may already be on in this Claude process. Typing /remote-control then would
    disconnect it, so any doubt counts as on."""
    pid = job.get('pid')
    cmd = ps(pid, 'command')
    if not cmd or os.path.exists(rc_path(pid)) or 'remote-control' in cmd:
        return True
    for name in ('settings.json', '../.claude.json', '.claude.json'):
        d = read_json(os.path.normpath(os.path.join(job.get('config_dir') or '', name))) or {}
        if isinstance(d, dict) and d.get('remoteControlAtStartup'):
            return True
    try:
        with open(job.get('transcript') or '', 'rb') as f:
            prev = b''
            for chunk in iter(lambda: f.read(1 << 20), b''):
                if b'"subtype":"bridge_status"' in prev[-64:] + chunk:
                    return True
                prev = chunk
    except OSError:
        return True   # cannot tell
    return False


def reset_busy(job):
    """reset.py is about to type /clear or /compact into this window."""
    import reset
    wp = os.path.join(RESET_STATE, f'win-{reset.term_key(job["listen"], job["window"])}.json')
    try:
        return time.time() - os.path.getmtime(wp) < 900
    except OSError:
        return False


def screen(job):
    """'busy' (a turn is running), 'empty' (input box, nothing typed), 'draft' (input box with text), 'unknown'
    (a dialog, a menu, or the window cannot be read), or None outside kitty."""
    if not (job.get('listen') and job.get('window')):
        return None
    import reset
    state, typed = reset.read_box(dict(listen=job['listen'], window=job['window']))
    return state if state != 'ok' else 'draft' if typed else 'empty'


def probe(job, c):
    pid, alive = job.get('pid'), False
    if pid:
        try:
            os.kill(int(pid), 0)
            alive = 'claude' in ps(pid, 'comm').lower()
        except (OSError, ValueError):
            alive = False
    if not alive:
        return dict(alive=False)
    if claude_tty(job) != job.get('tty') or ps(pid, 'lstart') != job.get('start'):
        return dict(alive=False)   # not the same Claude process on the same terminal any more
    f = dict(alive=True, looking=looking(job, c), screen=screen(job))
    if job.get('kind') == 'question' and f['screen'] == 'empty':
        f.update(rc_active=rc_active(job), reset_busy=reset_busy(job))
    return f


def decide(p, now, f, c):
    """What a waiter does with a pending alert: 'wait', 'extend', 'drop', 'type_rc' or 'reping'. Pure, for tests."""
    if p.get('escalated'):
        return 'drop'
    if now < p['due']:
        return 'wait'
    if not f.get('alive') or now - p['at'] > float(c['give_up']):
        return 'drop'
    if f.get('looking'):
        return 'extend'
    s = f.get('screen')
    if p.get('kind') != 'question':        # permission prompt or dialog: never type into it
        return 'drop' if s in ('busy', 'empty', 'draft') else 'reping'
    if s == 'busy':
        return 'drop'                       # the user answered and a turn is running
    if s == 'empty' and c['remote_control'] and not f.get('rc_active') and not f.get('reset_busy'):
        return 'type_rc'
    return 'reping'


def type_rc(job):
    """Type /remote-control <project> at the empty input box, checked the reset.py way. True when sent."""
    import reset
    rjob = dict(listen=job['listen'], window=job['window'], key=reset.term_key(job['listen'], job['window']))
    if reset.wait_for_empty(rjob, tries=2) != 'empty' or not current(job):
        return False
    name = re.sub(r'[^A-Za-z0-9._-]+', '-', job.get('project') or '').strip('-')[:40]
    return reset.type_line(rjob, f'/remote-control {name}'.strip())


def rc_confirmed(job, wait=20):
    tp, deadline = job.get('transcript') or '', time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        if any(r.get('subtype') == 'bridge_status' for r in tail_records(tp, 64 << 10)):
            return True
    return False


def current(job):
    p = read_json(pend_path(job.get('sid')))
    return bool(p) and p.get('token') == job.get('token')


def act(job, action, c):
    if not current(job):
        return log(event='cleared while escalating', sid=job.get('sid'))
    if action == 'type_rc':
        try:
            sent = type_rc(job)
        except Exception as e:   # noqa: BLE001 - a failed send falls back to a notification
            log(event='error', where='type_rc', error=repr(e))
            sent = False
        if sent:
            open(rc_path(job.get('pid')), 'w').close()   # never again in this process: a second one disconnects
            ok = rc_confirmed(job)
            log(event='remote-control', sid=job['sid'], project=job.get('project'), confirmed=ok)
            alert(job, c, 'rc', job.get('message', '') if ok else 'typed /remote-control; not confirmed yet')
            return
        log(event='rc not sent', sid=job['sid'])
        if not current(job):
            return
    alert(job, c, 'again', '' if action == 'reping' else ' (could not hand it to Remote Control)')
    log(event='reping', sid=job['sid'], kind=job.get('kind'), project=job.get('project'))


def waiter(sid, token, c, now=time.time, sleep=time.sleep, probe=probe, act=act):
    while True:
        p = read_json(pend_path(sid))
        if not p or p.get('token') != token or p.get('escalated'):
            return 'gone'
        t = now()
        if t < p['due']:
            sleep(min(p['due'] - t, 15))
            continue
        action = decide(p, t, probe(p, c), c)
        if action == 'extend':
            if not update(sid, token, due=t + float(c['extend'])):
                return 'gone'
            continue
        if action == 'drop':
            drop(sid, token)
            log(event='dropped', sid=sid, kind=p.get('kind'))
            return action
        if not update(sid, token, escalated=t, action=action):   # mark first: one escalation per alert
            return 'gone'
        act(p, action, c)
        return action


def tidy():
    now = time.time()
    try:
        names = os.listdir(STATE)
    except OSError:
        return
    for n in names:
        path = os.path.join(STATE, n)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if (n.startswith(('pending-', 'prompt-')) and age > 86400) or (n.startswith('rc-') and age > 7 * 86400) \
                or (n.endswith('.tmp') and age > 60):
            remove(path)


def bg(job):
    c = cfg()
    tidy()
    if job.get('alert'):
        time.sleep(1.0)   # let Claude finish drawing before writing to its terminal
        if job.get('wait'):
            job.update(tty=claude_tty(job), start=ps(job.get('pid'), 'lstart'))
            if not update(job['sid'], job['token'], tty=job['tty'], start=job['start']):
                return   # answered or replaced within the second
        if job.get('force') or not looking(job, c):
            how = alert(job, c, job['alert'])
            log(event='alerted', which=job['alert'], how=how, sid=job.get('sid'), project=job.get('project'))
        else:
            log(event='quiet', why='user looking', which=job['alert'], sid=job.get('sid'))
    elif job.get('wait'):
        job.update(tty=claude_tty(job), start=ps(job.get('pid'), 'lstart'))
        if not update(job['sid'], job['token'], tty=job['tty'], start=job['start']):
            return
    if job.get('wait'):
        waiter(job['sid'], job['token'], c)


# ---- commands ----------------------------------------------------------------------------------------------------

def status():
    c = cfg()
    print('alerts:', 'OFF' if os.path.exists(p_off()) else 'on', '| config:', json.dumps(c))
    print(place_line(c))
    now = time.time()
    for n in sorted(os.listdir(STATE)) if os.path.isdir(STATE) else []:
        if n.startswith('pending-'):
            p = read_json(os.path.join(STATE, n)) or {}
            state = 'escalated' if p.get('escalated') else f'escalates in {int(p.get("due", now) - now)}s'
            print(f'  {p.get("project")} {p.get("kind")} {state}: {p.get("message", "")[:60]}')
    try:
        rows = [json.loads(l) for l in open(p_log()) if l.strip()][-12:]
    except (OSError, ValueError):
        rows = []
    for r in rows:
        at = time.strftime('%d %b %H:%M:%S', time.localtime(r.pop('at', 0)))
        print(f'  {at} {r.pop("event", "")} ' + ' '.join(f'{k}={v}' for k, v in r.items() if k != 'sid'))


def test():
    c = cfg()
    job = dict(session_ctx({'session_id': os.environ.get('CLAUDE_CODE_SESSION_ID') or 'test'}),
               message='alerts.py test: the done alert')
    print(place_line(c))
    print('done:', alert(job, c, 'done'))
    time.sleep(1.5)
    job['message'] = 'alerts.py test: the needs-you alert'
    print('needs you:', alert(job, c, 'needs'))


def selftest():
    import tempfile
    global STATE, LOCATION
    keep, keep_loc, STATE = STATE, LOCATION, tempfile.mkdtemp(prefix='alerts-test-')
    LOCATION = os.path.join(STATE, 'location.json')
    c = dict(DEFAULTS, delay=300, extend=60, give_up=1800)
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f'{name}: got {got!r}, want {want!r}')

    class Clock:
        def __init__(self, t, on_sleep=None):
            self.t, self.on_sleep = t, on_sleep

        def now(self):
            return self.t

        def sleep(self, s):
            self.t += s
            if self.on_sleep:
                self.on_sleep(self.t)

    def scenario(name, kind, facts, want, cleared_at=None, clock_start=1000.0):
        sid, acts = f's-{name}', []
        job = new_pending(dict(sid=sid, project='p'), kind, 'q?', clock_start, c)
        clk = Clock(clock_start, (lambda t: clear({'session_id': sid}, 'prompt') if t >= cleared_at else None)
                    if cleared_at else None)
        seq = iter(facts)
        last = [facts[-1]]

        def fake_probe(p, c):
            last[0] = next(seq, last[0])
            return dict(alive=True, **last[0])
        got = waiter(sid, job['token'], c, now=clk.now, sleep=clk.sleep, probe=fake_probe,
                     act=lambda p, a, c: acts.append(a))
        check(name, got, want)
        check(f'{name} acts', acts, [want] if want in ('type_rc', 'reping') else [])
        if want in ('type_rc', 'reping'):   # never twice for one alert
            check(f'{name} twice', waiter(sid, job['token'], c, now=clk.now, sleep=clk.sleep, probe=fake_probe,
                                          act=lambda p, a, c: acts.append(a)), 'gone')
            check(f'{name} twice acts', len(acts), 1)
        return clk

    try:
        clk = scenario('question idle', 'question', [dict(screen='empty')], 'type_rc')
        check('fires at delay', clk.t, 1300.0)
        scenario('answered before due', 'question', [dict(screen='empty')], 'gone', cleared_at=1100)
        scenario('permission never typed', 'permission', [dict(screen='unknown')], 'reping')
        scenario('permission answered', 'permission', [dict(screen='empty')], 'drop')
        scenario('dialog answered', 'dialog', [dict(screen='empty')], 'drop')
        scenario('dialog still up', 'dialog', [dict(screen='unknown')], 'reping')
        scenario('draft not overwritten', 'question', [dict(screen='draft')], 'reping')
        scenario('rc already on', 'question', [dict(screen='empty', rc_active=True)], 'reping')
        scenario('reset in flight', 'question', [dict(screen='empty', reset_busy=True)], 'reping')
        scenario('turn running', 'question', [dict(screen='busy')], 'drop')
        scenario('no kitty', 'question', [dict(screen=None)], 'reping')
        clk = scenario('user looking', 'question', [dict(looking=True, screen='empty')] * 2 + [dict(screen='empty')],
                       'type_rc')
        check('extended twice', clk.t, 1420.0)
        scenario('looking forever', 'question', [dict(looking=True, screen='empty')], 'drop')
        sid = 's-replaced'
        old = new_pending(dict(sid=sid), 'question', 'q?', 1000.0, c)
        new_pending(dict(sid=sid), 'permission', 'x', 1001.0, c)
        check('replaced', waiter(sid, old['token'], c, now=lambda: 2000.0, sleep=lambda s: None,
                                 probe=lambda p, c: dict(alive=True, screen='empty'), act=lambda *a: None), 'gone')
        sid = 's-parallel'
        new_pending(dict(sid=sid, listen='unix:/x', window='1'), 'permission', 'x', 1000.0, c)
        clear({'session_id': sid}, 'tool')
        check('tool keeps kitty prompt', os.path.exists(pend_path(sid)), True)
        clear({'session_id': sid}, 'prompt')
        check('prompt clears it', os.path.exists(pend_path(sid)), False)
        new_pending(dict(sid=sid), 'permission', 'x', 1000.0, c)
        clear({'session_id': sid}, 'tool')
        check('tool clears prompt outside kitty', os.path.exists(pend_path(sid)), False)
        check('dead session', decide(dict(at=0, due=1, kind='question'), 5, dict(alive=False), c), 'drop')
        for text, want in [('Done. Want me to push it?', True),
                           ('Effort: low now\n\nAll done.\n\nSafe to close: nothing left to do.', False),
                           ('Should I use **Hero**?\n\nNot safe to close: waiting on you.', True),
                           ('Fixed it.\n\nNot safe to close: waiting on your answer above.', True),
                           ('What changed?\n\nThe build. It passes now.', False),
                           ('Which one do you want (A or B)?', True), ('', False)]:
            check(f'asks_user({text[:30]!r})', asks_user(text), want)
        check('question_line', question_line('Intro.\n\nI did X.\nShall I deploy?\n\nSafe to close: no.'),
              'Shall I deploy?')
        check('ring: no location file', ring_here(c, 5000), True)
        for name, body, want in [('away', dict(ring=False, at=4900), False), ('home', dict(ring=True, at=4900), True),
                                 ('stale', dict(ring=False, at=4000), True), ('future', dict(ring=False, at=6000), True),
                                 ('no at', dict(ring=False), True), ('bad at', dict(ring=False, at='x'), True)]:
            json.dump(body, open(LOCATION, 'w'))
            check(f'ring: {name}', ring_here(c, 5000), want)
        json.dump(dict(ring=False, at=4900), open(LOCATION, 'w'))
        check('ring: follow_places off', ring_here(dict(c, follow_places=False), 5000), True)
        check('ring: bad places_fresh', ring_here(dict(c, places_fresh=None), 5000), False)
        open(LOCATION, 'w').write('{not json')
        check('ring: corrupt file', ring_here(c, 5000), True)
    finally:
        import shutil
        shutil.rmtree(STATE, ignore_errors=True)
        STATE, LOCATION = keep, keep_loc
    for f in fails:
        print('FAIL', f)
    print(f'selftest: {"FAILED" if fails else "ok"} ({len(fails)} failures)')
    return 1 if fails else 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    try:
        if cmd in ('done', 'needs-you', 'clear'):
            try:
                data = json.load(sys.stdin)
            except ValueError:
                return
            if not isinstance(data, dict):
                return
            if cmd == 'done':
                done(data)
            elif cmd == 'needs-you':
                needs_you(data)
            else:
                clear(data, sys.argv[2] if len(sys.argv) > 2 else 'tool')
        elif cmd == 'bg':
            bg(json.loads(sys.argv[2]))
        elif cmd == 'off':
            os.makedirs(STATE, exist_ok=True)
            open(p_off(), 'w').close()
            print('alerts off')
        elif cmd == 'on':
            remove(p_off())
            print('alerts on')
        elif cmd == 'test':
            test()
        elif cmd == 'selftest':
            sys.exit(selftest())
        else:
            status()
    except SystemExit:
        raise
    except Exception as e:   # noqa: BLE001 - a hook must never break the session
        log(event='error', cmd=cmd, error=repr(e))


if __name__ == '__main__':
    main()
