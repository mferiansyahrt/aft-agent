"""Data security: the agent tools only compute; they never read the database.

- db_clients/aft_repository.py is the only reader of aft.sqlite: fixed queries, read-only,
  loaded into an in-memory snapshot without personal columns;
- engine and tools import no database module and still work when every sqlite3
  connection is forbidden;
- the agent gets exactly the whitelisted tools, agno's own data features are off;
- tool arguments cannot smuggle SQL; outputs are aggregates only.
"""
import ast
import inspect
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401

from agents.hermes_agent import HermesAgent
from agents.models import ModelSpec, build_model
from agents_tools.aft_stat_tools import ALLOWED_TOOLS, AftStatTools
from agents_tools.cards import CardStore
from agents_tools.stat_engine import StatEngine
from config import SOURCE_DIR, settings
from db_clients.aft_repository import _connect, load_snapshot

DB_WORDS = ["clean_rm_test", "rm_receipt", "rm_test_result", "pond_cycle", "field_sample", "wpa_stock_lot",
            "sqlite", "select ", "source_row", "baris excel", "farmer_name"]
FORBIDDEN_IMPORTS = {"sqlite3", "db_clients", "db_clients.aft_repository", "db_clients.run_log",
                     "db_clients.chat_store", "os", "pathlib", "subprocess", "shutil"}


def _all_tool_calls(tk: AftStatTools):
    return [
        tk.list_materials(), tk.rm_summary("MBM"), tk.rm_level_shift("MBM"), tk.rm_safe_value("MBM"),
        tk.rm_outliers("PBPM", "serat"), tk.rm_stock("MBM"), tk.feed_vs_label("788-3"), tk.perf_summary(),
        tk.perf_compare("own", "competitor"), tk.corr_nutrient_fcr(), tk.feed_cost_breakeven(11000, 120000, 1),
    ]


class TestEngineHasNoDatabaseCode(unittest.TestCase):
    def test_agents_tools_import_no_database_or_file_modules(self):
        for path in (SOURCE_DIR / "agents_tools").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    self.assertFalse(n in FORBIDDEN_IMPORTS or n.split(".")[0] in {"sqlite3", "db_clients"},
                                     f"{path.name} meng-import {n}")


@unittest.skipUnless(settings.AFT_DB_PATH.exists(), "aft.sqlite belum dibuat (jalankan run_pipeline.py)")
class TestDataSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_snapshot(settings.AFT_DB_PATH)   # satu-satunya pembacaan database
        cls.engine = StatEngine(cls.snapshot)
        cls.store = CardStore()
        cls.tk = AftStatTools(cls.engine, cls.store)

    def test_tools_work_with_database_access_forbidden(self):
        def forbidden(*a, **k):
            raise AssertionError("tool mencoba membuka database")
        with mock.patch.object(sqlite3, "connect", forbidden):
            outs = _all_tool_calls(AftStatTools(self.engine, CardStore()))
        for out in outs:
            self.assertFalse(out.startswith("GAGAL"), out)

    def test_only_whitelisted_computation_tools(self):
        self.assertEqual(set(self.tk.functions), set(ALLOWED_TOOLS))
        for name in ALLOWED_TOOLS:
            params = set(inspect.signature(getattr(self.tk, name)).parameters)
            self.assertFalse(params & {"sql", "query", "path", "file", "table", "column"}, name)

    def test_agent_has_no_other_data_access(self):
        spec = ModelSpec("openai", "test", "openai", "gpt-test")
        hermes = HermesAgent(engine=self.engine)
        with mock.patch.object(settings, "OPENAI_API_KEY", "test-key"):
            agent = hermes._new_agent(build_model(spec), "x", {"tools": [self.tk]})
        self.assertEqual(agent.tools, [self.tk])
        self.assertIsNone(agent.knowledge)
        self.assertIsNone(agent.db)
        self.assertFalse(agent.search_knowledge)
        self.assertFalse(agent.read_chat_history)
        self.assertFalse(agent.telemetry)

    def test_sql_in_arguments_is_refused(self):
        before = len(self.store.cards)
        for bad in ["MBM'; DROP TABLE rm_receipt;--", "x" * 80, "MBM\nSELECT * FROM pond_cycle"]:
            out = self.tk.rm_summary(bad)
            self.assertTrue(out.startswith("GAGAL: argumen material tidak valid"), out)
        self.assertEqual(len(self.store.cards), before)

    def test_repository_reads_read_only(self):
        con = _connect(settings.AFT_DB_PATH)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TABLE intruder (a)")
        finally:
            con.close()

    def test_outputs_are_aggregates_only(self):
        with sqlite3.connect(settings.AFT_DB_PATH) as con:
            names = {n for (n,) in con.execute(
                "SELECT farmer_name FROM pond_cycle UNION SELECT farmer_name FROM complaint") if n}
        for out in _all_tool_calls(self.tk):
            self.assertFalse(out.startswith("GAGAL"), out)
            low = out.lower()
            for word in DB_WORDS:
                self.assertNotIn(word, low, f"'{word}' muncul di: {out.splitlines()[0]}")
            for name in names:
                self.assertNotIn(name, out)


if __name__ == "__main__":
    unittest.main()
