# -*- coding: utf-8 -*-
"""
DBByte REST storage adapter.
Persistent bot objects are private and namespaced by user + bot. Firebase remains
in use only for Authentication and Firestore application records.

Sync rules: dependency/cache folders (.packages, node_modules, __pycache__ ...)
are never uploaded - they are rebuilt from requirements.txt / package.json on
start. Uploads run in parallel over a shared HTTP session.
"""
import os
import time
import base64
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import requests

BASE_URL = os.environ.get("DBBYTE_API_URL", "https://api.dbbyte.com").rstrip("/")
API_KEY = os.environ.get("DBBYTE_API_KEY", "").strip()
BUCKET = os.environ.get("DBBYTE_BUCKET", "cyber-bot-storage").strip()
TIMEOUT = (10, 90)
MAX_OBJECT_BYTES = 50 * 1024 * 1024
MAX_REMOTE_NAME = 240
UPLOAD_WORKERS = max(1, min(12, int(os.environ.get("DBBYTE_UPLOAD_WORKERS", "6"))))
USAGE_CACHE_SECONDS = 8

EXCLUDE_DIRS = {
    ".packages", "node_modules", "__pycache__", ".git", "__MACOSX",
    ".venv", "venv", ".cache", ".mypy_cache", ".pytest_cache",
}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db"}

_SYNC_CACHE = {}
_SESSION = requests.Session()
_USAGE_LOCK = threading.Lock()
_USAGE_CACHE = {"at": 0.0, "data": None}

# Last human-readable upload failure; shown to the user by the upload routes.
LAST_ERROR = ""


class DBByteError(RuntimeError):
    pass


def _ready():
    if not API_KEY:
        raise DBByteError("DBBYTE_API_KEY is missing in Render Environment.")
    if not BUCKET:
        raise DBByteError("DBBYTE_BUCKET is missing in Render Environment.")


def _headers():
    _ready()
    return {"Authorization": f"Bearer {API_KEY}"}


def _url(path):
    return f"{BASE_URL}{path}"


def _request(method, path, **kwargs):
    try:
        response = _SESSION.request(method, _url(path), headers=_headers(), timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise DBByteError(f"DBByte connection failed: {exc}") from exc
    if not response.ok:
        try:
            detail = response.json().get("error") or response.json().get("message") or response.text
        except Exception:
            detail = response.text
        raise DBByteError(f"DBByte HTTP {response.status_code}: {str(detail)[:350]}")
    return response


def _uid_tag(user_id):
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:12]


def _remote_name(user_id, script_id, relative_path):
    encoded = base64.urlsafe_b64encode(relative_path.replace("\\", "/").encode("utf-8")).decode("ascii").rstrip("=")
    return f"scripts--{_uid_tag(user_id)}--{script_id}--{encoded}"


def _decode_relative(remote_name):
    parts = remote_name.split("--", 3)
    if len(parts) != 4 or parts[0] != "scripts":
        return None
    encoded = parts[3]
    try:
        encoded += "=" * (-len(encoded) % 4)
        rel = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel or any(p in ("", ".", "..") for p in rel.split("/")):
            return None
        return rel
    except Exception:
        return None


def _excluded_rel(rel):
    return any(p in EXCLUDE_DIRS for p in rel.split("/")[:-1])


def _iter_local_files(local_dir):
    """Yield (absolute_path, relative_posix_path) for every syncable file."""
    for root, dirs, filenames in os.walk(local_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not os.path.islink(os.path.join(root, d))]
        for filename in filenames:
            if filename in EXCLUDE_FILES or filename.endswith(".pyc"):
                continue
            path = os.path.join(root, filename)
            if os.path.islink(path):
                continue
            yield path, os.path.relpath(path, local_dir).replace("\\", "/")


def _list_all():
    files, cursor = [], None
    while True:
        params = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", f"/storage/{quote(BUCKET, safe='')}/list", params=params).json()
        files.extend(data.get("files") or [])
        if not data.get("hasMore") or not data.get("nextCursor"):
            break
        cursor = data["nextCursor"]
    return files


