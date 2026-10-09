"""BaseAgent: retries, timeout, concurrency limit and model fallback around agno.

Same contract as live-html-editor: a fresh agno Agent per attempt (a retried
session must not inherit half-finished tool state), `arun` wrapped in
asyncio.wait_for and a semaphore, and a run with status ERROR treated as a
failure because agno does not raise on LLM errors.
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from loguru import logger

from agents.models import TRANSIENT, UNAVAILABLE, CallError, ModelSpec, build_model, chain_specs, classify
from config import settings

_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
    return _SEMAPHORE


class AgentUnavailable(RuntimeError):
    """No model in the chain can be used (missing key, unknown model, ...)."""


class BaseAgent(ABC):
    def __init__(self, agent_name: str, session_budget: Optional[int] = None,
                 specs: Optional[List[ModelSpec]] = None):
        self.agent_name = agent_name
        self.session_budget = session_budget or settings.AGENT_SESSION_BUDGET_S
        self.specs = specs or chain_specs()

    def _new_agent(self, model, system_message: str, agent_kwargs: Dict[str, Any]):
        from agno.agent import Agent
        # The model gets data only through the tools passed in agent_kwargs: no knowledge base,
        # no agent db/memory, no history-reading tools. telemetry=False: agno sends nothing out.
        return Agent(model=model, system_message=system_message, markdown=False, debug_mode=False,
                     telemetry=False, knowledge=None, db=None, search_knowledge=False,
                     read_chat_history=False, read_tool_call_history=False, add_history_to_context=False,
                     enable_agentic_memory=False, **agent_kwargs)

    @staticmethod
    def _run_failed(result) -> bool:
        if result is None:
            return True
        status = getattr(result, "status", None)
        return str(getattr(status, "value", status)).strip().upper() == "ERROR"

    async def _arun_once(self, spec: ModelSpec, human_prompt: str, system_message: str,
                         agent_kwargs: Dict[str, Any]) -> Tuple[Any, Optional[CallError]]:
        agent = self._new_agent(build_model(spec), system_message, agent_kwargs)
        try:
            async with _llm_semaphore():
                result = await asyncio.wait_for(agent.arun(human_prompt), timeout=self.session_budget)
        except asyncio.TimeoutError:
            return None, CallError(f"tidak ada jawaban dalam {self.session_budget} detik", 408)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - classified below
            return None, CallError(f"{type(e).__name__}: {e}", getattr(e, "status_code", None))
        if self._run_failed(result):
            return None, CallError(str(getattr(result, "content", ""))[:500] or "status=ERROR")
        return result, None

    async def _arun_session(self, human_prompt: str, system_message: str,
                            make_kwargs: Callable[[], Dict[str, Any]], *,
                            accept: Optional[Callable[[str], bool]] = None) -> Tuple[Optional[str], str, Optional[CallError]]:
        """Try every model spec; returns (text, model_key, last_error)."""
        last: Optional[CallError] = None
        usable = [(s, s.available) for s in self.specs]
        if not any(ok for _, (ok, _) in usable):
            raise AgentUnavailable("; ".join(reason for _, (_, reason) in usable))
        for spec, (ok, reason) in usable:
            if not ok:
                logger.warning(f"[{self.agent_name}] {spec.key} dilewati: {reason}")
                continue
            for attempt in range(1, settings.LLM_ATTEMPTS_PER_MODEL + 1):
                result, err = await self._arun_once(spec, human_prompt, system_message, make_kwargs())
                if err is None:
                    text = str(getattr(result, "content", "") or "")
                    if accept is None or accept(text):
                        return text, spec.key, None
                    err = CallError("jawaban kosong")
                last = err
                kind = classify(err)
                logger.warning(f"[{self.agent_name}] {spec.key} percobaan {attempt} gagal ({kind}): {err}")
                if kind == UNAVAILABLE:
                    break
                if kind == TRANSIENT:
                    await asyncio.sleep(min(2 ** attempt, 10))
        return None, "", last

    async def _astream_session(self, human_prompt: str, system_message: str,
                               make_kwargs: Callable[[], Dict[str, Any]]) -> AsyncIterator[tuple]:
        """Streaming twin of _arun_session, same retry/fallback rules.

        Yields ("event", agno_event) while a model runs, ("retry", message) when an attempt
        fails, and finally ("done", text_or_None, model_key, last_error).
        """
        last: Optional[CallError] = None
        usable = [(s, s.available) for s in self.specs]
        if not any(ok for _, (ok, _) in usable):
            raise AgentUnavailable("; ".join(reason for _, (_, reason) in usable))
        for spec, (ok, reason) in usable:
            if not ok:
                logger.warning(f"[{self.agent_name}] {spec.key} dilewati: {reason}")
                continue
            for attempt in range(1, settings.LLM_ATTEMPTS_PER_MODEL + 1):
                agent = self._new_agent(build_model(spec), system_message, make_kwargs())
                err, final = None, None
                try:
                    async with _llm_semaphore(), asyncio.timeout(self.session_budget):
                        async for ev in agent.arun(human_prompt, stream=True, stream_events=True):
                            name = type(ev).__name__
                            if name == "RunErrorEvent":
                                err = CallError(str(getattr(ev, "content", ""))[:500] or "status=ERROR")
                                break
                            if name == "RunCompletedEvent":
                                final = getattr(ev, "content", None)
                            yield ("event", ev)
                except TimeoutError:
                    err = CallError(f"tidak ada jawaban dalam {self.session_budget} detik", 408)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - classified below
                    err = CallError(f"{type(e).__name__}: {e}", getattr(e, "status_code", None))
                if err is None and final is not None and str(final).strip():
                    yield ("done", str(final), spec.key, None)
                    return
                last = err or CallError("jawaban kosong")
                kind = classify(last)
                logger.warning(f"[{self.agent_name}] {spec.key} percobaan {attempt} gagal ({kind}): {last}")
                yield ("retry", f"{spec.key} percobaan {attempt} gagal: {str(last)[:120]}")
                if kind == UNAVAILABLE:
                    break
                if kind == TRANSIENT:
                    await asyncio.sleep(min(2 ** attempt, 10))
        yield ("done", None, "", last)

    @abstractmethod
    async def run(self, *args, **kwargs) -> Any: ...
