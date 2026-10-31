"""Small file helpers shared by the snapshot, allowlist and report writers."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so readers never see a half-written file.

    The text goes to a temporary file in the same directory, which then
    replaces ``path`` in one ``os.replace``. Two CI jobs writing the same
    snapshot or allowlist end with one complete version, never a mix.
    """
    path = Path(path)
    directory = path.parent if str(path.parent) else Path(".")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            # mkstemp creates 0600 files; keep the permissions the file already had.
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
