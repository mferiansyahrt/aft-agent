"""agno Toolkit over StatEngine — what the Hermes model actually calls.

Docstrings are the tool descriptions the model reads (Indonesian, like the
prompts). Every successful call is logged as a run and returned as a card; a
refused call comes back as "GAGAL: ..." text, never as an exception, so the
model can correct itself.

Data security: these tools only COMPUTE. They hold an engine over an in-memory
snapshot and never open a database, read files or write logs (the agent stores
the audit trail after the model has finished). The registered set is checked
against ALLOWED_TOOLS at construction, text arguments are limited to short
names/codes that only select keys in the snapshot, and results are aggregates.
"""
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from loguru import logger

from agents_tools.cards import Card, CardStore, render
from agents_tools.stat_engine import Result, StatEngine, ToolError

ALLOWED_TOOLS = (
    "list_materials", "rm_summary", "rm_level_shift", "rm_safe_value", "rm_outliers", "rm_stock",
    "feed_vs_label", "perf_summary", "perf_compare", "corr_nutrient_fcr", "feed_cost_breakeven",
)
_ARG_TEXT = re.compile(r"^[\w\s.,()+&/-]{1,60}$")


def _check_args(params: Dict[str, Any]) -> None:
    """Text arguments are names/codes only (e.g. 'MBM', '788-3', 'fish meal')."""
    for key, value in params.items():
        if isinstance(value, str) and value and not _ARG_TEXT.match(value):
            raise ToolError(f"argumen {key} tidak valid: hanya nama/kode pendek (huruf, angka, spasi, . , - / ( ) + &)")


