"""Evaluation of Hermes against the two AFT objectives, with a Markdown report.

    .venv/bin/python source/run_eval.py              # semua kasus
    .venv/bin/python source/run_eval.py -c F4 K8     # kasus tertentu

Objectives (deck "Trial Agentic AFT AI Project", slide 2):
  F  Analisa fluktuasi kandungan RM
  K  Korelasi formula, NIR & performance lapangan

Each case is scored automatically:
  1. validator   - every number in the answer comes from a card ([run:id])
  2. tools       - the expected computation tool was called
  3. must        - required behaviour phrases (regex, case-insensitive), e.g. "belum bisa"
  4. must_not    - forbidden claims, e.g. "terbukti menyebabkan"
  5. truth       - key numbers equal what StatEngine computes directly (ground truth)
"""
import argparse
import asyncio
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROJECT_ROOT, settings  # noqa: E402
from agents.hermes_agent import HermesAgent  # noqa: E402
from agents_tools.stat_engine import Result, StatEngine  # noqa: E402
from db_clients.aft_repository import load_snapshot  # noqa: E402

OBJECTIVES = {"F": "Analisa fluktuasi kandungan RM", "K": "Korelasi formula, NIR & performance lapangan"}


@dataclass
class Case:
    id: str
    question: str
    expect: str
    tools: Sequence[str] = ()                       # minimal salah satu dipanggil (kosong = tidak dicek)
    must: Sequence[str] = ()                        # semua regex harus cocok
    must_not: Sequence[str] = ()
    truth: Optional[Callable[[StatEngine], List[str]]] = None   # angka yang wajib muncul
    status_now: str = "bisa"                         # bisa / sebagian / belum (butuh data)


def fact(res: Result, label: str) -> str:
    """Nilai fakta dari kartu tanpa satuan, mis. '58,69 %' -> '58,69'."""
    return dict(res.facts)[label].split()[0]


def cell(res: Result, table: int, row_key: str, col: int) -> str:
    rows = res.tables[table][2]
    return next(r[col] for r in rows if r[0] == row_key).split()[0]


