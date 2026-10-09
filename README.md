# Hermes AFT

Engine analisis pakan untuk tim formulasi CP Prima. Alurnya: data Excel CP Prima masuk ke database SQLite, dibersihkan, lalu dihitung oleh **mesin statistik**. Agent **Hermes** (agno + OpenAI/Gemini) menjawab pertanyaan dengan memanggil mesin itu. Hermes tidak pernah menghitung sendiri dan tidak pernah membaca database langsung. Setiap angka di jawaban punya nomor sumber `[run:id]` dan dicek otomatis oleh validator.

```
Excel CP Prima ─► ingest ─► cleansing ─► validasi ─► aft.sqlite
                                                        │
                       pertanyaan user ─► Hermes ─► tool mesin hitung ─► kartu [run:id]
                                             │
                                  validator angka ─► jawaban
```

---

## 1. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Linux / macOS | Windows bisa lewat WSL |
| Python **3.11** | Paling mudah lewat [uv](https://docs.astral.sh/uv/): `uv python install 3.11` |
| API key LLM | OpenAI (`OPENAI_API_KEY`) **atau** Gemini (`GOOGLE_API_KEY` / Vertex AI) |
| File Excel CP Prima | `... WPA RM FF CPB LAMPUNG.xlsx` dan `Feed Performance, Proximate & Complain_....xlsx` |

## 2. Instalasi

```bash
cd aft-agent

# dengan uv (disarankan)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# atau tanpa uv
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Konfigurasi

```bash
cp .env.example .env
```

Buka `.env`, lalu isi minimal salah satu:

```ini
# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL_NAME=gpt-5.6-luna

# atau Gemini
LLM_PROVIDER=gemini
GOOGLE_API_KEY=...
GEMINI_MODEL_NAME=gemini-3.7-flash

# atau fallback: coba OpenAI dulu, kalau gagal pakai Gemini
LLM_PROVIDER=openai,gemini
```

Pilihan lain (Vertex AI, LLM internal OpenAI-compatible) dijelaskan di `.env.example`. **Jangan pernah membagikan file `.env`**, karena berisi API key.

## 4. Siapkan data Excel

Letakkan kedua file Excel di satu folder:

- `docs_revised/` berisi **sampel kecil** (header + 10 baris data per sheet), cocok untuk uji coba pertama.
- Data lengkap boleh di folder lain, misalnya `data/`.

Format sheet harus sama dengan file contoh, karena posisi header dan nama kolom dicek. Kalau formatnya berubah, langkah validasi akan gagal dan menyebutkan kolom mana yang bergeser.

## 5. Bangun database (Excel → SQLite)

```bash
.venv/bin/python source/run_pipeline.py                  # pakai docs_revised/
.venv/bin/python source/run_pipeline.py --input data      # pakai folder lain
```

Perintah ini menjalankan 3 langkah dan berhenti kalau ada yang gagal:

| Langkah | Skrip | Hasil |
|---|---|---|
| 1. Ingest | `source/database/ingest.py` | Tabel mentah di `source/database/aft.sqlite` (dibuat ulang setiap run) |
| 2. Cleansing | `source/cleansing_data/cleanse.py` | `dq_issue` (data bermasalah) + view `clean_*` |
| 3. Validasi | `source/database/validate.py` | Isi database dicek sel per sel terhadap Excel. Harus muncul `HASIL: SEMUA COCOK` |

Mapping cleansing ada di `source/cleansing_data/mapping/*.csv` (kode SAP, company milik sendiri vs pesaing, range nilai uji). Setelah CSV diedit, jalankan ulang pipeline.

## 6. Uji tanpa LLM (gratis, cepat)

```bash
.venv/bin/python -m unittest discover -s tests
```

Mencakup: hitungan statistik (termasuk koreksi 2 kesalahan Hermes lama), validator angka, keamanan data (agent tidak bisa mengakses database), konfigurasi model OpenAI/Gemini, dan riwayat chat. Hasil yang diharapkan: `OK`.

## 7. Uji agent Hermes (memakai API key)

| Perintah | Isi |
|---|---|
| `.venv/bin/python source/run_trial.py` | 9 pertanyaan uji umum, laporan di `reports/trial_*.md` |
| `.venv/bin/python source/run_eval.py` | 20 kasus untuk 2 objective (fluktuasi RM; korelasi formula, NIR & performa), laporan di `reports/eval_objectives_*.md` |
| `.venv/bin/python source/run_chat_stream.py` | Chat interaktif dengan streaming |

### Chat dengan sesi

```bash
# mulai sesi (id dibuat otomatis dan ditampilkan), atau tentukan sendiri
.venv/bin/python source/run_chat_stream.py --session-id ses-demo01

# satu pertanyaan langsung, lanjut di sesi yang sama (riwayat diambil dari database)
.venv/bin/python source/run_chat_stream.py --session-id ses-demo01 -m "Angka aman protein MBM berapa?"
.venv/bin/python source/run_chat_stream.py --session-id ses-demo01 -m "Kalau pakai 2 SD jadi berapa?"

.venv/bin/python source/run_chat_stream.py --sessions                        # daftar sesi
.venv/bin/python source/run_chat_stream.py --session-id ses-demo01 --history # riwayat sesi
```

- Konteks yang dipakai adalah 3 tanya-jawab terakhir (`AGENT_HISTORY_TURNS`).
- Saat streaming, pemanggilan tool dan proses validasi tampil langsung. **Teks jawaban baru ditampilkan setelah lolos validator.**
- Tambahkan `--draft` untuk melihat token mentah model (khusus debug).

Untuk memilih model sementara tanpa mengubah `.env`:

```bash
LLM_PROVIDER=gemini .venv/bin/python source/run_trial.py -q 7
```

## 8. Lokasi file hasil

| File | Isi |
|---|---|
| `source/database/aft.sqlite` | Data Excel + lapisan cleansing |
| `source/database/runs.sqlite` | Setiap hitungan yang dikutip Hermes (`run_id`, tool, parameter, kartu, sidik data) |
| `source/database/chat.sqlite` | Sesi dan pesan chat |
| `reports/` | Laporan uji coba dan evaluasi |

Untuk menelusuri angka di jawaban, misalnya `[run:run-a8c52de8]`:

```bash
sqlite3 source/database/runs.sqlite "SELECT tool, params_json, card_text FROM stat_run WHERE run_id='run-a8c52de8'"
```

## 9. Struktur kode

```
source/
├── config/                  setting dari .env
├── database/                ERD.md, schema.sql, ingest/extract/validate Excel
├── cleansing_data/          cleanse.py, schema.sql, mapping/*.csv
├── agents/                  base.py (retry, fallback, streaming), models.py (OpenAI/Gemini/OpenAI-like)
│   └── hermes_agent/        agent.py, prompt.py
├── agents_tools/            stat_engine.py (mesin hitung), aft_stat_tools.py (tool agno), cards.py, snapshot.py
│                            (hanya menghitung; tidak meng-import modul database apa pun)
├── db_clients/              aft_repository.py (SATU-SATUNYA pembaca aft.sqlite -> snapshot di memori),
│                            run_log.py (runs.sqlite), chat_store.py (chat.sqlite)
├── utils/answer_validator.py
├── run_pipeline.py          Excel -> database
├── run_trial.py, run_eval.py, run_chat_stream.py
tests/                       unit test (tanpa LLM)
```

## 10. Masalah umum

| Gejala | Penyebab / solusi |
|---|---|
| `AgentUnavailable: OPENAI_API_KEY belum diisi` | Isi key di `.env`, atau ganti `LLM_PROVIDER` |
| `database tidak ditemukan` | Jalankan `run_pipeline.py` dulu |
| Validasi `GAGAL ... header beda` | Format Excel berbeda dari contoh (kolom bergeser/berganti nama). Sesuaikan `source/database/sheet_spec.py` |
| Banyak `kode_sap_belum_pasti` di cleansing | Isi kode SAP di `mapping/material_alias.csv` |
| Jawaban "belum bisa dihitung" | Data yang dibutuhkan (formula, harga SAP, spec, Feed Daily) memang belum ada di sistem. Ini perilaku yang benar. |
| `ModuleNotFoundError` | Pastikan memakai `.venv/bin/python`, bukan `python` sistem |

## 11. Keamanan data

- **Tool hanya menghitung, tidak membaca database.** Satu-satunya pembaca `aft.sqlite` adalah `db_clients/aft_repository.py` (query tetap, read-only). Data dimuat sekali sebagai snapshot di memori, tanpa kolom nama petani, farm, atau catatan bebas. Tool dan mesin hitung hanya menghitung dari snapshot itu. Test `tests/test_security.py` memblokir semua koneksi database lalu menjalankan ke-11 tool, dan semuanya harus tetap berhasil.
- LLM hanya menerima **kartu hasil hitungan** (agregat). Jejak audit (`runs.sqlite`) ditulis oleh agent setelah model selesai, bukan oleh tool.
- Telemetri agno dimatikan. Respons OpenAI tidak disimpan di server (`store=False`).
- Untuk data yang tidak boleh keluar: pakai Gemini via **Vertex AI** di project GCP sendiri (region `asia-southeast2`), atau LLM internal (`LLM_PROVIDER=openai_like`).
