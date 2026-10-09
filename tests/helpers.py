"""Test setup: put source/ on sys.path and silence loguru."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from loguru import logger  # noqa: E402

logger.remove()
