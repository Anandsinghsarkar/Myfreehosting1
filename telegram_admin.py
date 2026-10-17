# -*- coding: utf-8 -*-
"""Telegram inline-button admin controller for the hosting website.

All callback actions are restricted to the configured admin chat. This module
uses Telegram webhooks so it works with a single Railway web service.
"""
import os
import secrets
import requests
from datetime import datetime

API = "https://api.telegram.org/bot{}/{}"


def _settings(appmod):
    return appmod.db.get_settings()


def _api(appmod, method, payload=None, files=None):
    s = _settings(appmod)
    token = (s.get("telegram_bot_token") or "").strip()
    if not token:
        return {"ok": False, "description": "Bot token is not configured"}
    try:
        r = requests.post(API.format(token, method), data=payload or {}, files=files, timeout=15)
        return r.json()
    except Exception as exc:
        print("[TG ADMIN]", exc, flush=True)
        return {"ok": False, "description": str(exc)[:200]}


def send_message(appmod, text, keyboard=None, chat_id=None):
    s = _settings(appmod)
    target = str(chat_id or s.get("telegram_chat_id") or "").strip()
    payload = {"chat_id": target, "text": str(text)[:3900], "disable_web_page_preview": "true"}
    if keyboard:
        import json
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return _api(appmod, "sendMessage", payload)


def send_upload_notice(appmod, sid, title, details, file_paths=None):
    s = _settings(appmod)
    if not s.get("telegram_bot_enabled") or not s.get("telegram_chat_id"):
        return False
    rows = [[
        {"text": "👀 Review File", "callback_data": "script:view:" + sid},
        {"text": "✅ Approve", "callback_data": "script:approve:" + sid},
    ], [
        {"text": "❌ Reject", "callback_data": "script:reject:" + sid},
        {"text": "📋 Pending Files", "callback_data": "menu:pending"},
    ]]
    lines = [title] + [f"{k}: {v}" for k, v in details.items()]
    send_message(appmod, "\n".join(lines), rows)
    # Send the uploaded source itself so the admin can inspect it in Telegram.
    sent = False
    for path in (file_paths or []):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                result = _api(appmod, "sendDocument", {
                    "chat_id": str(s.get("telegram_chat_id")),
                    "caption": f"📄 {os.path.basename(path)} · Script ID: {sid}"[:900],
                }, files={"document": (os.path.basename(path), fh)})
            sent = sent or bool(result.get("ok"))
        except Exception as exc:
            print("[TG FILE SEND]", exc, flush=True)
    return sent


def _menu(appmod, chat_id):
    keyboard = [
        [{"text": "📊 Dashboard Stats", "callback_data": "menu:stats"},
         {"text": "📁 Pending Files", "callback_data": "menu:pending"}],
        [{"text": "💳 Pending Payments", "callback_data": "menu:payments"},
         {"text": "👥 Recent Users", "callback_data": "menu:users"}],
        [{"text": "▶️ Running Bots", "callback_data": "menu:running"},
         {"text": "🌐 Open Website Admin", "url": os.environ.get("PUBLIC_BASE_URL", "https://example.com/admin")}],
        [{"text": "🔄 Refresh Menu", "callback_data": "menu:home"}],
    ]
    send_message(appmod, "🤖 Hosting Admin Panel\nChoose an action:", keyboard, chat_id)


def _script_card(appmod, sid, chat_id):
    s = appmod.db.get_script(sid)
    if not s:
        send_message(appmod, "File record nahi mila.", chat_id=chat_id)
        return
    owner = appmod.db.get_user(s.get("user_id", "")) or {}
    text = (
        "📁 FILE REVIEW\n"
        f"Name: {s.get('name', '-')}\nType: {s.get('type', '-')}\n"
        f"Status: {s.get('status', '-')}\nScript ID: {sid}\n"
        f"User: {owner.get('name', '-')}\nEmail: {owner.get('email', '-')}\n"
        f"Created: {s.get('created_at', '-')}"
    )
    keyboard = [
        [{"text": "✅ Approve", "callback_data": "script:approve:" + sid},
         {"text": "❌ Reject", "callback_data": "script:reject:" + sid}],
        [{"text": "▶️ Start", "callback_data": "script:start:" + sid},
         {"text": "⏹ Stop", "callback_data": "script:stop:" + sid}],
        [{"text": "📄 Send Source Again", "callback_data": "script:file:" + sid},
         {"text": "🗑 Delete", "callback_data": "script:delete:" + sid}],
        [{"text": "⬅️ Main Menu", "callback_data": "menu:home"}],
    ]
    send_message(appmod, text, keyboard, chat_id)


