# -*- coding: utf-8 -*-
import os
import sys
import re
import subprocess
import threading
from datetime import datetime

import psutil

PACKAGE_MAP = {
    "telegram":      "python-telegram-bot",
    "telebot":       "pyTelegramBotAPI",
    "telethon":      "Telethon",
    "pyrogram":      "Pyrogram",
    "pyromod":       "pyromod",
    "tgcrypto":      "TgCrypto",
    "aiogram":       "aiogram",
    "PIL":           "Pillow",
    "cv2":           "opencv-python",
    "bs4":           "beautifulsoup4",
    "yaml":          "PyYAML",
    "dotenv":        "python-dotenv",
    "Crypto":        "pycryptodome",
    "Cryptodome":    "pycryptodomex",
    "dateutil":      "python-dateutil",
    "magic":         "python-magic",
    "skimage":       "scikit-image",
    "sklearn":       "scikit-learn",
    "google":        "google-api-python-client",
    "googletrans":   "googletrans",
    "OpenSSL":       "pyOpenSSL",
    "wx":            "wxPython",
    "psycopg2":      "psycopg2-binary",
    "MySQLdb":       "mysqlclient",
    "serial":        "pyserial",
    "win32api":      "pywin32",
    "ujson":         "ujson",
    "uvloop":        "uvloop",
    "discord":       "discord.py",
    "httpx":         "httpx",
    "aiohttp":       "aiohttp",
    "fastapi":       "fastapi",
    "flask":         "Flask",
    "starlette":     "starlette",
    "redis":         "redis",
    "pymongo":       "pymongo",
    "motor":         "motor",
    "psutil":        "psutil",
    "schedule":      "schedule",
    "apscheduler":   "APScheduler",
    "cryptography":  "cryptography",
    "github":        "PyGithub",
    "requests":      "requests",
    "nacl":          "PyNaCl",
    "git":           "GitPython",
    "jose":          "python-jose",
    "pkg_resources": "setuptools",
    "lxml":          "lxml",
    "chardet":       "chardet",
    "docx":          "python-docx",
    "pptx":          "python-pptx",
    "openpyxl":      "openpyxl",
    "fpdf":          "fpdf2",
    "qrcode":        "qrcode",
    "pytz":          "pytz",
    "yt_dlp":        "yt-dlp",
    "pytube":        "pytube",
    "instagrapi":    "instagrapi",
    "instaloader":   "instaloader",
    "tweepy":        "tweepy",
    "praw":          "praw",
    "wikipedia":     "wikipedia",
    "gtts":          "gTTS",
    "pydub":         "pydub",
    "moviepy":       "moviepy",
    "openai":        "openai",
    "anthropic":     "anthropic",
    "cohere":        "cohere",
    "transformers":  "transformers",
    "torch":         "torch",
    "tensorflow":    "tensorflow",
    "keras":         "keras",
    "numpy":         "numpy",
    "pandas":        "pandas",
    "matplotlib":    "matplotlib",
    "seaborn":       "seaborn",
    "plotly":        "plotly",
    "scipy":         "scipy",
    "selenium":      "selenium",
    "playwright":    "playwright",
    "scrapy":        "Scrapy",
    "pyautogui":     "pyautogui",
    "pynput":        "pynput",
    "keyboard":      "keyboard",
    "speech_recognition": "SpeechRecognition",
    "gspread":       "gspread",
    "cloudscraper":  "cloudscraper",
    "colorama":      "colorama",
    "rich":          "rich",
    "tqdm":          "tqdm",
    "tabulate":      "tabulate",
    "emoji":         "emoji",
    "pyfiglet":      "pyfiglet",
    "termcolor":     "termcolor",
    "psycopg":       "psycopg",
    "asyncpg":       "asyncpg",
    "sqlalchemy":    "SQLAlchemy",
    "alembic":       "alembic",
    "celery":        "celery",
    "django":        "Django",
    "jinja2":        "Jinja2",
    "werkzeug":      "Werkzeug",
    "click":         "click",
    "typer":         "typer",
    "loguru":        "loguru",
    "structlog":     "structlog",
    "orjson":        "orjson",
    "marshmallow":   "marshmallow",
    "pydantic":      "pydantic",
    "attrs":         "attrs",
    "boltons":       "boltons",
}