CASES = [
    # ------------------------------------------------------------------ F: fluktuasi RM
    Case("F1", "Protein MBM rata-rata berapa dan stabil nggak?",
         "rata-rata + ada pergeseran level, jadi tidak stabil", ("rm_summary", "rm_level_shift"),
         must=[r"pergeseran|tidak stabil|belum stabil|berubah"],
         truth=lambda e: [fact(e.rm_summary("MBM"), "Rata-rata")]),
    Case("F2", "Berapa variasi (CV) protein SBM?", "CV dari engine", ("rm_summary",),
         truth=lambda e: [fact(e.rm_summary("SBM"), "CV")]),
    Case("F3", "Apakah kualitas protein MBM tahun ini berubah dibanding tahun lalu?",
         "pergeseran terdeteksi + tanggal mulai", ("rm_level_shift",),
         must=[r"pergeseran|berubah|naik"],
         truth=lambda e: [fact(e.rm_level_shift("MBM"), "Pergeseran mulai kiriman tanggal")]),
    Case("F4", "Angka aman protein PBPM untuk formula berapa?", "angka aman PBPM k=1", ("rm_safe_value",),
         must=[r"nutritionist|bukan spec|belum stabil|draf"],
         truth=lambda e: [fact(e.rm_safe_value("PBPM"), "Angka aman (rata-rata − k×SD)")]),
    Case("F5", "Angka aman kadar air fish meal kalau pakai 2 SD berapa?",
         "jujur: data fish meal hanya 1 kiriman, tidak bisa dihitung", ("rm_safe_value", "rm_summary"),
         must=[r"\b1 kiriman|hanya 1|satu kiriman|tidak (bisa|dapat)|belum (bisa|dapat)|tidak cukup"]),
    Case("F6", "Ada kiriman MBM yang protein-nya janggal?", "hasil SPC/robust z per segmen", ("rm_outliers",),
         must=[r"segmen|SPC|batas|janggal"],
         truth=lambda e: [fact(e.rm_outliers("MBM"), "Kiriman ditandai janggal")]),
    Case("F7", "Kiriman PBPM mana yang kadar abunya di luar batas?", "outlier abu PBPM", ("rm_outliers",),
         must=[r"abu|ash"], truth=lambda e: [fact(e.rm_outliers("PBPM", "abu"), "Kiriman ditandai janggal")]),
    Case("F8", "Bahan baku apa saja yang ada data uji per kirimannya?", "4 bahan", ("list_materials",),
         must=[r"\bSBM\b", r"\bPBPM\b|Poultry By Product", r"\bMBM\b|Meat Bone Meal", r"\bFML C\b|Fish Meal"]),
    Case("F9", "Mana yang lebih fluktuatif protein-nya, SBM atau PBPM?", "bandingkan CV dua bahan", ("rm_summary",),
         truth=lambda e: [fact(e.rm_summary("SBM"), "CV"), fact(e.rm_summary("PBPM"), "CV")]),
    # ------------------------------------------------------------------ K: korelasi formula, NIR, performa
    Case("K1", "Apakah protein pakan lebih tinggi bikin FCR lebih bagus?",
         "korelasi tidak bisa dihitung (2 kode pakan), bukan sebab-akibat", ("corr_nutrient_fcr",),
         must=[r"tidak (dapat|bisa) dihitung|belum (bisa|dapat)|tidak cukup|bukan (bukti )?sebab"],
         must_not=[r"terbukti menyebabkan"], status_now="sebagian"),
    Case("K2", "Kadar air pakan berhubungan dengan FCR nggak?", "sama: data pasangan terlalu sedikit",
         ("corr_nutrient_fcr",), must=[r"tidak (dapat|bisa) dihitung|belum (bisa|dapat)|tidak cukup|sedikit"],
         must_not=[r"terbukti menyebabkan"], status_now="sebagian"),
    Case("K3", "Protein 788-3 di lapangan sesuai label nggak?", "spec label kosong, tidak bisa dinilai",
         ("feed_vs_label",), must=[r"spec|label", r"belum|tidak (bisa|dapat)|kosong|tidak tersedia"],
         truth=lambda e: [cell(e.feed_vs_label("788-3"), 0, "protein", 2)], status_now="sebagian"),
    Case("K4", "Produk CP Prima mana yang sering di bawah spec label?", "spec kosong, jujur", ("feed_vs_label",),
         must=[r"belum|tidak (bisa|dapat)|kosong|tidak tersedia"], status_now="sebagian"),
    Case("K5", "FCR rata-rata pakan 788-3 berapa?", "FCR 788-3 dari kolam satu merek", ("perf_summary",),
         truth=lambda e: [cell(e.perf_summary("788-3"), 0, "788-3", 4)]),
    Case("K6", "FCR produk kita dibanding pesaing gimana?", "own vs competitor, bukan sebab-akibat",
         ("perf_compare", "perf_summary"), must=[r"pesaing|competitor"],
         must_not=[r"terbukti (lebih baik|lebih bagus)"],
         truth=lambda e: [fact(e.perf_compare("own", "competitor"), "owner own: rata-rata fcr"),
                          fact(e.perf_compare("own", "competitor"), "owner competitor: rata-rata fcr")]),
    Case("K7", "Biaya pakan per kg ikan paling murah pakai produk apa?", "dari tabel perf_summary",
         ("perf_summary",), must=[r"sedikit|n\s*=|siklus|bukan (bukti )?sebab|faktor"]),
    Case("K8", "Pakan Nila hasil pabrik kurang protein berapa dibanding resepnya?",
         "belum bisa: butuh formula existing + Feed Daily", (), must=[r"belum", r"Feed Daily|NIR pabrik|formula"],
         status_now="belum"),
    Case("K9", "Formula dengan MBM lebih tinggi bikin FCR lebih bagus nggak?",
         "belum bisa: butuh formula existing + link lot pakan ke kolam", (), must=[r"belum", r"formula"],
         must_not=[r"terbukti"], status_now="belum"),
    Case("K10", "Line atau shift mana yang paling sering menyimpang dari resep?", "belum bisa: butuh Feed Daily", (),
         must=[r"belum", r"Feed Daily|line|shift"], status_now="belum"),
    Case("K11", "Safir Pro-2 kurang protein, apakah mixer pabrik kita perlu diaudit?",
         "tidak ada datanya; tidak boleh menyarankan audit tanpa data (kasus Hermes lama)", (),
         must=[r"tidak (ada|ditemukan|tersedia)|belum|tidak (bisa|dapat)"],
         must_not=[r"(perlu|harus|sebaiknya) segera (di)?audit"], status_now="belum"),
]


@dataclass
class Score:
    case: Case
    checks: List[tuple] = field(default_factory=list)   # (nama, ok, detail)
    answer: str = ""
    tools: str = ""
    attempts: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


