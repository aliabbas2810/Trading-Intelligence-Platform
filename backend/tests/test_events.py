from __future__ import annotations

from dataclasses import dataclass

from backend.core import EventBus


@dataclass(frozen=True, slots=True)
class SampleEvent:
    name: str


def test_event_bus_dispatches_synchronously_in_subscription_order() -> None:
    """Covers TEST-001 for deterministic foundation behavior."""

    bus = EventBus()
    handled: list[str] = []

    bus.subscribe(SampleEvent, lambda event: handled.append(f"first:{event.name}"))
    bus.subscribe(SampleEvent, lambda event: handled.append(f"second:{event.name}"))

    bus.publish(SampleEvent(name="ready"))

    assert handled == ["first:ready", "second:ready"]


def test_event_bus_ignores_unsubscribed_event_types() -> None:
    """Covers TEST-001."""

    bus = EventBus()
    handled: list[str] = []

    bus.subscribe(SampleEvent, lambda event: handled.append(event.name))
    bus.publish(object())

    assert handled == []
