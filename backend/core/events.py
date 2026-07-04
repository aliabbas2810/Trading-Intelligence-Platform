from __future__ import annotations

from collections import defaultdict
from typing import Callable, TypeVar, cast


EventT = TypeVar("EventT", bound=object)
EventHandler = Callable[[EventT], None]


class EventBus:
    """Synchronous in-process event bus for M1 foundation work."""

    def __init__(self) -> None:
        self._handlers: dict[type[object], list[Callable[[object], None]]] = defaultdict(list)

    def subscribe(self, event_type: type[EventT], handler: EventHandler[EventT]) -> None:
        self._handlers[event_type].append(cast(Callable[[object], None], handler))

    def publish(self, event: object) -> None:
        for handler in tuple(self._handlers[type(event)]):
            handler(event)
