# -*- coding: utf-8 -*-
"""
Firebase Storage helper — scripts ko Render restart ke baad bachane ke liye.
"""
import os
from firebase_config import get_bucket


def upload_script_file(local_path, user_id, script_id, filename):
    try:
        bucket = get_bucket()
        if not bucket:
            return None
        blob_path = f"scripts/{user_id}/{script_id}/{filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(local_path)
        print(f"✅ Uploaded: {blob_path}")
        return blob_path
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return None


def upload_script_folder(local_dir, user_id, script_id):
    """Best-effort mirror; return partial results so later deletion can clean them up."""
    uploaded = {}
    try:
        bucket = get_bucket()
        if not bucket:
            return {}
        for root, dirs, files in os.walk(local_dir):
            for fn in files:
                local_file = os.path.join(root, fn)
                rel = os.path.relpath(local_file, local_dir).replace('\\', '/')
                blob_path = f"scripts/{user_id}/{script_id}/{rel}"
                bucket.blob(blob_path).upload_from_filename(local_file)
                uploaded[rel] = blob_path
        print(f"✅ Uploaded {len(uploaded)} files for {script_id}")
        return uploaded
    except Exception as e:
        print(f"❌ Folder upload failed after {len(uploaded)} file(s): {e}")
        return uploaded


def download_script_folder(user_id, script_id, dest_dir):
    try:
        bucket = get_bucket()
        if not bucket:
            return False
        prefix = f"scripts/{user_id}/{script_id}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        if not blobs:
            return False
        os.makedirs(dest_dir, exist_ok=True)
        count = 0
        for blob in blobs:
            rel = blob.name[len(prefix):]
            if not rel:
                continue
            local_path = os.path.join(dest_dir, rel)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            blob.download_to_filename(local_path)
            count += 1
        print(f"✅ Downloaded {count} files for {script_id}")
        return count > 0
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False


def delete_script_folder(user_id, script_id):
    """Delete and verify every object below this bot's Firebase Storage prefix."""
    try:
        bucket = get_bucket()
        if not bucket:
            print("[FIREBASE] Storage bucket unavailable; refusing to report deletion success.")
            return False
        prefix = f"scripts/{user_id}/{script_id}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            blob.delete()
        # Verify the prefix is empty before the Firestore bot record is removed.
        remaining = list(bucket.list_blobs(prefix=prefix))
        if remaining:
            print(f"[FIREBASE] Delete verification failed for {prefix}: {len(remaining)} object(s) remain.")
            return False
        print(f"[FIREBASE] Deleted {len(blobs)} object(s) under {prefix}")
        return True
    except Exception as exc:
        print(f"[FIREBASE] Bot folder deletion failed for {user_id}/{script_id}: {type(exc).__name__}: {exc}")
        return False


def sync_script_folder(local_dir, user_id, script_id):
    """Mirror all current runtime files to Firebase and report whether all files synced."""
    expected = 0
    for _, _, filenames in os.walk(local_dir):
        expected += len(filenames)
    if expected == 0:
        return True
    uploaded = upload_script_folder(local_dir, user_id, script_id)
    return len(uploaded) == expected


def read_script_file(user_id, script_id, filename):
    """Read a saved file directly from Firebase without creating a Render copy."""
    try:
        bucket = get_bucket()
        if not bucket:
            return None
        blob = bucket.blob(f"scripts/{user_id}/{script_id}/{filename}")
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as exc:
        print(f"[FIREBASE] Remote read failed for {script_id}/{filename}: {exc}")
        return None


def upload_qr_image(local_path, filename):
    """Admin QR code upload kare to Firebase Storage me save."""
    try:
        bucket = get_bucket()
        if not bucket:
            return None
        blob_path = f"assets/qr/{filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(local_path)
        blob.make_public()
        return blob.public_url
    except Exception as e:
        print(f"❌ QR upload failed: {e}")
        return None


def get_storage_usage():
    """Measure actual bytes stored under scripts/ in the configured Firebase bucket."""
    result = {'configured': False, 'used_bytes': 0, 'file_count': 0}
    try:
        bucket = get_bucket()
        if not bucket:
            return result
        result['configured'] = True
        total = 0
        count = 0
        for blob in bucket.list_blobs(prefix='scripts/'):
            total += int(blob.size or 0)
            count += 1
        result['used_bytes'] = total
        result['file_count'] = count
    except Exception as exc:
        result['error'] = str(exc)
    return result
