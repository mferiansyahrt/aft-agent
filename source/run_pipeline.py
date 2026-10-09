"""One command from Excel to a ready database: ingest -> cleansing -> validation.

    .venv/bin/python source/run_pipeline.py                      # Excel dari docs_revised/
    .venv/bin/python source/run_pipeline.py --input data          # folder Excel lain

Steps (each is also runnable on its own):
  1. source/database/ingest.py         Excel -> tabel mentah di aft.sqlite (DB dibuat ulang)
  2. source/cleansing_data/cleanse.py  cek + standardisasi -> dq_issue, view clean_*
  3. source/database/validate.py       pastikan tabel mentah = Excel, sel per sel
Stops at the first failing step (exit code != 0).
"""
import argparse
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(ROOT / "docs_revised"), help="folder berisi file .xlsx CP Prima")
    ap.add_argument("--db", default=str(SOURCE / "database" / "aft.sqlite"), help="file SQLite tujuan")
    args = ap.parse_args()

    steps = [
        ("1/3 ingest Excel -> database", [SOURCE / "database" / "ingest.py", "--input", args.input, "--db", args.db]),
        ("2/3 cleansing", [SOURCE / "cleansing_data" / "cleanse.py", "--db", args.db]),
        ("3/3 validasi database vs Excel", [SOURCE / "database" / "validate.py", "--input", args.input, "--db", args.db]),
    ]
    for title, cmd in steps:
        print(f"\n{'=' * 80}\n{title}\n{'=' * 80}", flush=True)
        rc = subprocess.run([sys.executable, "-W", "ignore", *map(str, cmd)]).returncode
        if rc != 0:
            sys.exit(f"\nGAGAL di langkah: {title} (exit {rc})")
    print(f"\nSELESAI. Database siap: {args.db}")


if __name__ == "__main__":
    main()
