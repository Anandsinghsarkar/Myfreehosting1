# -*- coding: utf-8 -*-
"""
Firebase Admin SDK initialization.
"""
import os
import json
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

    key_json = os.environ.get('FIREBASE_KEY_JSON')

    if key_json:
        try:
            cred_dict = json.loads(key_json)
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            raise RuntimeError(f"Invalid FIREBASE_KEY_JSON: {e}")
    elif os.path.exists(KEY_PATH):
        cred = credentials.Certificate(KEY_PATH)
    else:
        raise RuntimeError(
            "Firebase key not found. Set FIREBASE_KEY_JSON env var."
        )

    bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET', '')

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'storageBucket': bucket_name})

    _db = firestore.client()

    try:
        _bucket = storage.bucket()
    except Exception as e:
        print(f"⚠️ Storage bucket not available: {e}")
        _bucket = None

    _initialized = True
    print("✅ Firebase initialized")
    return _db, _bucket


def get_db():
    if not _initialized:
        init_firebase()
    return _db


def get_bucket():
    if not _initialized:
        init_firebase()
    return _bucket
