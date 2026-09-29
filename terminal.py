# REAL_NAME: 
# -*- coding: utf-8 -*-
"""
Admin Web Terminal
==================
Ek interactive terminal jahan admin koi bhi command chala sakta hai.
WebSocket ke through real-time I/O.
"""
import os
import subprocess
import threading
import shlex
import signal
import time
from collections import deque

# ============================================================
# SESSION STORAGE
# ============================================================
# { sid: { 'cwd': str, 'history': [], 'proc': Popen or None } }
SESSIONS = {}
LOCK = threading.Lock()

MAX_HISTORY = 500
MAX_OUTPUT_LINES = 1000
CMD_TIMEOUT = 300  # 5 minutes

# Allowed initial directory
DEFAULT_CWD = os.path.abspath(os.path.dirname(__file__))


# ============================================================
# SESSION MANAGEMENT
# ============================================================
def create_session(sid, cwd=None):
    """Create new terminal session."""
    with LOCK:
        SESSIONS[sid] = {
            'cwd': cwd or DEFAULT_CWD,
            'history': deque(maxlen=MAX_HISTORY),
            'proc': None,
        }
    return SESSIONS[sid]


def get_session(sid):
    with LOCK:
        return SESSIONS.get(sid)


def destroy_session(sid):
    with LOCK:
        session = SESSIONS.pop(sid, None)
    if session and session.get('proc'):
        try:
            _kill_proc(session['proc'])
        except Exception:
            pass


# ============================================================
# COMMAND EXECUTION
# ============================================================
def _kill_proc(proc):
    """Kill process + children."""
    if not proc or proc.poll() is not None:
        return
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for ch in children:
            try: ch.terminate()
            except Exception: pass
        try: parent.terminate()
        except Exception: pass
        _, alive = psutil.wait_procs([parent] + children, timeout=2)
        for p in alive:
            try: p.kill()
            except Exception: pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_command(sid, command, cwd=None):
    """
    Execute a command. Returns generator yielding output lines.
    Supports: cd, clear, and any shell command.
    """
    session = get_session(sid)
    if not session:
        session = create_session(sid)

    command = (command or '').strip()
    if not command:
        yield {'type': 'prompt', 'cwd': session['cwd']}
        return

    # Store in history
    session['history'].append(command)

    # --- Built-in: cd ---
    if command.startswith('cd'):
        parts = command.split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else os.path.expanduser('~')
        target = os.path.expanduser(target)
        new_dir = os.path.abspath(os.path.join(session['cwd'], target))
        if os.path.isdir(new_dir):
            session['cwd'] = new_dir
            yield {'type': 'output', 'data': f'→ {new_dir}\n'}
        else:
            yield {'type': 'error', 'data': f'cd: no such directory: {target}\n'}
        yield {'type': 'prompt', 'cwd': session['cwd']}
        return

    # --- Built-in: clear ---
    if command in ('clear', 'cls'):
        yield {'type': 'clear'}
        yield {'type': 'prompt', 'cwd': session['cwd']}
        return

    # --- Built-in: pwd ---
    if command == 'pwd':
        yield {'type': 'output', 'data': session['cwd'] + '\n'}
        yield {'type': 'prompt', 'cwd': session['cwd']}
        return

    # --- Built-in: exit ---
    if command == 'exit':
        yield {'type': 'output', 'data': 'bye\n'}
        return

    # --- Shell command ---
    try:
        # Use bash -c so pipes, &&, etc. work
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=session['cwd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='ignore',
            bufsize=1,  # line buffered
            start_new_session=True,
        )
        session['proc'] = proc

        output_count = 0
        start_time = time.time()

        # Read line by line
        for line in iter(proc.stdout.readline, ''):
            if line:
                output_count += 1
                if output_count > MAX_OUTPUT_LINES:
                    yield {
                        'type': 'error',
                        'data': f'\n⚠️ Output truncated (> {MAX_OUTPUT_LINES} lines)\n'
                    }
                    break
                yield {'type': 'output', 'data': line}

            # Timeout check
            if time.time() - start_time > CMD_TIMEOUT:
                yield {'type': 'error', 'data': f'\n⏱️ Timeout ({CMD_TIMEOUT}s). Killing...\n'}
                _kill_proc(proc)
                break

            # User-abort check
            if session.get('abort'):
                session['abort'] = False
                yield {'type': 'error', 'data': '\n🛑 Aborted by user\n'}
                _kill_proc(proc)
                break

        proc.wait(timeout=5)
        rc = proc.returncode

        if rc != 0:
            yield {'type': 'error', 'data': f'\n[exit code: {rc}]\n'}
        else:
            yield {'type': 'output', 'data': '\n'}

    except Exception as e:
        yield {'type': 'error', 'data': f'Error: {e}\n'}
    finally:
        session['proc'] = None
        yield {'type': 'prompt', 'cwd': session['cwd']}


def abort_current(sid):
    """Abort currently running command in session."""
    session = get_session(sid)
    if session:
        session['abort'] = True
        return True
    return False


def get_history(sid):
    session = get_session(sid)
    if not session:
        return []
    return list(session['history'])
