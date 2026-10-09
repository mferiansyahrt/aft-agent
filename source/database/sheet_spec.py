"""Spesifikasi deklaratif sheet Excel CP Prima -> tabel SQLite.

Dipakai oleh extract.py (membaca) dan validate.py (mengecek ulang).
Teks header di sini sudah dinormalisasi: spasi/enter berturut-turut dijadikan satu spasi.
Tipe kolom: TEXT, REAL, INTEGER, DATE (disimpan sebagai teks ISO YYYY-MM-DD).
"""

# Kamus parameter uji bahan baku (tabel `parameter`).
PARAMETERS = {
    "moisture": "Moisture (kadar air)",
    "crude_protein": "Crude protein (protein kasar)",
    "fat": "Fat (lemak)",
    "fiber": "Fiber (serat kasar)",
    "ash": "Ash (abu)",
    "nacl": "NaCl (garam)",
    "calcium": "Calcium (Ca)",
    "phosphorus": "Phosphorus (P)",
    "pepsin_digest": "Pepsin digestibility (PD_02PCN)",
    "koh_digest": "KOH digest",
    "urease_tia": "Urease activity / Trypsin inhibitor (U.A./T.I.A.)",
    "aflatoxin_ppb": "Aflatoxin (ppb)",
    "ffa": "Free fatty acid",
    "iodine_value": "Iodine value (gr I2/100gr)",
    "tvbn": "TVBN",
    "mbm_index": "Index for MBM",
    "ethoxyquin": "Ethoxyquin",
    "phosphor_solubility": "Phosphor solubility",
    "pkm_shell": "Shell of PKM",
    "acid_value": "Acid value (mg KOH/gr oil)",
    "hulls": "Hulls",
    "nfe": "NFE",
    "cp_solubility": "CP solubility",
    "wet_gluten": "Wet gluten",
    "aim": "AIM",
    "brix": "Brix (%)",
    "pdi": "PDI",
    "pov": "POV",
    "lysine_availability": "Lysine availability",
    "cholesterol": "Cholesterol",
}

# ---------------------------------------------------------------------------
# File WPA (Weekly stock of raw material and quality report)
# ---------------------------------------------------------------------------
WPA_REPORT = {
    "sheet": "WPA REPORT",
    "header_row": 7,
    "data_start": 8,
    "scan_cols": ("A", "AP"),  # area tabel lot; BA-BB adalah tabel lookup kode SAP
    # metadata laporan: field -> (sel, tipe). Nilai setelah tanda ':' yang diambil.
    "meta": {
        "report_title": ("A1", "TEXT"),
        "form_code": ("A2", "TEXT"),
        "plant": ("C3", "TEXT"),
        "period_text": ("C4", "TEXT"),
        "stock_date_text": ("C5", "TEXT"),
        "qc_form_ref": ("AF3", "TEXT"),
        "reporter": ("AF4", "TEXT"),
        "reported_date_text": ("AF5", "TEXT"),
    },
    "meta_labels": {
        "A3": "P L A N T", "A4": "PERIODE DATE", "A5": "STOCK DATE",
        "AD3": "QC FORM REFF", "AD4": "REPORTER", "AD5": "REPORTED DATE",
    },
    # kolom lot: huruf -> (header, kolom DB, tipe)
    "lot_cols": {
        "A": ("No.", "item_no", "INTEGER"),
        "B": ("Raw Material Name", "material_name", "TEXT"),
        "C": ("Material SAP Code", "sap_code", "INTEGER"),
        "D": ("RM Receive Date", "receive_date", "DATE"),
        "E": ("Ex. Country", "origin_country", "TEXT"),
        "F": ("Producer Name", "producer_name", "TEXT"),
        "G": ("P/O. No.", "po_no_raw", "TEXT"),
        "H": ("Stock Amount (Ton)", "stock_ton", "REAL"),
        "I": ("Usage Ton/Day", "usage_ton_per_day", "REAL"),
        "J": ("DOH (Days)", "doh_days", "REAL"),
        "K": ("Description", "description", "TEXT"),
        "AP": ("Remark", "remark", "TEXT"),
    },
    # kolom kualitas: huruf -> (header, kode parameter); disimpan long di wpa_stock_lot_quality
    "quality_cols": {
        "L": ("Moisture", "moisture"),
        "M": ("CP", "crude_protein"),
        "N": ("Fat", "fat"),
        "O": ("Fiber", "fiber"),
        "P": ("T.Ash", "ash"),
        "Q": ("NaCl (Salt)", "nacl"),
        "R": ("Ca", "calcium"),
        "S": ("P", "phosphorus"),
        "T": ("Pepsin Digest /PD_02PCN", "pepsin_digest"),
        "U": ("KOH Digest", "koh_digest"),
        "V": ("U.A. (T.I.A.)", "urease_tia"),
        "W": ("Afla - toxin (ppb)", "aflatoxin_ppb"),
        "X": ("FFA", "ffa"),
        "Y": ("Iodine Value (gr I2 /100gr)", "iodine_value"),
        "Z": ("TVBN", "tvbn"),
        "AA": ("Index for MBM", "mbm_index"),
        "AB": ("Ethoxy -quin", "ethoxyquin"),
        "AC": ("Phosphor Solubility", "phosphor_solubility"),
        "AD": ("Shell of PKM", "pkm_shell"),
        "AE": ("Acid Value (mg KOH /gr Oil)", "acid_value"),
        "AF": ("Hulls", "hulls"),
        "AG": ("NFE", "nfe"),
        "AH": ("CP Sol-ubility", "cp_solubility"),
        "AI": ("Wet Gluten", "wet_gluten"),
        "AJ": ("AIM", "aim"),
        "AK": ("Brix (%)", "brix"),
        "AL": ("PDI", "pdi"),
        "AM": ("POV", "pov"),
        "AN": ("Lysine Avail-ability", "lysine_availability"),
        "AO": ("Choles-terol", "cholesterol"),
    },
    # daftar kode SAP (lookup untuk rumus VLOOKUP kolom B); baris dengan kode angka saja
    "material": {
        "header_row": 7, "data_start": 8,
        "code_col": ("BA", "SAP Code"),
        "desc_col": ("BB", "Raw Material Description"),
    },
}

