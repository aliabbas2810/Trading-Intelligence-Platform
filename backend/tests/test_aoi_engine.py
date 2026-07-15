from __future__ import annotations

import inspect

import pytest

from backend.engines.aoi import (
    ActiveStructureLeg,
    AoiBounds,
    AoiDirection,
    AoiEngine,
    AoiEvaluation,
    AoiLocationConfig,
    AoiLocationState,
    AoiSizingConfig,
    AoiSizingMode,
    AoiState,
    AoiTimeframe,
)
from backend.engines.aoi import engine as aoi_engine_module
from backend.engines.structure import StructureLabel, StructureSwing, SwingKind
from backend.engines.trend import TrendState
from backend.models import Candle, Timeframe


def candle(
    index: int,
    body_low: float,
    body_high: float,
    *,
    timeframe: Timeframe = Timeframe.DAILY,
    wick_low: float | None = None,
    wick_high: float | None = None,
    close_at_high: bool = True,
) -> Candle:
    open_price = body_low if close_at_high else body_high
    close_price = body_high if close_at_high else body_low
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time_ms=index * 1_000,
        close_time_ms=(index + 1) * 1_000,
        open=open_price,
        high=wick_high if wick_high is not None else body_high,
        low=wick_low if wick_low is not None else body_low,
        close=close_price,
        volume=1.0,
    )


def swing(
    label: StructureLabel,
    level: float,
    index: int,
    timeframe: Timeframe = Timeframe.DAILY,
) -> StructureSwing:
    return StructureSwing(
        symbol="BTCUSDT",
        timeframe=timeframe,
        kind=SwingKind.HIGH if label in {StructureLabel.HH, StructureLabel.LH} else SwingKind.LOW,
        label=label,
        level=level,
        candle_open_time_ms=index * 1_000,
        candle_close_time_ms=(index + 1) * 1_000,
    )


def leg(*, bearish: bool = False, timeframe: AoiTimeframe = AoiTimeframe.DAILY) -> ActiveStructureLeg:
    domain_timeframe = timeframe.to_timeframe()
    return ActiveStructureLeg(
        symbol="BTCUSDT",
        timeframe=timeframe,
        trend_state=TrendState.BEARISH if bearish else TrendState.BULLISH,
        start_swing=swing(
            StructureLabel.LH if bearish else StructureLabel.HL,
            110.0 if bearish else 90.0,
            0,
            domain_timeframe,
        ),
        end_swing=swing(
            StructureLabel.LL if bearish else StructureLabel.HH,
            90.0 if bearish else 110.0,
            20,
            domain_timeframe,
        ),
        leg_id="leg-1",
        trend_id="trend-1",
    )


def sizing() -> AoiSizingConfig:
    return AoiSizingConfig(
        mode=AoiSizingMode.FIXED_TICKS,
        minimum_ticks=1,
        maximum_ticks=1,
    )


def evaluate(
    candles: tuple[Candle, ...],
    *,
    active_leg: ActiveStructureLeg | None = None,
) -> AoiEvaluation:
    return AoiEngine().evaluate(
        leg=active_leg or leg(),
        candles=candles,
        sizing=sizing(),
        tick_size=1.0,
    )


def test_three_candle_body_overlaps_confirm_an_aoi_after_third_touch() -> None:
    result = evaluate((candle(1, 100, 101), candle(2, 100, 101), candle(3, 100, 101)))

    assert len(result.areas) == 1
    area = result.areas[0]
    assert area.touch_count == 3
    assert area.state is AoiState.ACTIVE
    assert area.first_touch_time_ms == 1_000
    assert area.confirmation_time_ms == 4_000


def test_two_touches_remain_candidate_and_are_not_tradable() -> None:
    result = evaluate((candle(1, 100, 101), candle(2, 100, 101)))

    assert result.areas == ()
    assert len(result.candidates) == 1
    assert result.candidates[0].state is AoiState.CANDIDATE
    assert result.candidates[0].confirmation_time_ms is None
    assert result.candidates[0].is_tradable is False


def test_wick_only_touch_does_not_count_for_historical_construction() -> None:
    result = evaluate(
        (
            candle(1, 100, 101),
            candle(2, 100, 101),
            candle(3, 104, 105, wick_low=100),
        )
    )

    cluster = next(item for item in result.candidates if item.bounds == AoiBounds(100, 101))
    assert cluster.touch_count == 2
    assert cluster.confirmation_time_ms is None


def test_multiple_aois_may_coexist_in_one_active_leg() -> None:
    result = evaluate(
        tuple(candle(index, 95, 96) for index in range(1, 4))
        + tuple(candle(index, 104, 105) for index in range(4, 7))
    )

    assert len(result.areas) == 2
    assert {area.bounds for area in result.areas} == {AoiBounds(95, 96), AoiBounds(104, 105)}