def upload_script_file(local_path, user_id, script_id, filename):
    global LAST_ERROR
    try:
        relative = str(filename).replace("\\", "/")
        remote_name = _remote_name(user_id, script_id, relative)
        if len(remote_name) > MAX_REMOTE_NAME:
            raise DBByteError(f"Path too long for storage: {relative[:80]}... Shorten folder/file names.")
        size = os.path.getsize(local_path)
        if size > MAX_OBJECT_BYTES:
            raise DBByteError(f"{filename} exceeds DBByte's 50 MB per-file upload limit.")
        with open(local_path, "rb") as handle:
            response = _request(
                "POST", f"/storage/{quote(BUCKET, safe='')}/upload",
                params={"overwrite": "true"},
                files={"file": (remote_name, handle, "application/octet-stream")},
            )
        stat = os.stat(local_path)
        _SYNC_CACHE[(str(user_id), str(script_id), relative)] = (stat.st_size, stat.st_mtime_ns)
        return response.json().get("key") or remote_name
    except Exception as exc:
        LAST_ERROR = str(exc)
        print(f"[DBBYTE] Upload failed for {script_id}/{filename}: {exc}", flush=True)
        return None


def upload_script_folder(local_dir, user_id, script_id):
    items = list(_iter_local_files(local_dir))
    uploaded = {}
    if not items:
        return uploaded
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        results = pool.map(lambda it: (it[1], upload_script_file(it[0], user_id, script_id, it[1])), items)
        for rel, remote in results:
            if remote:
                uploaded[rel] = remote
    return uploaded


def sync_script_folder(local_dir, user_id, script_id, prune=False):
    """Upload only new/changed files (in parallel); optionally prune stale remote objects."""
    global LAST_ERROR
    if not os.path.isdir(local_dir):
        return False
    LAST_ERROR = ""
    expected = {}
    for path, rel in _iter_local_files(local_dir):
        stat = os.stat(path)
        expected[rel] = (path, (stat.st_size, stat.st_mtime_ns))

    uid, sid = str(user_id), str(script_id)
    pending = [(path, rel) for rel, (path, sig) in expected.items()
               if _SYNC_CACHE.get((uid, sid, rel)) != sig]
    ok = True
    if pending:
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            results = list(pool.map(lambda it: upload_script_file(it[0], user_id, script_id, it[1]), pending))
        ok = all(results)

    # Prune only during explicit full syncs, not on the runner's periodic sync loop.
    if prune or os.environ.get("DBBYTE_PRUNE_ON_SYNC", "false").lower() == "true":
        try:
            prefix = f"scripts--{_uid_tag(user_id)}--{script_id}--"
            remote = [f for f in _list_all() if str(f.get("name", "")).startswith(prefix)]
            for item in remote:
                rel = _decode_relative(str(item.get("name", "")))
                if rel and (rel not in expected or _excluded_rel(rel)):
                    _delete_remote_name(str(item["name"]))
                    _SYNC_CACHE.pop((uid, sid, rel), None)
        except Exception as exc:
            print(f"[DBBYTE] Stale-file cleanup warning for {script_id}: {exc}", flush=True)
            # Do not fail a successful upload because list/delete cleanup failed.
    return ok


