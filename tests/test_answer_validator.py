"""Validator behaviour without any LLM."""
import unittest

import helpers  # noqa: F401

from agents_tools.cards import Card, CardStore
from utils.answer_validator import validate_answer

CARD = """KARTU [run:run-aaaa1111] rm_safe_value · MBM · crude_protein
Data: n=4 · periode 2026-05-09 s/d 2026-05-13
| Angka aman (rata-rata − k×SD) | 58,69 % |
| Rata-rata jendela | 59,52 % |"""


def store():
    s = CardStore()
    s.add(Card("run-aaaa1111", "rm_safe_value", CARD))
    return s


class TestValidator(unittest.TestCase):
    def test_good_answer_passes(self):
        ans = ("Angka aman protein MBM 58,69 % dari 4 kiriman (2026-05-09 s/d 2026-05-13) [run:run-aaaa1111].\n"
               "Ini draf, perlu persetujuan nutritionist.")
        r = validate_answer(ans, store())
        self.assertTrue(r.ok, r.errors)
        self.assertGreater(r.numbers_checked, 0)

    def test_number_without_source_is_rejected(self):
        r = validate_answer("Angka aman protein MBM 58,69 %.", store())
        self.assertFalse(r.ok)

    def test_rounded_number_is_rejected(self):
        r = validate_answer("Angka aman sekitar 58,7 % [run:run-aaaa1111].", store())
        self.assertFalse(r.ok)
        self.assertIn("58,7", r.errors[0])

    def test_hermes_v1_style_number_is_rejected(self):
        r = validate_answer("Batas aman MBM 52,62 % [run:run-aaaa1111].", store())
        self.assertFalse(r.ok)

    def test_unknown_run_id_is_rejected(self):
        r = validate_answer("Angka aman 58,69 % [run:run-ffff0000].", store())
        self.assertFalse(r.ok)

    def test_banned_phrase_is_rejected(self):
        r = validate_answer("Formula ini siap produksi.", store())
        self.assertFalse(r.ok)

    def test_list_numbering_is_ignored(self):
        r = validate_answer("1. Data masih sedikit.\n2) Perlu konfirmasi QC.", store())
        self.assertTrue(r.ok, r.errors)



class TestUserNumbers(unittest.TestCase):
    def test_numbers_from_question_are_allowed(self):
        q = "Kalau pakai 2 SD jadi berapa?"
        ans = "Dengan 2 SD, angka aman 58,69 % [run:run-aaaa1111]."
        self.assertTrue(validate_answer(ans, store(), q).ok)
        self.assertFalse(validate_answer(ans, store()).ok)

    def test_question_numbers_do_not_whitelist_results(self):
        r = validate_answer("Angka aman 52,62 % [run:run-aaaa1111].", store(), "Kalau pakai 2 SD?")
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