# Sheet detail per truk/kontainer. Kolom: huruf -> (header, baris header, kolom DB, tipe)
_RM_BASE = {
    "A": ("No", 1, "item_no", "INTEGER"),
    "B": ("Receive Date", 1, "receive_date", "DATE"),
    "C": ("Raw Material Name", 1, "material_name", "TEXT"),
    "E": ("Qtty (Tons)", 1, "qty_ton", "REAL"),
}


def _rm(po_header, transport_header, transport_type, group_header, tests, extra=None):
    cols = dict(_RM_BASE)
    cols["D"] = (po_header, 1, "po_no", "TEXT")
    cols["F"] = (transport_header, 1, "transport_no", "TEXT")
    cols.update(extra or {})
    return {
        "header_rows": (1, 2), "data_start": 3, "transport_type": transport_type,
        "group_header": ("G1", group_header),
        "base_cols": cols,
        # kolom uji: huruf -> (header baris 2, kode parameter)
        "test_cols": tests,
    }


RM_SHEETS = {
    "SBM": _rm("P/O No.", "No. Dump Truck", "dump_truck", "Proximate Analysis", {
        "G": ("M", "moisture"), "H": ("CP", "crude_protein"), "I": ("Fat", "fat"),
        "J": ("Fiber", "fiber"), "K": ("Ash", "ash"), "L": ("PDI", "pdi"),
        "M": ("KOH Digest", "koh_digest"),
    }, extra={"N": ("Remark", 2, "remark", "TEXT")}),
    "PBPM": _rm("P/O No.", "No. Container", "container", "Proximate Analysis", {
        "G": ("M", "moisture"), "H": ("CP", "crude_protein"), "I": ("Fat", "fat"),
        "J": ("Fiber", "fiber"), "K": ("Ash", "ash"), "L": ("Ca", "calcium"),
        "M": ("P", "phosphorus"), "N": ("PD_02PCN", "pepsin_digest"),
    }),
    "MBM": _rm("PO Number", "No. Container", "container", "Proximat Analysis", {
        "G": ("M", "moisture"), "H": ("Cp", "crude_protein"), "I": ("Fat", "fat"),
        "J": ("Fiber", "fiber"), "K": ("Ash", "ash"), "L": ("Ca", "calcium"),
        "M": ("P", "phosphorus"), "N": ("INDEX", "mbm_index"),
    }),
    "FML C": _rm("PO Number", "No. Container", "container", "Proximat Analysis", {
        "G": ("M", "moisture"), "H": ("Cp", "crude_protein"), "I": ("Fat", "fat"),
        "J": ("Ash", "ash"), "K": ("Ca", "calcium"), "L": ("P", "phosphorus"),
        "M": ("PD", "pepsin_digest"),  # PD diasumsikan pepsin digest (perlu konfirmasi QC)
        "N": ("TVBN", "tvbn"),
    }),
}

