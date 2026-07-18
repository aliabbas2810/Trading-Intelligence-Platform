from __future__ import annotations

from backend.api import (
    InMemoryAlignmentReadStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
)
from backend.engines.structure import (
    BreakDirection,
    BreakOfStructure,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.engines.market_state import MARKET_STRUCTURE_TIMEFRAMES, MarketStateService
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeMode,
    MultiTimeframeTrendResult,
    TimeframeTrendSnapshot,
    TrendState,
    TrendStrength,
    TrendUpdate,
)
from backend.models import Candle, Timeframe
from backend.storage import InMemoryCandleStore


DEMO_START_MS = 1_735_689_600_000
MINUTE_MS = 60_000
FOUR_HOUR_MS = 4 * 60 * MINUTE_MS
DAY_MS = 24 * 60 * MINUTE_MS
WEEK_MS = 7 * DAY_MS
DEMO_TIMEFRAMES = (
    Timeframe.WEEKLY,
    Timeframe.DAILY,
    Timeframe.FOUR_HOUR,
    Timeframe.TWO_HOUR,
    Timeframe.ONE_HOUR,
    Timeframe.THIRTY_MINUTE,
    Timeframe.FIFTEEN_MINUTE,
    Timeframe.FIVE_MINUTE,
    Timeframe.ONE_MINUTE,
)


def seed_demo_visualization_data(
    *,
    symbol: str,
    candle_store: InMemoryCandleStore,
    structure_store: InMemoryStructureReadStore,
    trend_store: InMemoryTrendReadStore,
    alignment_store: InMemoryAlignmentReadStore,
    market_state_service: MarketStateService | None = None,
) -> None:
    """Seed deterministic dry-run read models for local visualization under RUNTIME-005."""

    for candle in generate_demo_candles(symbol):
        candle_store.save(candle)
    for swing in generate_demo_swings(symbol):
        structure_store.add_swing(swing)
        if market_state_service is not None and swing.timeframe in MARKET_STRUCTURE_TIMEFRAMES:
            market_state_service.update_swing(swing)
    for break_of_structure in generate_demo_breaks(symbol):
        structure_store.add_break_of_structure(break_of_structure)
        if market_state_service is not None and break_of_structure.timeframe in MARKET_STRUCTURE_TIMEFRAMES:
            market_state_service.update_break_of_structure(break_of_structure)
    trend_updates = generate_demo_trend_updates(symbol)
    for update in trend_updates:
        trend_store.set(update)
        if market_state_service is not None and update.timeframe in MARKET_STRUCTURE_TIMEFRAMES:
            market_state_service.update_trend(update)
    alignment_store.set(generate_demo_alignment(symbol, trend_updates))


def generate_demo_candles(symbol: str) -> tuple[Candle, ...]:
    return (
        *generate_demo_one_minute_candles(symbol),
        *generate_demo_interval_candles(symbol, Timeframe.FIVE_MINUTE, count=24, start=42_020.0, step=55.0),
        *generate_demo_interval_candles(symbol, Timeframe.FIFTEEN_MINUTE, count=18, start=42_120.0, step=80.0),
        *generate_demo_interval_candles(symbol, Timeframe.THIRTY_MINUTE, count=16, start=42_240.0, step=110.0),
        *generate_demo_interval_candles(symbol, Timeframe.ONE_HOUR, count=14, start=42_380.0, step=145.0),
        *generate_demo_interval_candles(symbol, Timeframe.TWO_HOUR, count=12, start=42_520.0, step=210.0),
        *generate_demo_four_hour_candles(symbol),
        *generate_demo_daily_candles(symbol),
        *generate_demo_weekly_candles(symbol),
    )


def generate_demo_one_minute_candles(symbol: str) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    close = 42_000.0
    for index in range(90):
        open_price = close
        direction = 1 if index % 7 not in {0, 1} else -1
        body = direction * (18.0 + (index % 5) * 3.0)
        close = open_price + body
        high = max(open_price, close) + 22.0 + (index % 4) * 2.0
        low = min(open_price, close) - 18.0 - (index % 3) * 2.0
        open_time_ms = DEMO_START_MS + index * MINUTE_MS
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=Timeframe.ONE_MINUTE,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + MINUTE_MS,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1.25 + index * 0.03,
            ),
        )
    return tuple(candles)