CORE_MODULES = {
    'os', 'sys', 're', 'json', 'time', 'datetime', 'math', 'random',
    'logging', 'threading', 'subprocess', 'asyncio', 'collections',
    'itertools', 'functools', 'typing', 'pathlib', 'io', 'socket',
    'base64', 'hashlib', 'hmac', 'secrets', 'uuid', 'sqlite3',
    'urllib', 'http', 'email', 'zipfile', 'tempfile', 'shutil',
    'pickle', 'csv', 'xml', 'html', 'unittest', 'dataclasses',
    'traceback', 'warnings', 'contextlib', 'abc', 'copy', 'enum',
    'glob', 'signal', 'atexit', 'platform', 'statistics',
    'argparse', 'ast', 'binascii', 'bisect', 'calendar', 'cmath',
    'codecs', 'concurrent', 'configparser', 'contextvars',
    'crypt', 'ctypes', 'curses', 'decimal', 'difflib', 'dis',
    'doctest', 'errno', 'faulthandler', 'filecmp', 'fileinput',
    'fnmatch', 'fractions', 'ftplib', 'gc', 'getopt', 'getpass',
    'gettext', 'graphlib', 'gzip', 'heapq', 'imaplib', 'imp',
    'importlib', 'inspect', 'ipaddress', 'keyword', 'linecache',
    'locale', 'lzma', 'mailbox', 'marshal', 'mimetypes', 'mmap',
    'multiprocessing', 'netrc', 'numbers', 'operator', 'optparse',
    'pdb', 'pickletools', 'pkgutil', 'plistlib', 'poplib',
    'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile',
    'queue', 'quopri', 'select', 'selectors', 'shelve', 'shlex',
    'site', 'smtplib', 'sndhdr', 'socketserver', 'ssl', 'stat',
    'string', 'stringprep', 'struct', 'symtable', 'tabnanny',
    'tarfile', 'telnetlib', 'textwrap', 'timeit', 'tkinter',
    'token', 'tokenize', 'trace', 'tracemalloc', 'tty', 'turtle',
    'types', 'unicodedata', 'uu', 'venv', 'wave', 'weakref',
    'webbrowser', 'wsgiref', 'xdrlib', 'xmlrpc', 'zipapp', 'zlib',
    'zoneinfo',
}

RUNNING = {}
LOCK = threading.Lock()


def get_script_dir(user_id, script_id):
    from app import UPLOAD_DIR
    d = os.path.join(UPLOAD_DIR, str(user_id), str(script_id))
    os.makedirs(d, exist_ok=True)
    return d