def _payment_card(appmod, pid, chat_id):
    p = appmod.db.get_payment(pid)
    if not p:
        send_message(appmod, "Payment record nahi mila.", chat_id=chat_id)
        return
    owner = appmod.db.get_user(p.get("user_id", "")) or {}
    text = (
        "💳 PAYMENT REVIEW\n"
        f"User: {owner.get('name', '-')}\nEmail: {owner.get('email', '-')}\n"
        f"Amount: ₹{p.get('amount', 0)}\nPackage: {p.get('plan_name', '-')}\n"
        f"Validity: {p.get('days', 0)} days · Bot limit: {p.get('bots', 0)}\n"
        f"Reference: {p.get('note', '-')}\nStatus: {p.get('status', '-')}\n"
        f"Payment ID: {pid}"
    )
    keyboard = [
        [{"text": "✅ Approve & Activate", "callback_data": "payment:approve:" + pid},
         {"text": "❌ Reject", "callback_data": "payment:reject:" + pid}],
        [{"text": "⬅️ Pending Payments", "callback_data": "menu:payments"}],
    ]
    send_message(appmod, text, keyboard, chat_id)


def _callback(appmod, data, chat_id):
    parts = data.split(":")
    if len(parts) < 2:
        return send_message(appmod, "Unknown action.", chat_id=chat_id)
    area, action = parts[0], parts[1]
    ident = parts[2] if len(parts) > 2 else ""
    db = appmod.db
    if area == "menu":
        if action == "home":
            return _menu(appmod, chat_id)
        if action == "stats":
            users = db.list_users()
            scripts = db.list_scripts()
            pending = db.list_pending_scripts()
            payments = db.list_payments()
            running = sum(1 for x in scripts if x.get("status") == "running" or x.get("running"))
            send_message(appmod, f"📊 WEBSITE STATS\nUsers: {len(users)}\nFiles/Bots: {len(scripts)}\nPending files: {len(pending)}\nRunning: {running}\nPayments: {len(payments)}", [[{"text":"🏠 Menu","callback_data":"menu:home"}]], chat_id)
        elif action == "pending":
            items = db.list_pending_scripts()
            if not items:
                send_message(appmod, "✅ Koi pending file nahi hai.", [[{"text":"🏠 Menu","callback_data":"menu:home"}]], chat_id)
            else:
                for item in items[:15]:
                    owner = db.get_user(item.get("user_id", "")) or {}
                    send_message(appmod, f"📁 {item.get('name')}\nUser: {owner.get('name', '-')}\nID: {item['id']}\nStatus: {item.get('status')}", [[{"text":"👀 Review","callback_data":"script:view:"+item["id"]},{"text":"✅ Approve","callback_data":"script:approve:"+item["id"]},{"text":"❌ Reject","callback_data":"script:reject:"+item["id"]}]], chat_id)
        elif action == "payments":
            items = [p for p in db.list_payments(limit=100) if p.get("status") == "pending"]
            if not items:
                send_message(appmod, "✅ Koi pending payment nahi hai.", [[{"text":"🏠 Menu","callback_data":"menu:home"}]], chat_id)
            else:
                for p in items[:15]:
                    send_message(appmod, f"💳 ₹{p.get('amount')} · {p.get('plan_name','Package')}\nID: {p['id']}\n{p.get('note','')}", [[{"text":"🔎 Review","callback_data":"payment:view:"+p["id"]},{"text":"✅ Approve","callback_data":"payment:approve:"+p["id"]},{"text":"❌ Reject","callback_data":"payment:reject:"+p["id"]}]], chat_id)
        elif action == "users":
            users = db.list_users(limit=15)
            lines = ["👥 RECENT USERS"]
            for u in users[:15]:
                lines.append(f"• {u.get('name','User')} · {u.get('email','')} · files {db.count_scripts(u.get('uid',''))}")
            send_message(appmod, "\n".join(lines), [[{"text":"🏠 Menu","callback_data":"menu:home"}]], chat_id)
        elif action == "running":
            items = [x for x in db.list_scripts() if x.get("status") == "running" or x.get("running")]
            if not items:
                send_message(appmod, "Abhi koi bot running nahi hai.", [[{"text":"🏠 Menu","callback_data":"menu:home"}]], chat_id)
            else:
                for item in items[:15]:
                    send_message(appmod, f"▶️ {item.get('name')} · {item['id']}", [[{"text":"⏹ Stop","callback_data":"script:stop:"+item["id"]},{"text":"🔄 Restart","callback_data":"script:restart:"+item["id"]}]], chat_id)
        return
    if area == "script":
        s = db.get_script(ident)
        if not s:
            return send_message(appmod, "File record nahi mila.", chat_id=chat_id)
        uid = s.get("user_id", "")
        sdir = appmod.runner.get_script_dir(uid, ident)
        main = os.path.join(sdir, s.get("name", ""))
        if action == "view":
            return _script_card(appmod, ident, chat_id)
        if action == "file":
            if not os.path.isfile(main):
                appmod.storage_helper.download_script_folder(uid, ident, sdir)
            if os.path.isfile(main):
                with open(main, "rb") as fh:
                    _api(appmod, "sendDocument", {"chat_id": str(chat_id), "caption": f"Source: {s.get('name')} · {ident}"}, files={"document": (os.path.basename(main), fh)})
            else:
                send_message(appmod, "Source file local/cloud storage se nahi mil rahi.", chat_id=chat_id)
        elif action == "approve":
            db.approve_script(ident, "telegram-admin", "Approved via Telegram")
            send_message(appmod, f"✅ Approved: {s.get('name')}\nAb Start button se run kar sakte ho.", [[{"text":"▶️ Start","callback_data":"script:start:"+ident},{"text":"📋 Pending Files","callback_data":"menu:pending"}]], chat_id)
        elif action == "reject":
            db.reject_script(ident, "telegram-admin", "Rejected via Telegram")
            send_message(appmod, f"❌ Rejected: {s.get('name')}", chat_id=chat_id)
        elif action in ("start", "restart"):
            if s.get("status") not in ("approved", "running", "stopped"):
                return send_message(appmod, "Pehle file approve karein.", chat_id=chat_id)
            if action == "restart":
                appmod.runner.stop_script(ident)
            if not os.path.isfile(main):
                appmod.storage_helper.download_script_folder(uid, ident, sdir)
            if not os.path.isfile(main):
                return send_message(appmod, "Source file nahi mili.", chat_id=chat_id)
            ok, msg = appmod.runner.start_script(ident, uid, main, s.get("type", "py"))
            if ok:
                db.update_script(ident, {"running": True, "status": "running"})
            send_message(appmod, ("✅ " if ok else "❌ ") + str(msg), chat_id=chat_id)
        elif action == "stop":
            ok, msg = appmod.runner.stop_script(ident)
            if ok:
                db.update_script(ident, {"running": False, "status": "stopped"})
            send_message(appmod, ("⏹ " if ok else "⚠️ ") + str(msg), chat_id=chat_id)
        elif action == "delete":
            appmod.runner.stop_script(ident)
            if s.get("storage_path") and not appmod.storage_helper.delete_script_folder(uid, ident):
                return send_message(appmod, "Firebase Storage delete fail hui; record rakha hai.", chat_id=chat_id)
            import shutil
            shutil.rmtree(sdir, ignore_errors=True)
            db.delete_script(ident)
            send_message(appmod, f"🗑 Deleted: {s.get('name')}", chat_id=chat_id)
        return
    if area == "payment":
        p = db.get_payment(ident)
        if not p:
            return send_message(appmod, "Payment record nahi mila.", chat_id=chat_id)
        if action == "view":
            return _payment_card(appmod, ident, chat_id)
        if action == "reject":
            db.update_payment_status(ident, "failed")
            send_message(appmod, f"❌ Payment rejected: {ident}", chat_id=chat_id)
            return
        if action == "approve":
            if p.get("status") == "success":
                return send_message(appmod, "Ye payment pehle se approve hai.", chat_id=chat_id)
            eligible_at = p.get("eligible_at") or ""
            if eligible_at:
                try:
                    eligible_dt = datetime.fromisoformat(eligible_at)
                    if datetime.utcnow() < eligible_dt:
                        remaining = max(1, int((eligible_dt - datetime.utcnow()).total_seconds() + 0.99))
                        return send_message(appmod, f"⏳ 5-minute review window abhi baaki hai: {remaining} seconds.", [[{"text":"🔄 Check Again","callback_data":"payment:approve:"+ident}]], chat_id)
                except (TypeError, ValueError):
                    pass
            db.update_payment_status(ident, "success")
            uid = p.get("user_id")
            days = max(0, int(p.get("days") or 0))
            bots = max(1, int(p.get("bots") or 1))
            if uid and db.get_user(uid) and p.get("plan_id"):
                db.set_user_plan(uid, p.get("plan_id") or p.get("plan_name", "premium"), days or 30)
                db.update_user(uid, {"file_limit": bots, "plan_name": p.get("plan_name", "")})
            send_message(appmod, f"✅ Payment approved and package activated.\nPackage: {p.get('plan_name','')}\nAmount: ₹{p.get('amount',0)}\nUser UID: {uid}", chat_id=chat_id)
        return


def handle_update(appmod, update):
    """Handle one webhook update. Caller validates webhook secret."""
    settings = _settings(appmod)
    admin_chat = str(settings.get("telegram_chat_id") or "").strip()
    msg = update.get("message") or update.get("edited_message")
    cb = update.get("callback_query")
    if msg:
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        sender_id = str((msg.get("from") or {}).get("id", ""))
        if chat.get("type") != "private" or chat_id != admin_chat or sender_id != admin_chat:
            return
        text = (msg.get("text") or "").strip().lower()
        if text in ("/start", "/menu", "/help"):
            return _menu(appmod, chat_id)
        return send_message(appmod, "Menu ke liye /start bhejein ya neeche buttons use karein.", chat_id=chat_id)
    if cb:
        chat = ((cb.get("message") or {}).get("chat") or {})
        chat_id = str(chat.get("id", ""))
        sender_id = str((cb.get("from") or {}).get("id", ""))
        if chat.get("type") != "private" or chat_id != admin_chat or sender_id != admin_chat:
            _api(appmod, "answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Not authorized", "show_alert": "true"})
            return
        _api(appmod, "answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Processing..."})
        return _callback(appmod, cb.get("data", ""), chat_id)
