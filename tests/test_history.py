"""History context: only the last AGENT_HISTORY_TURNS question/answer pairs reach the prompt."""
import unittest

import helpers  # noqa: F401

from agents.hermes_agent import HermesAgent
from config import settings


class TestHistory(unittest.TestCase):
    def test_keeps_last_turns_only(self):
        turns = []
        for i in range(1, 6):
            turns += [("user", f"pertanyaan {i}"), ("assistant", f"jawaban {i}")]
        text = HermesAgent._history(turns)
        n = settings.AGENT_HISTORY_TURNS
        for i in range(1, 6):
            self.assertEqual(f"pertanyaan {i}" in text, i > 5 - n)
        self.assertEqual(HermesAgent._history([]), "")


if __name__ == "__main__":
    unittest.main()
