from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.models import Trade


def test_trade_accepts_valid_normalized_data() -> None:
    """Covers FR-103, user-specified FR-105, and TEST-001."""

    trade = Trade(
        symbol="BTCUSDT",
        price=100_000.0,
        quantity=0.25,
        timestamp_ms=1_725_000_000_123,
        source="bitmart_usdt_m_perpetual",
    )

    assert trade.symbol == "BTCUSDT"
    assert trade.timestamp_ms == 1_725_000_000_123


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Trade(
            symbol="",
            price=100_000.0,
            quantity=0.25,
            timestamp_ms=1_725_000_000_123,
            source="bitmart_usdt_m_perpetual",
        ),
        lambda: Trade(
            symbol="BTCUSDT",
            price=0.0,
            quantity=0.25,
            timestamp_ms=1_725_000_000_123,
            source="bitmart_usdt_m_perpetual",
        ),
        lambda: Trade(
            symbol="BTCUSDT",
            price=float("nan"),
            quantity=0.25,
            timestamp_ms=1_725_000_000_123,
            source="bitmart_usdt_m_perpetual",
        ),
        lambda: Trade(
            symbol="BTCUSDT",
            price=100_000.0,
            quantity=-1.0,
            timestamp_ms=1_725_000_000_123,
            source="bitmart_usdt_m_perpetual",
        ),
        lambda: Trade(
            symbol="BTCUSDT",
            price=100_000.0,
            quantity=0.25,
            timestamp_ms=-1,
            source="bitmart_usdt_m_perpetual",
        ),
        lambda: Trade(
            symbol="BTCUSDT",
            price=100_000.0,
            quantity=0.25,
            timestamp_ms=1_725_000_000_123,
            source="",
        ),
    ],
)
def test_trade_rejects_invalid_normalized_data(factory: Callable[[], Trade]) -> None:
    """Covers FR-103 and TEST-001 validation of canonical trades."""

    with pytest.raises(ValueError):
        factory()
