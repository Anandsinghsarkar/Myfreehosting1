# -*- coding: utf-8 -*-
"""
ZIP handling for bot uploads: safe extraction, junk filtering, wrapper-folder
flattening and main-file detection. Pure Python, no Flask imports.
"""
import os
import re
import shutil
import zipfile

SKIP_DIRS = {
    '__MACOSX', '__pycache__', '.git', '.idea', '.vscode', 'node_modules',
    '.venv', 'venv', '.packages', '.mypy_cache', '.pytest_cache',
}
SKIP_FILES = {'.DS_Store', 'Thumbs.db', 'output.log'}

PREFERRED_PY = ['main.py', 'bot.py', 'app.py', 'server.py', 'run.py', 'start.py', 'index.py']
PREFERRED_JS = ['index.js', 'main.js', 'bot.js', 'app.js', 'server.js']
NEVER_MAIN = {'__init__.py', 'setup.py', 'conftest.py'}


class ZipError(ValueError):
    """Raised with a user-facing message when a ZIP cannot be used."""


def _skip(parts):
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    return name in SKIP_FILES or name.endswith('.pyc') or name.startswith('._')


def extract_zip(zip_path, dest, max_files=2000, max_total=100 * 1024 * 1024):
    """Extract zip_path into dest. Returns number of files written."""
    root = os.path.realpath(dest)
    files = 0
    total = 0
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipError('This is not a valid ZIP file (corrupted or wrong format).') from exc
    try:
        with zf:
            for m in zf.infolist():
                name = m.filename.replace('\\', '/')
                if name.endswith('/'):
                    continue
                parts = [p for p in name.split('/') if p not in ('', '.')]
                if not parts:
                    continue
                if name.startswith('/') or '..' in parts or re.match(r'^[A-Za-z]:', parts[0]):
                    raise ZipError(f'Unsafe path inside ZIP: {m.filename}')
                if _skip(parts):
                    continue
                if ((m.external_attr >> 16) & 0o170000) == 0o120000:
                    continue  # symlink entry: ignore
                if m.flag_bits & 0x1:
                    raise ZipError('Password-protected ZIP files are not supported.')
                files += 1
                if files > max_files:
                    raise ZipError(f'ZIP has too many files (max {max_files}).')
                target = os.path.realpath(os.path.join(root, *parts))
                if os.path.commonpath([root, target]) != root:
                    raise ZipError(f'Unsafe path inside ZIP: {m.filename}')
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(m) as src, open(target, 'wb') as out:
                    while True:
                        chunk = src.read(256 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_total:
                            raise ZipError(f'Extracted size exceeds {max_total // (1024 * 1024)} MB.')
                        out.write(chunk)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ZipError(f'Could not extract ZIP: {exc}') from exc
    if files == 0:
        raise ZipError('ZIP is empty (no usable files found).')
    return files


def flatten_wrapper(root):
    """If the archive holds a single top-level folder, return that folder."""
    for _ in range(3):
        items = os.listdir(root)
        if len(items) == 1 and os.path.isdir(os.path.join(root, items[0])):
            root = os.path.join(root, items[0])
        else:
            break
    return root


def find_main(root, max_depth=2):
    """Return (relative_path, 'py'|'js') of the best entry file, or None."""
    best = None
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == '.' else rel_dir.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        dirnames.sort()
        for fn in sorted(filenames):
            low = fn.lower()
            if low in NEVER_MAIN:
                continue
            if low.endswith('.py'):
                kind = 'py'
                rank = PREFERRED_PY.index(low) if low in PREFERRED_PY else None
            elif low.endswith('.js'):
                kind = 'js'
                rank = 100 + PREFERRED_JS.index(low) if low in PREFERRED_JS else None
            else:
                continue
            preferred = rank is not None
            if rank is None:
                rank = 200 if kind == 'py' else 300
            rel = os.path.join(rel_dir, fn) if rel_dir != '.' else fn
            rel = rel.replace(os.sep, '/')
            key = (0 if preferred else 1, depth, rank, rel)
            if best is None or key < best[0]:
                best = (key, rel, kind)
    return (best[1], best[2]) if best else None


def move_tree(src_root, dst_root):
    """Move everything inside src_root into dst_root, replacing collisions."""
    os.makedirs(dst_root, exist_ok=True)
    for item in os.listdir(src_root):
        src = os.path.join(src_root, item)
        dst = os.path.join(dst_root, item)
        if os.path.isdir(dst) and not os.path.islink(dst):
            shutil.rmtree(dst)
        elif os.path.lexists(dst):
            os.remove(dst)
        shutil.move(src, dst)