@pytest.mark.parametrize(
    ("active_leg", "expected_direction"),
    [
        (leg(), AoiDirection.SUPPORT),
        (leg(bearish=True), AoiDirection.RESISTANCE),
    ],
)
def test_bullish_and_bearish_active_ranges_work(
    active_leg: ActiveStructureLeg,
    expected_direction: AoiDirection,
) -> None:
    candles = tuple(candle(index, 100, 101) for index in range(1, 4))

    result = evaluate(candles, active_leg=active_leg)

    assert result.areas[0].direction is expected_direction


def test_wick_penetration_does_not_invalidate_but_body_close_does() -> None:
    engine = AoiEngine()
    area = evaluate(tuple(candle(index, 100, 101) for index in range(1, 4))).areas[0]
    wick_penetration = candle(4, 100, 100.5, wick_low=95)

    unchanged = engine.update_lifecycle(
        area,
        candle=wick_penetration,
        current_structure_leg_id="leg-1",
        current_trend_id="trend-1",
    )
    broken = engine.update_lifecycle(
        area,
        candle=candle(5, 98, 99),
        current_structure_leg_id="leg-1",
        current_trend_id="trend-1",
    )

    assert unchanged.state is AoiState.ACTIVE
    assert broken.state is AoiState.BROKEN
    assert engine.mark_retest_pending(broken, event_time_ms=7_000).state is AoiState.RETEST_PENDING


def test_leg_or_trend_change_archives_or_invalidates_old_area() -> None:
    engine = AoiEngine()
    area = evaluate(tuple(candle(index, 100, 101) for index in range(1, 4))).areas[0]
    latest = candle(4, 100, 101)

    archived = engine.update_lifecycle(
        area,
        candle=latest,
        current_structure_leg_id="leg-2",
        current_trend_id="trend-1",
    )
    invalidated = engine.update_lifecycle(
        area,
        candle=latest,
        current_structure_leg_id="leg-1",
        current_trend_id="trend-2",
    )

    assert archived.state is AoiState.ARCHIVED
    assert invalidated.state is AoiState.STRUCTURALLY_INVALIDATED


def test_weekly_daily_overlap_is_detected_without_merging_sources() -> None:
    engine = AoiEngine()
    daily = evaluate(tuple(candle(index, 100, 101) for index in range(1, 4))).areas[0]
    weekly_leg = leg(timeframe=AoiTimeframe.WEEKLY)
    weekly_candles = tuple(
        candle(index, 100.5, 101.5, timeframe=Timeframe.WEEKLY) for index in range(1, 4)
    )
    weekly = evaluate(weekly_candles, active_leg=weekly_leg).areas[0]

    overlaps = engine.find_overlaps((weekly,), (daily,), confluence_weight=0.25)

    assert len(overlaps) == 1
    assert overlaps[0].intersection_bounds == AoiBounds(100.5, 101)
    assert overlaps[0].weekly_aoi_id == weekly.aoi_id
    assert overlaps[0].daily_aoi_id == daily.aoi_id


def test_candidate_ranking_is_deterministic_and_prefers_more_closes() -> None:
    candles = (
        candle(1, 95, 96),
        candle(2, 95, 96),
        candle(3, 95, 96),
        candle(4, 104, 105, close_at_high=False),
        candle(5, 104, 105, close_at_high=False),
        candle(6, 104, 105, close_at_high=False),
    )

    first = evaluate(candles)
    second = evaluate(candles)

    assert first == second
    assert tuple(area.aoi_id for area in first.areas) == tuple(area.aoi_id for area in second.areas)


def test_live_location_uses_wicks_and_exposes_entry_window() -> None:
    engine = AoiEngine()
    area = evaluate(tuple(candle(index, 100, 101) for index in range(1, 4))).areas[0]
    config = AoiLocationConfig(proximity_tolerance=1, maximum_post_reaction_excursion=3)
    touch = candle(4, 102, 103, wick_low=100.5)
    reaction = candle(5, 102, 103)

    inside = engine.locate(area, candle=touch, config=config)
    entry_window = engine.locate(area, candle=reaction, previous_candle=touch, config=config)

    assert inside.state is AoiLocationState.REACTING
    assert inside.current_touch is True
    assert entry_window.state is AoiLocationState.ENTRY_WINDOW
    assert entry_window.gate_open is True


def test_aoi_module_does_not_import_or_call_analysis_engines() -> None:
    source = inspect.getsource(aoi_engine_module)

    assert "MarketStructureEngine" not in source
    assert "TrendEngine" not in source
