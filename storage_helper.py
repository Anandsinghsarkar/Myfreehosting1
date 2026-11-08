# -*- coding: utf-8 -*-
"""
Backblaze B2 S3-compatible storage adapter.
Firebase remains in use only for Authentication and Firestore application records.

Bot files and runtime/session data are stored as private objects under:
  scripts/<hashed-user-id>/<script-id>/<relative-path>

Uses AWS Signature Version 4 through boto3. Dependency/cache folders are
excluded because they are rebuilt from requirements.txt / package.json.
"""
import os
import time
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

MAX_OBJECT_BYTES = 50 * 1024 * 1024
UPLOAD_WORKERS = max(1, min(8, int(os.environ.get("B2_UPLOAD_WORKERS", "4"))))
USAGE_CACHE_SECONDS = 15

ENDPOINT = os.environ.get("B2_ENDPOINT", "https://s3.us-east-005.backblazeb2.com").strip().rstrip("/")
REGION = os.environ.get("B2_REGION", "us-east-005").strip()
BUCKET = os.environ.get("B2_BUCKET_NAME", "Myfreehosting").strip()
KEY_ID = os.environ.get("B2_KEY_ID", "").strip()
APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY", "").strip()

EXCLUDE_DIRS = {
    ".packages", "node_modules", "__pycache__", ".git", "__MACOSX",
    ".venv", "venv", ".cache", ".mypy_cache", ".pytest_cache",
}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db"}

_SYNC_CACHE = {}
_CLIENT = None
_CLIENT_LOCK = threading.Lock()
_USAGE_LOCK = threading.Lock()
_USAGE_CACHE = {"at": 0.0, "data": None}
LAST_ERROR = ""


class BackblazeError(RuntimeError):
    pass


def _ready():
    missing = []
    if not KEY_ID:
        missing.append("B2_KEY_ID")
    if not APPLICATION_KEY:
        missing.append("B2_APPLICATION_KEY")
    if not BUCKET:
        missing.append("B2_BUCKET_NAME")
    if not ENDPOINT:
        missing.append("B2_ENDPOINT")
    if not REGION:
        missing.append("B2_REGION")
    if missing:
        raise BackblazeError("Missing Render environment variable(s): " + ", ".join(missing))


def _client():
    global _CLIENT
    _ready()
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = boto3.client(
                    "s3",
                    endpoint_url=ENDPOINT,
                    aws_access_key_id=KEY_ID,
                    aws_secret_access_key=APPLICATION_KEY,
                    region_name=REGION,
                    config=Config(
                        signature_version="s3v4",
                        s3={"addressing_style": "path"},
                        retries={"max_attempts": 3, "mode": "standard"},
                        connect_timeout=10,
                        read_timeout=90,
                    ),
                )
    return _CLIENT


def _error_text(exc):
    if isinstance(exc, ClientError):
        detail = exc.response.get("Error", {})
        code = detail.get("Code", "ClientError")
        message = detail.get("Message", str(exc))
        if code in ("AccessDenied", "AccessDeniedByObjectLockConfiguration", "InvalidRequest"):
            return (
                f"Backblaze B2 {code}: {message}. Check the application key permissions "
                "and bucket Object Lock retention/legal-hold settings."
            )
        return f"Backblaze B2 {code}: {message}"
    return f"Backblaze B2 connection failed: {exc}"


def _uid_tag(user_id):
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16]


def _prefix(user_id, script_id):
    return f"scripts/{_uid_tag(user_id)}/{str(script_id)}/"


def _object_key(user_id, script_id, relative_path):
    rel = str(relative_path).replace("\\", "/").lstrip("/")
    parts = rel.split("/")
    if not rel or any(part in ("", ".", "..") for part in parts):
        raise BackblazeError("Invalid bot file path.")
    return _prefix(user_id, script_id) + rel


def _excluded_rel(rel):
    return any(part in EXCLUDE_DIRS for part in rel.split("/")[:-1])


def _iter_local_files(local_dir):
    for root, dirs, filenames in os.walk(local_dir, followlinks=False):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDE_DIRS and not os.path.islink(os.path.join(root, d))
        ]
        for filename in filenames:
            if filename in EXCLUDE_FILES or filename.endswith(".pyc"):
                continue
            path = os.path.join(root, filename)
            if os.path.islink(path):
                continue
            yield path, os.path.relpath(path, local_dir).replace("\\", "/")


def _iter_current_objects(prefix):
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            yield item


