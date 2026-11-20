"""Small atomic JSON journal and versioned theory snapshots; no database needed."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from config import strict_json
from validation import ValidationError


def _canonical_bytes(entry):
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _last_chain_link(path):
    if not path.exists():
        return 0, "GENESIS"
    last = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            last = raw
    if last is None:
        return 0, "GENESIS"
    obj = strict_json(last)
    return int(obj.get("seq", 0)), str(obj.get("record_hash", "GENESIS"))


def verify_chain(path):
    path = Path(path)
    if not path.exists():
        return {"valid": True, "count": 0, "broken_seq": None, "reason": "No log file yet"}
    expected_seq = 1
    expected_prev = "GENESIS"
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = strict_json(raw)
        except (ValueError, TypeError):
            return {"valid": False, "count": expected_seq - 1, "broken_seq": expected_seq,
                    "reason": "Malformed JSON log record"}
        if not isinstance(obj, dict) or obj.get("seq") != expected_seq or obj.get("prev_hash") != expected_prev:
            return {"valid": False, "count": expected_seq - 1, "broken_seq": expected_seq,
                    "reason": "Sequence or previous-hash link mismatch"}
        record_hash = obj.get("record_hash")
        if not isinstance(record_hash, str) or len(record_hash) != 64:
            return {"valid": False, "count": expected_seq - 1, "broken_seq": expected_seq,
                    "reason": "Missing or invalid SHA-256 record hash"}
        payload = {k: v for k, v in obj.items() if k != "record_hash"}
        actual = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        if actual != record_hash:
            return {"valid": False, "count": expected_seq - 1, "broken_seq": expected_seq,
                    "reason": "SHA-256 payload digest mismatch (tampered record)"}
        expected_seq += 1
        expected_prev = record_hash
    return {"valid": True, "count": expected_seq - 1, "broken_seq": None, "reason": "SHA-256 chain verified"}


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
        log_path = self.root / f"{self.role}.jsonl"
        prev_seq, prev_hash = _last_chain_link(log_path)
        entry = {**fields, "seq": prev_seq + 1, "time": utc_now(), "event": event, "prev_hash": prev_hash}
        record_hash = hashlib.sha256(_canonical_bytes(entry)).hexdigest()
        full_entry = {**entry, "record_hash": record_hash}
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(full_entry, allow_nan=False) + "\n")

    def snapshot(self, theory):
        path = self.root / "theories" / f"{theory['id']}-{theory['version']}.json"
        if path.exists():
            if strict_json(path.read_text(encoding="utf-8")) != theory:
                raise ValidationError("Saved theory snapshot changed; investigate provenance")
        else:
            atomic_json(path, theory)

    def theory(self, theory_id, version):
        if type(theory_id) is not int or type(version) is not int or theory_id <= 0 or version <= 0:
            raise ValidationError("Missing valid order theory provenance")
        path = self.root / "theories" / f"{theory_id}-{version}.json"
        if not path.exists():
            raise ValidationError("Exact submitted theory snapshot is unavailable")
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