def is_running(script_id):
    with LOCK:
        info = RUNNING.get(script_id)
        if not info:
            return False
        proc = info['proc']
        try:
            p = psutil.Process(proc.pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                _cleanup(script_id)
                return False
            return True
        except psutil.NoSuchProcess:
            _cleanup(script_id)
            return False
        except Exception:
            _cleanup(script_id)
            return False


def _cleanup(script_id):
    info = RUNNING.pop(script_id, None)
    if info and info.get('log_file'):
        try:
            if not info['log_file'].closed:
                info['log_file'].close()
        except Exception:
            pass


def _sync_runtime_folder(script_id, user_id, script_dir, proc):
    """Persist bot-created session/database files to DBByte while the process runs."""
    import time
    while proc.poll() is None:
        time.sleep(60)
        if proc.poll() is not None:
            break
        try:
            from storage_helper import sync_script_folder
            if not sync_script_folder(script_dir, user_id, script_id):
                print(f"[DBBYTE] Runtime sync incomplete for bot {script_id}", flush=True)
        except Exception as exc:
            print(f"[DBBYTE] Runtime sync error for bot {script_id}: {exc}", flush=True)


def start_script(script_id, user_id, file_path, file_type, env_vars=None):
    if is_running(script_id):
        return False, "Script already running"

    script_dir = get_script_dir(user_id, script_id)
    log_path = os.path.join(script_dir, 'output.log')

    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > 2 * 1024 * 1024:
            os.remove(log_path)
    except Exception:
        pass

    log_file = open(log_path, 'a', encoding='utf-8', errors='ignore')
    cmd = [sys.executable, file_path] if file_type == 'py' else ['node', file_path]

    log_file.write(f"\n\n===== Deploy started {datetime.now().isoformat()} =====\n")
    log_file.flush()
    child_env = os.environ.copy()
    if isinstance(env_vars, dict):
        for key, value in env_vars.items():
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", str(key)):
                child_env[str(key)] = str(value)
    deps_declared = False
    try:
        req_path = os.path.join(script_dir, "requirements.txt")
        if file_type == "py" and os.path.isfile(req_path):
            with open(req_path, "r", encoding="utf-8", errors="ignore") as rf:
                req_text = rf.read()
            if len(req_text) > 20000:
                raise RuntimeError("requirements.txt exceeds 20 KB limit")
            packages_dir = os.path.join(script_dir, ".packages")
            os.makedirs(packages_dir, exist_ok=True)
            log_file.write("[SYSTEM] Installing requirements.txt into bot-local packages...\n")
            log_file.flush()
            install = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--target", packages_dir, "-r", req_path], cwd=script_dir, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=300)
            log_file.write((install.stdout or "")[-12000:] + (install.stderr or "")[-12000:])
            if install.returncode != 0:
                raise RuntimeError("requirements.txt installation failed; see install log")
            child_env["PYTHONPATH"] = packages_dir + os.pathsep + child_env.get("PYTHONPATH", "")
            deps_declared = True
        elif file_type == "js" and os.path.isfile(os.path.join(script_dir, "package.json")):
            log_file.write("[SYSTEM] Installing package.json dependencies...\n")
            log_file.flush()
            install = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=script_dir, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=300)
            log_file.write((install.stdout or "")[-12000:] + (install.stderr or "")[-12000:])
            if install.returncode != 0:
                raise RuntimeError("npm install failed; see install log")
        log_file.write("[SYSTEM] Dependencies ready. Launching process...\n")
        log_file.flush()
        missing = None if deps_declared else _precheck(cmd, script_dir, log_file)
        if missing:
            log_file.write(f"[SYSTEM] Missing module: {missing}\n")
            log_file.flush()
            ok = _auto_install(missing, file_type, script_dir, user_id, log_file)
            if not ok:
                log_file.write(f"[SYSTEM] Auto-install failed for '{missing}'.\n")
                log_file.flush()
                log_file.close()
                return False, f"Missing '{missing}' and install failed"
            log_file.write(f"[SYSTEM] ✅ Installed '{missing}'. Retrying...\n")
            log_file.flush()
    except Exception as e:
        log_file.write(f"[SYSTEM] Dependency/precheck failed: {e}\n")
        log_file.flush()
        log_file.close()
        return False, str(e)

    try:
        kwargs = {}
        if os.name != 'nt':
            kwargs['start_new_session'] = True
        else:
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            cmd, cwd=script_dir,
            stdout=log_file, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=child_env, **kwargs
        )

        with LOCK:
            RUNNING[script_id] = {
                'proc': proc,
                'log_file': log_file,
                'start_time': datetime.now(),
                'user_id': user_id,
                'type': file_type,
            }
        threading.Thread(
            target=_sync_runtime_folder,
            args=(script_id, user_id, script_dir, proc),
            name=f"dbbyte-sync-{script_id}",
            daemon=True,
        ).start()
        threading.Thread(target=_watch_exit, args=(script_id, proc), name=f"bot-watch-{script_id}", daemon=True).start()
        return True, f"Started (PID: {proc.pid})"

    except FileNotFoundError as e:
        log_file.close()
        return False, f"Executable not found: {e}"
    except Exception as e:
        log_file.close()
        return False, f"Error: {e}"



def _watch_exit(script_id, proc):
    try:
        code = proc.wait()
        with LOCK:
            info = RUNNING.get(script_id)
            if info and info.get('proc') is proc:
                _cleanup(script_id)
        try:
            from db import update_script
            update_script(script_id, {'running': False, 'status': 'stopped' if code == 0 else 'failed', 'last_exit_code': int(code), 'last_exit_at': datetime.now().isoformat()})
        except Exception as exc:
            print(f'[RUNNER] Could not persist exit status for {script_id}: {exc}', flush=True)
        print(f'[RUNNER] Bot {script_id} exited with code {code}', flush=True)
    except Exception as exc:
        print(f'[RUNNER] Exit watcher error for {script_id}: {exc}', flush=True)


def stop_script(script_id):
    with LOCK:
        info = RUNNING.get(script_id)
    if not info:
        return False, "Not running"

    pid = info['proc'].pid
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for ch in children:
            try: ch.terminate()
            except Exception: pass
        try: parent.terminate()
        except Exception: pass
        gone, alive = psutil.wait_procs([parent] + children, timeout=3)
        for p in alive:
            try: p.kill()
            except Exception: pass
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        return False, f"Error stopping: {e}"
    sync_ok = True
    sync_error = ""
    try:
        # Upload the final session/database/log changes before app.py clears the
        # temporary Render working directory.
        from storage_helper import sync_script_folder
        sync_ok = sync_script_folder(os.path.dirname(info['log_file'].name), info.get('user_id'), script_id, prune=True)
        if not sync_ok:
            sync_error = "DBByte sync was incomplete"
    except Exception as exc:
        sync_ok = False
        sync_error = str(exc)
    finally:
        _cleanup(script_id)
    if not sync_ok:
        return False, f"Bot stopped, but local files were kept: {sync_error}"
    return True, "Stopped"