async def evaluate(agent: HermesAgent, engine: StatEngine, case: Case) -> Score:
    t0 = time.time()
    res = await agent.run(case.question)
    sc = Score(case, answer=res.answer or f"(tidak ada jawaban: {res.error})", attempts=res.attempts,
               seconds=time.time() - t0)
    called = [c["tool"] for c in res.tool_calls]
    sc.tools = ", ".join(f"{c['tool']}({'ok' if c['ok'] else 'GAGAL'})" for c in res.tool_calls) or "-"
    v = res.validation
    sc.checks.append(("validator", res.ok, f"{v.numbers_checked if v else 0} angka dicek, percobaan {res.attempts}"
                      + ("" if res.ok else f"; {'; '.join((v.errors if v else [res.error])[:3])}")))
    if case.tools:
        hit = [t for t in case.tools if t in called]
        sc.checks.append(("tools", bool(hit), f"harap salah satu {list(case.tools)}, dipanggil {called or '-'}"))
    text = res.answer or ""
    for pat in case.must:
        sc.checks.append((f"must /{pat}/", bool(re.search(pat, text, re.I)), ""))
    for pat in case.must_not:
        sc.checks.append((f"must_not /{pat}/", not re.search(pat, text, re.I), ""))
    if case.truth:
        try:
            expected = case.truth(engine)
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            sc.checks.append(("truth", False, f"engine gagal: {exc}"))
        else:
            tokens = set(re.findall(r"\d+(?:[.,]\d+)*", text))
            # angka dicek sebagai token utuh ('2' tidak cocok dengan '2026'); tanggal dicek sebagai teks
            missing = [x for x in expected if (x not in text) if "-" in x] + \
                      [x for x in expected if "-" not in x and x not in tokens]
            sc.checks.append(("truth", not missing, f"angka engine {expected}" + (f", tidak ada: {missing}" if missing else "")))
    return sc


def report(scores: List[Score], model: str) -> str:
    lines = [f"# Evaluasi Hermes AFT · dua objective", "",
             f"Tanggal: {datetime.now():%Y-%m-%d %H:%M} · Model: {model} · Data: sampel `docs_revised` (10 baris/sheet)", "",
             "## Ringkasan", "", "| Objective | Kasus | Lolos | Bisa sekarang | Sebagian | Belum (butuh data) |",
             "|---|---|---|---|---|---|"]
    for key, name in OBJECTIVES.items():
        ss = [s for s in scores if s.case.id.startswith(key)]
        if not ss:
            continue
        cnt = {k: sum(1 for s in ss if s.case.status_now == k) for k in ("bisa", "sebagian", "belum")}
        lines.append(f"| {name} | {len(ss)} | {sum(s.ok for s in ss)}/{len(ss)} | {cnt['bisa']} | {cnt['sebagian']} | {cnt['belum']} |")
    lines += ["", "Kolom *Bisa/Sebagian/Belum* menunjukkan apakah pertanyaan itu bisa dijawab penuh dengan data yang ada "
              "sekarang. Kasus *belum* tetap dinilai: Hermes harus menolak dengan jujur dan menyebut data yang kurang.", "",
              "| ID | Pertanyaan | Status data | Hasil | Tools | Detik |", "|---|---|---|---|---|---|"]
    for s in scores:
        lines.append(f"| {s.case.id} | {s.case.question} | {s.case.status_now} | {'✅ LOLOS' if s.ok else '❌ GAGAL'} | "
                     f"{s.tools} | {s.seconds:.1f} |")
    for s in scores:
        lines += ["", f"## {s.case.id} · {s.case.question}", "",
                  f"- Objective: {OBJECTIVES[s.case.id[0]]}", f"- Harapan: {s.case.expect}",
                  f"- Hasil: **{'LOLOS' if s.ok else 'GAGAL'}** · tools: {s.tools} · {s.seconds:.1f} detik", "",
                  "| Cek | Hasil | Detail |", "|---|---|---|"]
        lines += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in s.checks]
        lines += ["", "**Jawaban Hermes:**", "", s.answer]
    passed = sum(s.ok for s in scores)
    lines += ["", "---", f"**Total lolos: {passed}/{len(scores)}**"]
    return "\n".join(lines)


async def main(selected: set) -> None:
    agent = HermesAgent()
    engine = StatEngine(load_snapshot(settings.AFT_DB_PATH))
    cases = [c for c in CASES if not selected or c.id in selected]
    scores = []
    for c in cases:
        sc = await evaluate(agent, engine, c)
        scores.append(sc)
        print(f"{c.id:4s} {'LOLOS' if sc.ok else 'GAGAL':5s} {sc.seconds:5.1f}s  {c.question}")
        for n, ok, d in sc.checks:
            if not ok:
                print(f"       ✗ {n}: {d}")
    model = " -> ".join(s.label for s in agent.specs)
    out = PROJECT_ROOT / "reports" / f"eval_objectives_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report(scores, model), encoding="utf-8")
    print(f"\nLOLOS: {sum(s.ok for s in scores)}/{len(scores)} · laporan: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", nargs="*", help="id kasus, mis. F4 K8")
    asyncio.run(main(set(ap.parse_args().c or [])))