def download_script_folder(user_id, script_id, dest_dir):
    try:
        prefix = f"scripts--{_uid_tag(user_id)}--{script_id}--"
        objects = [f for f in _list_all() if str(f.get("name", "")).startswith(prefix)]
        if not objects:
            return False
        dest_abs = os.path.abspath(dest_dir)
        count = 0
        for item in objects:
            remote_name = str(item.get("name", ""))
            rel = _decode_relative(remote_name)
            if not rel or _excluded_rel(rel):
                continue  # skip legacy dependency folders uploaded by older versions
            response = _request(
                "GET",
                f"/storage/{quote(BUCKET, safe='')}/download/{quote(remote_name, safe='')}",
                stream=True,
            )
            target = os.path.abspath(os.path.join(dest_dir, *rel.split("/")))
            if not target.startswith(dest_abs + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                for chunk in response.iter_content(1024 * 256):
                    if chunk:
                        out.write(chunk)
            stat = os.stat(target)
            _SYNC_CACHE[(str(user_id), str(script_id), rel)] = (stat.st_size, stat.st_mtime_ns)
            count += 1
        print(f"[DBBYTE] Downloaded {count} files for bot {script_id}", flush=True)
        return count > 0
    except Exception as exc:
        print(f"[DBBYTE] Download failed for {script_id}: {exc}", flush=True)
        return False


def _delete_remote_name(name):
    _request(
        "DELETE",
        f"/storage/{quote(BUCKET, safe='')}/delete/{quote(name, safe='')}",
        params={"version": "all"},
    )


def delete_script_folder(user_id, script_id):
    try:
        prefix = f"scripts--{_uid_tag(user_id)}--{script_id}--"
        objects = [f for f in _list_all() if str(f.get("name", "")).startswith(prefix)]
        for item in objects:
            _delete_remote_name(str(item["name"]))
        remaining = [f for f in _list_all() if str(f.get("name", "")).startswith(prefix)]
        if remaining:
            raise DBByteError(f"{len(remaining)} DBByte object(s) remain after delete.")
        for key in list(_SYNC_CACHE):
            if key[0] == str(user_id) and key[1] == str(script_id):
                _SYNC_CACHE.pop(key, None)
        print(f"[DBBYTE] Deleted {len(objects)} objects for bot {script_id}", flush=True)
        return True
    except Exception as exc:
        print(f"[DBBYTE] Delete failed for {user_id}/{script_id}: {exc}", flush=True)
        return False


def read_script_file(user_id, script_id, filename):
    try:
        remote_name = _remote_name(user_id, script_id, filename)
        response = _request(
            "GET",
            f"/storage/{quote(BUCKET, safe='')}/download/{quote(remote_name, safe='')}",
        )
        return response.content
    except Exception as exc:
        print(f"[DBBYTE] Remote read failed for {script_id}/{filename}: {exc}", flush=True)
        return None


def upload_qr_image(local_path, filename):
    # QR images remain available through the existing local/static upload path.
    # Private DBByte objects intentionally are not exposed as permanent public URLs.
    return None


def _measure_storage_usage():
    quota_gb = max(0.1, float(os.environ.get("DBBYTE_QUOTA_GB", "20")))
    quota_bytes = int(quota_gb * 1024 ** 3)
    result = {
        "configured": False, "available": False, "used_bytes": 0,
        "file_count": 0, "quota_bytes": quota_bytes, "free_bytes": quota_bytes,
        "used_percent": 0, "bucket": BUCKET, "provider": "DBByte",
        "quota_source": "DBBYTE_QUOTA_GB environment setting (default 20 GB)",
    }
    try:
        _ready()
        health = _request("GET", "/health").json()
        # Count every object in this bucket, not only this app's scripts prefix.
        objects = _list_all()
        used = 0
        for item in objects:
            size = item.get("size_bytes", item.get("size", item.get("bytes", 0)))
            try:
                used += int(size or 0)
            except (TypeError, ValueError):
                pass
        result.update({
            "configured": True, "available": True,
            "api_status": health.get("status", "unknown"),
            "used_bytes": used, "file_count": len(objects),
            "free_bytes": max(0, quota_bytes - used),
            "used_percent": min(100.0, round((used / quota_bytes) * 100, 3)) if quota_bytes else 0,
        })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def get_storage_usage():
    """Measured bucket usage, cached briefly so the live monitor cannot hammer DBByte."""
    with _USAGE_LOCK:
        now = time.time()
        if _USAGE_CACHE["data"] is not None and now - _USAGE_CACHE["at"] < USAGE_CACHE_SECONDS:
            return dict(_USAGE_CACHE["data"])
        data = _measure_storage_usage()
        _USAGE_CACHE.update({"at": now, "data": data})
        return dict(data)
