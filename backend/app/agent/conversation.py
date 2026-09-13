"""Bounded, per-user conversation state — in-process memory, not persisted
to Postgres (see docs/decisions.md's conversation-memory ADR: no
cross-replica sharing or restart-survival requirement exists yet, and
persisting full conversation text would raise retention/privacy questions
this phase doesn't need to answer). Same "in-memory, correct for a
single dev/demo process" tradeoff already documented for
`app/core/rate_limit.py`.

Keyed by `(user_id, conversation_id)` — a `conversation_id` is never valid
across different users, even if guessed or reused, which is what prevents
cross-user conversation leakage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Lock

DEFAULT_MAX_TURNS = 6  # one "turn" = one user message + one final assistant answer


@dataclass(frozen=True)
class StoredTurn:
    role: str  # "user" | "assistant"
    content: str


class ConversationStore:
    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS):
        self._max_messages = max_turns * 2  # a user message + an assistant message per turn
        self._lock = Lock()
        self._conversations: dict[tuple[str, str], list[StoredTurn]] = {}

    def get_history(self, *, user_id: str, conversation_id: str) -> list[StoredTurn]:
        with self._lock:
            return list(self._conversations.get((user_id, conversation_id), []))

    def append_turn(self, *, user_id: str, conversation_id: str, role: str, content: str) -> None:
        with self._lock:
            key = (user_id, conversation_id)
            history = self._conversations.setdefault(key, [])
            history.append(StoredTurn(role=role, content=content))
            if len(history) > self._max_messages:
                del history[: len(history) - self._max_messages]

    @staticmethod
    def new_conversation_id() -> str:
        return str(uuid.uuid4())


_default_store = ConversationStore()


def get_conversation_store() -> ConversationStore:
    return _default_store