class AftStatTools(Toolkit):

    def __init__(self, engine: StatEngine, store: CardStore, **kwargs):
        self.engine = engine
        self.store = store
        self.fingerprint = engine.fingerprint()
        self.calls: List[Dict[str, Any]] = []
        super().__init__(name="aft_stat_tools", tools=[
            self.list_materials, self.rm_summary, self.rm_level_shift, self.rm_safe_value, self.rm_outliers,
            self.rm_stock, self.feed_vs_label, self.perf_summary, self.perf_compare, self.corr_nutrient_fcr,
            self.feed_cost_breakeven,
        ], **kwargs)
        if set(self.functions) != set(ALLOWED_TOOLS):
            raise RuntimeError(f"tool di luar whitelist: {sorted(set(self.functions) ^ set(ALLOWED_TOOLS))}")

    def _call(self, name: str, params: Dict[str, Any], fn: Callable[[], Result]) -> str:
        try:
            _check_args(params)
            res = fn()
        except ToolError as exc:
            out, ok = f"GAGAL: {exc}", False
        except Exception as exc:  # noqa: BLE001 - a tool bug must not end the session
            logger.exception(f"[aft_stat_tools] {name} crashed")
            out, ok = f"GAGAL: kesalahan internal tool {name}: {exc}", False
        else:
            run_id = f"run-{uuid.uuid4().hex[:8]}"
            out, ok = render(run_id, res, self.fingerprint), True
            self.store.add(Card(run_id, name, out, list(res.banned_phrases), params=dict(params), data=res.data,
                                fingerprint=self.fingerprint))
        self.calls.append({"tool": name, "params": params, "ok": ok, "first_line": out.split("\n", 1)[0]})
        return out

    # ------------------------------------------------------------ bahan baku
    def list_materials(self) -> str:
        """Daftar bahan baku yang punya data uji per kiriman: nama sheet, kode SAP, jumlah kiriman, periode, parameter.

        Returns:
            str: Kartu hasil.
        """
        return self._call("list_materials", {}, self.engine.list_materials)

    def rm_summary(self, material: str, parameter: str = "protein") -> str:
        """Ringkasan kualitas bahan baku per kiriman: n, rata-rata, SD, CV%, min, maks, dan per blok data.

        Args:
            material (str): Bahan baku: SBM, PBPM, MBM, FML C, kode SAP, atau sebagian nama (mis. 'fish meal').
            parameter (str): Parameter uji: protein, air, lemak, serat, abu, kalsium, fosfor, pepsin, koh, pdi, index, tvbn.
        Returns:
            str: Kartu hasil.
        """
        return self._call("rm_summary", {"material": material, "parameter": parameter},
                          lambda: self.engine.rm_summary(material, parameter))

    def rm_level_shift(self, material: str, parameter: str = "protein") -> str:
        """Deteksi pergeseran level kualitas bahan baku dari waktu ke waktu (mis. grade berubah), dengan rata-rata tiap segmen.

        Args:
            material (str): Bahan baku: SBM, PBPM, MBM, FML C, kode SAP, atau sebagian nama.
            parameter (str): Parameter uji, mis. protein.
        Returns:
            str: Kartu hasil.
        """
        return self._call("rm_level_shift", {"material": material, "parameter": parameter},
                          lambda: self.engine.rm_level_shift(material, parameter))

    def rm_safe_value(self, material: str, parameter: str = "protein", k: float = 1.0) -> str:
        """Angka aman gizi bahan baku untuk formula: rata-rata − k × SD dari jendela data terbaru (setelah pergeseran level).

        Args:
            material (str): Bahan baku: SBM, PBPM, MBM, FML C, kode SAP, atau sebagian nama.
            parameter (str): Parameter uji, mis. protein.
            k (float): Jumlah SD pengaman, default 1.
        Returns:
            str: Kartu hasil.
        """
        return self._call("rm_safe_value", {"material": material, "parameter": parameter, "k": k},
                          lambda: self.engine.rm_safe_value(material, parameter, k))

    def rm_outliers(self, material: str, parameter: str = "protein") -> str:
        """Kiriman bahan baku yang janggal: di luar batas peta SPC I-MR atau robust z > 3,5, per segmen level.

        Args:
            material (str): Bahan baku: SBM, PBPM, MBM, FML C, kode SAP, atau sebagian nama.
            parameter (str): Parameter uji, mis. protein.
        Returns:
            str: Kartu hasil.
        """
        return self._call("rm_outliers", {"material": material, "parameter": parameter},
                          lambda: self.engine.rm_outliers(material, parameter))

    def rm_stock(self, material: str) -> str:
        """Stok bahan baku dari laporan mingguan WPA: total stok semua lot, pemakaian per hari, dan DOH (hari stok).

        Args:
            material (str): Bahan baku: MBM, kode SAP, atau sebagian nama.
        Returns:
            str: Kartu hasil.
        """
        return self._call("rm_stock", {"material": material}, lambda: self.engine.rm_stock(material))

    # ------------------------------------------------------------ pakan lapangan & performa
    def feed_vs_label(self, feed_code: Optional[str] = None, owner: Optional[str] = None) -> str:
        """Bandingkan NIR sampel pakan dari lapangan dengan spec label (min/max) per nutrien.

        Args:
            feed_code (str): Kode pakan, mis. '788-3'. Kosong = semua.
            owner (str): 'own' (produk CP Prima) atau 'competitor'. Kosong = semua.
        Returns:
            str: Kartu hasil.
        """
        return self._call("feed_vs_label", {"feed_code": feed_code, "owner": owner},
                          lambda: self.engine.feed_vs_label(feed_code, owner))

    def perf_summary(self, feed_code: Optional[str] = None, owner: Optional[str] = None,
                     species: Optional[str] = None) -> str:
        """Performa kolam per kode pakan (FCR, SR, ADG, feed cost per kg ikan), pakan campuran dikeluarkan.

        Args:
            feed_code (str): Kode pakan, mis. '788-3'. Kosong = semua.
            owner (str): 'own' (produk CP Prima) atau 'competitor'. Kosong = semua.
            species (str): Jenis ikan, mis. 'Nila'. Kosong = semua.
        Returns:
            str: Kartu hasil.
        """
        return self._call("perf_summary", {"feed_code": feed_code, "owner": owner, "species": species},
                          lambda: self.engine.perf_summary(feed_code, owner, species))

    def perf_compare(self, group_a: str, group_b: str, metric: str = "fcr") -> str:
        """Bandingkan performa kolam dua grup: kode pakan vs kode pakan, atau 'own' vs 'competitor'.

        Args:
            group_a (str): Kode pakan (mis. '788-3') atau 'own'/'competitor'.
            group_b (str): Kode pakan atau 'own'/'competitor'.
            metric (str): fcr, sr, adg, atau feed_cost.
        Returns:
            str: Kartu hasil.
        """
        return self._call("perf_compare", {"group_a": group_a, "group_b": group_b, "metric": metric},
                          lambda: self.engine.perf_compare(group_a, group_b, metric))

    def corr_nutrient_fcr(self, nutrient: str = "protein") -> str:
        """Korelasi nutrien NIR sampel lapangan dengan FCR kolam, di level kode pakan (bukan bukti sebab-akibat).

        Args:
            nutrient (str): protein, air, lemak, serat, abu, kalsium, atau fosfor.
        Returns:
            str: Kartu hasil.
        """
        return self._call("corr_nutrient_fcr", {"nutrient": nutrient}, lambda: self.engine.corr_nutrient_fcr(nutrient))

    # ------------------------------------------------------------ ekonomi
    def feed_cost_breakeven(self, feed_price_rp_per_kg: float, additive_price_rp_per_kg: float,
                            dose_kg_per_ton: float, base_fcr: Optional[float] = None) -> str:
        """Titik impas aditif: berapa persen FCR minimal harus turun supaya biaya pakan per kg ikan tidak naik.

        Args:
            feed_price_rp_per_kg (float): Harga pakan tanpa aditif (Rp/kg).
            additive_price_rp_per_kg (float): Harga aditif (Rp/kg).
            dose_kg_per_ton (float): Dosis aditif (kg per ton pakan).
            base_fcr (float): FCR awal, OPSIONAL. Tanpa ini tool tetap menghitung persen penurunan FCR
                minimum; jangan minta FCR awal ke user kalau yang ditanya hanya persennya.
        Returns:
            str: Kartu hasil.
        """
        params = {"feed_price_rp_per_kg": feed_price_rp_per_kg, "additive_price_rp_per_kg": additive_price_rp_per_kg,
                  "dose_kg_per_ton": dose_kg_per_ton, "base_fcr": base_fcr}
        return self._call("feed_cost_breakeven", params, lambda: self.engine.feed_cost_breakeven(
            feed_price_rp_per_kg, additive_price_rp_per_kg, dose_kg_per_ton, base_fcr))
