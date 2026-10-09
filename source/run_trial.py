"""Trial run: ask Hermes a set of user questions and report how each answer did.

    .venv/bin/python source/run_trial.py            # semua pertanyaan
    .venv/bin/python source/run_trial.py -q 2 7      # nomor tertentu
    .venv/bin/python source/run_trial.py --chat      # percakapan bersambung (riwayat 3 tanya-jawab)
    LLM_PROVIDER=gemini,openai .venv/bin/python source/run_trial.py -q 7   # pilih/urutkan model

Prints each answer with the tools called and the validator verdict, and writes
a Markdown report to reports/trial_<timestamp>.md.
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings  # noqa: E402
from agents.hermes_agent import HermesAgent  # noqa: E402

QUESTIONS = [
    ("Protein MBM rata-rata berapa dan stabil nggak?", "menyebut beberapa blok/periode"),
    ("Angka aman protein MBM untuk formula berapa?", "memakai jendela terbaru setelah pergeseran"),
    ("Ada kiriman PBPM yang janggal?", "daftar kiriman janggal atau tidak ada"),
    ("Stok MBM cukup berapa hari?", "jujur DOH hitung ulang vs Excel"),
    ("FCR pakan CPB 788-3 dibanding pesaing gimana?", "own vs competitor, n kecil, bukan sebab-akibat"),
    ("Apakah protein lebih tinggi bikin FCR lebih bagus?", "korelasi tidak bisa dihitung / bukan sebab-akibat"),
    ("Kalau aditif harganya Rp120.000/kg dengan dosis 1 kg/ton di pakan lele Rp11.000/kg, FCR harus turun berapa supaya impas?",
     "1,08 %"),
    ("Protein 788-3 di lapangan sesuai label nggak?", "spec label kosong -> tidak bisa dinilai"),
    ("Buatkan formula termurah untuk pakan Lele.", "menolak, sebut data yang kurang"),
]

# Percakapan bersambung: pertanyaan 2-4 hanya bisa dijawab dengan konteks sebelumnya
CONVERSATION = [
    ("Angka aman protein MBM untuk formula berapa?", "rm_safe_value MBM, k=1"),
    ("Kalau pakai 2 SD jadi berapa?", "rm_safe_value MBM, k=2 (dari konteks)"),
    ("Bahan itu stoknya cukup berapa hari?", "rm_stock MBM (dari konteks)"),
    ("Kalau PBPM angka amannya berapa?", "rm_safe_value PBPM protein (dari konteks)"),
]


async def chat(agent: HermesAgent) -> None:
    """Run CONVERSATION with app-managed history (last AGENT_HISTORY_TURNS pairs)."""
    history = []
    for i, (q, expect) in enumerate(CONVERSATION, 1):
        res = await agent.run(q, history=history)
        tools = ", ".join(f"{c['tool']}({c['params']})" for c in res.tool_calls if c["ok"]) or "-"
        print(f"\n{'=' * 100}\n[giliran {i}] {q}\nharapan : {expect}\ntools   : {tools}\n"
              f"validator: {'LOLOS' if res.ok else 'DITOLAK'} · percobaan {res.attempts}\n\n{res.answer}")
        history += [("user", q), ("assistant", res.answer if res.ok else "(jawaban tidak lolos validator)")]


async def main(selected):
    agent = HermesAgent()
    lines = [f"# Uji coba Hermes AFT — {datetime.now():%Y-%m-%d %H:%M}",
             f"Model: {agent.specs[0].label} · DB: {settings.AFT_DB_PATH.name}", ""]
    passed = 0
    for i, (q, expect) in enumerate(QUESTIONS, 1):
        if selected and i not in selected:
            continue
        t0 = time.time()
        res = await agent.run(q)
        dt = time.time() - t0
        passed += res.ok
        tools = ", ".join(f"{c['tool']}({'ok' if c['ok'] else 'GAGAL'})" for c in res.tool_calls) or "-"
        v = res.validation
        verdict = "LOLOS" if res.ok else "DITOLAK"
        print(f"\n{'=' * 100}\n[{i}] {q}\nharapan : {expect}\ntools   : {tools}")
        print(f"validator: {verdict} · angka dicek {v.numbers_checked if v else 0} · percobaan {res.attempts} · {dt:.1f}s")
        if v and v.errors:
            print("kesalahan:\n" + v.feedback())
        if res.error and not v:
            print(f"error: {res.error}")
        print(f"\n{res.answer}")
        lines += [f"## {i}. {q}", f"- Harapan: {expect}", f"- Tools: {tools}",
                  f"- Validator: **{verdict}** (angka dicek {v.numbers_checked if v else 0}, percobaan {res.attempts}, {dt:.1f} detik)"]
        if v and v.errors:
            lines += ["- Kesalahan validator:"] + [f"  - {e}" for e in v.errors]
        lines += ["", "**Jawaban:**", "", res.answer or f"_(tidak ada jawaban: {res.error})_", "",
                  "<details><summary>Kartu</summary>", ""]
        for rid, text in res.cards.items():
            lines += ["```", text, "```", ""]
        lines += ["</details>", ""]
    total = len(selected) if selected else len(QUESTIONS)
    print(f"\n{'=' * 100}\nLOLOS VALIDATOR: {passed}/{total}")
    out = PROJECT_ROOT / "reports" / f"trial_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines + [f"**Lolos validator: {passed}/{total}**"]), encoding="utf-8")
    print(f"laporan: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-q", type=int, nargs="*", help="nomor pertanyaan (1-based)")
    ap.add_argument("--chat", action="store_true", help="uji percakapan bersambung (konteks riwayat)")
    args = ap.parse_args()
    if args.chat:
        print(f"Model chain: {' -> '.join(s.label for s in HermesAgent().specs)}")
        asyncio.run(chat(HermesAgent()))
    else:
        asyncio.run(main(set(args.q or [])))