# ---------------------------------------------------------------------------
# File Feed Performance, Proximate & Complain (tabel lebar, 1 baris Excel = 1 baris DB)
# kolom: huruf -> (header, kolom DB, tipe)
# ---------------------------------------------------------------------------
POND_CYCLE = {
    "sheet": "Database Performance", "table": "pond_cycle", "header_row": 3, "data_start": 4,
    "cols": {
        "B": ("Nama Petani", "farmer_name", "TEXT"),
        "C": ("Area", "area", "TEXT"),
        "D": ("Sub Area", "sub_area", "TEXT"),
        "E": ("Jenis Ikan", "fish_species", "TEXT"),
        "F": ("Vol. Kolam (m3)", "pond_volume_m3", "REAL"),
        "G": ("Konstruksi", "pond_construction", "TEXT"),
        "H": ("Tgl. Tebar", "stocking_date", "DATE"),
        "I": ("Biomass Benih (Kg)", "seed_biomass_kg", "REAL"),
        "J": ("Size Benih (ekor/kg)", "seed_size_pcs_per_kg", "REAL"),
        "K": ("Jumlah Tebar (ekor)", "stocking_count", "REAL"),
        "L": ("Harga Benih (Rp/kg)", "seed_price_rp_per_kg", "REAL"),
        "M": ("Asal Benih", "seed_origin", "TEXT"),
        "N": ("Jumlah Pakan(Kg)", "feed_qty_kg", "REAL"),
        "O": ("Harga pakan (Rp/Kg)", "feed_price_rp_per_kg", "REAL"),
        "P": ("Jumlah Limbah (Kg)", "waste_qty_kg", "REAL"),
        "Q": ("Harga Limbah (Rp/Kg)", "waste_price_rp_per_kg", "REAL"),
        "R": ("%-ase Limbah", "waste_pct", "REAL"),
        "S": ("Total Pakan (Kg)", "total_feed_kg", "REAL"),
        "T": ("Harga pakan (Rp/Kg)", "avg_feed_price_rp_per_kg", "REAL"),
        "U": ("Tgl. Panen", "harvest_date", "DATE"),
        "V": ("Biomass Panen (Kg)", "harvest_biomass_kg", "REAL"),
        "W": ("Size panen", "harvest_size_pcs_per_kg", "REAL"),
        "X": ("Harga Panen (Rp/kg)", "harvest_price_rp_per_kg", "REAL"),
        "Y": ("Company", "company", "TEXT"),
        "Z": ("Brand", "brand", "TEXT"),
        "AA": ("Density (ekor/m3)", "density_pcs_per_m3", "REAL"),
        "AB": ("DOC (hari)", "doc_days", "REAL"),
        "AC": ("SR (%)", "sr_pct", "REAL"),
        "AD": ("ADG (g/hr)", "adg_g_per_day", "REAL"),
        "AE": ("FCE (%)", "fce_pct", "REAL"),
        "AF": ("FCR", "fcr", "REAL"),
        "AG": ("Feed Cost (Rp/kg ikan)", "feed_cost_rp_per_kg_fish", "REAL"),
        "AH": ("Seed Cost (Rp/kg ikan)", "seed_cost_rp_per_kg_fish", "REAL"),
        "AI": ("Prod. Cost (RP/kg ikan)", "prod_cost_rp_per_kg_fish", "REAL"),
        "AJ": ("Productivity (kg/m3)", "productivity_kg_per_m3", "REAL"),
        "AK": ("Remark", "remark", "TEXT"),
        "AL": ("Month", "month", "TEXT"),
        "AM": ("Year", "year", "INTEGER"),
        "AN": ("Marketing Area", "marketing_area", "TEXT"),
        "AO": ("Marketing Sub Area", "marketing_sub_area", "TEXT"),
        "AP": ("Rendeman", "rendeman", "REAL"),
        "AQ": ("Reporting", "reporting", "TEXT"),
        "AR": ("Stadia", "stadia", "TEXT"),
        "AS": ("Note", "note", "TEXT"),
    },
    "skip_cols": {},
}