def upload_script_file(local_path, user_id, script_id, filename):
    global LAST_ERROR
    try:
        key = _object_key(user_id, script_id, filename)
        size = os.path.getsize(local_path)
        if size > MAX_OBJECT_BYTES:
            raise BackblazeError(f"{filename} exceeds the configured 50 MB per-file safety limit.")
        client = _client()
        with open(local_path, "rb") as handle:
            client.upload_fileobj(
                handle, BUCKET, key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
        stat = os.stat(local_path)
        _SYNC_CACHE[(str(user_id), str(script_id), str(filename))] = (stat.st_size, stat.st_mtime_ns)
        return key
    except Exception as exc:
        LAST_ERROR = _error_text(exc)
        print(f"[BACKBLAZE] Upload failed for {script_id}/{filename}: {LAST_ERROR}", flush=True)
        return None


def upload_script_folder(local_dir, user_id, script_id):
    items = list(_iter_local_files(local_dir))
    uploaded = {}
    if not items:
        return uploaded
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        results = pool.map(
            lambda item: (item[1], upload_script_file(item[0], user_id, script_id, item[1])),
            items,
        )
        for relative, remote in results:
            if remote:
                uploaded[relative] = remote
    return uploaded


def _delete_key_all_versions(key):
    """Permanently remove every version and delete marker for one object key."""
    client = _client()
    paginator = client.get_paginator("list_object_versions")
    entries = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=key):
        for field in ("Versions", "DeleteMarkers"):
            for item in page.get(field, []):
                if item.get("Key") == key:
                    entries.append({"Key": key, "VersionId": item["VersionId"]})
    for offset in range(0, len(entries), 1000):
        client.delete_objects(
            Bucket=BUCKET,
            Delete={"Objects": entries[offset:offset + 1000], "Quiet": True},
        )
    return len(entries)


def sync_script_folder(local_dir, user_id, script_id, prune=False):
    """Upload changed files and optionally remove stale remote file versions."""
    global LAST_ERROR
    if not os.path.isdir(local_dir):
        LAST_ERROR = f"Local bot folder is missing: {local_dir}"
        return False
    LAST_ERROR = ""
    expected = {}
    for path, relative in _iter_local_files(local_dir):
        stat = os.stat(path)
        expected[relative] = (path, (stat.st_size, stat.st_mtime_ns))

    uid, sid = str(user_id), str(script_id)
    pending = [
        (path, relative) for relative, (path, signature) in expected.items()
        if _SYNC_CACHE.get((uid, sid, relative)) != signature
    ]
    ok = True
    if pending:
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            results = list(pool.map(
                lambda item: upload_script_file(item[0], user_id, script_id, item[1]),
                pending,
            ))
        ok = all(results)

    if prune and ok:
        try:
            prefix = _prefix(user_id, script_id)
            stale_keys = set()
            for item in _iter_current_objects(prefix):
                key = str(item.get("Key", ""))
                relative = key[len(prefix):] if key.startswith(prefix) else ""
                if relative and (relative not in expected or _excluded_rel(relative)):
                    stale_keys.add(key)
            for key in stale_keys:
                _delete_key_all_versions(key)
                relative = key[len(prefix):]
                _SYNC_CACHE.pop((uid, sid, relative), None)
        except Exception as exc:
            LAST_ERROR = _error_text(exc)
            print(f"[BACKBLAZE] Stale-file cleanup warning for {script_id}: {LAST_ERROR}", flush=True)
    return ok