def generate_demo_four_hour_candles(symbol: str) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    values = (
        (42_000.0, 42_850.0, 41_740.0, 42_620.0, 180.0),
        (42_620.0, 43_180.0, 42_220.0, 42_360.0, 155.0),
        (42_360.0, 43_420.0, 42_050.0, 43_180.0, 210.0),
        (43_180.0, 43_760.0, 42_900.0, 43_520.0, 190.0),
        (43_520.0, 44_080.0, 43_100.0, 43_240.0, 175.0),
        (43_240.0, 44_620.0, 43_020.0, 44_280.0, 230.0),
        (44_280.0, 44_900.0, 43_860.0, 44_020.0, 205.0),
        (44_020.0, 45_180.0, 43_820.0, 44_860.0, 245.0),
        (44_860.0, 45_420.0, 44_340.0, 44_610.0, 212.0),
        (44_610.0, 45_780.0, 44_420.0, 45_360.0, 260.0),
        (45_360.0, 46_050.0, 45_020.0, 45_720.0, 238.0),
        (45_720.0, 46_360.0, 45_280.0, 45_980.0, 226.0),
    )
    for index, (open_price, high, low, close, volume) in enumerate(values):
        open_time_ms = DEMO_START_MS + index * FOUR_HOUR_MS
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=Timeframe.FOUR_HOUR,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + FOUR_HOUR_MS,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
            ),
        )
    return tuple(candles)


def generate_demo_interval_candles(
    symbol: str,
    timeframe: Timeframe,
    *,
    count: int,
    start: float,
    step: float,
) -> tuple[Candle, ...]:
    interval_ms = interval_for_timeframe(timeframe)
    candles: list[Candle] = []
    close = start
    for index in range(count):
        open_price = close
        direction = 1 if index % 4 != 1 else -1
        body = direction * (step * (0.35 + (index % 3) * 0.08))
        close = open_price + body
        high = max(open_price, close) + step * 0.55
        low = min(open_price, close) - step * 0.42
        candles.append(
            demo_candle(
                symbol=symbol,
                timeframe=timeframe,
                interval_ms=interval_ms,
                index=index,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                volume=25.0 + index * 4.0,
            ),
        )
    return tuple(candles)


