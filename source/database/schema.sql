-- Skema SQLite Hermes AFT: data mentah terstruktur dari Excel CP Prima.
-- Tanggal disimpan sebagai TEXT ISO (YYYY-MM-DD). Setiap baris menyimpan asal sel (source_row/source_col).
PRAGMA foreign_keys = ON;

CREATE TABLE source_file (
    file_id      INTEGER PRIMARY KEY,
    file_name    TEXT NOT NULL,
    file_kind    TEXT NOT NULL CHECK (file_kind IN ('WPA', 'FEED_PERF')),
    sha256       TEXT NOT NULL,
    ingested_at  TEXT NOT NULL
);

CREATE TABLE parameter (
    code  TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

-- Daftar kode SAP dari WPA REPORT kolom BA-BB
CREATE TABLE material (
    sap_code     INTEGER PRIMARY KEY,
    description  TEXT,
    file_id      INTEGER NOT NULL REFERENCES source_file(file_id),
    source_row   INTEGER NOT NULL
);

-- ---------------------------------------------------------------- WPA
CREATE TABLE wpa_report (
    report_id           INTEGER PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES source_file(file_id),
    report_title        TEXT,
    form_code           TEXT,
    plant               TEXT,
    period_text         TEXT,
    stock_date_text     TEXT,
    stock_date          TEXT,
    qc_form_ref         TEXT,
    reporter            TEXT,
    reported_date_text  TEXT
);

-- 1 baris = 1 baris lot di WPA REPORT (satu bahan bisa punya beberapa lot)
CREATE TABLE wpa_stock_lot (
    lot_id             INTEGER PRIMARY KEY,
    report_id          INTEGER NOT NULL REFERENCES wpa_report(report_id),
    file_id            INTEGER NOT NULL REFERENCES source_file(file_id),
    source_row         INTEGER NOT NULL,
    item_no            INTEGER,          -- hanya terisi di baris pertama tiap bahan
    material_name      TEXT,
    sap_code           INTEGER REFERENCES material(sap_code),
    receive_date       TEXT,
    origin_country     TEXT,
    producer_name      TEXT,
    po_no_raw          TEXT,             -- bisa berisi beberapa PO, mis. "17805, 17854"
    stock_ton          REAL,
    usage_ton_per_day  REAL,
    doh_days           REAL,
    description        TEXT,
    remark             TEXT
);

CREATE TABLE wpa_stock_lot_quality (
    lot_id          INTEGER NOT NULL REFERENCES wpa_stock_lot(lot_id),
    parameter_code  TEXT NOT NULL REFERENCES parameter(code),
    value           REAL NOT NULL,
    source_col      TEXT NOT NULL,
    PRIMARY KEY (lot_id, parameter_code)
);

-- 1 baris = 1 truk/kontainer di sheet SBM, PBPM, MBM, FML C
CREATE TABLE rm_receipt (
    receipt_id      INTEGER PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
    sheet_name      TEXT NOT NULL,
    source_row      INTEGER NOT NULL,
    block_no        INTEGER NOT NULL,    -- blok data yang dipisah baris kosong (No. mulai lagi dari 1)
    item_no         INTEGER,
    receive_date    TEXT,
    material_name   TEXT,
    po_no           TEXT,
    qty_ton         REAL,
    transport_type  TEXT NOT NULL CHECK (transport_type IN ('dump_truck', 'container')),
    transport_no    TEXT,
    remark          TEXT
);

CREATE TABLE rm_test_result (
    receipt_id      INTEGER NOT NULL REFERENCES rm_receipt(receipt_id),
    parameter_code  TEXT NOT NULL REFERENCES parameter(code),
    value           REAL NOT NULL,
    source_col      TEXT NOT NULL,
    PRIMARY KEY (receipt_id, parameter_code)
);

-- ---------------------------------------------------------------- Feed Performance
-- 1 baris = 1 siklus budidaya (sheet Database Performance)
CREATE TABLE pond_cycle (
    cycle_id                  INTEGER PRIMARY KEY,
    file_id                   INTEGER NOT NULL REFERENCES source_file(file_id),
    source_row                INTEGER NOT NULL,
    farmer_name               TEXT,
    area                      TEXT,
    sub_area                  TEXT,
    fish_species              TEXT,
    pond_volume_m3            REAL,
    pond_construction         TEXT,
    stocking_date             TEXT,
    seed_biomass_kg           REAL,
    seed_size_pcs_per_kg      REAL,
    stocking_count            REAL,
    seed_price_rp_per_kg      REAL,
    seed_origin               TEXT,
    feed_qty_kg               REAL,
    feed_price_rp_per_kg      REAL,
    waste_qty_kg              REAL,
    waste_price_rp_per_kg     REAL,
    waste_pct                 REAL,
    total_feed_kg             REAL,
    avg_feed_price_rp_per_kg  REAL,
    harvest_date              TEXT,
    harvest_biomass_kg        REAL,
    harvest_size_pcs_per_kg   REAL,
    harvest_price_rp_per_kg   REAL,
    company                   TEXT,
    brand                     TEXT,
    density_pcs_per_m3        REAL,
    doc_days                  REAL,
    sr_pct                    REAL,
    adg_g_per_day             REAL,
    fce_pct                   REAL,
    fcr                       REAL,
    feed_cost_rp_per_kg_fish  REAL,
    seed_cost_rp_per_kg_fish  REAL,
    prod_cost_rp_per_kg_fish  REAL,
    productivity_kg_per_m3    REAL,
    remark                    TEXT,
    month                     TEXT,
    year                      INTEGER,
    marketing_area            TEXT,
    marketing_sub_area        TEXT,
    rendeman                  REAL,
    reporting                 TEXT,
    stadia                    TEXT,
    note                      TEXT
);

-- 1 baris = 1 sampel pakan lapangan (sheet Database Proximate)
CREATE TABLE field_sample (
    sample_id            INTEGER PRIMARY KEY,
    file_id              INTEGER NOT NULL REFERENCES source_file(file_id),
    source_row           INTEGER NOT NULL,
    fish                 TEXT,
    month                TEXT,
    year                 INTEGER,
    date_sent            TEXT,
    date_received        TEXT,
    feed_type            TEXT,
    produced_by          TEXT,
    feed_code            TEXT,
    prod_code            TEXT,
    moisture_nir         REAL,
    protein_nir          REAL,
    fat_nir              REAL,
    fiber_nir            REAL,
    ash_nir              REAL,
    calcium_nir          REAL,
    phosphor_nir         REAL,
    size_range           TEXT,
    size_average         REAL,
    size_under_pct       REAL,
    size_proper_pct      REAL,
    size_over_pct        REAL,
    density_g_per_l      REAL,
    durability_pct       REAL,
    absorb_pct           REAL,
    water_stability_min  REAL,
    hardness_kg          REAL,
    floating_rate_pct    REAL,
    remark               TEXT,
    area                 TEXT,
    sub_area             TEXT,
    farm                 TEXT,
    sample_source        TEXT,
    spec_moisture_min    REAL,
    spec_moisture_max    REAL,
    spec_protein_min     REAL,
    spec_protein_max     REAL,
    spec_fat_min         REAL,
    spec_fat_max         REAL,
    spec_fiber_min       REAL,
    spec_fiber_max       REAL,
    spec_ash_min         REAL,
    spec_ash_max         REAL,
    spec_calcium_min     REAL,
    spec_calcium_max     REAL,
    spec_phosphor_min    REAL,
    spec_phosphor_max    REAL,
    note                 TEXT,
    reporting            TEXT
);

-- 1 baris = 1 keluhan (sheet Rekap Complain)
CREATE TABLE complaint (
    complaint_id      INTEGER PRIMARY KEY,
    file_id           INTEGER NOT NULL REFERENCES source_file(file_id),
    source_row        INTEGER NOT NULL,
    complaint_no      INTEGER,
    month             TEXT,
    farmer_name       TEXT,
    area              TEXT,
    sub_area          TEXT,
    district          TEXT,
    complaint_date    TEXT,
    visit_date        TEXT,
    follow_up_by      TEXT,
    plant             TEXT,
    feed_code         TEXT,
    production_code   TEXT,
    info_source       TEXT,
    complaint_text    TEXT,
    preliminary_info  TEXT,
    investigation     TEXT,
    action_taken      TEXT,
    conclusion        TEXT,
    category_note     TEXT
);

-- Sel yang tidak bisa dikonversi ke tipe kolomnya (nilai DB dibiarkan NULL)
CREATE TABLE ingest_issue (
    issue_id       INTEGER PRIMARY KEY,
    file_id        INTEGER NOT NULL REFERENCES source_file(file_id),
    sheet_name     TEXT NOT NULL,
    cell_ref       TEXT NOT NULL,
    raw_value      TEXT,
    expected_type  TEXT,
    reason         TEXT NOT NULL
);

CREATE INDEX idx_lot_sap ON wpa_stock_lot(sap_code);
CREATE INDEX idx_receipt_sheet ON rm_receipt(sheet_name, receive_date);
CREATE INDEX idx_test_param ON rm_test_result(parameter_code);
CREATE INDEX idx_pond_brand ON pond_cycle(company, brand);
CREATE INDEX idx_sample_feed ON field_sample(produced_by, feed_code);
CREATE INDEX idx_complaint_feed ON complaint(plant, feed_code);