def download_script_folder(user_id, script_id, dest_dir):
    try:
        prefix = _prefix(user_id, script_id)
        dest_abs = os.path.abspath(dest_dir)
        count = 0
        for item in _iter_current_objects(prefix):
            key = str(item.get("Key", ""))
            relative = key[len(prefix):] if key.startswith(prefix) else ""
            if not relative or _excluded_rel(relative):
                continue
            target = os.path.abspath(os.path.join(dest_dir, *relative.split("/")))
            if not target.startswith(dest_abs + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            response = _client().get_object(Bucket=BUCKET, Key=key)
            with response["Body"] as body, open(target, "wb") as output:
                while True:
                    chunk = body.read(256 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            stat = os.stat(target)
            _SYNC_CACHE[(str(user_id), str(script_id), relative)] = (stat.st_size, stat.st_mtime_ns)
            count += 1
        print(f"[BACKBLAZE] Restored {count} files for bot {script_id}", flush=True)
        return count > 0
    except Exception as exc:
        print(f"[BACKBLAZE] Restore failed for {script_id}: {_error_text(exc)}", flush=True)
        return False


def delete_script_folder(user_id, script_id):
    """Delete every object version belonging to a bot and verify the prefix is empty."""
    try:
        prefix = _prefix(user_id, script_id)
        client = _client()
        paginator = client.get_paginator("list_object_versions")
        entries = []
        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
            for field in ("Versions", "DeleteMarkers"):
                for item in page.get(field, []):
                    entries.append({"Key": item["Key"], "VersionId": item["VersionId"]})
        for offset in range(0, len(entries), 1000):
            client.delete_objects(
                Bucket=BUCKET,
                Delete={"Objects": entries[offset:offset + 1000], "Quiet": True},
            )
        remaining = False
        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
            if page.get("Versions") or page.get("DeleteMarkers"):
                remaining = True
                break
        if remaining:
            raise BackblazeError("Some object versions remain after delete; check Object Lock retention/legal hold.")
        for cache_key in list(_SYNC_CACHE):
            if cache_key[0] == str(user_id) and cache_key[1] == str(script_id):
                _SYNC_CACHE.pop(cache_key, None)
        print(f"[BACKBLAZE] Deleted {len(entries)} object versions for bot {script_id}", flush=True)
        return True
    except Exception as exc:
        global LAST_ERROR
        LAST_ERROR = _error_text(exc)
        print(f"[BACKBLAZE] Delete failed for {user_id}/{script_id}: {LAST_ERROR}", flush=True)
        return False


def read_script_file(user_id, script_id, filename):
    try:
        key = _object_key(user_id, script_id, filename)
        response = _client().get_object(Bucket=BUCKET, Key=key)
        return response["Body"].read()
    except Exception as exc:
        print(f"[BACKBLAZE] Remote read failed for {script_id}/{filename}: {_error_text(exc)}", flush=True)
        return None


def upload_qr_image(local_path, filename):
    # Payment QR files intentionally remain on the existing static upload path.
    return None


def _measure_storage_usage():
    try:
        quota_gb = max(0.1, float(os.environ.get("B2_QUOTA_GB", "10")))
    except (TypeError, ValueError):
        quota_gb = 10.0
    quota_bytes = int(quota_gb * 1024 ** 3)
    result = {
        "configured": False, "available": False, "used_bytes": 0,
        "file_count": 0, "quota_bytes": quota_bytes, "free_bytes": quota_bytes,
        "used_percent": 0, "bucket": BUCKET, "provider": "Backblaze B2",
        "quota_source": "B2_QUOTA_GB environment setting (display estimate, not provider billing telemetry)",
    }
    try:
        client = _client()
        client.head_bucket(Bucket=BUCKET)
        used = 0
        count = 0
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=BUCKET):
            for item in page.get("Versions", []):
                used += int(item.get("Size", 0) or 0)
                count += 1
        result.update({
            "configured": True, "available": True,
            "used_bytes": used, "file_count": count,
            "free_bytes": max(0, quota_bytes - used),
            "used_percent": min(100.0, round((used / quota_bytes) * 100, 3)) if quota_bytes else 0,
        })
    except Exception as exc:
        result["error"] = _error_text(exc)
    return result


def get_storage_usage():
    """Measured bucket usage; cached briefly to avoid frequent full bucket scans."""
    with _USAGE_LOCK:
        now = time.time()
        if _USAGE_CACHE["data"] is not None and now - _USAGE_CACHE["at"] < USAGE_CACHE_SECONDS:
            return dict(_USAGE_CACHE["data"])
        data = _measure_storage_usage()
        _USAGE_CACHE.update({"at": now, "data": data})
        return dict(data)



def clear_all_storage():
    """Permanently empty the configured B2 bucket, including old versions and delete markers.

    Returns a structured result and verifies that no object versions/markers remain.
    """
    global LAST_ERROR, _USAGE_CACHE
    try:
        client = _client()
        paginator = client.get_paginator("list_object_versions")
        deleted_versions = 0
        deleted_markers = 0

        # Process one listing page at a time so large buckets do not exhaust memory.
        for page in paginator.paginate(Bucket=BUCKET):
            entries = []
            for item in page.get("Versions", []):
                entries.append({"Key": item["Key"], "VersionId": item["VersionId"]})
                deleted_versions += 1
            for item in page.get("DeleteMarkers", []):
                entries.append({"Key": item["Key"], "VersionId": item["VersionId"]})
                deleted_markers += 1
            for offset in range(0, len(entries), 1000):
                client.delete_objects(
                    Bucket=BUCKET,
                    Delete={"Objects": entries[offset:offset + 1000], "Quiet": True},
                )

        # Verify from a fresh listing; never report an empty bucket without proof.
        remaining_versions = 0
        remaining_markers = 0
        for page in client.get_paginator("list_object_versions").paginate(Bucket=BUCKET):
            remaining_versions += len(page.get("Versions", []))
            remaining_markers += len(page.get("DeleteMarkers", []))
        if remaining_versions or remaining_markers:
            raise BackblazeError(
                f"Bucket is not empty: {remaining_versions} versions and "
                f"{remaining_markers} delete markers remain. Check Object Lock/retention."
            )

        _SYNC_CACHE.clear()
        with _USAGE_LOCK:
            _USAGE_CACHE = {"at": 0.0, "data": None}
        LAST_ERROR = ""
        return {
            "ok": True,
            "bucket": BUCKET,
            "deleted_versions": deleted_versions,
            "deleted_markers": deleted_markers,
            "remaining_versions": 0,
            "remaining_markers": 0,
        }
    except Exception as exc:
        LAST_ERROR = _error_text(exc)
        print(f"[BACKBLAZE] Full storage reset failed: {LAST_ERROR}", flush=True)
        return {"ok": False, "bucket": BUCKET, "error": LAST_ERROR}
