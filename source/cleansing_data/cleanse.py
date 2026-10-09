"""Cleansing data hasil ingest (hanya yang dibutuhkan statistical engine dan analisis performa).

Contoh (jalankan setelah ingest):
    python3 source/database/ingest.py
    python3 source/cleansing_data/cleanse.py --db source/database/aft.sqlite

Yang dikerjakan:
  Bahan baku  : kode SAP kiriman (mapping/material_alias.csv), range nilai uji
                (mapping/param_range.csv), tanggal terima wajib, protein wajib, kiriman dobel.
  Lapangan    : kode pakan/merek dirapikan, penanda pakan campuran, produk kita vs pesaing
                (mapping/company_owner.csv), hitung ulang FCR.
Data mentah tidak diubah. Hasilnya: tabel dq_issue, *_enrich, dan view clean_*.
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAPPING = HERE / "mapping"
FCR_TOLERANCE = 0.01  # beda relatif yang masih dianggap sama (1%)
MIXED = re.compile(r"[+&]")


def load_csv(con, table, cols):
    with open(MAPPING / f"{table}.csv", newline="", encoding="utf-8") as f:
        rows = [[(r[c].strip() or None) for c in cols] for r in csv.DictReader(f)]
    con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
    return len(rows)


def norm_code(code):
    """'HDPIN B-3' -> 'HDPINB-3', '788-3.' -> '788-3'."""
    if code is None:
        return None
    return re.sub(r"\s+", "", code).upper().rstrip(".")


class Issues:
    def __init__(self):
        self.rows = []

    def add(self, table, row_id, source_row, column, rule, severity, value, message):
        self.rows.append((table, row_id, source_row, column, rule, severity,
                          None if value is None else str(value), message))


def owner_of(company, owners):
    """own / competitor / mixed / unknown untuk company tunggal atau campuran 'A+B'."""
    parts = [p.strip() for p in MIXED.split(company) if p.strip()]
    groups = {owners.get(p.lower(), "unknown") for p in parts}
    if "unknown" in groups:
        return "unknown", [p for p in parts if p.lower() not in owners]
    return (groups.pop() if len(groups) == 1 else "mixed"), []


# ---------------------------------------------------------------------- bahan baku
def check_raw_material(con, issues):
    receipts = con.execute(
        "SELECT r.receipt_id, r.source_row, r.sheet_name, r.material_name, r.receive_date, "
        "r.transport_no, r.qty_ton, a.sap_code, a.status "
        "FROM rm_receipt r LEFT JOIN material_alias a USING (sheet_name, material_name) "
        "ORDER BY r.sheet_name, r.source_row").fetchall()
    has_protein = {rid for (rid,) in con.execute(
        "SELECT receipt_id FROM rm_test_result WHERE parameter_code = 'crude_protein'")}
    seen = {}
    for rid, row, sheet, name, rdate, tno, qty, sap, status in receipts:
        if status is None:
            issues.add("rm_receipt", rid, row, "material_name", "material_tanpa_mapping", "warning", name,
                       f"{sheet}: nama bahan belum ada di material_alias.csv")
        elif sap is None:
            issues.add("rm_receipt", rid, row, "material_name", "kode_sap_belum_pasti", "warning", name,
                       f"{sheet}: kode SAP {status}")
        if rdate is None:
            issues.add("rm_receipt", rid, row, "receive_date", "wajib_isi", "critical", None,
                       "tanggal terima kosong")
        if rid not in has_protein:
            issues.add("rm_receipt", rid, row, "crude_protein", "wajib_isi", "warning", None,
                       "tidak ada nilai protein")
        key = (sheet, tno, rdate, qty)
        if tno is not None and key in seen:
            issues.add("rm_receipt", rid, row, None, "kiriman_dobel", "critical", tno,
                       f"sama dengan baris Excel {seen[key]} (truk/kontainer, tanggal, tonase sama)")
        else:
            seen.setdefault(key, row)

    ranges = {p: (lo, hi) for p, lo, hi in con.execute("SELECT parameter_code, min_value, max_value FROM param_range")}
    no_range = set()
    for rid, row, param, value in con.execute(
            "SELECT t.receipt_id, r.source_row, t.parameter_code, t.value "
            "FROM rm_test_result t JOIN rm_receipt r USING (receipt_id)"):
        if param not in ranges:
            no_range.add(param)
            continue
        lo, hi = ranges[param]
        if not lo <= value <= hi:
            issues.add("rm_test_result", rid, row, param, "di_luar_range", "critical", value,
                       f"{param} di luar range {lo}-{hi}")
    return sorted(no_range)


# ---------------------------------------------------------------------- data lapangan
def enrich_pond_cycle(con, issues, owners):
    out = []
    for cid, row, company, brand, feed, harvest, seed, fcr in con.execute(
            "SELECT cycle_id, source_row, company, brand, total_feed_kg, harvest_biomass_kg, "
            "seed_biomass_kg, fcr FROM pond_cycle"):
        owner = None
        if company is not None:
            owner, unknown = owner_of(company, owners)
            if unknown:
                issues.add("pond_cycle", cid, row, "company", "company_tanpa_mapping", "warning", company,
                           f"belum ada di company_owner.csv: {', '.join(unknown)}")
        fcr_calc, check = None, "tidak_bisa_dihitung"
        if None not in (feed, harvest, seed) and harvest - seed > 0:
            fcr_calc = feed / (harvest - seed)
            check = "ok"
            if fcr is None or abs(fcr_calc - fcr) > FCR_TOLERANCE * fcr_calc:
                check = "beda"
                issues.add("pond_cycle", cid, row, "fcr", "fcr_tidak_cocok", "warning", fcr,
                           f"FCR hitung ulang {fcr_calc:.4f}")
        else:
            issues.add("pond_cycle", cid, row, "fcr", "fcr_tidak_bisa_dihitung", "warning", fcr,
                       "total pakan/biomassa kosong atau biomassa panen <= benih")
        out.append((cid, owner, norm_code(brand), int(bool(brand and MIXED.search(brand))), fcr_calc, check))
    con.executemany("INSERT INTO pond_cycle_enrich VALUES (?, ?, ?, ?, ?, ?)", out)
    return len(out)


def enrich_field_sample(con, issues, owners):
    out = []
    for sid, row, produced_by, code in con.execute(
            "SELECT sample_id, source_row, produced_by, feed_code FROM field_sample"):
        owner = None
        if produced_by is not None:
            owner, unknown = owner_of(produced_by, owners)
            if unknown:
                issues.add("field_sample", sid, row, "produced_by", "company_tanpa_mapping", "warning",
                           produced_by, f"belum ada di company_owner.csv: {', '.join(unknown)}")
        out.append((sid, owner, norm_code(code), int(bool(code and MIXED.search(code)))))
    con.executemany("INSERT INTO field_sample_enrich VALUES (?, ?, ?, ?)", out)
    return len(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "source" / "database" / "aft.sqlite"))
    args = ap.parse_args()
    if not Path(args.db).exists():
        sys.exit(f"database tidak ditemukan: {args.db} (jalankan ingest.py dulu)")

    con = sqlite3.connect(args.db)
    con.executescript((HERE / "schema.sql").read_text())
    n_alias = load_csv(con, "material_alias", ["sheet_name", "material_name", "sap_code", "status", "note"])
    n_owner = load_csv(con, "company_owner", ["company", "owner_group", "status", "note"])
    n_range = load_csv(con, "param_range", ["parameter_code", "min_value", "max_value", "status", "note"])
    owners = {c.lower(): g for c, g in con.execute("SELECT company, owner_group FROM company_owner")}

    issues = Issues()
    no_range = check_raw_material(con, issues)
    n_pond = enrich_pond_cycle(con, issues, owners)
    n_sample = enrich_field_sample(con, issues, owners)
    con.executemany("INSERT INTO dq_issue (table_name, row_id, source_row, column_name, rule, severity, value, message) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", issues.rows)
    con.commit()

    print(f"mapping dimuat: material_alias {n_alias}, company_owner {n_owner}, param_range {n_range}")
    print(f"enrich: pond_cycle {n_pond}, field_sample {n_sample}")
    if no_range:
        print(f"parameter tanpa range (tidak dicek): {', '.join(no_range)}")
    print("\ndq_issue per aturan:")
    for table, rule, sev, n in con.execute(
            "SELECT table_name, rule, severity, count(*) FROM dq_issue GROUP BY 1, 2, 3 ORDER BY 3, 1, 2"):
        print(f"  {sev:8s} {table:15s} {rule:25s} {n}")
    print("\nview clean:")
    for view, src in [("clean_rm_test", "rm_test_result"), ("clean_pond_cycle", "pond_cycle"),
                      ("clean_field_sample", "field_sample")]:
        n_view = con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
        n_src = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        print(f"  {view:20s} {n_view:5d} baris (mentah {n_src})")
    con.close()


if __name__ == "__main__":
    main()
