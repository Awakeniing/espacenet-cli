"""Durable JSON state helpers.

`locked_save_json` follows the CLI-Anything session-locking guide: open
without truncation, acquire an exclusive lock, truncate inside the lock.
"""

import json
import os
from pathlib import Path


def _lock_file(fd):
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        return "fcntl"
    except (ImportError, OSError):
        pass
    try:
        import msvcrt

        msvcrt.locking(fd.fileno() if hasattr(fd, "fileno") else fd, msvcrt.LK_LOCK, 1)
        return "msvcrt"
    except (ImportError, OSError, ValueError):
        return None


def _unlock_file(fd, kind):
    try:
        if kind == "fcntl":
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        elif kind == "msvcrt":
            import msvcrt

            f = fd if hasattr(fd, "seek") else None
            if f:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError, ValueError):
        pass


def locked_save_json(path, data, **dump_kwargs):
    """Atomically persist JSON with exclusive file locking (session-locking.md)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        f = open(path, "r+", encoding="utf-8")  # no truncation on open
    except FileNotFoundError:
        f = open(path, "w", encoding="utf-8")  # first save
    with f:
        kind = None
        try:
            kind = _lock_file(f)
        except Exception:
            kind = None
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, ensure_ascii=False,
                      **{"indent": 2, **dump_kwargs})
            f.flush()
        finally:
            if kind:
                _unlock_file(f, kind)


def read_json_or_none(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
