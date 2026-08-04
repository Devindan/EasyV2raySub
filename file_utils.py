import os
import stat
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, content: str) -> None:
    """Atomically replace *path* with UTF-8 text content."""
    target = Path(path)
    temporary_path: str | None = None

    try:
        destination_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        current_umask = os.umask(0)
        os.umask(current_umask)
        destination_mode = 0o666 & ~current_umask

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, destination_mode)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass
