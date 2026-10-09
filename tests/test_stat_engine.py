"""Engine maths without any LLM. The two Hermes v1 errors are reproduced here."""
import unittest

import helpers  # noqa: F401

from agents_tools.stat_engine import (StatEngine, ToolError, breakeven_fcr_reduction, find_level_shifts, fmt,
                                      imr_limits, norm_code, safe_value)
from config import settings
from db_clients.aft_repository import load_snapshot


class TestPureMaths(unittest.TestCase):
    def test_mbm_safe_value_hermes_v1_correction(self):
        # Modul: rata-rata 55,93 %, CV 5,43 % -> angka aman (mean - 1 SD) ~52,90 %, bukan 52,62 %
        mean, cv = 55.93, 5.43
        safe = safe_value(mean, mean * cv / 100, 1.0)
        self.assertAlmostEqual(safe, 52.89, places=2)
        self.assertNotAlmostEqual(safe, 52.62, places=1)

    def test_additive_breakeven_hermes_v1_correction(self):
        # pakan Rp11.000/kg, aditif Rp120.000/kg dosis 1 kg/ton -> +Rp120/kg -> FCR turun min 1,08 %
        red = breakeven_fcr_reduction(11000, 120000 * 1 / 1000)
        self.assertEqual(fmt(red * 100), "1,08")
        self.assertNotEqual(fmt(red * 100), "1,11")

    def test_level_shift_detects_grade_change(self):
        vals = [49.6, 49.5, 49.5, 49.2, 50.1, 59.9, 59.3, 60.4, 58.5]
        self.assertEqual(find_level_shifts(vals, alpha=0.01, min_segment=3), [5])
        self.assertEqual(find_level_shifts([47.5, 46.1, 46.3, 46.7, 46.5, 47.5, 46.7], 0.01, 3), [])

    def test_imr_limits(self):
        c, lcl, ucl = imr_limits([10, 12, 11, 13, 12])
        self.assertAlmostEqual(c, 11.6)
        self.assertLess(lcl, 10)
        self.assertGreater(ucl, 13)

    def test_format_and_codes(self):
        self.assertEqual(fmt(11120), "11.120,00")
        self.assertEqual(fmt(52.896), "52,90")
        self.assertEqual(norm_code("HDPIN B-3"), "HDPINB-3")
        self.assertEqual(norm_code("782-3."), "782-3")


@unittest.skipUnless(settings.AFT_DB_PATH.exists(), "aft.sqlite belum dibuat (jalankan ingest + cleanse)")
class TestEngineOnSampleData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = StatEngine(load_snapshot(settings.AFT_DB_PATH))

    def test_safe_value_uses_latest_window(self):
        r = self.e.rm_safe_value("MBM", "protein")
        self.assertEqual(r.data["window"], [5, 9])
        self.assertGreater(r.data["safe"], r.data["safe_all"])

    def test_material_resolution(self):
        self.assertEqual(self.e.resolve_material("fish meal")["sheet_name"], "FML C")
        self.assertEqual(self.e.resolve_material("301100")["sheet_name"], "MBM")
        with self.assertRaises(ToolError):
            self.e.resolve_material("meal")

    def test_label_check_is_honest_when_spec_missing(self):
        r = self.e.feed_vs_label("788-3")
        self.assertFalse(r.data["any_spec"])
        self.assertTrue(any("TIDAK BISA" in w for w in r.warnings))

    def test_correlation_refuses_with_few_products(self):
        r = self.e.corr_nutrient_fcr("protein")
        self.assertLess(r.n, 3)
        self.assertNotIn("Korelasi Pearson r", dict(r.facts))

    def test_snapshot_has_no_personal_columns(self):
        for rows in (self.e.data.pond_cycles, self.e.data.field_samples, self.e.data.stock_lots, self.e.data.rm_tests):
            for r in rows[:1]:
                self.assertFalse({"farmer_name", "farm", "remark", "note"} & set(r))


if __name__ == "__main__":
    unittest.main()
