"""Deterministic statistics over the cleansed AFT data. No LLM, no database.

StatEngine computes on an in-memory DataSnapshot (built once by
db_clients/aft_repository.py with fixed read-only queries). This module never
opens a database, runs no SQL and does not import sqlite3: the agent tools that
call it can only compute. Every public method returns a Result: the numbers
(formatted as the card shows them), the method, n, period and the caveats.
Results are aggregates plus shipment identifiers (PO, truck/container); the
snapshot itself contains no farmer names.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

from agents_tools.snapshot import DataSnapshot


class ToolError(Exception):
    """A refused tool call; the message goes back to the model verbatim."""


@dataclass
class Result:
    tool: str
    subject: str
    method: str
    facts: List[Tuple[str, str]] = field(default_factory=list)
    tables: List[Tuple[str, List[str], List[List[str]]]] = field(default_factory=list)
    n: Optional[int] = None
    period: Optional[str] = None
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)       # aturan untuk model (kalimat)
    banned_phrases: List[str] = field(default_factory=list)  # frasa yang ditolak validator
    data: Dict[str, Any] = field(default_factory=dict)        # angka mentah untuk run log


# ---------------------------------------------------------------------- formatting
def fmt(x: Optional[float], d: int = 2) -> str:
    """Format angka gaya Indonesia: 11120.5 -> '11.120,50'."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    s = f"{x:,.{d}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_p(p: float) -> str:
    return "<0,0001" if p < 0.0001 else fmt(p, 4)


def norm_code(code: Optional[str]) -> Optional[str]:
    """Sama dengan cleansing: 'HDPIN B-3' -> 'HDPINB-3', '782-3.' -> '782-3'."""
    if code is None:
        return None
    return re.sub(r"\s+", "", str(code)).upper().rstrip(".")


def _period(dates: Sequence[Optional[str]]) -> Optional[str]:
    ds = sorted(d for d in dates if d)
    if not ds:
        return None
    return ds[0] if ds[0] == ds[-1] else f"{ds[0]} s/d {ds[-1]}"


# ---------------------------------------------------------------------- pure statistics
def mean_sd(values: Sequence[float]) -> Tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    sd = float(arr.std(ddof=1)) if len(arr) > 1 else float("nan")
    return float(arr.mean()), sd


def safe_value(mean: float, sd: float, k: float = 1.0) -> float:
    """Angka aman = rata-rata − k × SD."""
    return mean - k * sd


def breakeven_fcr_reduction(feed_price: float, extra_cost_per_kg: float) -> float:
    """Penurunan FCR minimum (fraksi) supaya biaya pakan per kg ikan tidak naik.

    biaya/kg ikan = harga × FCR, jadi FCR_baru/FCR_lama ≤ harga_lama/harga_baru.
    """
    return 1.0 - feed_price / (feed_price + extra_cost_per_kg)


def welch_p(a: Sequence[float], b: Sequence[float]) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.var() == 0 and b.var() == 0:
        return 0.0 if a.mean() != b.mean() else 1.0
    p = stats.ttest_ind(a, b, equal_var=False).pvalue
    return 1.0 if p is None or math.isnan(p) else float(p)


def find_level_shifts(values: Sequence[float], alpha: float = 0.01, min_segment: int = 3) -> List[int]:
    """Segmentasi biner: indeks awal setiap segmen baru (rata-rata berbeda nyata, uji Welch)."""
    vals = list(values)
    cuts: List[int] = []

    def split(lo: int, hi: int) -> None:
        if hi - lo < 2 * min_segment:
            return
        best = None
        for k in range(lo + min_segment, hi - min_segment + 1):
            p = welch_p(vals[lo:k], vals[k:hi])
            if best is None or p < best[1]:
                best = (k, p)
        if best and best[1] < alpha:
            cuts.append(best[0])
            split(lo, best[0])
            split(best[0], hi)

    split(0, len(vals))
    return sorted(cuts)


def segments_of(n: int, cuts: Sequence[int]) -> List[Tuple[int, int]]:
    bounds = [0, *cuts, n]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def imr_limits(values: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """Peta individu I-MR: (center, LCL, UCL) dengan σ = MR̄ / 1,128."""
    if len(values) < 3:
        return None
    arr = np.asarray(values, float)
    sigma = float(np.mean(np.abs(np.diff(arr)))) / 1.128
    c = float(arr.mean())
    return c, c - 3 * sigma, c + 3 * sigma


def robust_z(values: Sequence[float]) -> List[float]:
    arr = np.asarray(values, float)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    if mad == 0:
        return [0.0] * len(arr)
    return [0.6745 * (x - med) / mad for x in arr]


# ---------------------------------------------------------------------- dictionaries
PARAM_ALIASES = {
    "crude_protein": ["protein", "cp", "protein kasar", "crude protein"],
    "moisture": ["air", "kadar air", "m", "moisture", "kelembaban"],
    "fat": ["lemak", "fat"],
    "fiber": ["serat", "serat kasar", "fiber"],
    "ash": ["abu", "ash"],
    "calcium": ["ca", "kalsium", "calcium"],
    "phosphorus": ["p", "fosfor", "phosphor", "phosphorus"],
    "pepsin_digest": ["pd", "pepsin", "pepsin digest", "kecernaan pepsin"],
    "koh_digest": ["koh", "koh digest"],
    "pdi": ["pdi"],
    "mbm_index": ["index", "mbm index", "index mbm"],
    "tvbn": ["tvbn"],
}
PARAM_UNIT = {"tvbn": "mg/100 g", "mbm_index": "", "pdi": ""}
MATERIAL_ALIASES = {
    "tepung ikan": "fish meal", "fishmeal": "fish meal", "bungkil kedelai": "sbm", "kedelai": "sbm",
    "soybean": "sbm", "tepung daging": "meat bone", "daging tulang": "meat bone", "ayam": "poultry",
}
OWNER_ALIASES = {
    "own": "own", "kita": "own", "sendiri": "own", "cp prima": "own", "cpb": "own", "cpp": "own",
    "competitor": "competitor", "pesaing": "competitor", "kompetitor": "competitor",
}
# nutrien sampel lapangan: alias -> (kolom NIR, kolom spec min, kolom spec max)
FIELD_NUTRIENTS = {
    "moisture": ("moisture_nir", "spec_moisture_min", "spec_moisture_max"),
    "protein": ("protein_nir", "spec_protein_min", "spec_protein_max"),
    "fat": ("fat_nir", "spec_fat_min", "spec_fat_max"),
    "fiber": ("fiber_nir", "spec_fiber_min", "spec_fiber_max"),
    "ash": ("ash_nir", "spec_ash_min", "spec_ash_max"),
    "calcium": ("calcium_nir", "spec_calcium_min", "spec_calcium_max"),
    "phosphor": ("phosphor_nir", "spec_phosphor_min", "spec_phosphor_max"),
}
FIELD_NUTRIENT_ALIASES = {
    "air": "moisture", "kadar air": "moisture", "protein": "protein", "cp": "protein", "lemak": "fat",
    "serat": "fiber", "abu": "ash", "kalsium": "calcium", "ca": "calcium", "fosfor": "phosphor",
    "p": "phosphor", "phosphorus": "phosphor",
}
GLOBAL_BANNED = ["siap produksi", "dijamin"]

# Label sumber di kartu: deskriptif, tanpa nama tabel/skema database
SRC_RM = "uji kiriman bahan baku (lolos cleansing)"
SRC_STOCK = "laporan stok mingguan WPA"
SRC_FIELD = "sampel pakan lapangan (NIR)"
SRC_POND = "siklus kolam satu merek"


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def resolve_parameter(query: str, available: Sequence[str]) -> str:
    q = _key(query).replace("_", " ")
    for code, aliases in PARAM_ALIASES.items():
        if q in (code.replace("_", " "), *aliases):
            if code not in available:
                raise ToolError(f"parameter {code} tidak ada untuk bahan ini. Tersedia: {', '.join(sorted(available))}")
            return code
    raise ToolError(f"parameter '{query}' tidak dikenal. Tersedia: {', '.join(sorted(available))}")


def resolve_owner(query: Optional[str]) -> Optional[str]:
    if query is None or not str(query).strip():
        return None
    q = _key(query)
    if q not in OWNER_ALIASES:
        raise ToolError(f"owner '{query}' tidak dikenal. Pakai 'own' (produk CP Prima) atau 'competitor'.")
    return OWNER_ALIASES[q]


# ---------------------------------------------------------------------- engine
def _by_key(rows: Sequence[dict], *keys: str) -> Dict[tuple, List[dict]]:
    out: Dict[tuple, List[dict]] = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


class StatEngine:
    """Pure computation over a DataSnapshot. Holds no database handle and runs no SQL."""

    def __init__(self, snapshot: DataSnapshot, *, min_n: int = 10, alpha: float = 0.01, min_segment: int = 3):
        self.data = snapshot
        self.min_n = min_n
        self.alpha = alpha
        self.min_segment = min_segment

    def fingerprint(self) -> str:
        """Sidik data: hash dari sha256 semua file sumber yang di-ingest."""
        return self.data.fingerprint

    def _small_n(self, n: int, what: str) -> List[str]:
        if n < self.min_n:
            return [f"Data sedikit: hanya {n} {what} (< {self.min_n}). Angka belum stabil untuk keputusan."]
        return []

    # ------------------------------------------------------------ bahan baku
    def _materials(self) -> List[dict]:
        mats = []
        for (sheet, sap, name), rs in sorted(_by_key(self.data.rm_tests, "sheet_name", "sap_code", "material_name").items(),
                                             key=lambda kv: kv[0][0]):
            dates = [r["receive_date"] for r in rs if r["receive_date"]]
            mats.append({"sheet_name": sheet, "sap_code": sap, "material_name": name,
                         "n": len({r["receipt_id"] for r in rs}),
                         "d0": min(dates) if dates else None, "d1": max(dates) if dates else None,
                         "params": sorted({r["parameter_code"] for r in rs})})
        return mats

    def resolve_material(self, query: str) -> dict:
        mats = self._materials()
        q = _key(query)
        q = MATERIAL_ALIASES.get(q, q)
        exact = [m for m in mats if q in (_key(m["sheet_name"]), str(m["sap_code"]), _key(m["material_name"]))]
        hits = exact or [m for m in mats if q in _key(m["material_name"]) or q in _key(m["sheet_name"])]
        choices = "; ".join(f"{m['sheet_name']} ({m['material_name']})" for m in mats)
        if not hits:
            raise ToolError(f"bahan '{query}' tidak ditemukan. Pilihan: {choices}")
        if len(hits) > 1:
            raise ToolError(f"bahan '{query}' ambigu: {'; '.join(m['sheet_name'] for m in hits)}. Pilihan: {choices}")
        return hits[0]

    def _material_series(self, material: str, parameter: str):
        mat = self.resolve_material(material)
        param = resolve_parameter(parameter, mat["params"])
        rows = sorted((r for r in self.data.rm_tests
                       if r["sheet_name"] == mat["sheet_name"] and r["parameter_code"] == param),
                      key=lambda r: (r["receive_date"] or "", r["source_row"]))
        if not rows:
            raise ToolError(f"tidak ada data {param} untuk {mat['sheet_name']}")
        sap = f"SAP {mat['sap_code']}" if mat["sap_code"] is not None else "kode SAP belum dikonfirmasi"
        subject = f"{mat['sheet_name']} ({mat['material_name']}, {sap}) · {param}"
        warnings = [] if mat["sap_code"] is not None else [
            "Kode SAP bahan ini belum dikonfirmasi (lihat mapping material_alias.csv)."]
        return mat, param, rows, subject, warnings

    def _unit(self, param: str) -> str:
        u = PARAM_UNIT.get(param, "%")
        return f" {u}" if u else ""

    def list_materials(self) -> Result:
        mats = self._materials()
        rows = [[m["sheet_name"], m["material_name"], str(m["sap_code"] or "belum dikonfirmasi"), str(m["n"]),
                 _period([m["d0"], m["d1"]]) or "-", ", ".join(m["params"])] for m in mats]
        return Result(
            tool="list_materials", subject="daftar bahan baku di data kiriman",
            method="Daftar bahan dari data uji kiriman yang lolos cleansing.",
            tables=[("Bahan", ["Sheet", "Nama", "Kode SAP", "n kiriman", "Periode", "Parameter"], rows)],
            n=sum(m["n"] for m in mats), source=SRC_RM, data={"materials": mats})

    def rm_summary(self, material: str, parameter: str = "crude_protein") -> Result:
        mat, param, rows, subject, warnings = self._material_series(material, parameter)
        vals = [r["value"] for r in rows]
        mean, sd = mean_sd(vals)
        u = self._unit(param)
        cv = sd / mean * 100 if mean and not math.isnan(sd) else float("nan")
        facts = [("n kiriman", str(len(vals))), ("Periode", _period([r["receive_date"] for r in rows]) or "-"),
                 ("Rata-rata", fmt(mean) + u), ("SD", fmt(sd) + u), ("CV", fmt(cv) + " %"),
                 ("Minimum", fmt(min(vals)) + u), ("Maksimum", fmt(max(vals)) + u)]
        tables = []
        blocks = sorted({r["block_no"] for r in rows})
        if len(blocks) > 1:
            trows = []
            for b in blocks:
                sub = [r for r in rows if r["block_no"] == b]
                bm, _ = mean_sd([r["value"] for r in sub])
                trows.append([str(b), str(len(sub)), _period([r["receive_date"] for r in sub]),
                              fmt(bm) + u, fmt(min(r["value"] for r in sub)) + u, fmt(max(r["value"] for r in sub)) + u])
            tables.append(("Per blok data di Excel (dipisah baris kosong)",
                           ["Blok", "n", "Periode", "Rata-rata", "Min", "Maks"], trows))
            warnings.append("Data terdiri dari beberapa blok dengan periode berbeda; cek pergeseran level (rm_level_shift) "
                            "sebelum memakai rata-rata gabungan.")
        warnings += self._small_n(len(vals), "kiriman")
        return Result(
            tool="rm_summary", subject=subject,
            method="Statistik deskriptif per kiriman: rata-rata, SD sampel (n−1), CV = SD/rata-rata × 100.",
            facts=facts, tables=tables, n=len(vals), period=facts[1][1], source=SRC_RM,
            warnings=warnings, forbidden=["memakai rata-rata gabungan sebagai angka formula tanpa cek pergeseran level"],
            data={"values": vals, "mean": mean, "sd": sd, "cv": cv})

    def _segments(self, vals):
        cuts = find_level_shifts(vals, self.alpha, self.min_segment)
        return cuts, segments_of(len(vals), cuts)

    def rm_level_shift(self, material: str, parameter: str = "crude_protein") -> Result:
        mat, param, rows, subject, warnings = self._material_series(material, parameter)
        vals = [r["value"] for r in rows]
        cuts, segs = self._segments(vals)
        u = self._unit(param)
        trows, seg_data = [], []
        for i, (a, b) in enumerate(segs, 1):
            m, s = mean_sd(vals[a:b])
            per = _period([r["receive_date"] for r in rows[a:b]])
            trows.append([str(i), str(b - a), per, fmt(m) + u, fmt(s) + u])
            seg_data.append({"start": a, "end": b, "mean": m, "sd": s, "period": per})
        facts = [("n kiriman", str(len(vals))), ("Periode", _period([r["receive_date"] for r in rows]) or "-"),
                 ("Jumlah pergeseran level", str(len(cuts)))]
        for c in cuts:
            left = next(s for s in seg_data if s["end"] == c)
            right = next(s for s in seg_data if s["start"] == c)
            p = welch_p(vals[left["start"]:c], vals[c:right["end"]])
            facts += [("Pergeseran mulai kiriman tanggal", rows[c]["receive_date"]),
                      ("Selisih rata-rata (sesudah − sebelum)", fmt(right["mean"] - left["mean"]) + u),
                      ("p-value uji Welch", fmt_p(p))]
        if len(vals) < 2 * self.min_segment:
            warnings.append(f"Kurang dari {2 * self.min_segment} kiriman: pergeseran level tidak bisa diuji.")
        warnings += self._small_n(len(vals), "kiriman")
        return Result(
            tool="rm_level_shift", subject=subject,
            method=(f"Segmentasi biner: setiap titik potong diuji dengan uji t Welch; potongan diterima kalau "
                    f"p < {fmt(self.alpha)} dan tiap segmen minimal {self.min_segment} kiriman. Data diurutkan menurut tanggal terima."),
            facts=facts, tables=[("Segmen", ["Segmen", "n", "Periode", "Rata-rata", "SD"], trows)],
            n=len(vals), period=facts[1][1], source=SRC_RM, warnings=warnings,
            forbidden=["menyebut penyebab pergeseran (supplier/grade) tanpa konfirmasi QC"],
            data={"cuts": cuts, "segments": seg_data})

    def rm_safe_value(self, material: str, parameter: str = "crude_protein", k: float = 1.0) -> Result:
        mat, param, rows, subject, warnings = self._material_series(material, parameter)
        if k <= 0 or k > 4:
            raise ToolError("k harus di antara 0 dan 4 (contoh: 1 = rata-rata − 1 SD)")
        vals = [r["value"] for r in rows]
        cuts, segs = self._segments(vals)
        a, b = segs[-1]
        win = vals[a:b]
        if len(win) < 2:
            raise ToolError(f"jendela data terbaru hanya {len(win)} kiriman; angka aman butuh minimal 2")
        m, s = mean_sd(win)
        safe = safe_value(m, s, k)
        m_all, s_all = mean_sd(vals)
        safe_all = safe_value(m_all, s_all, k)
        u = self._unit(param)
        per = _period([r["receive_date"] for r in rows[a:b]])
        facts = [("k (jumlah SD)", fmt(k, 1)),
                 ("Jendela data terbaru: n kiriman", str(len(win))), ("Jendela data terbaru: periode", per),
                 ("Rata-rata jendela", fmt(m) + u), ("SD jendela", fmt(s) + u),
                 ("Angka aman (rata-rata − k×SD)", fmt(safe) + u),
                 ("Pembanding: angka aman dari semua data", fmt(safe_all) + u),
                 ("Pembanding: n semua data", str(len(vals)))]
        if cuts:
            warnings.append(f"Ada {len(cuts)} pergeseran level; angka aman dihitung dari jendela terbaru saja. "
                            "Angka dari semua data mencampur kualitas lama dan baru.")
        warnings += self._small_n(len(win), "kiriman di jendela terbaru")
        return Result(
            tool="rm_safe_value", subject=subject,
            method=(f"Angka aman = rata-rata − k × SD (SD sampel n−1) dari jendela data terbaru, yaitu kiriman "
                    f"setelah pergeseran level terakhir (uji Welch, p < {fmt(self.alpha)})."),
            facts=facts, n=len(win), period=per, source=SRC_RM, warnings=warnings,
            forbidden=["menyebut angka aman sebagai spec final tanpa persetujuan nutritionist",
                       "menghitung ulang angka aman dengan k lain tanpa memanggil tool"],
            data={"k": k, "window": [a, b], "mean": m, "sd": s, "safe": safe, "safe_all": safe_all})

    def rm_outliers(self, material: str, parameter: str = "crude_protein") -> Result:
        mat, param, rows, subject, warnings = self._material_series(material, parameter)
        vals = [r["value"] for r in rows]
        cuts, segs = self._segments(vals)
        u = self._unit(param)
        flagged, limits = [], []
        for i, (a, b) in enumerate(segs, 1):
            seg = vals[a:b]
            lim = imr_limits(seg)
            if lim is None:
                warnings.append(f"Segmen {i} hanya {len(seg)} kiriman; batas SPC tidak dihitung.")
                continue
            c, lcl, ucl = lim
            limits.append([str(i), str(len(seg)), fmt(c) + u, fmt(lcl) + u, fmt(ucl) + u])
            for j, (x, z) in enumerate(zip(seg, robust_z(seg))):
                why = []
                if x < lcl or x > ucl:
                    why.append("di luar batas SPC")
                if abs(z) > 3.5:
                    why.append(f"robust z {fmt(z)}")
                if why:
                    r = rows[a + j]
                    flagged.append([r["receive_date"], str(r["po_no"] or "-"), str(r["transport_no"] or "-"),
                                    fmt(x) + u, str(i), "; ".join(why)])
        facts = [("n kiriman dicek", str(len(vals))), ("Periode", _period([r["receive_date"] for r in rows]) or "-"),
                 ("Jumlah segmen level", str(len(segs))), ("Kiriman ditandai janggal", str(len(flagged)))]
        tables = [("Batas SPC per segmen", ["Segmen", "n", "Garis tengah", "Batas bawah", "Batas atas"], limits)]
        if flagged:
            tables.append(("Kiriman janggal", ["Tanggal", "PO", "Truk/Kontainer", "Nilai", "Segmen", "Alasan"], flagged))
        warnings += self._small_n(len(vals), "kiriman")
        return Result(
            tool="rm_outliers", subject=subject,
            method=("Per segmen level: peta SPC individu I-MR (batas = rata-rata ± 3σ, σ = rata-rata moving range / 1,128) "
                    "dan robust z berbasis median/MAD (|z| > 3,5)."),
            facts=facts, tables=tables, n=len(vals), period=facts[1][1], source=SRC_RM, warnings=warnings,
            forbidden=["menyatakan kiriman ditandai pasti salah atau harus ditolak; keputusan ada di QC"],
            data={"flagged": flagged, "limits": limits})

    def rm_stock(self, material: str) -> Result:
        lots_all = self.data.stock_lots
        sap = None
        try:
            sap = self.resolve_material(material)["sap_code"]
        except ToolError:
            pass
        q = _key(material)
        lots = ([l for l in lots_all if l["sap_code"] == sap] if sap is not None
                else [l for l in lots_all if q in _key(l["material_name"] or "")])
        names = sorted({l["material_name"] for l in lots_all if l["material_name"]})
        if not lots:
            raise ToolError(f"bahan '{material}' tidak ada di laporan stok WPA. Ada: {'; '.join(names)}")
        if len({l["material_name"] for l in lots}) > 1:
            raise ToolError(f"'{material}' cocok ke beberapa bahan stok: {'; '.join(sorted({l['material_name'] for l in lots}))}")
        total = sum(l["stock_ton"] or 0 for l in lots)
        usage = [l["usage_ton_per_day"] for l in lots if l["usage_ton_per_day"] is not None]
        doh_xl = [l["doh_days"] for l in lots if l["doh_days"] is not None]
        facts = [("Plant", lots[0]["plant"] or "-"), ("Tanggal stok", lots[0]["stock_date"] or "-"),
                 ("Jumlah lot di laporan", str(len(lots))), ("Total stok", fmt(total) + " ton")]
        warnings = []
        doh_calc = None
        if usage:
            doh_calc = total / usage[0]
            facts += [("Pemakaian per hari", fmt(usage[0], 4) + " ton/hari"),
                      ("DOH hitung ulang (total stok ÷ pemakaian)", fmt(doh_calc, 1) + " hari")]
        else:
            warnings.append("Pemakaian per hari kosong; DOH tidak bisa dihitung.")
        if doh_xl:
            facts.append(("DOH tercatat di Excel", fmt(doh_xl[0], 1) + " hari"))
            if doh_calc is not None and abs(doh_calc - doh_xl[0]) > 0.01 * doh_xl[0]:
                warnings.append("DOH hitung ulang berbeda dengan DOH di Excel. Rumus DOH di Excel bisa mencakup baris lot "
                                "yang tidak ada di data ini (mis. data contoh yang terpotong). Konfirmasi ke pembuat laporan.")
        return Result(
            tool="rm_stock", subject=f"{lots[0]['material_name']} (SAP {lots[0]['sap_code']}) · stok",
            method="Total stok = jumlah stok semua lot bahan ini di WPA REPORT; DOH = total stok ÷ pemakaian per hari.",
            facts=facts, n=len(lots), period=lots[0]["stock_date"], source=SRC_STOCK, warnings=warnings,
            data={"total": total, "usage": usage, "doh_calc": doh_calc, "doh_excel": doh_xl})

    # ------------------------------------------------------------ pakan lapangan
    def feed_vs_label(self, feed_code: Optional[str] = None, owner: Optional[str] = None) -> Result:
        owner_g = resolve_owner(owner)
        code = norm_code(feed_code) if feed_code else None
        rows = [r for r in self.data.field_samples if not r["is_mixed_code"]
                and (code is None or r["feed_code_norm"] == code) and (owner_g is None or r["owner_group"] == owner_g)]
        if not rows:
            codes = sorted({r["feed_code_norm"] for r in self.data.field_samples if r["feed_code_norm"]})
            raise ToolError(f"tidak ada sampel lapangan untuk filter ini. Kode tersedia: {', '.join(codes)}")
        trows, any_spec = [], False
        for name, (col, smin, smax) in FIELD_NUTRIENTS.items():
            vals = [r[col] for r in rows if r[col] is not None]
            if not vals:
                continue
            with_spec = [r for r in rows if r[col] is not None and (r[smin] is not None or r[smax] is not None)]
            any_spec |= bool(with_spec)
            below = sum(1 for r in with_spec if r[smin] is not None and r[col] < r[smin])
            above = sum(1 for r in with_spec if r[smax] is not None and r[col] > r[smax])
            m, _ = mean_sd(vals)
            trows.append([name, str(len(vals)), fmt(m) + " %", str(len(with_spec)), str(below), str(above)])
        owners = sorted({f"{r['produced_by']} ({r['owner_group']})" for r in rows})
        facts = [("n sampel", str(len(rows))), ("Periode kirim sampel", _period([r["date_sent"] for r in rows]) or "-"),
                 ("Produsen (owner)", "; ".join(owners)),
                 ("Kode pakan", ", ".join(sorted({r["feed_code_norm"] for r in rows if r["feed_code_norm"]})))]
        warnings = []
        if not any_spec:
            warnings.append("Kolom spec label (min/max) kosong untuk semua sampel ini: kesesuaian dengan label TIDAK BISA dinilai.")
        if any(r["owner_group"] == "competitor" for r in rows):
            warnings.append("Sebagian sampel adalah produk pesaing.")
        warnings += self._small_n(len(rows), "sampel")
        return Result(
            tool="feed_vs_label", subject=f"sampel pakan lapangan · kode {code or 'semua'} · owner {owner_g or 'semua'}",
            method="NIR sampel lapangan dibandingkan spec label per sampel: dihitung jumlah sampel di bawah min dan di atas max.",
            facts=facts, tables=[("Per nutrien", ["Nutrien", "n NIR", "Rata-rata NIR", "n punya spec", "Di bawah min", "Di atas max"], trows)],
            n=len(rows), period=facts[1][1], source=SRC_FIELD, warnings=warnings,
            forbidden=["menyarankan audit lini produksi CP Prima untuk produk pesaing",
                       "menyimpulkan sesuai/tidak sesuai label kalau spec label kosong"],
            data={"rows": trows, "any_spec": any_spec})

    # ------------------------------------------------------------ performa kolam
    def _pond(self, code=None, owner=None, species=None) -> List[dict]:
        sp = _key(species) if species else None
        return [r for r in self.data.pond_cycles if not r["is_mixed_brand"]
                and (code is None or r["brand_norm"] == code) and (owner is None or r["owner_group"] == owner)
                and (sp is None or _key(r["fish_species"] or "") == sp)]

    def perf_summary(self, feed_code: Optional[str] = None, owner: Optional[str] = None,
                     species: Optional[str] = None) -> Result:
        owner_g, code = resolve_owner(owner), norm_code(feed_code) if feed_code else None
        rows = self._pond(code, owner_g, species)
        mixed = sum(1 for r in self.data.pond_cycles if r["is_mixed_brand"])
        if not rows:
            codes = sorted({r["brand_norm"] for r in self.data.pond_cycles if not r["is_mixed_brand"] and r["brand_norm"]})
            raise ToolError(f"tidak ada data kolam untuk filter ini. Kode pakan (non-campuran): {', '.join(codes)}")
        trows = []
        for (b, comp, og), rs in sorted(_by_key(rows, "brand_norm", "company", "owner_group").items()):
            def avg(col):
                v = [x[col] for x in rs if x[col] is not None]
                return fmt(mean_sd(v)[0]) if v else "-"
            trows.append([b, comp, og, str(len(rs)), avg("fcr"), avg("sr_pct"), avg("adg_g_per_day"),
                          avg("feed_cost_rp_per_kg_fish")])
        fcr_bad = sum(1 for r in rows if r["fcr_check"] != "ok")
        facts = [("n siklus kolam", str(len(rows))), ("Periode panen", _period([r["harvest_date"] for r in rows]) or "-"),
                 ("Siklus pakan campuran dikeluarkan", str(mixed)), ("FCR yang tidak cocok saat dihitung ulang", str(fcr_bad))]
        warnings = self._small_n(len(rows), "siklus kolam")
        warnings.append("Performa kolam juga dipengaruhi benih, padat tebar, dan manajemen petambak; perbedaan antar produk bukan bukti sebab-akibat.")
        return Result(
            tool="perf_summary",
            subject=f"performa kolam · kode {code or 'semua'} · owner {owner_g or 'semua'} · ikan {species or 'semua'}",
            method="Rata-rata per kode pakan dari siklus kolam yang memakai satu merek saja (pakan campuran dikeluarkan). FCR, SR, ADG, feed cost sesuai Excel.",
            facts=facts, tables=[("Per kode pakan", ["Kode", "Company", "Owner", "n", "FCR", "SR %", "ADG g/hari", "Feed cost Rp/kg ikan"], trows)],
            n=len(rows), period=facts[1][1], source=SRC_POND, warnings=warnings,
            forbidden=["menyimpulkan produk A lebih baik dari B hanya dari rata-rata dengan n kecil",
                       "menyarankan audit lini produksi CP Prima untuk produk pesaing"],
            data={"rows": trows})

    def _group(self, spec: str):
        og = OWNER_ALIASES.get(_key(spec))
        if og:
            return f"owner {og}", self._pond(owner=og)
        code = norm_code(spec)
        return f"kode {code}", self._pond(code=code)

    def perf_compare(self, group_a: str, group_b: str, metric: str = "fcr") -> Result:
        cols = {"fcr": "fcr", "sr": "sr_pct", "adg": "adg_g_per_day", "feed_cost": "feed_cost_rp_per_kg_fish"}
        if metric not in cols:
            raise ToolError(f"metric harus salah satu: {', '.join(cols)}")
        col = cols[metric]
        (la, ra), (lb, rb) = self._group(group_a), self._group(group_b)
        va = [r[col] for r in ra if r[col] is not None]
        vb = [r[col] for r in rb if r[col] is not None]
        if not va or not vb:
            raise ToolError(f"data kosong untuk {la if not va else lb} (pakan campuran tidak dihitung)")
        ma, _ = mean_sd(va)
        mb, _ = mean_sd(vb)
        facts = [(f"{la}: n siklus", str(len(va))), (f"{la}: rata-rata {metric}", fmt(ma)),
                 (f"{lb}: n siklus", str(len(vb))), (f"{lb}: rata-rata {metric}", fmt(mb)),
                 ("Selisih (A − B)", fmt(ma - mb))]
        warnings = []
        if len(va) >= 3 and len(vb) >= 3:
            facts.append(("p-value uji Welch", fmt_p(welch_p(va, vb))))
        else:
            warnings.append("n < 3 di salah satu grup: uji beda tidak dilakukan, hanya deskriptif.")
        warnings += self._small_n(min(len(va), len(vb)), "siklus di grup terkecil")
        warnings.append("Perbedaan bisa disebabkan faktor lain (benih, padat tebar, manajemen); bukan bukti sebab-akibat.")
        return Result(
            tool="perf_compare", subject=f"{la} vs {lb} · {metric}",
            method="Rata-rata metrik per grup dari siklus kolam satu merek; uji t Welch kalau tiap grup n ≥ 3.",
            facts=facts, n=len(va) + len(vb), period=_period([r["harvest_date"] for r in [*ra, *rb]]),
            source=SRC_POND, warnings=warnings,
            forbidden=["menyatakan satu produk terbukti lebih baik tanpa uji beda yang nyata"],
            data={"a": va, "b": vb})

    def corr_nutrient_fcr(self, nutrient: str = "protein") -> Result:
        key = FIELD_NUTRIENT_ALIASES.get(_key(nutrient), _key(nutrient))
        if key not in FIELD_NUTRIENTS:
            raise ToolError(f"nutrien '{nutrient}' tidak dikenal. Pilihan: {', '.join(FIELD_NUTRIENTS)}")
        col = FIELD_NUTRIENTS[key][0]
        nir = {code[0]: [r[col] for r in rs] for code, rs in _by_key(
            [r for r in self.data.field_samples if not r["is_mixed_code"] and r[col] is not None], "feed_code_norm").items()}
        fcr = {code[0]: [r["fcr"] for r in rs] for code, rs in _by_key(
            [r for r in self.data.pond_cycles if not r["is_mixed_brand"] and r["fcr"] is not None], "brand_norm").items()}
        pairs = [(c, mean_sd(nir[c])[0], len(nir[c]), mean_sd(fcr[c])[0], len(fcr[c])) for c in sorted(nir) if c in fcr]
        trows = [[c, fmt(x) + " %", str(nx), fmt(y), str(ny)] for c, x, nx, y, ny in pairs]
        facts = [("Kode pakan dengan data NIR dan FCR", str(len(pairs))),
                 ("Kode pakan dengan data NIR", str(len(nir))), ("Kode pakan dengan data FCR", str(len(fcr)))]
        warnings = ["Korelasi di level kode pakan (bukan per lot), dari data observasi lapangan: BUKAN bukti sebab-akibat."]
        if len(pairs) >= 3:
            r, p = stats.pearsonr([x for _, x, _, _, _ in pairs], [y for _, _, _, y, _ in pairs])
            facts += [("Korelasi Pearson r", fmt(float(r))), ("p-value", fmt_p(float(p)))]
            if len(pairs) < 10:
                warnings.append(f"Hanya {len(pairs)} kode pakan: korelasi sangat tidak stabil.")
        else:
            warnings.append(f"Hanya {len(pairs)} kode pakan punya data NIR dan FCR: korelasi tidak bisa dihitung (butuh minimal 3).")
        return Result(
            tool="corr_nutrient_fcr", subject=f"korelasi {key} (NIR lapangan) vs FCR",
            method="Rata-rata NIR per kode pakan (sampel lapangan) dipasangkan dengan rata-rata FCR per kode pakan (kolam satu merek); Pearson r.",
            facts=facts, tables=[("Pasangan per kode pakan", ["Kode", f"Rata-rata {key} NIR", "n sampel", "Rata-rata FCR", "n kolam"], trows)],
            n=len(pairs), source=f"{SRC_FIELD} + {SRC_POND}", warnings=warnings,
            forbidden=["menyebut nutrien ini menyebabkan FCR naik/turun"],
            banned_phrases=["terbukti menyebabkan"], data={"pairs": pairs})

    # ------------------------------------------------------------ ekonomi
    def feed_cost_breakeven(self, feed_price_rp_per_kg: float, additive_price_rp_per_kg: float,
                            dose_kg_per_ton: float, base_fcr: Optional[float] = None) -> Result:
        if min(feed_price_rp_per_kg, additive_price_rp_per_kg, dose_kg_per_ton) <= 0:
            raise ToolError("harga pakan, harga aditif, dan dosis harus > 0")
        extra = additive_price_rp_per_kg * dose_kg_per_ton / 1000.0
        new_price = feed_price_rp_per_kg + extra
        red = breakeven_fcr_reduction(feed_price_rp_per_kg, extra)
        facts = [("Harga pakan awal", fmt(feed_price_rp_per_kg, 0) + " Rp/kg"),
                 ("Harga aditif", fmt(additive_price_rp_per_kg, 0) + " Rp/kg"),
                 ("Dosis aditif", fmt(dose_kg_per_ton) + " kg/ton"),
                 ("Tambahan biaya pakan", fmt(extra) + " Rp/kg"),
                 ("Harga pakan dengan aditif", fmt(new_price) + " Rp/kg"),
                 ("Penurunan FCR minimum supaya impas", fmt(red * 100) + " %")]
        if base_fcr:
            facts += [("FCR awal", fmt(base_fcr, 3)), ("FCR maksimum dengan aditif", fmt(base_fcr * (1 - red), 3)),
                      ("Penurunan FCR minimum (poin)", fmt(base_fcr * red, 3))]
        return Result(
            tool="feed_cost_breakeven", subject="titik impas aditif pakan",
            method=("Biaya pakan per kg ikan = harga pakan × FCR. Impas kalau FCR_baru/FCR_lama ≤ harga_lama/harga_baru, "
                    "jadi penurunan FCR minimum = 1 − harga_lama/harga_baru (bukan kenaikan harga ÷ harga lama)."),
            facts=facts, source="input user", warnings=["Hanya menghitung titik impas; efek aditif ke FCR harus dibuktikan lewat trial kolam."],
            forbidden=["menyatakan aditif pasti menurunkan FCR"],
            data={"extra": extra, "new_price": new_price, "reduction": red})
