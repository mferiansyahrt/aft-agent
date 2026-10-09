"""Application settings, loaded from the project's .env (same pattern as live-html-editor).

Field names are the env var names. Paths are resolved against the project root.
"""
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic.v1 import BaseSettings, validator

path_this = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = Path(path_this).parent
PROJECT_ROOT = SOURCE_DIR.parent
if str(SOURCE_DIR) not in sys.path:
    sys.path.append(str(SOURCE_DIR))
load_dotenv(PROJECT_ROOT / ".env")


class AppConfig(BaseSettings):
    # LLM untuk Hermes. Urutan fallback, pisahkan koma, mis. "openai,gemini".
    #   openai      = OpenAI Responses API
    #   gemini      = Google Gemini native (agno.models.google.Gemini): Gemini API key atau Vertex AI
    #   openai_like = server OpenAI-compatible (LLM internal, atau endpoint OpenAI-compat milik Gemini)
    LLM_PROVIDER: str = "openai"
    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL_NAME: str = "gemini-3.7-flash"
    GEMINI_THINKING_BUDGET: Optional[int] = None
    GOOGLE_VERTEXAI: bool = False                       # True = lewat Vertex AI (project GCP sendiri)
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: str = "asia-southeast2"      # Jakarta
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL_NAME: str = "gpt-5.6-luna"
    OPENAI_REASONING_EFFORT: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL_NAME: Optional[str] = None
    LLM_MAX_TOKENS: Optional[int] = None
    LLM_TIMEOUT: int = 180
    LLM_ATTEMPTS_PER_MODEL: int = 2
    LLM_MAX_CONCURRENCY: int = 4

    # Agent
    AGENT_TOOL_CALL_LIMIT: int = 20
    AGENT_SESSION_BUDGET_S: int = 300
    VALIDATOR_MAX_RETRIES: int = 2
    AGENT_HISTORY_TURNS: int = 3     # jumlah tanya-jawab terakhir yang ikut sebagai konteks

    # Data
    AFT_DB_PATH: Path = Path("source/database/aft.sqlite")
    RUNS_DB_PATH: Path = Path("source/database/runs.sqlite")
    CHAT_DB_PATH: Path = Path("source/database/chat.sqlite")

    # Statistik
    MIN_N_WARNING: int = 10          # n di bawah ini -> peringatan "data sedikit"
    LEVEL_SHIFT_ALPHA: float = 0.01  # batas p-value uji pergeseran level
    LEVEL_SHIFT_MIN_SEGMENT: int = 3

    @validator("OPENAI_API_KEY", "OPENAI_REASONING_EFFORT", "LLM_BASE_URL", "LLM_API_KEY",
               "LLM_MODEL_NAME", "LLM_MAX_TOKENS", "GOOGLE_API_KEY", "GEMINI_THINKING_BUDGET",
               "GOOGLE_CLOUD_PROJECT", pre=True)
    def _empty_is_none(cls, v):
        return None if v in ("", None, 0, "0") else v

    @validator("AFT_DB_PATH", "RUNS_DB_PATH", "CHAT_DB_PATH")
    def _resolve_against_root(cls, v: Path) -> Path:
        return v if v.is_absolute() else (PROJECT_ROOT / v)

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"


settings = AppConfig()
