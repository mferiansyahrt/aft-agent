"""Chat with Hermes, streamed, with session_id-based history.

    .venv/bin/python source/run_chat_stream.py                         # sesi baru, interaktif
    .venv/bin/python source/run_chat_stream.py --session-id ses-demo01  # lanjutkan / buat sesi ini
    .venv/bin/python source/run_chat_stream.py --session-id ses-demo01 -m "Kalau pakai 2 SD?"
    .venv/bin/python source/run_chat_stream.py --sessions               # daftar sesi
    .venv/bin/python source/run_chat_stream.py --session-id ses-demo01 --history
    .venv/bin/python source/run_chat_stream.py --draft ...              # tampilkan juga token mentah model

History: every message is stored in chat.sqlite under its session_id; for each new
question the last AGENT_HISTORY_TURNS question/answer pairs are read back from there,
so a conversation continues across separate runs of this script.

Streaming: tool calls and validation are shown live. The answer text is shown only
after it passes the number validator (with --draft the raw tokens are shown too,
clearly labelled, for debugging).
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from agents.hermes_agent import HermesAgent  # noqa: E402
from db_clients.chat_store import ChatStore  # noqa: E402

DIM, BOLD, RED, GREEN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[0m"


def out(text: str = "", end: str = "\n") -> None:
    print(text, end=end, flush=True)


async def ask(agent: HermesAgent, store: ChatStore, session_id: str, question: str, draft: bool) -> None:
    history = store.history(session_id, settings.AGENT_HISTORY_TURNS)
    out(f"{DIM}  konteks: {len(history) // 2} tanya-jawab sebelumnya dari sesi {session_id}{RESET}")
    in_draft = False
    result = None
    async for ev in agent.run_stream(question, history=history):
        t = ev["type"]
        if t == "draft":
            if draft:
                if not in_draft:
                    out(f"{DIM}  draf (belum divalidasi): ", end="")
                    in_draft = True
                out(ev["text"], end="")
            continue
        if in_draft:
            out(RESET)
            in_draft = False
        if t == "status":
            out(f"{DIM}  ⋯ {ev['message']}{RESET}")
        elif t == "tool_start":
            args = ", ".join(f"{k}={v}" for k, v in ev["args"].items() if v not in (None, ""))
            out(f"{DIM}  → {ev['tool']}({args}){RESET}")
        elif t == "tool_done":
            mark = f"{GREEN}✓{RESET}" if ev["ok"] else f"{RED}✗{RESET}"
            out(f"  {mark} {DIM}{ev['summary']}{RESET}")
        elif t == "validation":
            if ev["ok"]:
                out(f"  {GREEN}✓ validator: lolos ({ev['numbers_checked']} angka dicek){RESET}")
            else:
                out(f"  {RED}✗ validator: ditolak ({len(ev['errors'])} kesalahan){RESET}")
                for e in ev["errors"][:5]:
                    out(f"{DIM}      - {e}{RESET}")
        elif t == "final":
            result = ev["result"]

    store.add(session_id, "user", question)
    if result and result.ok:
        out(f"\n{BOLD}Hermes:{RESET} {result.answer}\n")
        store.add(session_id, "assistant", result.answer, ok=True,
                  run_ids=result.validation.runs_cited if result.validation else [], model=result.model)
    else:
        msg = "Maaf, jawaban belum lolos pemeriksaan angka, jadi tidak ditampilkan."
        out(f"\n{BOLD}Hermes:{RESET} {RED}{msg}{RESET} ({result.error if result else 'tidak ada hasil'})\n")
        store.add(session_id, "assistant", (result.answer if result else "") or msg, ok=False,
                  model=result.model if result else "")


def show_history(store: ChatStore, session_id: str) -> None:
    msgs = store.messages(session_id)
    if not msgs:
        out(f"sesi {session_id} belum punya pesan")
        return
    for m in msgs:
        who = "Anda" if m["role"] == "user" else ("Hermes" if m["ok"] else "Hermes (DITOLAK)")
        out(f"{DIM}[{m['created_at']}]{RESET} {BOLD}{who}:{RESET} {m['content']}\n")


async def main(args) -> None:
    store = ChatStore(settings.CHAT_DB_PATH)
    if args.sessions:
        for s in store.sessions():
            out(f"{s['session_id']}  pesan={s['n_messages']}  dibuat={s['created_at']}  terakhir={s['last_at'] or '-'}")
        return
    session_id = store.ensure_session(args.session_id)
    if args.history:
        show_history(store, session_id)
        return
    agent = HermesAgent()
    out(f"{BOLD}Hermes AFT{RESET} · sesi {session_id} · model {' -> '.join(s.label for s in agent.specs)}")
    if args.message:
        for q in args.message:
            out(f"\n{BOLD}Anda:{RESET} {q}")
            await ask(agent, store, session_id, q, args.draft)
        return
    out(f"{DIM}ketik pertanyaan; 'keluar' untuk berhenti; lanjutkan nanti dengan --session-id {session_id}{RESET}")
    while True:
        try:
            q = input(f"\n{BOLD}Anda:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("keluar", "exit", "quit"):
            break
        if q:
            await ask(agent, store, session_id, q, args.draft)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-id", help="id sesi; kosong = sesi baru")
    ap.add_argument("-m", "--message", nargs="+", help="satu atau beberapa pertanyaan (non-interaktif)")
    ap.add_argument("--sessions", action="store_true", help="daftar sesi")
    ap.add_argument("--history", action="store_true", help="tampilkan riwayat sesi")
    ap.add_argument("--draft", action="store_true", help="tampilkan token mentah model (belum divalidasi)")
    asyncio.run(main(ap.parse_args()))
