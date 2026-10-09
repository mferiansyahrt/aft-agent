"""The only code that reads aft.sqlite for the statistics engine.

Fixed queries, read-only connection, nothing from the model ever reaches SQL.
The result is an in-memory DataSnapshot; the engine and the agent tools compute
on that snapshot and never open the database themselves.

Data minimisation: columns the computations do not need (farmer names, farm,
free-text remarks, raw Excel rows of other sheets) are not loaded at all.
"""
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from agents_tools.snapshot import DataSnapshot

_RM_TEST = """
SELECT receipt_id, sheet_name, source_row, block_no, sap_code, material_name, receive_date,
       po_no, transport_no, parameter_code, value
FROM clean_rm_test"""

_STOCK = """
SELECT l.sap_code, l.material_name, l.stock_ton, l.usage_ton_per_day, l.doh_days,
       r.plant, r.stock_date
FROM wpa_stock_lot l JOIN wpa_report r USING (report_id)
ORDER BY l.source_row"""

_FIELD = """
SELECT date_sent, produced_by, owner_group, feed_code_norm, is_mixed_code,
       moisture_nir, protein_nir, fat_nir, fiber_nir, ash_nir, calcium_nir, phosphor_nir,
       spec_moisture_min, spec_moisture_max, spec_protein_min, spec_protein_max, spec_fat_min, spec_fat_max,
       spec_fiber_min, spec_fiber_max, spec_ash_min, spec_ash_max, spec_calcium_min, spec_calcium_max,
       spec_phosphor_min, spec_phosphor_max
FROM clean_field_sample"""

_POND = """
SELECT fish_species, harvest_date, company, owner_group, brand_norm, is_mixed_brand,
       fcr, fcr_check, sr_pct, adg_g_per_day, feed_cost_rp_per_kg_fish
FROM clean_pond_cycle"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_snapshot(path: Path) -> DataSnapshot:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"database tidak ditemukan: {path} (jalankan source/run_pipeline.py dulu)")
    con = _connect(path)
    try:
        def rows(sql: str) -> Tuple[dict, ...]:
            return tuple(dict(r) for r in con.execute(sql))
        shas = [r[0] for r in con.execute("SELECT sha256 FROM source_file ORDER BY file_name")]
        snap = DataSnapshot(rm_tests=rows(_RM_TEST), stock_lots=rows(_STOCK), field_samples=rows(_FIELD),
                            pond_cycles=rows(_POND),
                            fingerprint=hashlib.sha256("|".join(shas).encode()).hexdigest()[:8],
                            loaded_from=path.name)
    finally:
        con.close()
    return snap


class SnapshotCache:
    """Reload the snapshot only when the database file changed (e.g. after run_pipeline.py)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._key: Optional[Tuple[float, int]] = None
        self._snap: Optional[DataSnapshot] = None

    def get(self) -> DataSnapshot:
        st = self.path.stat()
        key = (st.st_mtime, st.st_size)
        if self._snap is None or key != self._key:
            self._snap, self._key = load_snapshot(self.path), key
        return self._snap
