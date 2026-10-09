"""Model chain: OpenAI, Gemini (native) and OpenAI-compatible, built without network calls."""
import unittest
from unittest import mock

import helpers  # noqa: F401

from agents.models import build_model, chain_specs
from config import settings


class TestModelChain(unittest.TestCase):
    def test_chain_order(self):
        with mock.patch.object(settings, "LLM_PROVIDER", "openai, gemini"):
            self.assertEqual([s.key for s in chain_specs()], ["openai", "gemini"])
        with mock.patch.object(settings, "LLM_PROVIDER", "nope"), self.assertRaises(ValueError):
            chain_specs()

    def test_gemini_api_key(self):
        from agno.models.google import Gemini
        with mock.patch.multiple(settings, LLM_PROVIDER="gemini", GOOGLE_API_KEY="test-key", GOOGLE_VERTEXAI=False):
            spec = chain_specs()[0]
            self.assertEqual(spec.available, (True, ""))
            model = build_model(spec)
        self.assertIsInstance(model, Gemini)
        self.assertEqual(model.id, settings.GEMINI_MODEL_NAME)
        self.assertEqual(model.api_key, "test-key")
        self.assertFalse(model.vertexai)

    def test_gemini_vertex(self):
        with mock.patch.multiple(settings, LLM_PROVIDER="gemini", GOOGLE_API_KEY=None, GOOGLE_VERTEXAI=True,
                                 GOOGLE_CLOUD_PROJECT="cp-prima-aft"):
            model = build_model(chain_specs()[0])
        self.assertTrue(model.vertexai)
        self.assertEqual(model.project_id, "cp-prima-aft")
        self.assertEqual(model.location, "asia-southeast2")

    def test_gemini_without_key_is_unavailable(self):
        with mock.patch.multiple(settings, LLM_PROVIDER="gemini", GOOGLE_API_KEY=None, GOOGLE_VERTEXAI=False):
            ok, reason = chain_specs()[0].available
        self.assertFalse(ok)
        self.assertIn("GOOGLE_API_KEY", reason)

    def test_gemini_via_openai_like(self):
        from agno.models.openai.like import OpenAILike
        with mock.patch.multiple(settings, LLM_PROVIDER="openai_like", LLM_MODEL_NAME="gemini-3.7-flash",
                                 LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
                                 LLM_API_KEY="test-key"):
            model = build_model(chain_specs()[0])
        self.assertIsInstance(model, OpenAILike)
        self.assertIn("generativelanguage", model.base_url)


if __name__ == "__main__":
    unittest.main()
