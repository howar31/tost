"""Local persistence: latest snapshot, history JSONL, agent state.

All writes are atomic (tmp + rename) with mode 600; the base directory is
created with mode 700 because snapshots contain personal data.
"""

import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path


def _atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


class Store:
    def __init__(self, base_dir):
        self.base = Path(base_dir)
        self._latest = self.base / "latest.json"
        self._history = self.base / "history.jsonl"
        self._agent_state = self.base / "agent_state.json"
        self._observations = self.base / "observations.jsonl"

    def _ensure_base(self):
        self.base.mkdir(parents=True, exist_ok=True)
        os.chmod(self.base, 0o700)

    @contextlib.contextmanager
    def lock(self):
        """Advisory exclusive lock serializing whole fetch pipelines, so a
        manual run and the launchd agent cannot interleave their writes."""
        self._ensure_base()
        lock_path = self.base / ".lock"
        with open(lock_path, "w") as f:
            os.chmod(lock_path, 0o600)
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _load_latest_doc(self):
        if not self._latest.exists():
            return {}
        return json.loads(self._latest.read_text(encoding="utf-8"))

    def load_latest(self):
        return self._load_latest_doc().get("orders", {})

    def load_fetched_at(self):
        return self._load_latest_doc().get("fetched_at")

    def save_latest(self, snapshot, fetched_at):
        self._ensure_base()
        doc = {"fetched_at": fetched_at, "orders": snapshot}
        _atomic_write(self._latest, json.dumps(doc, indent=2, ensure_ascii=False))

    def append_history(self, events, ts):
        if not events:
            return
        self._ensure_base()
        lines = []
        for event in events:
            stamped = {"ts": ts, **event}
            lines.append(json.dumps(stamped, ensure_ascii=False, separators=(",", ":")))
        with open(self._history, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(self._history, 0o600)

    def read_history(self, limit=None):
        if not self._history.exists():
            return []
        events = []
        for line in self._history.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        if limit is not None:
            events = events[-limit:]
        return events

    @staticmethod
    def canonical_sha256(snapshot):
        blob = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")).encode()
        return blob, hashlib.sha256(blob).hexdigest()

    def archive_if_changed(self, snapshot, ts):
        """Persist the raw snapshot to data/archive/ when its content differs
        from the last archived one (any byte, including noise-filtered paths).
        Returns the archive filename when written, None when deduplicated.

        This is the audit trail: history.jsonl records *interpreted* changes,
        the archive keeps every distinct raw response so nothing the diff layer
        drops is ever unrecoverable. observations.jsonl (see record_observation)
        logs every fetch, so "unchanged" is distinguishable from "not polled".
        """
        blob, digest = self.canonical_sha256(snapshot)
        state = self.load_agent_state()
        if state.get("last_archive_sha256") == digest:
            return None
        archive_dir = self.base / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(archive_dir, 0o700)
        safe_ts = ts.replace(":", "").replace("-", "").replace("Z", "")
        path = archive_dir / f"{ts[:10]}-{safe_ts[9:]}.json.gz"
        with gzip.open(path, "wb") as f:
            f.write(blob)
        os.chmod(path, 0o600)
        state["last_archive_sha256"] = digest
        self.save_agent_state(state)
        return path.name

    def record_observation(self, ts, sha, archive):
        """Append one line per fetch — the dense poll log behind the sparse
        archive. Lets a dashboard tell "value unchanged" from "never polled"."""
        self._ensure_base()
        line = json.dumps({"ts": ts, "sha": sha, "archive": archive},
                          ensure_ascii=False, separators=(",", ":"))
        with open(self._observations, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        os.chmod(self._observations, 0o600)

    def read_observations(self, limit=None):
        if not self._observations.exists():
            return []
        rows = [json.loads(line) for line
                in self._observations.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return rows[-limit:] if limit is not None else rows

    def list_archives(self):
        archive_dir = self.base / "archive"
        if not archive_dir.exists():
            return []
        return sorted(p.name for p in archive_dir.glob("*.json.gz"))

    def read_archive(self, name):
        path = self.base / "archive" / name
        with gzip.open(path, "rb") as f:
            return name, json.loads(f.read())

    def load_agent_state(self):
        if not self._agent_state.exists():
            return {}
        return json.loads(self._agent_state.read_text(encoding="utf-8"))

    def save_agent_state(self, state):
        self._ensure_base()
        _atomic_write(self._agent_state, json.dumps(state, ensure_ascii=False))
