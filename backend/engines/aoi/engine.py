from __future__ import annotations

from dataclasses import replace
from hashlib import sha1

from backend.engines.aoi.models import (
    ActiveStructureLeg,
    AoiBounds,
    AoiCandidate,
    AoiDirection,
    AoiEvaluation,
    AoiLocationConfig,
    AoiLocationResult,
    AoiLocationState,
    AoiOverlap,
    AoiRankingMetadata,
    AoiRankingWeights,
    AoiSizingConfig,
    AoiState,
    AoiTimeframe,
    AoiTouch,
    AreaOfInterest,
    candle_body_overlaps,
)
from backend.models import Candle


class AoiEngine:
    """Deterministic Weekly/Daily AOI discovery over precomputed structure legs."""

    def __init__(
        self,
        *,
        ranking_weights: AoiRankingWeights | None = None,
        minimum_touches: int = 3,
    ) -> None:
        if minimum_touches < 3:
            raise ValueError("AOIs require at least three qualifying body interactions")
        self._weights = ranking_weights or AoiRankingWeights()
        self._minimum_touches = minimum_touches

    def evaluate(
        self,
        *,
        leg: ActiveStructureLeg,
        candles: tuple[Candle, ...],
        sizing: AoiSizingConfig,
        tick_size: float | None = None,
        atr: float | None = None,
    ) -> AoiEvaluation:
        relevant = self._relevant_candles(leg, candles)
        if not relevant:
            return AoiEvaluation(leg=leg)
        minimum_width, maximum_width = sizing.resolve(
            reference_price=(leg.price_bounds.lower + leg.price_bounds.upper) / 2,
            tick_size=tick_size,
            atr=atr,
        )
        bounds = self._candidate_bounds(relevant, leg.price_bounds, minimum_width, maximum_width)
        candidates = tuple(
            sorted(
                (self._candidate(leg, item, relevant, maximum_width) for item in bounds),
                key=self._rank_key,
            )
        )
        selected = self._deduplicate(candidates)
        areas = tuple(self._to_area(candidate) for candidate in selected if candidate.is_tradable)
        return AoiEvaluation(leg=leg, candidates=selected, areas=areas)

    def update_lifecycle(
        self,
        area: AreaOfInterest,
        *,
        candle: Candle,
        current_structure_leg_id: str,
        current_trend_id: str,
    ) -> AreaOfInterest:
        if current_trend_id != area.origin_trend_id:
            return replace(
                area,
                state=AoiState.STRUCTURALLY_INVALIDATED,
                state_changed_time_ms=candle.close_time_ms,
            )
        if current_structure_leg_id != area.origin_structure_leg_id:
            return replace(
                area,
                state=AoiState.ARCHIVED,
                state_changed_time_ms=candle.close_time_ms,
            )
        broken = (
            area.direction is AoiDirection.SUPPORT and candle.close < area.bounds.lower
        ) or (
            area.direction is AoiDirection.RESISTANCE and candle.close > area.bounds.upper
        )
        if broken:
            return replace(
                area,
                state=AoiState.BROKEN,
                state_changed_time_ms=candle.close_time_ms,
            )
        return area

    def mark_retest_pending(self, area: AreaOfInterest, *, event_time_ms: int) -> AreaOfInterest:
        if area.state is not AoiState.BROKEN:
            raise ValueError("Only a broken AOI can become retest-pending")
        return replace(area, state=AoiState.RETEST_PENDING, state_changed_time_ms=event_time_ms)

    def find_overlaps(
        self,
        weekly: tuple[AreaOfInterest, ...],
        daily: tuple[AreaOfInterest, ...],
        *,
        confluence_weight: float,
    ) -> tuple[AoiOverlap, ...]:
        overlaps: list[AoiOverlap] = []
        for weekly_area in weekly:
            if weekly_area.timeframe is not AoiTimeframe.WEEKLY:
                raise ValueError("Weekly AOI input must use the weekly timeframe")
            for daily_area in daily:
                if daily_area.timeframe is not AoiTimeframe.DAILY:
                    raise ValueError("Daily AOI input must use the daily timeframe")
                intersection = weekly_area.bounds.intersection(daily_area.bounds)
                if intersection is None:
                    continue
                smallest_width = min(weekly_area.width, daily_area.width)
                ratio = intersection.width / smallest_width
                overlaps.append(
                    AoiOverlap(
                        weekly_aoi_id=weekly_area.aoi_id,
                        daily_aoi_id=daily_area.aoi_id,
                        intersection_bounds=intersection,
                        overlap_ratio=ratio,
                        is_full_intersection=abs(ratio - 1.0) < 1e-12,
                        confluence_weight=confluence_weight,
                    )
                )
        return tuple(overlaps)

    def locate(
        self,
        area: AreaOfInterest,
        *,
        candle: Candle,
        config: AoiLocationConfig,
        previous_candle: Candle | None = None,
    ) -> AoiLocationResult:
        current_touch = area.bounds.overlaps(candle.low, candle.high)
        distance = self._distance(candle.close, area.bounds)
        previous_touch = (
            previous_candle is not None
            and area.bounds.overlaps(previous_candle.low, previous_candle.high)
        )
        if current_touch:
            moved_to_expected_side = (
                area.direction is AoiDirection.SUPPORT and candle.close > area.bounds.upper
            ) or (
                area.direction is AoiDirection.RESISTANCE and candle.close < area.bounds.lower
            )
            state = AoiLocationState.REACTING if moved_to_expected_side else AoiLocationState.INSIDE
        elif previous_touch:
            state = (
                AoiLocationState.ENTRY_WINDOW
                if distance <= config.maximum_post_reaction_excursion
                else AoiLocationState.MOVED_AWAY
            )
        elif distance <= config.proximity_tolerance:
            state = AoiLocationState.APPROACHING
        else:
            state = AoiLocationState.OUTSIDE
        gate_open = state in {
            AoiLocationState.INSIDE,
            AoiLocationState.REACTING,
            AoiLocationState.ENTRY_WINDOW,
        }
        return AoiLocationResult(
            aoi_id=area.aoi_id,
            state=state,
            distance=distance,
            current_touch=current_touch,
            gate_open=gate_open,
            reason=f"price_{state.value}_aoi",
        )

    def _relevant_candles(
        self,
        leg: ActiveStructureLeg,
        candles: tuple[Candle, ...],
    ) -> tuple[Candle, ...]:
        timeframe = leg.timeframe.to_timeframe()
        return tuple(
            sorted(
                (
                    candle
                    for candle in candles
                    if candle.symbol == leg.symbol
                    and candle.timeframe is timeframe
                    and leg.start_time_ms <= candle.open_time_ms
                    and candle.close_time_ms <= leg.end_time_ms
                    and candle_body_overlaps(candle, leg.price_bounds)
                ),
                key=lambda candle: candle.open_time_ms,
            )
        )

    def _candidate_bounds(
        self,
        candles: tuple[Candle, ...],
        leg_bounds: AoiBounds,
        minimum_width: float,
        maximum_width: float,
    ) -> tuple[AoiBounds, ...]:
        lower_anchors = {
            max(leg_bounds.lower, candle.body_low)
            for candle in candles
        }
        anchors = sorted(
            lower_anchors
            | {
                min(leg_bounds.upper, candle.body_high)
                for candle in candles
            }
        )
        generated: set[tuple[float, float]] = set()
        for lower in anchors:
            for upper in anchors:
                width = upper - lower
                if minimum_width <= width <= maximum_width:
                    generated.add((lower, upper))
            if lower in lower_anchors:
                upper = lower + minimum_width
                if upper <= leg_bounds.upper:
                    generated.add((lower, upper))
        return tuple(AoiBounds(lower=lower, upper=upper) for lower, upper in sorted(generated))

    def _candidate(
        self,
        leg: ActiveStructureLeg,
        bounds: AoiBounds,
        candles: tuple[Candle, ...],
        maximum_width: float,
    ) -> AoiCandidate:
        touches = tuple(
            AoiTouch(
                candle_open_time_ms=candle.open_time_ms,
                candle_close_time_ms=candle.close_time_ms,
                body_low=candle.body_low,
                body_high=candle.body_high,
                close=candle.close,
                close_inside=bounds.lower <= candle.close <= bounds.upper,
            )
            for candle in candles
            if candle_body_overlaps(candle, bounds)
        )
        confirmation = (
            touches[self._minimum_touches - 1].candle_close_time_ms
            if len(touches) >= self._minimum_touches
            else None
        )
        close_count = sum(touch.close_inside for touch in touches)
        reaction_count = self._reaction_count(bounds, candles)
        recent = touches[-1].candle_close_time_ms if touches else 0
        normalized_width = bounds.width / maximum_width
        score = (
            self._weights.body_close * close_count
            + self._weights.body_touch * len(touches)
            + self._weights.reaction * reaction_count
            + self._weights.recency * recent / 1_000_000_000_000
            - self._weights.width_penalty * normalized_width
        )
        candidate_id = self._identifier(leg, bounds)
        return AoiCandidate(
            candidate_id=candidate_id,
            symbol=leg.symbol,
            timeframe=leg.timeframe,
            direction=leg.direction,
            bounds=bounds,
            state=AoiState.CONFIRMED if confirmation is not None else AoiState.CANDIDATE,
            origin_structure_leg_id=leg.leg_id,
            origin_trend_id=leg.trend_id,
            origin_timeframe=leg.timeframe,
            touches=touches,
            first_touch_time_ms=touches[0].candle_open_time_ms if touches else 0,
            confirmation_time_ms=confirmation,
            ranking=AoiRankingMetadata(
                score=score,
                body_close_count=close_count,
                body_touch_count=len(touches),
                reaction_count=reaction_count,
                recency_time_ms=recent,
                normalized_width=normalized_width,
            ),
        )

    def _deduplicate(self, candidates: tuple[AoiCandidate, ...]) -> tuple[AoiCandidate, ...]:
        selected: list[AoiCandidate] = []
        for candidate in candidates:
            if candidate.touch_count < 2:
                continue
            timestamps = set(candidate.contributing_candle_timestamps)
            if any(
                self._jaccard(timestamps, set(item.contributing_candle_timestamps)) >= 0.8
                for item in selected
            ):
                continue
            selected.append(candidate)
        return tuple(selected)

    def _to_area(self, candidate: AoiCandidate) -> AreaOfInterest:
        if candidate.confirmation_time_ms is None:
            raise ValueError("An AOI cannot be active before its third touch")
        return AreaOfInterest(
            aoi_id=candidate.candidate_id,
            symbol=candidate.symbol,
            timeframe=candidate.timeframe,
            direction=candidate.direction,
            bounds=candidate.bounds,
            state=AoiState.ACTIVE,
            origin_structure_leg_id=candidate.origin_structure_leg_id,
            origin_trend_id=candidate.origin_trend_id,
            origin_timeframe=candidate.origin_timeframe,
            contributing_candle_timestamps=candidate.contributing_candle_timestamps,
            first_touch_time_ms=candidate.first_touch_time_ms,
            confirmation_time_ms=candidate.confirmation_time_ms,
            touch_count=candidate.touch_count,
            close_count=candidate.ranking.body_close_count,
            reaction_count=candidate.ranking.reaction_count,
            ranking=candidate.ranking,
            state_changed_time_ms=candidate.confirmation_time_ms,
        )

    def _reaction_count(self, bounds: AoiBounds, candles: tuple[Candle, ...]) -> int:
        count = 0
        for current, following in zip(candles, candles[1:], strict=False):
            if candle_body_overlaps(current, bounds) and not candle_body_overlaps(following, bounds):
                count += 1
        return count

    def _rank_key(self, candidate: AoiCandidate) -> tuple[int, int, float, int, int, float, str]:
        return (
            -candidate.ranking.body_close_count,
            -candidate.touch_count,
            candidate.bounds.width,
            -candidate.ranking.recency_time_ms,
            -candidate.ranking.reaction_count,
            -candidate.ranking.score,
            candidate.candidate_id,
        )

    def _identifier(self, leg: ActiveStructureLeg, bounds: AoiBounds) -> str:
        payload = f"{leg.symbol}|{leg.timeframe.value}|{leg.leg_id}|{bounds.lower:.12g}|{bounds.upper:.12g}"
        return f"aoi-{sha1(payload.encode(), usedforsecurity=False).hexdigest()[:16]}"

    def _jaccard(self, left: set[int], right: set[int]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    def _distance(self, price: float, bounds: AoiBounds) -> float:
        if bounds.lower <= price <= bounds.upper:
            return 0.0
        return bounds.lower - price if price < bounds.lower else price - bounds.upper
