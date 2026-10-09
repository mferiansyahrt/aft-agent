"""Answer validator: every number Hermes writes must come from a card.

Rules (line based, so tables and bullet lists work):
  1. every [run:id] in the answer was produced by a tool call for this question;
  2. every line that contains a number carries at least one [run:id];
  3. every number on that line appears verbatim as a number token in one of
     the cards cited on that line (no rounding, no reformatting);
  4. no banned phrase (global list + per-card phrases).
List numbering ("1. ", "2) ") and the run ids themselves are not counted. Numbers the
user wrote in the question (e.g. "2 SD", "Rp11.000") are inputs, not results, and may
be repeated anywhere.
"""
import re
from dataclasses import dataclass, field
from typing import List, Set

from agents_tools.cards import CardStore

RUN_TAG = re.compile(r"\[run:([A-Za-z0-9-]+)\]")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
LIST_PREFIX = re.compile(r"^\s*(?:[-*>#]+\s*)?\d+[.)]\s+")


@dataclass
class ValidationReport:
    ok: bool
    errors: List[str] = field(default_factory=list)
    numbers_checked: int = 0
    runs_cited: List[str] = field(default_factory=list)

    def feedback(self) -> str:
        return "\n".join(f"- {e}" for e in self.errors)


def _numbers(text: str) -> List[str]:
    return NUMBER.findall(text)


def validate_answer(answer: str, store: CardStore, question: str = "") -> ValidationReport:
    errors: List[str] = []
    checked = 0
    cited_all: List[str] = []
    card_tokens = {rid: set(_numbers(c.text)) for rid, c in store.cards.items()}
    user_tokens = set(_numbers(question))

    for no, raw in enumerate(answer.splitlines(), 1):
        ids = RUN_TAG.findall(raw)
        cited_all += ids
        unknown = [i for i in ids if i not in store.cards]
        for i in unknown:
            errors.append(f"baris {no}: [run:{i}] tidak berasal dari tool yang dipanggil untuk pertanyaan ini")
        body = LIST_PREFIX.sub("", RUN_TAG.sub(" ", raw), count=1)
        nums = [n for n in _numbers(body) if n not in user_tokens]
        if not nums:
            continue
        known = [i for i in ids if i in store.cards]
        if not ids:
            errors.append(f"baris {no}: memuat angka {', '.join(nums[:5])} tanpa [run:...] — \"{raw.strip()[:120]}\"")
            continue
        allowed: Set[str] = set().union(*(card_tokens[i] for i in known)) if known else set()
        for n in nums:
            checked += 1
            if n not in allowed:
                errors.append(f"baris {no}: angka {n} tidak ada (persis) di kartu {', '.join(f'[run:{i}]' for i in ids)}")

    low = answer.lower()
    for phrase in store.banned_phrases():
        if phrase.lower() in low:
            errors.append(f"frasa terlarang dipakai: \"{phrase}\"")

    return ValidationReport(ok=not errors, errors=errors, numbers_checked=checked,
                            runs_cited=sorted(set(cited_all)))
