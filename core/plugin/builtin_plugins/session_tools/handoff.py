"""Keep cross-session lineage and a shared budget outside model-visible text."""

import time
import uuid
from dataclasses import dataclass, field

HANDOFF_KEY = "session_handoff"


@dataclass
class HandoffChain:
    chain_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    transfers: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SessionHandoff:
    chain: HandoffChain = field(default_factory=HandoffChain)
    parent_id: str | None = None
    hops: int = 0

    @classmethod
    def for_event(cls, event):
        extra = getattr(event, "extra", None)
        if extra is None:
            extra = event.extra = {}
        cached = extra.get(HANDOFF_KEY)
        if isinstance(cached, cls):
            return cached
        messages = getattr(event, "messages", [])
        # Real user input starts a new action, even when notices share its batch.
        inherited = []
        if messages and all(message.is_notice for message in messages):
            for message in messages:
                handoff = (message.extra or {}).get(HANDOFF_KEY)
                if isinstance(handoff, cls):
                    inherited.append(handoff)
        # A merged batch follows its most consumed chain rather than resetting it.
        handoff = (
            max(inherited, key=lambda item: (len(item.chain.transfers), item.hops))
            if inherited
            else cls()
        )
        extra[HANDOFF_KEY] = handoff
        return handoff

    def new_record(self, source: str, target: str, description: str) -> dict:
        return {
            "chain_id": self.chain.chain_id,
            "transfer_id": uuid.uuid4().hex,
            "parent_id": self.parent_id,
            "hop": self.hops + 1,
            "timestamp": time.time(),
            "source": source,
            "target": target,
            "description": description,
            "status": "denied",
        }

    def reserve(
        self, record: dict, max_transfers: int, repeat_window: int
    ) -> str | None:
        """Reserve before any await so concurrent branches share one finite budget."""
        if len(self.chain.transfers) >= max_transfers:
            return f"Cross-session transfer blocked: chain limit of {max_transfers} reached; wait for new user input"
        fingerprint = (
            record["source"],
            record["target"],
            " ".join(record["description"].split()),
        )
        now = time.time()
        for previous in self.chain.transfers:
            if previous["status"] not in {"pending", "sent"}:
                continue
            if now - previous["timestamp"] > repeat_window:
                continue
            if fingerprint == (
                previous["source"],
                previous["target"],
                " ".join(previous["description"].split()),
            ):
                return "Cross-session transfer blocked: repeated source, target and description in this chain"
        record["status"] = "pending"
        record["chain_transfer"] = len(self.chain.transfers) + 1
        self.chain.transfers.append(record)
        return None

    def next(self, record: dict) -> "SessionHandoff":
        return SessionHandoff(self.chain, record["transfer_id"], self.hops + 1)
