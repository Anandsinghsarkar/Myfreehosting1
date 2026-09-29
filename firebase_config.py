# REAL_NAME: firebase_config.py
# -*- coding: utf-8 -*-
import os
import json
import traceback
import firebase_admin
from firebase_admin import credentials, firestore, storage

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
KEY_PATH = os.environ.get('FIREBASE_KEY_PATH',
                          os.path.join(BASE_DIR, 'firebase-key.json'))

_db = None
_bucket = None
_initialized = False


def init_firebase():
    global _db, _bucket, _initialized
    if _initialized:
        return _db, _bucket

    print("🔥 Firebase init starting...", flush=True)

    key_json = os.environ.get('FIREBASE_KEY_JSON')
    print(f"   FIREBASE_KEY_JSON present: {bool(key_json)}", flush=True)
    print(f"   KEY_PATH exists: {os.path.exists(KEY_PATH)}", flush=True)

    if key_json:
        try:
            cred_dict = json.loads(key_json)
            cred = credentials.Certificate(cred_dict)
            print(f"✅ Loaded from env (project: {cred_dict.get('project_id')})", flush=True)
        except Exception as e:
            print(f"❌ FIREBASE_KEY_JSON parse failed: {e}", flush=True)
            traceback.print_exc()
            raise
    elif os.path.exists(KEY_PATH):
        cred = credentials.Certificate(KEY_PATH)
        print("✅ Loaded from file", flush=True)
    else:
        print("❌ No Firebase key found!", flush=True)
        raise RuntimeError("Firebase key not found. Set FIREBASE_KEY_JSON.")

    bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET', '')

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'storageBucket': bucket_name})

    _db = firestore.client()
    print("✅ Firestore connected", flush=True)

    try:
        _bucket = storage.bucket()
        print(f"✅ Storage bucket: {bucket_name or '(default)'}", flush=True)
    except Exception as e:
        print(f"⚠️ Storage bucket failed: {e}", flush=True)
        _bucket = None

    _initialized = True
    print("✅ Firebase fully initialized", flush=True)
    return _db, _bucket


def get_db():
    if not _initialized:
        init_firebase()
    return _db


def get_bucket():
    if not _initialized:
        init_firebase()
    return _bucket
