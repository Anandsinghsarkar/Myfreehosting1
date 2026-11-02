# REAL_NAME: firebase_config.py
# -*- coding: utf-8 -*-
"""
Firebase Admin SDK — supports BASE64 (recommended for Railway).
Env vars:
  FIREBASE_KEY_B64  → base64 encoded service account JSON  (BEST)
  FIREBASE_KEY_JSON → raw JSON string
  FIREBASE_KEY_PATH → path to firebase-key.json file
"""
import os
import json
import base64
import traceback
import firebase_admin
from firebase_admin import credentials, firestore

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
KEY_PATH = os.environ.get('FIREBASE_KEY_PATH',
                          os.path.join(BASE_DIR, 'firebase-key.json'))

_db = None
_bucket = None
_firebase_app = None
_storage_bucket_name = ''
_storage_project_id = ''
_initialized = False


def _fix_private_key(cred_dict):
    """Ensure private_key has proper newlines and PEM headers."""
    if 'private_key' not in cred_dict:
        return cred_dict

    pk = cred_dict['private_key']

    # If \n literals exist, replace with actual newlines
    if '\\n' in pk:
        pk = pk.replace('\\n', '\n')

    # Strip whitespace
    pk = pk.strip()

    # Ensure BEGIN header
    if not pk.startswith('-----BEGIN'):
        pk = '-----BEGIN PRIVATE KEY-----\n' + pk

    # Ensure END footer
    if not pk.endswith('-----'):
        pk = pk + '\n-----END PRIVATE KEY-----'

    # Always end with newline
    if not pk.endswith('\n'):
        pk = pk + '\n'

    cred_dict['private_key'] = pk
    return cred_dict


def _load_credentials():
    """Try multiple methods to load Firebase credentials. Returns dict."""

    # ---- Method 1: BASE64 (BEST for Railway) ----
    key_b64 = os.environ.get('FIREBASE_KEY_B64', '').strip()
    if key_b64:
        print("   Trying FIREBASE_KEY_B64...", flush=True)
        try:
            # Clean whitespace/newlines in base64
            key_b64_clean = ''.join(key_b64.split())
            decoded = base64.b64decode(key_b64_clean).decode('utf-8')
            cred_dict = json.loads(decoded)
            cred_dict = _fix_private_key(cred_dict)
            print(f"✅ Loaded from BASE64 (project: {cred_dict.get('project_id')})",
                  flush=True)
            return cred_dict
        except Exception as e:
            print(f"⚠️ BASE64 load failed: {e}", flush=True)
            traceback.print_exc()

    # ---- Method 2: Raw JSON ----
    key_json = os.environ.get('FIREBASE_KEY_JSON', '').strip()
    if key_json:
        print("   Trying FIREBASE_KEY_JSON...", flush=True)
        try:
            cred_dict = json.loads(key_json)
            cred_dict = _fix_private_key(cred_dict)
            print(f"✅ Loaded from JSON (project: {cred_dict.get('project_id')})",
                  flush=True)
            return cred_dict
        except Exception as e:
            print(f"⚠️ JSON load failed: {e}", flush=True)

    # ---- Method 3: File ----
    if os.path.exists(KEY_PATH):
        print("   Trying file...", flush=True)
        try:
            with open(KEY_PATH, 'r', encoding='utf-8') as f:
                cred_dict = json.load(f)
            cred_dict = _fix_private_key(cred_dict)
            print(f"✅ Loaded from file: {KEY_PATH}", flush=True)
            return cred_dict
        except Exception as e:
            print(f"⚠️ File load failed: {e}", flush=True)

    raise RuntimeError(
        "❌ No Firebase credentials found!\n"
        "   Set FIREBASE_KEY_B64 (recommended) or FIREBASE_KEY_JSON."
    )


def _validate_private_key(cred_dict):
    """Validate private key by trying to sign something."""
    try:
        from cryptography.hazmat.primitives import serialization
        pk = cred_dict['private_key'].encode('utf-8')
        key = serialization.load_pem_private_key(pk, password=None)
        print(f"✅ PEM key valid ({key.key_size} bits)", flush=True)
        return True
    except Exception as e:
        print(f"❌ PEM validation failed: {e}", flush=True)
        return False


def init_firebase():
    """Initialize Firebase Admin for Authentication and Firestore only.

    Bot object storage is handled separately by DBByte; Firebase Storage is
    intentionally not initialized or queried by this application.
    """
    global _db, _bucket, _firebase_app, _initialized
    if _initialized:
        return _db, None

    print("=" * 60, flush=True)
    print("[FIREBASE] Initializing Authentication / Firestore (DBByte handles files)", flush=True)
    try:
        cred_dict = _load_credentials()
        if not _validate_private_key(cred_dict):
            raise RuntimeError("Firebase private key is invalid. Recreate the service-account key.")

        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            _firebase_app = firebase_admin.initialize_app(cred)
        else:
            _firebase_app = firebase_admin.get_app()

        _db = firestore.client(app=_firebase_app)
        _bucket = None
        _initialized = True
        print("[FIREBASE] Firestore connected; Firebase Storage disabled (DBByte is the object store).", flush=True)
        print("=" * 60, flush=True)
        return _db, None
    except Exception as exc:
        print(f"[FIREBASE] Initialization FAILED: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        print("=" * 60, flush=True)
        raise


def get_db():
    if not _initialized:
        init_firebase()
    return _db


def get_bucket():
    if not _initialized:
        init_firebase()
    return _bucket


def get_storage_diagnostics():
    """Return non-secret Firebase Storage configuration details for the admin monitor."""
    if not _initialized:
        init_firebase()
    return {
        'bucket': _storage_bucket_name or '',
        'service_account_project': _storage_project_id or '',
        'available': _bucket is not None,
    }
