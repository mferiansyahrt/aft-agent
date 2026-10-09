"""Model specs and the agno model factory (same shape as live-html-editor).

LLM_PROVIDER is an ordered fallback chain, e.g. "openai,gemini": BaseAgent
tries each spec in turn when one is unavailable or keeps failing.

  openai       OpenAI Responses API (agno.models.openai.OpenAIResponses)
  gemini       Google Gemini, native (agno.models.google.Gemini, needs google-genai);
               Gemini API key, or Vertex AI in our own GCP project/region
  openai_like  any OpenAI-compatible server (agno.models.openai.like.OpenAILike):
               an internal LLM, or Gemini's OpenAI-compatible endpoint
               (LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/)
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from config import settings

PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_OPENAI_LIKE = "openai_like"

TRANSIENT, UNAVAILABLE, BAD_OUTPUT = "transient", "unavailable", "bad_output"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    provider: str
    model_id: str

    @property
    def available(self) -> Tuple[bool, str]:
        if self.provider == PROVIDER_OPENAI and not settings.OPENAI_API_KEY:
            return False, "OPENAI_API_KEY belum diisi di .env"
        if self.provider == PROVIDER_GEMINI:
            if settings.GOOGLE_VERTEXAI and not settings.GOOGLE_CLOUD_PROJECT:
                return False, "GOOGLE_CLOUD_PROJECT belum diisi (GOOGLE_VERTEXAI=true)"
            if not settings.GOOGLE_VERTEXAI and not settings.GOOGLE_API_KEY:
                return False, "GOOGLE_API_KEY belum diisi di .env"
        if self.provider == PROVIDER_OPENAI_LIKE and not (settings.LLM_BASE_URL and settings.LLM_MODEL_NAME):
            return False, "LLM_BASE_URL / LLM_MODEL_NAME belum diisi di .env"
        return True, ""


def _spec(provider: str) -> ModelSpec:
    if provider == PROVIDER_OPENAI:
        return ModelSpec("openai", f"OpenAI ({settings.OPENAI_MODEL_NAME})", provider, settings.OPENAI_MODEL_NAME)
    if provider == PROVIDER_GEMINI:
        via = "Vertex AI" if settings.GOOGLE_VERTEXAI else "Gemini API"
        return ModelSpec("gemini", f"Gemini ({settings.GEMINI_MODEL_NAME}, {via})", provider, settings.GEMINI_MODEL_NAME)
    if provider == PROVIDER_OPENAI_LIKE:
        return ModelSpec("openai_like", f"OpenAI-compatible ({settings.LLM_MODEL_NAME})", provider,
                         settings.LLM_MODEL_NAME or "")
    raise ValueError(f"LLM_PROVIDER tidak dikenal: {provider!r} (pilihan: openai, gemini, openai_like)")


def chain_specs() -> List[ModelSpec]:
    providers = [p.strip().lower() for p in settings.LLM_PROVIDER.split(",") if p.strip()]
    return [_spec(p) for p in providers or [PROVIDER_OPENAI]]


def build_model(spec: ModelSpec, *, timeout: Optional[int] = None):
    timeout = timeout or settings.LLM_TIMEOUT
    if spec.provider == PROVIDER_GEMINI:
        from agno.models.google import Gemini
        params = dict(id=spec.model_id, timeout=timeout)
        if settings.GOOGLE_VERTEXAI:
            params.update(vertexai=True, project_id=settings.GOOGLE_CLOUD_PROJECT, location=settings.GOOGLE_CLOUD_LOCATION)
        else:
            params["api_key"] = settings.GOOGLE_API_KEY
        if settings.GEMINI_THINKING_BUDGET is not None:
            params["thinking_budget"] = settings.GEMINI_THINKING_BUDGET
        if settings.LLM_MAX_TOKENS:
            params["max_output_tokens"] = settings.LLM_MAX_TOKENS
        return Gemini(**params)
    if spec.provider == PROVIDER_OPENAI_LIKE:
        from agno.models.openai.like import OpenAILike
        return OpenAILike(id=spec.model_id, base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY or "EMPTY",
                          timeout=timeout, max_retries=0)
    # Responses API: reasoning models + function tools are refused on /chat/completions.
    from agno.models.openai import OpenAIResponses
    params = dict(id=spec.model_id, api_key=settings.OPENAI_API_KEY, timeout=timeout,
                  max_retries=0, store=False, include=["reasoning.encrypted_content"])
    if settings.OPENAI_REASONING_EFFORT:
        params["reasoning_effort"] = settings.OPENAI_REASONING_EFFORT
    if settings.LLM_MAX_TOKENS:
        params["max_output_tokens"] = settings.LLM_MAX_TOKENS
    return OpenAIResponses(**params)


class CallError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def classify(err: CallError) -> str:
    """Should the agent retry the same model, move on, or give up on this output?"""
    msg = str(err).lower()
    if err.status in (401, 403, 404) or any(m in msg for m in (
            "api key", "api_key_invalid", "not found", "does not exist", "permission", "permission_denied",
            "unauthenticated")):
        return UNAVAILABLE
    if err.status in (408, 409, 429, 500, 502, 503, 504) or any(m in msg for m in (
            "timeout", "rate limit", "temporarily", "connection", "overloaded", "resource_exhausted", "unavailable")):
        return TRANSIENT
    return BAD_OUTPUT
