# REAL_NAME: app.py
# -*- coding: utf-8 -*-
import os, sys, re, zipfile, tempfile, shutil, subprocess, uuid
import requests
from functools import wraps
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash, abort, send_file)
from werkzeug.utils import secure_filename

import db
import runner
import storage_helper
import terminal
from firebase_config import init_firebase
from firebase_admin import auth as fb_auth

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
MAX_FILE_SIZE = 20 * 1024 * 1024
ALLOWED_EXT = {'.py', '.js', '.zip'}
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
# Keep the signed session cookie across browser restarts; explicit logout clears it.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'true').lower() == 'true',
    PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.environ.get('SESSION_DAYS', '30'))),
)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

init_firebase()

FIREBASE_WEB_CONFIG = {
    'apiKey': os.environ.get('FB_API_KEY', ''),
    'authDomain': os.environ.get('FB_AUTH_DOMAIN', ''),
    'projectId': os.environ.get('FB_PROJECT_ID', ''),
    'storageBucket': os.environ.get('FB_STORAGE_BUCKET', ''),
    'messagingSenderId': os.environ.get('FB_SENDER_ID', ''),
    'appId': os.environ.get('FB_APP_ID', ''),
}


# --- Auth ---
def verify_token(id_token):
    try:
        return fb_auth.verify_id_token(id_token)
    except Exception as e:
        print(f"Token fail: {e}")
        return None


def current_user():
    uid = session.get('uid')
    if not uid:
        return None
    u = db.get_user(uid)
    if not u:
        return None
    u['uid'] = uid
    return u


def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not current_user():
            return redirect(url_for('login'))
        return f(*a, **kw)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or not u.get('is_admin'):
            abort(403)
        return f(*a, **kw)
    return w


def notify_telegram_event(title, details):
    """Send event notifications to the configured admin Telegram chat."""
    try:
        settings = db.get_settings()
        token = (settings.get('telegram_bot_token') or '').strip()
        chat_id = str(settings.get('telegram_chat_id') or '').strip()
        if not settings.get('telegram_bot_enabled') or not token or not chat_id:
            return False
        lines = [f"🔔 {title}"] + [f"{key}: {value}" for key, value in details.items()]
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(lines), "disable_web_page_preview": True},
            timeout=8,
        )
        if not response.ok or not response.json().get('ok'):
            print(f"[TELEGRAM] Notification failed: {response.text[:300]}", flush=True)
            return False
        return True
    except Exception as exc:
        print(f"[TELEGRAM] Notification error: {exc}", flush=True)
        return False


# --- Security (disabled for host-any-file) ---
DANGEROUS = []
def scan_code(text):
    return True, None


# ========== PUBLIC ==========
@app.route('/')
def index():
    if current_user():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/login')
def login():
    if current_user():
        return redirect(url_for('dashboard'))
    return render_template('login.html', fb_config=FIREBASE_WEB_CONFIG)


@app.route('/auth/session', methods=['POST'])
def auth_session():
    data = request.get_json() or {}
    id_token = data.get('idToken')
    if not id_token:
        return jsonify({'ok': False, 'error': 'No token'}), 400
    claims = verify_token(id_token)
    if not claims:
        return jsonify({'ok': False, 'error': 'Invalid token'}), 401
    uid = claims['uid']
    email = claims.get('email', '')
    name = claims.get('name', email.split('@')[0] if email else 'User')
    picture = claims.get('picture', '')
    was_new_user = db.get_user(uid) is None
    user = db.create_or_update_user(uid, email, name, picture)
    notify_telegram_event('New user registered' if was_new_user else 'User login', {'Name': name, 'Email': email or '(not provided)', 'UID': uid})
    session.clear()
    session.permanent = True
    session['uid'] = uid
    return jsonify({'ok': True, 'is_admin': user.get('is_admin', False)})


@app.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('login', logged_out='1'))
    response.delete_cookie(app.config.get('SESSION_COOKIE_NAME', 'session'))
    return response


