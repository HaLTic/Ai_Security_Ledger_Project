"""Small atomic JSON journal and versioned theory snapshots; no database needed."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from config import strict_json


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    def __init__(self, directory, role):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.role = role
        self.journal = self.root / f"{role}.json"

    def read(self):
        return strict_json(self.journal.read_text(encoding="utf-8")) if self.journal.exists() else None

    def save(self, state):
        atomic_json(self.journal, state)

    def log(self, event, **fields):
        with (self.root / f"{self.role}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": utc_now(), "event": event, **fields}, allow_nan=False) + "\n")

    def snapshot(self, theory):
        path = self.root / "theories" / f"{theory['id']}-{theory['version']}.json"
        if path.exists():
            if strict_json(path.read_text(encoding="utf-8")) != theory:
                raise ValueError("Saved theory snapshot changed; investigate provenance")
        else:
            atomic_json(path, theory)

    def theory(self, theory_id, version):
        if type(theory_id) is not int or type(version) is not int or theory_id <= 0 or version <= 0:
            raise ValueError("Missing valid order theory provenance")
        path = self.root / "theories" / f"{theory_id}-{version}.json"
        if not path.exists():
            raise ValueError("Exact submitted theory snapshot is unavailable")
        return strict_json(path.read_text(encoding="utf-8"))

    @contextmanager
    def lock(self):
        """OS lock is released even after a crash; only one process per role."""
        with (self.root / f"{self.role}.lock").open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Another process is already running this role") from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
