"""Run log: every engine call that produced a card is stored in its own SQLite.

Kept apart from aft.sqlite because ingest.py rebuilds that file from scratch.
A run id in an answer ([run:...]) can always be looked up here: tool, params,
the card text the model saw, and the data fingerprint it was computed from.
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stat_run (
    run_id            TEXT PRIMARY KEY,
    tool              TEXT NOT NULL,
    params_json       TEXT NOT NULL,
    card_text         TEXT NOT NULL,
    data_json         TEXT,
    data_fingerprint  TEXT,
    question          TEXT,
    created_at        TEXT NOT NULL
);
"""


class RunLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.executescript(_SCHEMA)

    @staticmethod
    def new_id() -> str:
        return f"run-{uuid.uuid4().hex[:8]}"

    def save(self, run_id: str, tool: str, params: Dict[str, Any], card_text: str, data: Dict[str, Any],
             fingerprint: Optional[str], question: Optional[str] = None) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT INTO stat_run VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, tool, json.dumps(params, ensure_ascii=False, default=str), card_text,
                 json.dumps(data, ensure_ascii=False, default=str), fingerprint, question,
                 datetime.now().isoformat(timespec="seconds")))

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM stat_run WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
