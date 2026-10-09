"""Hermes: answers user questions by calling the statistics tools, never by computing.

Each question gets its own CardStore. After the model answers, the answer
validator checks every number against the cards; a rejected answer is sent
back with the errors (and the cards) up to VALIDATOR_MAX_RETRIES times.

run_stream() is the single code path: it yields progress events (tool calls,
draft text, validation) and ends with a "final" event holding the HermesResult.
run() simply drains it. Draft text is the model's raw output BEFORE validation;
callers must only present the final, validated answer as Hermes' answer.
"""
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from agents.base import BaseAgent
from agents.hermes_agent.prompt import FEEDBACK_BLOCK, HISTORY_BLOCK, HUMAN_PROMPT, system_prompt
from agents_tools.aft_stat_tools import AftStatTools
from agents_tools.cards import CardStore
from agents_tools.stat_engine import StatEngine
from config import settings
from db_clients.aft_repository import SnapshotCache
from db_clients.run_log import RunLog
from utils.answer_validator import ValidationReport, validate_answer


@dataclass
class HermesResult:
    ok: bool
    answer: str = ""
    model: str = ""
    error: str = ""
    attempts: int = 0
    tool_calls: List[dict] = field(default_factory=list)
    cards: Dict[str, str] = field(default_factory=dict)
    validation: Optional[ValidationReport] = None


class HermesAgent(BaseAgent):
    def __init__(self, engine: Optional[StatEngine] = None, run_log: Optional[RunLog] = None, **kwargs):
        super().__init__(agent_name="Hermes AFT", **kwargs)
        self._fixed_engine = engine
        self._snapshots = SnapshotCache(settings.AFT_DB_PATH)
        self.run_log = run_log or RunLog(settings.RUNS_DB_PATH)

    @property
    def engine(self) -> StatEngine:
        """Engine over the current data snapshot. The repository is the only reader of
        aft.sqlite; the engine and the tools only compute on the in-memory snapshot."""
        if self._fixed_engine is not None:
            return self._fixed_engine
        return StatEngine(self._snapshots.get(), min_n=settings.MIN_N_WARNING, alpha=settings.LEVEL_SHIFT_ALPHA,
                          min_segment=settings.LEVEL_SHIFT_MIN_SEGMENT)

    @staticmethod
    def _history(turns: Sequence[Tuple[str, str]]) -> str:
        """Last AGENT_HISTORY_TURNS question/answer pairs as plain text context (app-managed, like
        live-html-editor). Only previous questions and validated answers, never data rows."""
        if not turns:
            return ""
        keep = list(turns)[-2 * settings.AGENT_HISTORY_TURNS:]
        lines = [f"{'User' if role == 'user' else 'Hermes'}: {text.strip()}" for role, text in keep]
        return HISTORY_BLOCK.format(turns="\n".join(lines))

    def _save_trail(self, store: CardStore, question: str) -> None:
        """Audit trail: every card the model saw goes to runs.sqlite, written here (not by the tools)."""
        for rid, c in store.cards.items():
            self.run_log.save(rid, c.tool, c.params, c.text, c.data, c.fingerprint, question)

    async def run(self, question: str, history: Optional[Sequence[Tuple[str, str]]] = None) -> HermesResult:
        result = HermesResult(ok=False, error="tidak ada hasil")
        async for ev in self.run_stream(question, history):
            if ev["type"] == "final":
                result = ev["result"]
        return result

    async def run_stream(self, question: str,
                         history: Optional[Sequence[Tuple[str, str]]] = None) -> AsyncIterator[dict]:
        store = CardStore()
        toolkits: List[AftStatTools] = []
        engine = self.engine  # one snapshot for the whole question, loaded before the model runs

        def make_kwargs() -> dict:
            # fresh toolkit per attempt; the card store is shared across attempts of this question
            toolkits.append(AftStatTools(engine, store))
            return {"tools": [toolkits[-1]], "tool_call_limit": settings.AGENT_TOOL_CALL_LIMIT}

        def calls() -> List[dict]:
            return [c for tk in toolkits for c in tk.calls]

        system = system_prompt()
        feedback, text, model, report, attempts = "", None, "", None, 0
        for attempts in range(1, settings.VALIDATOR_MAX_RETRIES + 2):
            yield {"type": "status", "message": "menyusun jawaban" if attempts == 1
                   else f"jawaban ditolak validator, memperbaiki (percobaan {attempts})"}
            human = HUMAN_PROMPT.format(history=self._history(history or []), question=question.strip(),
                                        feedback=feedback)
            text, err = None, None
            async for item in self._astream_session(human, system, make_kwargs):
                if item[0] == "event":
                    ev = item[1]
                    name = type(ev).__name__
                    if name == "ToolCallStartedEvent":
                        yield {"type": "tool_start", "tool": ev.tool.tool_name, "args": ev.tool.tool_args or {}}
                    elif name == "ToolCallCompletedEvent":
                        out = str(ev.tool.result or "")
                        yield {"type": "tool_done", "tool": ev.tool.tool_name, "ok": not out.startswith("GAGAL"),
                               "summary": out.split("\n", 1)[0][:160]}
                    elif name == "RunContentEvent" and getattr(ev, "content", None):
                        yield {"type": "draft", "text": str(ev.content)}
                elif item[0] == "retry":
                    yield {"type": "status", "message": item[1]}
                else:
                    _, text, model, err = item
            if text is None:
                self._save_trail(store, question)
                yield {"type": "final", "result": HermesResult(
                    ok=False, error=str(err or "model tidak menghasilkan jawaban"), attempts=attempts,
                    tool_calls=calls(), cards={rid: c.text for rid, c in store.cards.items()})}
                return
            report = validate_answer(text, store, question)
            yield {"type": "validation", "ok": report.ok, "errors": report.errors,
                   "numbers_checked": report.numbers_checked, "attempt": attempts}
            if report.ok:
                break
            logger.info(f"[{self.agent_name}] jawaban ditolak validator (percobaan {attempts}): {len(report.errors)} kesalahan")
            cards = "\n\n".join(c.text for c in store.cards.values()) or "(belum ada kartu)"
            feedback = FEEDBACK_BLOCK.format(errors=report.feedback(), cards=cards, previous=text)

        self._save_trail(store, question)
        yield {"type": "final", "result": HermesResult(
            ok=bool(report and report.ok), answer=(text or "").strip(), model=model,
            error="" if report and report.ok else "jawaban tidak lolos validator angka",
            attempts=attempts, tool_calls=calls(),
            cards={rid: c.text for rid, c in store.cards.items()}, validation=report)}
