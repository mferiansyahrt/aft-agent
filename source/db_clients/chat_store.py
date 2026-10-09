"""Chat sessions: messages per session_id in their own SQLite (chat.sqlite).

History for the next question is read back from here (last N question/answer
pairs). An answer that did not pass the validator is stored for audit but never
fed back as context.
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_session (
    session_id  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_message (
    message_id  INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_session(session_id),
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    ok          INTEGER,            -- assistant: 1 = lolos validator
    run_ids     TEXT,               -- assistant: JSON list run id yang dikutip
    model       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON chat_message(session_id, message_id);
"""


class ChatStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(_SCHEMA)

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def ensure_session(self, session_id: Optional[str] = None) -> str:
        sid = session_id or f"ses-{uuid.uuid4().hex[:8]}"
        with self._con() as con:
            con.execute("INSERT OR IGNORE INTO chat_session VALUES (?, ?)", (sid, self._now()))
        return sid

    def add(self, session_id: str, role: str, content: str, ok: Optional[bool] = None,
            run_ids: Sequence[str] = (), model: str = "") -> None:
        with self._con() as con:
            con.execute("INSERT INTO chat_message (session_id, role, content, ok, run_ids, model, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (session_id, role, content, None if ok is None else int(ok),
                         json.dumps(list(run_ids)) if role == "assistant" else None, model or None, self._now()))

    def messages(self, session_id: str) -> List[Dict]:
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM chat_message WHERE session_id = ? ORDER BY message_id", (session_id,))]

    def history(self, session_id: str, turns: int) -> List[Tuple[str, str]]:
        """Last `turns` question/answer pairs as (role, text); rejected answers are masked."""
        pairs: List[Tuple[str, str]] = []
        for m in self.messages(session_id):
            if m["role"] == "user":
                pairs.append(("user", m["content"]))
            else:
                pairs.append(("assistant", m["content"] if m["ok"] else "(jawaban tidak lolos validator)"))
        return pairs[-2 * turns:] if turns > 0 else []

    def sessions(self) -> List[Dict]:
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT s.session_id, s.created_at, COUNT(m.message_id) AS n_messages, MAX(m.created_at) AS last_at "
                "FROM chat_session s LEFT JOIN chat_message m USING (session_id) "
                "GROUP BY s.session_id ORDER BY last_at DESC")]