FIELD_SAMPLE = {
    "sheet": "Database Proximate", "table": "field_sample", "header_row": 5, "data_start": 6,
    "cols": {
        "A": ("Fish", "fish", "TEXT"),
        "B": ("Month", "month", "TEXT"),
        "C": ("Year", "year", "INTEGER"),
        "D": ("Date Sent", "date_sent", "DATE"),
        "E": ("Date Received", "date_received", "DATE"),
        "F": ("Type of Feed", "feed_type", "TEXT"),
        "G": ("Produced By", "produced_by", "TEXT"),
        "H": ("Feed Code", "feed_code", "TEXT"),
        "I": ("Prod. Code", "prod_code", "TEXT"),
        "J": ("Moisture_NIR", "moisture_nir", "REAL"),
        "K": ("Protein_NIR", "protein_nir", "REAL"),
        "L": ("Fat_NIR", "fat_nir", "REAL"),
        "M": ("Fiber_NIR", "fiber_nir", "REAL"),
        "N": ("Ash_NIR", "ash_nir", "REAL"),
        "O": ("Calcium_NIR", "calcium_nir", "REAL"),
        "P": ("Phosphor_NIR", "phosphor_nir", "REAL"),
        "Q": ("Range", "size_range", "TEXT"),
        "R": ("Average", "size_average", "REAL"),
        "S": ("Under", "size_under_pct", "REAL"),
        "T": ("Proper", "size_proper_pct", "REAL"),
        "U": ("Over", "size_over_pct", "REAL"),
        "V": ("Density (gr/l)", "density_g_per_l", "REAL"),
        "W": ("Durability (%)", "durability_pct", "REAL"),
        "X": ("Absorb T. (%)", "absorb_pct", "REAL"),
        "Y": ("WS (min)", "water_stability_min", "REAL"),
        "Z": ("Hardness (kg)", "hardness_kg", "REAL"),
        "AA": ("Floating Rate (%)", "floating_rate_pct", "REAL"),
        "AB": ("Remark", "remark", "TEXT"),
        "AC": ("Area", "area", "TEXT"),
        "AD": ("Sub Area", "sub_area", "TEXT"),
        "AE": ("Farm", "farm", "TEXT"),
        "AF": ("Sample Source (Sub Area)", "sample_source", "TEXT"),
        "AG": ("MOISTURE_Min", "spec_moisture_min", "REAL"),
        "AH": ("MOISTURE_Max", "spec_moisture_max", "REAL"),
        "AI": ("PROTEIN_Min", "spec_protein_min", "REAL"),
        "AJ": ("PROTEIN_Max", "spec_protein_max", "REAL"),
        "AK": ("FAT_Min", "spec_fat_min", "REAL"),
        "AL": ("FAT_Max", "spec_fat_max", "REAL"),
        "AM": ("FIBER_Min", "spec_fiber_min", "REAL"),
        "AN": ("FIBER_Max", "spec_fiber_max", "REAL"),
        "AO": ("ASH_Min", "spec_ash_min", "REAL"),
        "AP": ("ASH_Max", "spec_ash_max", "REAL"),
        "AQ": ("CALCIUM_Min", "spec_calcium_min", "REAL"),
        "AR": ("CALCIUM_Max", "spec_calcium_max", "REAL"),
        "AS": ("PHOSPHOR_Min", "spec_phosphor_min", "REAL"),
        "AT": ("PHOSPHOR_Max", "spec_phosphor_max", "REAL"),
        "AU": ("Note", "note", "TEXT"),
        "AV": ("Reporting", "reporting", "TEXT"),
    },
    "skip_cols": {},
}

COMPLAINT = {
    "sheet": "Rekap Complain", "table": "complaint", "header_row": 1, "data_start": 2,
    "cols": {
        "A": ("No.", "complaint_no", "INTEGER"),
        "B": ("Bulan", "month", "TEXT"),
        "C": ("Nama Petani", "farmer_name", "TEXT"),
        "D": ("Area", "area", "TEXT"),
        "E": ("Sub Area", "sub_area", "TEXT"),
        "F": ("Distrik", "district", "TEXT"),
        "G": ("Tgl. Masuk Keluhan", "complaint_date", "DATE"),
        "H": ("Tgl. Kunjungan", "visit_date", "DATE"),
        "I": ("Follow Up By", "follow_up_by", "TEXT"),
        "J": ("Plant Pabrik", "plant", "TEXT"),
        "K": ("Kode Pakan", "feed_code", "TEXT"),
        "L": ("Kode Produksi", "production_code", "TEXT"),
        "M": ("Sumber Informasi Keluhan", "info_source", "TEXT"),
        "N": ("Keluhan", "complaint_text", "TEXT"),
        "O": ("Info Pendahuluan", "preliminary_info", "TEXT"),
        "P": ("Informasi Investigasi", "investigation", "TEXT"),
        "Q": ("Tindakan di Lokasi", "action_taken", "TEXT"),
        "R": ("Kesimpulan", "conclusion", "TEXT"),
        "S": ("Catatan", "category_note", "TEXT"),
    },
    # Foto berupa gambar tempel, tidak di-ingest tahap ini
    "skip_cols": {"T": "Foto"},
}

WIDE_SHEETS = [POND_CYCLE, FIELD_SAMPLE, COMPLAINT]

# Sheet rekap/pivot yang sengaja tidak di-ingest (bisa dihitung ulang dari tabel DB)
SKIPPED_SHEETS = {"Pivot Performance", "Pivot Proximate", "N_Performance", "N_Proximate", "Stat_Complain"}


def file_kind(sheetnames):
    """Tentukan jenis file dari nama sheet."""
    if WPA_REPORT["sheet"] in sheetnames:
        return "WPA"
    if POND_CYCLE["sheet"] in sheetnames:
        return "FEED_PERF"
    return None
