"""Cards: the only form in which engine results reach the model.

A card is plain text with the run id, the method, a facts table, n/period,
warnings and "tidak boleh" rules. The CardStore keeps the cards produced while
answering one question; the answer validator checks the answer against them.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from agents_tools.stat_engine import GLOBAL_BANNED, Result


@dataclass
class Card:
    run_id: str
    tool: str
    text: str
    banned_phrases: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""


def render(run_id: str, res: Result, fingerprint: str) -> str:
    lines = [f"KARTU [run:{run_id}] {res.tool} · {res.subject}",
             f"Metode: {res.method}"]
    meta = []
    if res.n is not None:
        meta.append(f"n={res.n}")
    if res.period:
        meta.append(f"periode {res.period}")
    meta.append(f"sumber {res.source or '-'}")
    meta.append(f"sidik data {fingerprint}")
    lines.append("Data: " + " · ".join(meta))
    if res.facts:
        lines += ["", "| Fakta | Nilai |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in res.facts]
    for title, header, rows in res.tables:
        lines += ["", f"{title}:", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(r) + " |" for r in rows] if rows else ["| (kosong) |"]
    if res.warnings:
        lines += ["", "Peringatan:"] + [f"- {w}" for w in res.warnings]
    rules = res.forbidden + ["mengubah, membulatkan, atau menghitung ulang angka di kartu ini"]
    lines += ["", "Tidak boleh:"] + [f"- {f}" for f in rules]
    return "\n".join(lines)


class CardStore:
    def __init__(self):
        self.cards: Dict[str, Card] = {}

    def add(self, card: Card) -> None:
        self.cards[card.run_id] = card

    def get(self, ids: Iterable[str]) -> List[Card]:
        return [self.cards[i] for i in ids if i in self.cards]

    def banned_phrases(self) -> List[str]:
        phrases = list(GLOBAL_BANNED)
        for c in self.cards.values():
            phrases += c.banned_phrases
        return sorted(set(phrases))
