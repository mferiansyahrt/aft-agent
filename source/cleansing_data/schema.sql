-- Lapisan cleansing di aft.sqlite. Data mentah hasil ingest tidak diubah.
-- Dibuat ulang setiap kali cleanse.py dijalankan.

DROP VIEW IF EXISTS clean_rm_test;
DROP VIEW IF EXISTS clean_pond_cycle;
DROP VIEW IF EXISTS clean_field_sample;
DROP TABLE IF EXISTS pond_cycle_enrich;
DROP TABLE IF EXISTS field_sample_enrich;
DROP TABLE IF EXISTS dq_issue;
DROP TABLE IF EXISTS material_alias;
DROP TABLE IF EXISTS company_owner;
DROP TABLE IF EXISTS param_range;

-- ---------------------------------------------------------------- mapping (dari mapping/*.csv)
CREATE TABLE material_alias (
    sheet_name     TEXT NOT NULL,
    material_name  TEXT NOT NULL,
    sap_code       INTEGER,            -- NULL kalau belum dikonfirmasi
    status         TEXT NOT NULL,
    note           TEXT,
    PRIMARY KEY (sheet_name, material_name)
);

CREATE TABLE company_owner (
    company      TEXT PRIMARY KEY COLLATE NOCASE,
    owner_group  TEXT NOT NULL CHECK (owner_group IN ('own', 'competitor')),
    status       TEXT NOT NULL,
    note         TEXT
);

CREATE TABLE param_range (
    parameter_code  TEXT PRIMARY KEY,
    min_value       REAL NOT NULL,
    max_value       REAL NOT NULL,
    status          TEXT NOT NULL,
    note            TEXT
);

-- ---------------------------------------------------------------- hasil cek
-- severity 'critical' = dikeluarkan dari view clean; 'warning' = tetap dipakai, hanya ditandai
CREATE TABLE dq_issue (
    issue_id     INTEGER PRIMARY KEY,
    table_name   TEXT NOT NULL,
    row_id       INTEGER NOT NULL,     -- id baris di table_name (receipt_id, cycle_id, sample_id)
    source_row   INTEGER,              -- baris Excel
    column_name  TEXT,                 -- kolom/parameter yang bermasalah
    rule         TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('critical', 'warning')),
    value        TEXT,
    message      TEXT NOT NULL
);

-- ---------------------------------------------------------------- kolom turunan
CREATE TABLE pond_cycle_enrich (
    cycle_id        INTEGER PRIMARY KEY REFERENCES pond_cycle(cycle_id),
    owner_group     TEXT,              -- own / competitor / mixed / unknown
    brand_norm      TEXT,              -- kode merek dirapikan: huruf besar, tanpa spasi, tanpa titik di akhir
    is_mixed_brand  INTEGER NOT NULL,  -- 1 kalau lebih dari satu merek (pakai '+' atau '&')
    fcr_calc        REAL,              -- total pakan / (biomassa panen - biomassa benih)
    fcr_check       TEXT NOT NULL      -- ok / beda / tidak_bisa_dihitung
);

CREATE TABLE field_sample_enrich (
    sample_id       INTEGER PRIMARY KEY REFERENCES field_sample(sample_id),
    owner_group     TEXT,
    feed_code_norm  TEXT,
    is_mixed_code   INTEGER NOT NULL
);

-- ---------------------------------------------------------------- view clean
-- Nilai uji bahan baku siap pakai statistical engine:
-- kiriman dengan masalah critical dan nilai uji di luar range dikeluarkan.
CREATE VIEW clean_rm_test AS
SELECT r.receipt_id, r.sheet_name, r.source_row, r.block_no,
       a.sap_code, r.material_name, r.receive_date, r.po_no, r.qty_ton,
       r.transport_type, r.transport_no, t.parameter_code, t.value
FROM rm_receipt r
JOIN rm_test_result t USING (receipt_id)
LEFT JOIN material_alias a ON a.sheet_name = r.sheet_name AND a.material_name = r.material_name
WHERE NOT EXISTS (SELECT 1 FROM dq_issue d
                  WHERE d.table_name = 'rm_receipt' AND d.row_id = r.receipt_id AND d.severity = 'critical')
  AND NOT EXISTS (SELECT 1 FROM dq_issue d
                  WHERE d.table_name = 'rm_test_result' AND d.row_id = r.receipt_id
                    AND d.column_name = t.parameter_code AND d.severity = 'critical');

CREATE VIEW clean_pond_cycle AS
SELECT p.*, e.owner_group, e.brand_norm, e.is_mixed_brand, e.fcr_calc, e.fcr_check
FROM pond_cycle p JOIN pond_cycle_enrich e USING (cycle_id);

CREATE VIEW clean_field_sample AS
SELECT s.*, e.owner_group, e.feed_code_norm, e.is_mixed_code
FROM field_sample s JOIN field_sample_enrich e USING (sample_id);
