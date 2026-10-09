from abc import ABC, abstractmethod
from typing import Generic, TypeVar

ContextT = TypeVar("ContextT")


class BaseStage(ABC, Generic[ContextT]):
    """A workflow stage that keeps per-event state in its context."""

    @abstractmethod
    async def run(self, ctx: ContextT) -> bool:
        """Return True to continue the pipeline, or False to end it."""
        raise NotImplementedError