# ========== USER PAGES ==========
@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    scripts = db.list_scripts(user['uid'])
    for s in scripts:
        s['status_info'] = runner.get_status(s['id'])
        s['running'] = s['status_info'].get('running', False)
    running_count = sum(1 for s in scripts if s['running'])
    total_users = db.count_users()
    pending_count = len(db.list_pending_scripts()) if user.get('is_admin') else 0

    return render_template('dashboard.html', user=user, scripts=scripts,
                           running_count=running_count, total_users=total_users,
                           pending_count=pending_count,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/my-bots')
@login_required
def my_bots():
    user = current_user()
    scripts = db.list_scripts(user['uid'])
    for s in scripts:
        s['status_info'] = runner.get_status(s['id'])
        s['running'] = s['status_info'].get('running', False)
    return render_template('my_bots.html', user=user, scripts=scripts,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/create-bot')
@login_required
def create_bot():
    user = current_user()
    return render_template('create_bot.html', user=user,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/upload', methods=['POST'])
@login_required
def upload():
    user = current_user()
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No file'}), 400
    if db.count_scripts(user['uid']) >= user.get('file_limit', 2):
        return jsonify({'ok': False, 'error': 'File limit reached'}), 400

    filename = secure_filename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'ok': False, 'error': 'Only .py/.js/.zip'}), 400

    sid = str(uuid.uuid4())[:12]
    sdir = runner.get_script_dir(user['uid'], sid)
    os.makedirs(sdir, exist_ok=True)

    # Handle requirements
    req_content = None
    req_file = request.files.get('requirements')
    if req_file and req_file.filename:
        try:
            req_content = req_file.read().decode('utf-8', errors='ignore')
        except Exception:
            pass
    if not req_content:
        req_text = request.form.get('requirements_text', '').strip()
        if req_text:
            req_content = req_text

    if req_content and req_content.strip():
        try:
            with open(os.path.join(sdir, 'requirements.txt'), 'w', encoding='utf-8') as rf:
                rf.write(req_content)
        except Exception:
            pass

    if ext == '.zip':
        return _handle_zip(f, user, sid, sdir)
    return _handle_single(f, user, sid, sdir, filename, ext)


def _start_uploaded_script(sid, user, sdir, filename, file_type):
    """Start a newly uploaded, already-approved admin script."""
    file_path = os.path.join(sdir, filename)
    if not os.path.isfile(file_path):
        return False, 'Main file missing'
    ok, message = runner.start_script(sid, user['uid'], file_path, file_type)
    if ok:
        db.update_script(sid, {'running': True, 'status': 'running', 'last_started_at': datetime.utcnow().isoformat()})
    else:
        db.update_script(sid, {'running': False, 'status': 'approved', 'last_start_error': str(message)[:500]})
    return ok, message


def _handle_single(f, user, sid, sdir, filename, ext):
    content = f.read()
    if len(content) > MAX_FILE_SIZE:
        return jsonify({'ok': False, 'error': 'Too large'}), 400

    local_path = os.path.join(sdir, filename)
    with open(local_path, 'wb') as out:
        out.write(content)

    # Firebase Storage is an optional mirror. The previous local upload flow must
    # keep working when Storage is not configured; if configured, deletion syncs too.
    storage_path = storage_helper.upload_script_file(local_path, user['uid'], sid, filename) or ''

    settings = db.get_settings()
    is_admin_upload = bool(user.get('is_admin'))
    initial_status = 'approved' if (is_admin_upload or settings.get('auto_approve')) else 'pending'
    db.add_script(sid, user['uid'], filename, ext[1:], storage_path, status=initial_status)

    started = False
    start_message = ''
    if is_admin_upload:
        started, start_message = _start_uploaded_script(sid, user, sdir, filename, ext[1:])
    script = db.get_script(sid) or {}
    notify_telegram_event('New file upload', {'User': user.get('name', user.get('email', user['uid'])), 'Email': user.get('email', ''), 'File': filename, 'Type': ext[1:], 'Status': script.get('status', initial_status), 'Started': started, 'Script ID': sid})
    msg = "Admin upload approved and started." if started else (
        f"Admin upload approved; start failed: {start_message}" if is_admin_upload else
        ("Uploaded! Admin approval ka wait karo." if initial_status == 'pending' else "Uploaded & approved!")
    )
    return jsonify({'ok': True, 'sid': sid, 'status': script.get('status', initial_status),
                    'started': started, 'message': msg})


def _handle_zip(f, user, sid, sdir):
    tmp = tempfile.mkdtemp(prefix='zip_')
    try:
        zpath = os.path.join(tmp, 'archive.zip')
        f.save(zpath)
        with zipfile.ZipFile(zpath) as z:
            for m in z.infolist():
                p = os.path.abspath(os.path.join(tmp, m.filename))
                if not p.startswith(os.path.abspath(tmp)):
                    return jsonify({'ok': False, 'error': 'Unsafe zip'}), 400
            z.extractall(tmp)

        items = os.listdir(tmp)
        if len(items) == 1 and os.path.isdir(os.path.join(tmp, items[0])):
            tmp = os.path.join(tmp, items[0])
            items = os.listdir(tmp)

        py = [x for x in items if x.endswith('.py')]
        js = [x for x in items if x.endswith('.js')]
        main, main_type = None, None
        for p in ['main.py', 'bot.py', 'app.py', 'server.py', 'run.py']:
            if p in py:
                main, main_type = p, 'py'; break
        if not main:
            for p in ['index.js', 'main.js', 'bot.js', 'app.js']:
                if p in js:
                    main, main_type = p, 'js'; break
        if not main:
            if py: main, main_type = py[0], 'py'
            elif js: main, main_type = js[0], 'js'
        if not main:
            return jsonify({'ok': False, 'error': 'No .py/.js found'}), 400

        for item in os.listdir(tmp):
            src = os.path.join(tmp, item)
            dst = os.path.join(sdir, item)
            if os.path.isdir(dst): shutil.rmtree(dst)
            elif os.path.exists(dst): os.remove(dst)
            shutil.move(src, dst)

        # Optional Firebase mirror; do not block the previous local upload flow.
        uploaded_files = storage_helper.upload_script_folder(sdir, user['uid'], sid)

        settings = db.get_settings()
        is_admin_upload = bool(user.get('is_admin'))
        initial_status = 'approved' if (is_admin_upload or settings.get('auto_approve')) else 'pending'
        storage_path = f"scripts/{user['uid']}/{sid}/" if uploaded_files else ''
        db.add_script(sid, user['uid'], main, main_type, storage_path, status=initial_status)

        started = False
        start_message = ''
        if is_admin_upload:
            started, start_message = _start_uploaded_script(sid, user, sdir, main, main_type)
        script = db.get_script(sid) or {}
        notify_telegram_event('New ZIP upload', {'User': user.get('name', user.get('email', user['uid'])), 'Email': user.get('email', ''), 'File': f.filename, 'Main file': main, 'Status': script.get('status', initial_status), 'Started': started, 'Script ID': sid})
        msg = "Admin ZIP approved and started." if started else (
            f"Admin ZIP approved; start failed: {start_message}" if is_admin_upload else
            ("Uploaded! Admin approval ka wait karo." if initial_status == 'pending' else "Uploaded & approved!")
        )
        return jsonify({'ok': True, 'sid': sid, 'status': script.get('status', initial_status),
                        'started': started, 'message': msg})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ========== API: Start / Stop / Restart / Logs / Delete ==========

def _get_script_for_user(sid, user):
    s = db.get_script(sid)
    if not s:
        return None, ('Not found', 404)
    if s['user_id'] != user['uid'] and not user.get('is_admin'):
        return None, ('Forbidden', 403)
    return s, None


@app.route('/api/script/<sid>/start', methods=['POST'])
@login_required
def api_start(sid):
    user = current_user()
    s, err = _get_script_for_user(sid, user)
    if err: return jsonify({'ok': False, 'error': err[0]}), err[1]

    if s.get('status') != 'approved':
        return jsonify({'ok': False, 'error': f"Script status: {s.get('status')} — admin approval required"}), 400

    sdir = runner.get_script_dir(s['user_id'], sid)
    fpath = os.path.join(sdir, s['name'])
    if not os.path.exists(fpath):
        storage_helper.download_script_folder(s['user_id'], sid, sdir)
    if not os.path.exists(fpath):
        return jsonify({'ok': False, 'error': 'File missing'}), 400

    ok, msg = runner.start_script(sid, s['user_id'], fpath, s['type'])
    if ok:
        db.update_script(sid, {'running': True, 'status': 'running'})
    return jsonify({'ok': ok, 'message': msg})


@app.route('/api/script/<sid>/stop', methods=['POST'])
@login_required
def api_stop(sid):
    user = current_user()
    s, err = _get_script_for_user(sid, user)
    if err: return jsonify({'ok': False}), err[1]

    ok, msg = runner.stop_script(sid)
    if ok:
        db.update_script(sid, {'running': False, 'status': 'stopped'})
    return jsonify({'ok': ok, 'message': msg})


@app.route('/api/script/<sid>/restart', methods=['POST'])
@login_required
def api_restart(sid):
    user = current_user()
    s, err = _get_script_for_user(sid, user)
    if err: return jsonify({'ok': False}), err[1]

    if s.get('status') not in ('approved', 'running', 'stopped'):
        return jsonify({'ok': False, 'error': 'Not approved'}), 400

    runner.stop_script(sid)
    sdir = runner.get_script_dir(s['user_id'], sid)
    fpath = os.path.join(sdir, s['name'])
    if not os.path.exists(fpath):
        storage_helper.download_script_folder(s['user_id'], sid, sdir)
    ok, msg = runner.start_script(sid, s['user_id'], fpath, s['type'])
    if ok:
        db.update_script(sid, {'running': True, 'status': 'running'})
    return jsonify({'ok': ok, 'message': msg})


@app.route('/api/script/<sid>/logs')
@login_required
def api_logs(sid):
    user = current_user()
    s, err = _get_script_for_user(sid, user)
    if err: return jsonify({'ok': False}), err[1]
    log = runner.read_log(sid, s['user_id'])
    status = runner.get_status(sid)
    return jsonify({'ok': True, 'log': log, 'status': status})


@app.route('/api/script/<sid>/delete', methods=['POST'])
@login_required
def api_delete(sid):
    user = current_user()
    s, err = _get_script_for_user(sid, user)
    if err: return jsonify({'ok': False}), err[1]
    runner.stop_script(sid)
    # Delete cloud copies immediately when this script was mirrored to Firebase.
    # If cloud deletion fails, keep its database record so the operation can be retried.
    if s.get('storage_path') and not storage_helper.delete_script_folder(s['user_id'], sid):
        return jsonify({'ok': False, 'error': 'Firebase Storage delete failed. Check bucket permissions and retry.'}), 502
    sdir = runner.get_script_dir(s['user_id'], sid)
    shutil.rmtree(sdir, ignore_errors=True)
    db.delete_script(sid)
    return jsonify({'ok': True})


# ========== ADMIN: Review Queue ==========

@app.route('/admin/review')
@admin_required
def admin_review_queue():
    user = current_user()
    pending = db.list_pending_scripts()
    users_map = {u['uid']: u for u in db.list_users()}
    return render_template('admin_review.html',
                           user=user,
                           pending=pending,
                           users=users_map,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/admin/review/<sid>')
@admin_required
def admin_review_detail(sid):
    user = current_user()
    s = db.get_script(sid)
    if not s:
        abort(404)
    owner = db.get_user(s['user_id'])
    sdir = runner.get_script_dir(s['user_id'], sid)

    # Read main file content
    main_path = os.path.join(sdir, s['name'])
    content = ''
    if os.path.exists(main_path):
        try:
            with open(main_path, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
        except Exception:
            content = '(unable to read)'

    # List all files in folder
    files = []
    for root, dirs, files_in_dir in os.walk(sdir):
        for fn in files_in_dir:
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, sdir)
            try:
                sz = os.path.getsize(fp)
            except Exception:
                sz = 0
            files.append({'rel': rel, 'size': sz, 'abs': fp})

    return render_template('admin_review.html',
                           user=user, script=s, owner=owner,
                           content=content, files=files,
                           fb_config=FIREBASE_WEB_CONFIG,
                           mode='detail')


@app.route('/admin/review/<sid>/file')
@admin_required
def admin_review_file(sid):
    """Serve a specific file for download/preview."""
    user = current_user()
    s = db.get_script(sid)
    if not s:
        abort(404)
    rel = request.args.get('path', s['name'])
    sdir = runner.get_script_dir(s['user_id'], sid)
    fpath = os.path.join(sdir, rel)
    if not os.path.exists(fpath):
        abort(404)
    return send_file(fpath, as_attachment=True,
                     download_name=os.path.basename(rel))


@app.route('/admin/review/<sid>/approve', methods=['POST'])
@admin_required
def admin_review_approve(sid):
    user = current_user()
    s = db.get_script(sid)
    if not s:
        abort(404)
    note = request.form.get('note', '')
    db.approve_script(sid, user['uid'], note)
    flash(f"✅ Approved: {s['name']}", "success")
    return redirect(url_for('admin_review_queue'))


@app.route('/admin/review/<sid>/reject', methods=['POST'])
@admin_required
def admin_review_reject(sid):
    user = current_user()
    s = db.get_script(sid)
    if not s:
        abort(404)
    note = request.form.get('note', '')
    db.reject_script(sid, user['uid'], note)
    flash(f"❌ Rejected: {s['name']}", "success")
    return redirect(url_for('admin_review_queue'))


# ========== ADMIN: Terminal ==========

@app.route('/admin/terminal')
@admin_required
def admin_terminal_page():
    user = current_user()
    return render_template('admin_terminal.html',
                           user=user,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/admin/terminal/exec', methods=['POST'])
@admin_required
def admin_terminal_exec():
    """Execute a command in the terminal."""
    user = current_user()
    data = request.get_json() or {}
    command = data.get('command', '').strip()
    sid = f"admin_{user['uid']}"

    if not command:
        return jsonify({'ok': False, 'error': 'Empty command'}), 400

    lines = []
    try:
        for event in terminal.run_command(sid, command):
            lines.append(event)
        return jsonify({'ok': True, 'events': lines})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/admin/terminal/abort', methods=['POST'])
@admin_required
def admin_terminal_abort():
    user = current_user()
    sid = f"admin_{user['uid']}"
    terminal.abort_current(sid)
    return jsonify({'ok': True})


@app.route('/admin/terminal/history')
@admin_required
def admin_terminal_history():
    user = current_user()
    sid = f"admin_{user['uid']}"
    return jsonify({'ok': True, 'history': terminal.get_history(sid)})


# ========== ADMIN: Dashboard / Users / Payments ==========

@app.route('/admin')
@admin_required
def admin_dashboard():
    user = current_user()
    users = db.list_users()
    scripts = db.list_scripts()
    pending = db.list_pending_scripts()
    for u in users:
        u['script_count'] = db.count_scripts(u['uid'])
    for s in scripts:
        s['status_info'] = runner.get_status(s['id'])
        s['running'] = s['status_info'].get('running', False)
    return render_template('admin.html', user=user, users=users, scripts=scripts,
                           pending=pending,
                           pending_count=len(pending),
                           running_count=sum(1 for s in scripts if s['running']),
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/admin/user/<uid>/limit', methods=['POST'])
@admin_required
def admin_set_limit(uid):
    try:
        limit = int(request.form.get('limit', 2))
        db.set_user_limit(uid, limit)
        flash(f"Limit set to {limit}", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<uid>/plan', methods=['POST'])
@admin_required
def admin_set_plan(uid):
    plan = request.form.get('plan', 'free')
    days = int(request.form.get('days', 30))
    db.set_user_plan(uid, plan, days)
    flash(f"Plan {plan} ({days} days) set", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<uid>/admin', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    val = request.form.get('is_admin') == '1'
    db.make_admin(uid, val)
    flash(f"Admin: {val}", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<uid>/delete', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid == current_user()['uid']:
        flash("Can't delete yourself", "error")
        return redirect(url_for('admin_dashboard'))
    for script in db.list_scripts(uid):
        runner.stop_script(script['id'])
        if script.get('storage_path') and not storage_helper.delete_script_folder(uid, script['id']):
            flash(f"Firebase Storage delete failed for {script.get('name', script['id'])}; user not deleted. Check Storage permissions and retry.", "error")
            return redirect(url_for('admin_dashboard'))
    shutil.rmtree(os.path.join(UPLOAD_DIR, uid), ignore_errors=True)
    db.delete_user(uid)
    flash("User deleted", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/payments')
@admin_required
def admin_payments():
    user = current_user()
    payments = db.list_payments()
    users_map = {u['uid']: u for u in db.list_users()}
    settings = db.get_settings()
    return render_template('admin_payments.html', user=user, payments=payments,
                           users=users_map, settings=settings,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/admin/payment/add', methods=['POST'])
@admin_required
def admin_add_payment():
    try:
        user_id = request.form['user_id']
        amount = request.form['amount']
        method = request.form.get('method', 'manual')
        status = request.form.get('status', 'success')
        note = request.form.get('note', '')
        db.add_payment(user_id, amount, method, status, note)
        flash("Payment added", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('admin_payments'))


@app.route('/admin/payment/<pid>/status', methods=['POST'])
@admin_required
def admin_payment_status(pid):
    status = request.form.get('status', 'pending')
    if status not in {'pending', 'success', 'failed'}:
        abort(400)
    payment = db.get_payment(pid)
    if not payment:
        abort(404)
    was_successful = payment.get('status') == 'success'
    db.update_payment_status(pid, status)
    # Only an explicit admin approval activates the package, once.
    if status == 'success' and not was_successful and payment.get('plan_id'):
        uid = payment.get('user_id')
        days = max(0, int(payment.get('days') or 0))
        bots = max(1, int(payment.get('bots') or 1))
        if uid and db.get_user(uid):
            db.set_user_plan(uid, payment.get('plan_id') or payment.get('plan_name', 'premium'), days or 30)
            db.update_user(uid, {'file_limit': bots, 'plan_name': payment.get('plan_name', '')})
    flash(f"Payment status: {status}", "success")
    return redirect(url_for('admin_payments'))


@app.route('/admin/pricing', methods=['POST'])
@admin_required
def admin_update_pricing():
    try:
        plans = []
        legacy_pricing = {}
        defaults = [
            ('free', 'Free', 0, 2, 0),
            ('premium', 'Premium', 199, 20, 30),
            ('business', 'Business', 499, 999, 30),
        ]
        for idx, (plan_id, default_name, default_price, default_bots, default_days) in enumerate(defaults, 1):
            name = request.form.get(f'plan_name_{idx}', default_name).strip()[:40] or default_name
            price = max(0, int(request.form.get(f'plan_price_{idx}', default_price)))
            bots = max(1, int(request.form.get(f'plan_bots_{idx}', default_bots)))
            days = max(0, int(request.form.get(f'plan_days_{idx}', default_days)))
            plan = {'id': plan_id, 'name': name, 'price': price, 'bots': bots, 'days': days}
            plans.append(plan)
            legacy_pricing[plan_id] = {'price': price, 'bots': bots, 'days': days, 'name': name}

        current_settings = db.get_settings()
        data = {
            'plans': plans,
            'pricing': legacy_pricing,
            'per_bot_price': max(0, int(request.form.get('per_bot_price', 49))),
            'upi_id': request.form.get('upi_id', '').strip()[:120],
            'upi_name': request.form.get('upi_name', '').strip()[:100],
            'offer_text': request.form.get('offer_text', '').strip()[:250],
            'support_contact': request.form.get('support_contact', '').strip()[:120],
            'payment_note': request.form.get('payment_note', '').strip()[:1000],
            'auto_approve': current_settings.get('auto_approve', False),
        }

        qr_file = request.files.get('qr_image')
        if qr_file and qr_file.filename:
            ext = os.path.splitext(secure_filename(qr_file.filename))[1].lower()
            if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('QR file PNG/JPG/WEBP hona chahiye.')
            qr_file.stream.seek(0, os.SEEK_END)
            size = qr_file.stream.tell()
            qr_file.stream.seek(0)
            if size > 5 * 1024 * 1024:
                raise ValueError('QR image 5 MB se chhoti honi chahiye.')
            qr_dir = os.path.join(BASE_DIR, 'static', 'uploads', 'payment_qr')
            os.makedirs(qr_dir, exist_ok=True)
            qr_name = f"qr_{uuid.uuid4().hex}{ext}"
            qr_path = os.path.join(qr_dir, qr_name)
            qr_file.save(qr_path)
            local_qr_url = url_for('static', filename=f'uploads/payment_qr/{qr_name}')
            # Mirror QR to Firebase when available, but keep local upload working if not.
            cloud_qr_url = storage_helper.upload_qr_image(qr_path, qr_name)
            data['qr_code_url'] = cloud_qr_url or local_qr_url

        db.update_settings(data)
        flash("Payment details aur pricing save ho gayi ✅", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('admin_payments'))


@app.route('/admin/script/<sid>/start', methods=['POST'])
@admin_required
def admin_start(sid):
    s = db.get_script(sid)
    if not s: return jsonify({'ok': False}), 404
    sdir = runner.get_script_dir(s['user_id'], sid)
    fpath = os.path.join(sdir, s['name'])
    if not os.path.exists(fpath):
        storage_helper.download_script_folder(s['user_id'], sid, sdir)
    if not os.path.exists(fpath):
        return jsonify({'ok': False, 'error': 'File missing'}), 400
    ok, msg = runner.start_script(sid, s['user_id'], fpath, s['type'])
    if ok:
        db.update_script(sid, {'running': True, 'status': 'running'})
    return jsonify({'ok': ok, 'message': msg})


@app.route('/admin/script/<sid>/stop', methods=['POST'])
@admin_required
def admin_stop(sid):
    ok, msg = runner.stop_script(sid)
    if ok:
        db.update_script(sid, {'running': False, 'status': 'stopped'})
    return jsonify({'ok': ok, 'message': msg})


# ========== PUBLIC PAGES ==========
@app.route('/pricing')
def pricing():
    user = current_user()
    settings = db.get_settings()
    return render_template('pricing.html', user=user, settings=settings,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/payment/request', methods=['POST'])
@login_required
def payment_request():
    user = current_user()
    settings = db.get_settings()
    plan_id = request.form.get('plan_id', '').strip()
    plan = next((p for p in settings.get('plans', []) if p.get('id') == plan_id), None)
    if not plan:
        flash('Package nahi mila. Pricing page refresh karke try karein.', 'error')
        return redirect(url_for('pricing'))
    try:
        amount = max(0, int(plan.get('price', 0)))
        days = max(0, int(plan.get('days', 0)))
        bots = max(1, int(plan.get('bots', 1)))
        if amount <= 0 or days <= 0:
            flash('Free package ke liye payment request ki zaroorat nahi hai.', 'error')
            return redirect(url_for('pricing'))
        reference = request.form.get('transaction_ref', '').strip()[:160]
        if not reference:
            flash('Payment ke baad UTR / transaction reference daalein.', 'error')
            return redirect(url_for('pricing'))
        db.add_payment(
            user['uid'], amount, 'upi', 'pending',
            note=f'Transaction reference: {reference}',
            plan_id=plan_id, plan_name=plan.get('name', plan_id),
            days=days, bots=bots
        )
        flash('Payment request admin ko bhej di gayi hai. Approval ke baad package activate hoga.', 'success')
        return redirect(url_for('payment_history'))
    except Exception as exc:
        flash(f'Payment request save nahi hui: {exc}', 'error')
        return redirect(url_for('pricing'))


@app.route('/docs')
def docs():
    user = current_user()
    return render_template('docs.html', user=user, fb_config=FIREBASE_WEB_CONFIG)


@app.route('/support')
def support():
    user = current_user()
    settings = db.get_settings()
    return render_template('support.html', user=user, settings=settings,
                           fb_config=FIREBASE_WEB_CONFIG)


@app.route('/payment-history')
@login_required
def payment_history():
    user = current_user()
    payments = db.list_payments(user['uid'])
    settings = db.get_settings()
    return render_template('payment_history.html', user=user, payments=payments,
                           settings=settings, fb_config=FIREBASE_WEB_CONFIG)


def restore_running_scripts():
    """Rehydrate approved bots marked running from Firebase Storage after Railway restarts."""
    if os.environ.get('RESTORE_BOTS_ON_STARTUP', 'true').lower() != 'true':
        print('[RESTORE] Disabled by RESTORE_BOTS_ON_STARTUP', flush=True)
        return
    try:
        scripts = db.list_scripts()
    except Exception as exc:
        print(f'[RESTORE] Firestore read failed: {exc}', flush=True)
        return
    restored = 0
    for script in scripts:
        if script.get('status') != 'running' and not script.get('running'):
            continue
        sid = script.get('id')
        uid = script.get('user_id')
        if not sid or not uid:
            continue
        try:
            script_dir = runner.get_script_dir(uid, sid)
            main_path = os.path.join(script_dir, script.get('name', ''))
            if not os.path.isfile(main_path):
                storage_helper.download_script_folder(uid, sid, script_dir)
            if not os.path.isfile(main_path):
                print(f'[RESTORE] Missing source for {sid}; keeping it stopped', flush=True)
                db.update_script(sid, {'running': False, 'status': 'approved', 'last_start_error': 'Source files not found in persistent storage'})
                continue
            ok, message = runner.start_script(sid, uid, main_path, script.get('type', 'py'))
            if ok:
                db.update_script(sid, {'running': True, 'status': 'running', 'last_restored_at': datetime.utcnow().isoformat()})
                restored += 1
                print(f'[RESTORE] Started {sid}: {message}', flush=True)
            else:
                db.update_script(sid, {'running': False, 'status': 'approved', 'last_start_error': str(message)[:500]})
                print(f'[RESTORE] Could not start {sid}: {message}', flush=True)
        except Exception as exc:
            print(f'[RESTORE] Error for {sid}: {exc}', flush=True)
    print(f'[RESTORE] Finished. Restarted {restored} bot(s).', flush=True)


# Run once when the single Gunicorn worker imports this module.
restore_running_scripts()

import atexit
atexit.register(runner.cleanup_all)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
