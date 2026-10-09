"""DataSnapshot: the in-memory data the statistics engine computes on.

Plain immutable data, no database handle. Built by db_clients/aft_repository.py,
the only module that reads aft.sqlite for the engine.
"""
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class DataSnapshot:
    rm_tests: Tuple[dict, ...]
    stock_lots: Tuple[dict, ...]
    field_samples: Tuple[dict, ...]
    pond_cycles: Tuple[dict, ...]
    fingerprint: str
    loaded_from: str = field(default="")