def get_status(script_id):
    if not is_running(script_id):
        return {'running': False}
    with LOCK:
        info = RUNNING.get(script_id)
    if not info:
        return {'running': False}
    proc = info['proc']
    try:
        p = psutil.Process(proc.pid)
        mem = p.memory_info().rss / 1024 / 1024
        cpu = p.cpu_percent(interval=0.1)
    except Exception:
        mem, cpu = 0, 0
    uptime = int((datetime.now() - info['start_time']).total_seconds())
    return {
        'running': True,
        'pid': proc.pid,
        'uptime': uptime,
        'memory_mb': round(mem, 2),
        'cpu': round(cpu, 2),
    }


def read_log(script_id, user_id, tail_kb=100):
    script_dir = get_script_dir(user_id, script_id)
    log_path = os.path.join(script_dir, 'output.log')
    if not os.path.exists(log_path):
        return "(No log yet)"
    size = os.path.getsize(log_path)
    with open(log_path, 'rb') as f:
        if size > tail_kb * 1024:
            f.seek(-tail_kb * 1024, os.SEEK_END)
        data = f.read()
    return data.decode('utf-8', errors='ignore')


def _resolve_package_name(module):
    module = module.split('.')[0]
    if module in CORE_MODULES:
        return None
    return PACKAGE_MAP.get(module, module)


def _precheck(cmd, cwd, log_file=None):
    try:
        r = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore',
            timeout=8
        )
        if r.returncode != 0 and r.stderr:
            stderr = r.stderr
            m = re.search(r"ModuleNotFoundError: No module named '([^']+)'", stderr)
            if m:
                mod = m.group(1).split('.')[0]
                if mod in CORE_MODULES:
                    return None
                return mod
            m = re.search(r"ImportError: cannot import name .+ from '([^']+)'", stderr)
            if m:
                mod = m.group(1).split('.')[0]
                if mod in CORE_MODULES:
                    return None
                return mod
            m = re.search(r"Cannot find module '([^']+)'", stderr)
            if m:
                mod = m.group(1)
                if not mod.startswith('.') and not mod.startswith('/'):
                    return mod
        return None
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError as e:
        if log_file:
            log_file.write(f"[SYSTEM] Executable not found: {e}\n")
            log_file.flush()
        return None
    except Exception as e:
        if log_file:
            log_file.write(f"[SYSTEM] Precheck exception: {e}\n")
            log_file.flush()
        return None


def _auto_install(module, file_type, cwd, user_id, log_file=None):
    try:
        from db import log_install
    except Exception:
        log_install = None

    package = _resolve_package_name(module)

    if package is None:
        if log_file:
            log_file.write(f"[SYSTEM] '{module}' is core, skipping.\n")
            log_file.flush()
        return False

    try:
        if file_type == 'py':
            cmd = [sys.executable, '-m', 'pip', 'install', '--no-cache-dir', package]
        else:
            cmd = ['npm', 'install', module]

        if log_file:
            log_file.write(f"[SYSTEM] Running: {' '.join(cmd)}\n")
            log_file.flush()

        r = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore',
            timeout=180
        )

        full_log = f"$ {' '.join(cmd)}\n\n{r.stdout or ''}\n\n{r.stderr or ''}"

        if log_install:
            try:
                status = 'success' if r.returncode == 0 else 'failed'
                log_install(user_id, f"{module} → {package}", status, full_log)
            except Exception:
                pass

        if log_file:
            if r.returncode == 0:
                log_file.write(f"[SYSTEM] ✅ Installed '{package}'.\n")
            else:
                log_file.write(f"[SYSTEM] ❌ Failed to install '{package}'.\n")
                if r.stderr:
                    log_file.write(f"[SYSTEM] {r.stderr[:500]}\n")
            log_file.flush()

        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        if log_file:
            log_file.write(f"[SYSTEM] Install exception: {e}\n")
            log_file.flush()
        return False


def cleanup_all():
    for sid in list(RUNNING.keys()):
        try:
            stop_script(sid)
        except Exception:
            pass
