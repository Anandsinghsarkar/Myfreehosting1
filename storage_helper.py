# -*- coding: utf-8 -*-
"""
DBByte REST storage adapter.
Persistent bot objects are private and namespaced by user + bot. Firebase remains
in use only for Authentication and Firestore application records.
"""
import os
import time
import base64
import hashlib
from urllib.parse import quote
import requests

BASE_URL = os.environ.get("DBBYTE_API_URL", "https://api.dbbyte.com").rstrip("/")
API_KEY = os.environ.get("DBBYTE_API_KEY", "").strip()
BUCKET = os.environ.get("DBBYTE_BUCKET", "cyber-bot-storage").strip()
TIMEOUT = (10, 90)
MAX_OBJECT_BYTES = 50 * 1024 * 1024
_SYNC_CACHE = {}


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
        response = requests.request(method, _url(path), headers=_headers(), timeout=TIMEOUT, **kwargs)
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
    try:
        relative = str(filename).replace("\\", "/")
        remote_name = _remote_name(user_id, script_id, relative)
        size = os.path.getsize(local_path)
        if size > MAX_OBJECT_BYTES:
            raise DBByteError(f"{filename} exceeds DBByte's 50 MB per-file upload limit.")
        with open(local_path, "rb") as handle:
            response = _request(
                "POST", f"/storage/{quote(BUCKET, safe='')}/upload",
                params={"overwrite": "true"},
                files={"file": (remote_name, handle, "application/octet-stream")},
            )
        _SYNC_CACHE[(str(user_id), str(script_id), relative)] = (os.path.getsize(local_path), os.stat(local_path).st_mtime_ns)
        return response.json().get("key") or remote_name
    except Exception as exc:
        print(f"[DBBYTE] Upload failed for {script_id}/{filename}: {exc}", flush=True)
        return None


def upload_script_folder(local_dir, user_id, script_id):
    uploaded = {}
    for root, dirs, filenames in os.walk(local_dir):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for filename in filenames:
            path = os.path.join(root, filename)
            if os.path.islink(path):
                continue
            rel = os.path.relpath(path, local_dir).replace("\\", "/")
            remote = upload_script_file(path, user_id, script_id, rel)
            if remote:
                uploaded[rel] = remote
    return uploaded


def sync_script_folder(local_dir, user_id, script_id):
    """Upload only new/changed files; remove stale remote objects for this bot."""
    if not os.path.isdir(local_dir):
        return False
    expected = {}
    for root, dirs, filenames in os.walk(local_dir):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for filename in filenames:
            path = os.path.join(root, filename)
            if os.path.islink(path):
                continue
            rel = os.path.relpath(path, local_dir).replace("\\", "/")
            stat = os.stat(path)
            expected[rel] = (stat.st_size, stat.st_mtime_ns)

    prefix = f"scripts--{_uid_tag(user_id)}--{script_id}--"
    cache_prefix = (str(user_id), str(script_id))
    ok = True
    for rel, signature in expected.items():
        if _SYNC_CACHE.get((cache_prefix[0], cache_prefix[1], rel)) == signature:
            continue
        if not upload_script_file(os.path.join(local_dir, rel), user_id, script_id, rel):
            ok = False

    # Prune only during explicit full syncs, not on the runner's periodic sync loop.
    if os.environ.get("DBBYTE_PRUNE_ON_SYNC", "true").lower() == "true":
        try:
            remote = [f for f in _list_all() if str(f.get("name", "")).startswith(prefix)]
            for item in remote:
                rel = _decode_relative(str(item.get("name", "")))
                if rel and rel not in expected:
                    _delete_remote_name(str(item["name"]))
                    _SYNC_CACHE.pop((str(user_id), str(script_id), rel), None)
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
        count = 0
        for item in objects:
            remote_name = str(item.get("name", ""))
            rel = _decode_relative(remote_name)
            if not rel:
                continue
            response = _request(
                "GET",
                f"/storage/{quote(BUCKET, safe='')}/download/{quote(remote_name, safe='')}",
                stream=True,
            )
            target = os.path.abspath(os.path.join(dest_dir, *rel.split("/")))
            if not target.startswith(os.path.abspath(dest_dir) + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                for chunk in response.iter_content(1024 * 256):
                    if chunk:
                        out.write(chunk)
            _SYNC_CACHE[(str(user_id), str(script_id), rel)] = (os.path.getsize(target), os.stat(target).st_mtime_ns)
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


def get_storage_usage():
    """Return real bytes and object count for this app's bot objects in DBByte."""
    result = {
        "configured": False, "available": False, "used_bytes": 0,
        "file_count": 0, "bucket": BUCKET, "provider": "DBByte",
    }
    try:
        _ready()
        health = _request("GET", "/health").json()
        objects = [f for f in _list_all() if str(f.get("name", "")).startswith("scripts--")]
        result["configured"] = True
        result["available"] = True
        result["api_status"] = health.get("status", "unknown")
        result["used_bytes"] = sum(int(f.get("size") or 0) for f in objects)
        result["file_count"] = len(objects)
    except Exception as exc:
        result["error"] = str(exc)
    return result
