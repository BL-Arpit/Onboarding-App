"""Per-chat state and transcript, one JSON file per session so a server restart loses nothing."""
import json
import os
import re
import threading
from collections import defaultdict
from pathlib import Path

SID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class Sessions:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir) / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def valid(self, sid: str) -> bool:
        return bool(SID_RE.match(sid or ""))

    def lock(self, sid: str) -> threading.Lock:
        return self._locks[sid]

    def load(self, sid: str) -> dict:
        p = self.dir / f"{sid}.json"
        if p.exists():
            try:
                return json.loads(p.read_text("utf-8"))
            except json.JSONDecodeError:
                p.rename(p.with_suffix(".corrupt"))
        return {"state": {"phase": "idle", "queue": [], "idx": 0}, "messages": []}

    def save(self, sid: str, sess: dict) -> None:
        p = self.dir / f"{sid}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(sess, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