def generate_demo_daily_candles(symbol: str) -> tuple[Candle, ...]:
    values = (
        (41_800.0, 43_420.0, 41_520.0, 42_860.0, 920.0),
        (42_860.0, 44_080.0, 42_420.0, 43_520.0, 980.0),
        (43_520.0, 44_900.0, 43_100.0, 44_280.0, 1_060.0),
        (44_280.0, 45_780.0, 43_820.0, 45_360.0, 1_140.0),
        (45_360.0, 46_360.0, 45_020.0, 45_980.0, 1_020.0),
        (45_980.0, 46_900.0, 45_400.0, 46_520.0, 1_090.0),
    )
    return tuple(
        demo_candle(
            symbol=symbol,
            timeframe=Timeframe.DAILY,
            interval_ms=DAY_MS,
            index=index,
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for index, (open_price, high, low, close, volume) in enumerate(values)
    )


def generate_demo_weekly_candles(symbol: str) -> tuple[Candle, ...]:
    values = (
        (39_800.0, 43_420.0, 39_200.0, 42_860.0, 5_800.0),
        (42_860.0, 45_780.0, 42_100.0, 45_360.0, 6_260.0),
        (45_360.0, 48_100.0, 44_900.0, 47_420.0, 6_840.0),
        (47_420.0, 49_600.0, 46_800.0, 48_950.0, 6_420.0),
    )
    return tuple(
        demo_candle(
            symbol=symbol,
            timeframe=Timeframe.WEEKLY,
            interval_ms=WEEK_MS,
            index=index,
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for index, (open_price, high, low, close, volume) in enumerate(values)
    )


def generate_demo_swings(symbol: str) -> tuple[StructureSwing, ...]:
    """Return precomputed HH/HL/LH/LL overlays without invoking structure logic."""

    swings: list[StructureSwing] = []
    for index, timeframe in enumerate(DEMO_TIMEFRAMES):
        if timeframe in {Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE}:
            base = 42_000.0 + (index - 6) * 110.0
        else:
            base = 42_000.0 + index * 420.0
        swings.extend(
            demo_swings_for_timeframe(
                symbol,
                timeframe,
                hh_level=base + 300.0,
                hl_level=base + 210.0,
                lh_level=base + 520.0,
                ll_level=base + 430.0,
            ),
        )
    return tuple(swings)


def generate_demo_breaks(symbol: str) -> tuple[BreakOfStructure, ...]:
    return tuple(
        demo_break(
            symbol,
            timeframe,
            broken_level=42_300.0 + index * 420.0,
            candle_close=42_380.0 + index * 420.0,
            candle_index=break_index_for_timeframe(timeframe),
        )
        for index, timeframe in enumerate(DEMO_TIMEFRAMES)
    )


def generate_demo_trend_updates(symbol: str) -> tuple[TrendUpdate, ...]:
    event_time_ms = DEMO_START_MS + 12 * FOUR_HOUR_MS
    return tuple(
        TrendUpdate(
            symbol=symbol,
            timeframe=timeframe,
            state=TrendState.BULLISH,
            previous_state=TrendState.TRANSITION,
            strength=TrendStrength(confirming_structure_count=max(2, 6 - index // 2)),
            reason=f"demo_seed_bullish_{timeframe.value}",
            event_time_ms=event_time_ms,
        )
        for index, timeframe in enumerate(DEMO_TIMEFRAMES)
    )


def generate_demo_alignment(
    symbol: str,
    trend_updates: tuple[TrendUpdate, ...],
) -> MultiTimeframeTrendResult:
    snapshots = tuple(
        TimeframeTrendSnapshot(
            symbol=update.symbol,
            timeframe=update.timeframe,
            state=update.state,
            strength=update.strength,
            event_time_ms=update.event_time_ms,
        )
        for update in trend_updates
        if update.timeframe in {Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR}
    )
    return MultiTimeframeTrendResult(
        symbol=symbol,
        mode=MultiTimeframeMode.VOTING,
        bias=DirectionalBias.BULLISH,
        alignment_score=3,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        missing_timeframes=(),
        snapshots=snapshots,
        reason="demo_seed_all_bullish",
    )


def demo_swing(
    symbol: str,
    timeframe: Timeframe,
    kind: SwingKind,
    label: StructureLabel,
    level: float,
    candle_index: int,
) -> StructureSwing:
    interval_ms = interval_for_timeframe(timeframe)
    open_time_ms = DEMO_START_MS + candle_index * interval_ms
    return StructureSwing(
        symbol=symbol,
        timeframe=timeframe,
        kind=kind,
        label=label,
        level=level,
        candle_open_time_ms=open_time_ms,
        candle_close_time_ms=open_time_ms + interval_ms,
    )


def demo_swings_for_timeframe(
    symbol: str,
    timeframe: Timeframe,
    hh_level: float,
    hl_level: float,
    lh_level: float,
    ll_level: float,
) -> tuple[StructureSwing, ...]:
    return (
        demo_swing(symbol, timeframe, SwingKind.HIGH, StructureLabel.HH, hh_level, 1),
        demo_swing(symbol, timeframe, SwingKind.LOW, StructureLabel.HL, hl_level, 2),
        demo_swing(symbol, timeframe, SwingKind.HIGH, StructureLabel.LH, lh_level, 3),
        demo_swing(symbol, timeframe, SwingKind.LOW, StructureLabel.LL, ll_level, 4),
    )


def demo_break(
    symbol: str,
    timeframe: Timeframe,
    broken_level: float,
    candle_close: float,
    candle_index: int,
) -> BreakOfStructure:
    interval_ms = interval_for_timeframe(timeframe)
    open_time_ms = DEMO_START_MS + candle_index * interval_ms
    return BreakOfStructure(
        symbol=symbol,
        timeframe=timeframe,
        direction=BreakDirection.BULLISH,
        broken_label=StructureLabel.HH,
        broken_level=broken_level,
        candle_close=candle_close,
        candle_open_time_ms=open_time_ms,
        candle_close_time_ms=open_time_ms + interval_ms,
    )


def demo_candle(
    *,
    symbol: str,
    timeframe: Timeframe,
    interval_ms: int,
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> Candle:
    open_time_ms = DEMO_START_MS + index * interval_ms
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + interval_ms,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def interval_for_timeframe(timeframe: Timeframe) -> int:
    if timeframe is Timeframe.ONE_MINUTE:
        return MINUTE_MS
    if timeframe is Timeframe.FIVE_MINUTE:
        return 5 * MINUTE_MS
    if timeframe is Timeframe.FIFTEEN_MINUTE:
        return 15 * MINUTE_MS
    if timeframe is Timeframe.THIRTY_MINUTE:
        return 30 * MINUTE_MS
    if timeframe is Timeframe.ONE_HOUR:
        return 60 * MINUTE_MS
    if timeframe is Timeframe.TWO_HOUR:
        return 2 * 60 * MINUTE_MS
    if timeframe is Timeframe.FOUR_HOUR:
        return FOUR_HOUR_MS
    if timeframe is Timeframe.DAILY:
        return DAY_MS
    return WEEK_MS


def break_index_for_timeframe(timeframe: Timeframe) -> int:
    if timeframe is Timeframe.ONE_MINUTE:
        return 58
    if timeframe in {Timeframe.FIVE_MINUTE, Timeframe.FIFTEEN_MINUTE, Timeframe.THIRTY_MINUTE}:
        return 5
    if timeframe in {Timeframe.ONE_HOUR, Timeframe.TWO_HOUR, Timeframe.FOUR_HOUR}:
        return 4
    if timeframe is Timeframe.DAILY:
        return 3
    return 2
