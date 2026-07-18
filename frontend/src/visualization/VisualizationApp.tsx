import { BarChart3, Eye, EyeOff, Layers, RefreshCw, Ribbon, Search, ToggleLeft } from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCandles,
  fetchAoiLocation,
  fetchAois,
  fetchDataReadiness,
  fetchHealthStatus,
  fetchMarketStructure,
  fetchMultiTimeframeAlignment,
  fetchReplayStatus,
  fetchScannerStatus,
  fetchTrendState,
  evaluateTradingIntelligence,
  pauseReplay,
  resumeReplay,
  runScanner,
  startReplay,
  stepReplay,
  stopReplay,
} from "../api";
import { POLL_INTERVAL_MS } from "../config";
import type {
  BosMode,
  AoiDto,
  AoiGateDto,
  AoiOverlapDto,
  AoiStateFilter,
  AnalysisReadinessDto,
  BreakOfStructureDto,
  CandleDto,
  HealthStatusDto,
  ReplaySourceType,
  ReplayStatusDto,
  ScannerBiasFilter,
  ScannerSummaryDto,
  SetupCandidateDto,
  StructureSnapshotDto,
  Timeframe,
  TradingIntelligenceDto,
  TrendSnapshotDto,
} from "../types";

const TIMEFRAMES: Timeframe[] = ["1w", "1d", "4h", "2h", "1h", "30m", "15m", "5m", "1m"];
const DEFAULT_SYMBOL = "BTCUSDT";

interface VisualizationData {
  candles: CandleDto[];
  structure: StructureSnapshotDto;
  trend: TrendSnapshotDto;
  alignmentScore: number;
  health: HealthStatusDto | null;
  readiness: AnalysisReadinessDto | null;
  aois: AoiDto[];
  aoiOverlaps: AoiOverlapDto[];
  aoiGate: AoiGateDto | null;
}

export function VisualizationApp() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>("4h");
  const [bosVisible, setBosVisible] = useState(true);
  const [bosMode, setBosMode] = useState<BosMode>("permanent");
  const [trendBackground, setTrendBackground] = useState(true);
  const [trendRibbon, setTrendRibbon] = useState(true);
  const [aoiVisible, setAoiVisible] = useState(true);
  const [weeklyAoiVisible, setWeeklyAoiVisible] = useState(true);
  const [dailyAoiVisible, setDailyAoiVisible] = useState(true);
  const [aoiOverlapVisible, setAoiOverlapVisible] = useState(true);
  const [aoiStateFilter, setAoiStateFilter] = useState<AoiStateFilter>("active");
  const [replaySource, setReplaySource] = useState<ReplaySourceType>("candles");
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [replayStartIndex, setReplayStartIndex] = useState(0);
  const [replayStatus, setReplayStatus] = useState<ReplayStatusDto | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [scannerSymbols, setScannerSymbols] = useState("BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT");
  const [scannerBias, setScannerBias] = useState<ScannerBiasFilter>("any");
  const [scannerMinimumAlignment, setScannerMinimumAlignment] = useState(0);
  const [scannerMinimumScore, setScannerMinimumScore] = useState(0);
  const [scannerLimit, setScannerLimit] = useState(10);
  const [scannerSummary, setScannerSummary] = useState<ScannerSummaryDto | null>(null);
  const [scannerLoading, setScannerLoading] = useState(false);
  const [scannerError, setScannerError] = useState<string | null>(null);
  const [selectedScannerSymbol, setSelectedScannerSymbol] = useState<string | null>(null);
  const [intelligence, setIntelligence] = useState<TradingIntelligenceDto | null>(null);
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastRefreshTime, setLastRefreshTime] = useState<string | null>(null);
  const [data, setData] = useState<VisualizationData>({
    candles: [],
    structure: { swings: [], breaks_of_structure: [] },
    trend: { update: null },
    alignmentScore: 0,
    health: null,
    readiness: null,
    aois: [],
    aoiOverlaps: [],
    aoiGate: null,
  });

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setErrorMessage(null);
      try {
        const [candles, structure, trend, alignment, health, readiness, aoiRead, aoiGate] = await Promise.all([
          fetchCandles(symbol, timeframe),
          fetchMarketStructure(symbol, timeframe),
          fetchTrendState(symbol, timeframe),
          fetchMultiTimeframeAlignment(symbol),
          fetchHealthStatus(),
          fetchDataReadiness(symbol),
          fetchAois(symbol, aoiStateFilter),
          fetchAoiLocation(symbol),
        ]);
        if (!active) {
          return;
        }
        setData({
          candles,
          structure,
          trend,
          alignmentScore: alignment?.alignment_score ?? 0,
          health,
          readiness,
          aois: aoiRead.aois,
          aoiOverlaps: aoiRead.overlaps,
          aoiGate,
        });
        setLastRefreshTime(new Date().toLocaleTimeString());
      } catch (error) {
        if (active) {
          setErrorMessage(error instanceof Error ? error.message : "Unable to load backend data");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [symbol, timeframe, aoiStateFilter, refreshKey]);

  useEffect(() => {
    if (POLL_INTERVAL_MS <= 0) {
      return;
    }
    const interval = window.setInterval(() => {
      setRefreshKey((value) => value + 1);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let active = true;
    async function loadReplayStatus() {
      try {
        const status = await fetchReplayStatus();
        if (active) {
          setReplayStatus(status);
        }
      } catch (error) {
        if (active) {
          setReplayError(error instanceof Error ? error.message : "Unable to load replay status");
        }
      }
    }
    void loadReplayStatus();
    return () => {
      active = false;
    };
  }, [refreshKey]);

  useEffect(() => {
    let active = true;
    async function loadScannerStatus() {
      try {
        const summary = await fetchScannerStatus();
        if (active) {
          setScannerSummary(summary);
        }
      } catch (error) {
        if (active) {
          setScannerError(error instanceof Error ? error.message : "Unable to load scanner status");
        }
      }
    }
    void loadScannerStatus();
    return () => {
      active = false;
    };
  }, [refreshKey]);

  useEffect(() => {
    let active = true;
    async function loadTradingIntelligence() {
      setIntelligenceLoading(true);
      setIntelligenceError(null);
      try {
        const response = await evaluateTradingIntelligence(symbol, timeframe);
        if (active) {
          setIntelligence(response);
        }
      } catch (error) {
        if (active) {
          setIntelligenceError(error instanceof Error ? error.message : "Unable to load trading intelligence");
        }
      } finally {
        if (active) {
          setIntelligenceLoading(false);
        }
      }
    }
    void loadTradingIntelligence();
    return () => {
      active = false;
    };
  }, [symbol, timeframe, refreshKey]);

  const replayActive = isReplayActive(replayStatus);
  const replayCursorTimeMs = replayCursorTimestamp(data.candles, replayStatus);
  const visibleCandles = useMemo(
    () => filterCandlesForReplayCursor(data.candles, replayCursorTimeMs),
    [data.candles, replayCursorTimeMs],
  );
  const visibleStructure = useMemo(
    () => filterStructureForReplayCursor(data.structure, replayCursorTimeMs),
    [data.structure, replayCursorTimeMs],
  );
  const visibleTrend = useMemo(
    () => filterTrendForReplayCursor(data.trend, replayCursorTimeMs),
    [data.trend, replayCursorTimeMs],
  );
  const visibleAois = useMemo(
    () =>
      filterAoisForReplayCursor(
        data.aois.filter(
          (item) =>
            aoiVisible &&
            ((item.timeframe === "1w" && weeklyAoiVisible) ||
              (item.timeframe === "1d" && dailyAoiVisible)),
        ),
        replayCursorTimeMs,
      ),
    [data.aois, aoiVisible, weeklyAoiVisible, dailyAoiVisible, replayCursorTimeMs],
  );
  const visibleAoiOverlaps = useMemo(
    () => filterAoiOverlaps(data.aoiOverlaps, visibleAois, aoiVisible && aoiOverlapVisible),
    [data.aoiOverlaps, visibleAois, aoiVisible, aoiOverlapVisible],
  );
  const trendState = visibleTrend.update?.state ?? "transition";
  const visibleBos = useMemo(
    () => selectVisibleBos(visibleStructure.breaks_of_structure, bosMode),
    [visibleStructure.breaks_of_structure, bosMode],
  );
  const chartDataMessage =
    selectedScannerSymbol === symbol && !loading && errorMessage === null && data.candles.length === 0
      ? `No chart data available for ${symbol} on ${timeframe}`
      : null;
  const replayNoCandlesMessage =
    replayActive && !loading && errorMessage === null && data.candles.length > 0 && visibleCandles.length === 0
      ? "Replay has not produced completed candles yet."
      : null;
  const structureCount = visibleStructure.swings.length;
  const bosCount = visibleStructure.breaks_of_structure.length;
  const runtimeMode = data.health?.mode ?? "mode unknown";
  const replayState = replayStatus?.status ?? "replay unknown";
  const aoiMissingMessage =
    !loading && data.aois.length === 0
      ? "Weekly/Daily AOI inputs are not ready or no active AOIs are cached yet."
      : null;

  async function runReplayAction(action: () => Promise<ReplayStatusDto>): Promise<void> {
    setReplayLoading(true);
    setReplayError(null);
    try {
      const status = await action();
      setReplayStatus(status);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setReplayError(error instanceof Error ? error.message : "Replay action failed");
    } finally {
      setReplayLoading(false);
    }
  }

  async function handleRunScanner(): Promise<void> {
    setScannerLoading(true);
    setScannerError(null);
    try {
      const summary = await runScanner({
        symbols: parseScannerSymbols(scannerSymbols),
        timeframe,
        bias: scannerBias,
        minimum_alignment_score: scannerMinimumAlignment,
        minimum_setup_score: scannerMinimumScore,
        limit: scannerLimit,
      });
      setScannerSummary(summary);
    } catch (error) {
      setScannerError(error instanceof Error ? error.message : "Scanner action failed");
    } finally {
      setScannerLoading(false);
    }
  }

  function selectScannerCandidate(candidate: SetupCandidateDto): void {
    setSelectedScannerSymbol(candidate.symbol);
    setSymbol(candidate.symbol);
    setRefreshKey((value) => value + 1);
  }

  return (
    <main className={`tip-shell trend-${trendBackground ? trendState : "none"}`}>
      <section className="topbar">
        <div className="brand">
          <BarChart3 size={20} />
          <strong>Trading Intelligence Platform</strong>
        </div>
        <div className="controls">
          <select aria-label="Symbol" value={symbol} onChange={(event) => setSymbol(event.target.value)}>
            <option value="BTCUSDT">BTCUSDT</option>
          </select>
          <select
            aria-label="Timeframe"
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value as Timeframe)}
          >
            {TIMEFRAMES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => setBosVisible((value) => !value)} title="Toggle BOS">
            {bosVisible ? <Eye size={16} /> : <EyeOff size={16} />}
            BOS
          </button>
          <select
            aria-label="BOS mode"
            value={bosMode}
            onChange={(event) => setBosMode(event.target.value as BosMode)}
          >
            <option value="permanent">permanent</option>
            <option value="auto-clean">auto-clean</option>
          </select>
          <button
            type="button"
            onClick={() => setTrendBackground((value) => !value)}
            title="Toggle trend background"
          >
            <ToggleLeft size={16} />
            Background
          </button>
          <button type="button" onClick={() => setTrendRibbon((value) => !value)} title="Toggle trend ribbon">
            <Ribbon size={16} />
            Ribbon
          </button>
          <button type="button" onClick={() => setAoiVisible((value) => !value)} title="Toggle AOI visibility">
            {aoiVisible ? <Eye size={16} /> : <EyeOff size={16} />}
            AOI
          </button>
          <button type="button" onClick={() => setWeeklyAoiVisible((value) => !value)} title="Toggle Weekly AOI">
            W AOI
          </button>
          <button type="button" onClick={() => setDailyAoiVisible((value) => !value)} title="Toggle Daily AOI">
            D AOI
          </button>
          <button type="button" onClick={() => setAoiOverlapVisible((value) => !value)} title="Toggle AOI overlap">
            W+D
          </button>
          <select
            aria-label="AOI state filter"
            value={aoiStateFilter}
            onChange={(event) => setAoiStateFilter(event.target.value as AoiStateFilter)}
          >
            <option value="active">active only</option>
            <option value="active_broken">active+broken</option>
            <option value="all">all</option>
          </select>
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} title="Refresh backend data">
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </section>
      <section className="status-strip" aria-live="polite">
        <span>{loading ? "Loading backend data" : "Backend data loaded"}</span>
        <span>Runtime: {runtimeMode}</span>
        <span>Candles: {visibleCandles.length}</span>
        <span>Structure: {structureCount}</span>
        <span>BOS: {bosCount}</span>
        <span>AOIs: {visibleAois.length}/{data.aois.length}</span>
        <span>AOI gate: {data.aoiGate?.eligible ? "eligible" : "closed"}</span>
        <span>Trend: {trendState}</span>
        <span>Replay: {replayState}</span>
        <span>Replay cursor: {replayStatus ? `${replayStatus.processed_events}/${replayStatus.total_events}` : "off"}</span>
        <span>Last refresh: {lastRefreshTime ?? "not yet"}</span>
        {errorMessage ? <strong role="alert">API error: {errorMessage}</strong> : null}
      </section>
      {trendRibbon ? (
        <section className={`trend-ribbon state-${trendState}`}>
          <Layers size={16} />
          <span>{trendState}</span>
          <span>{data.alignmentScore}/3 aligned</span>
        </section>
      ) : null}
      <TradingIntelligencePanel
        intelligence={intelligence}
        readiness={data.readiness}
        loading={intelligenceLoading}
        error={intelligenceError}
      />
      <ReplayControls
        source={replaySource}
        speed={replaySpeed}
        startIndex={replayStartIndex}
        status={replayStatus}
        loading={replayLoading}
        error={replayError}
        onSourceChange={setReplaySource}
        onSpeedChange={setReplaySpeed}
        onStartIndexChange={setReplayStartIndex}
        onStart={() => runReplayAction(() => startReplay(replaySource, replaySpeed, replayStartIndex))}
        onPause={() => runReplayAction(pauseReplay)}
        onResume={() => runReplayAction(resumeReplay)}
        onStop={() => runReplayAction(stopReplay)}
        onStep={() => runReplayAction(stepReplay)}
      />
      <ScannerPanel
        symbols={scannerSymbols}
        bias={scannerBias}
        minimumAlignment={scannerMinimumAlignment}
        minimumScore={scannerMinimumScore}
        limit={scannerLimit}
        summary={scannerSummary}
        loading={scannerLoading}
        error={scannerError}
        onSymbolsChange={setScannerSymbols}
        onBiasChange={setScannerBias}
        onMinimumAlignmentChange={setScannerMinimumAlignment}
        onMinimumScoreChange={setScannerMinimumScore}
        onLimitChange={setScannerLimit}
        onRun={handleRunScanner}
        onSelectCandidate={selectScannerCandidate}
      />
      {replayNoCandlesMessage ? (
        <section className="chart-message" role="status">{replayNoCandlesMessage}</section>
      ) : null}
      {chartDataMessage ? <section className="chart-message" role="status">{chartDataMessage}</section> : null}
      {aoiMissingMessage ? <section className="chart-message" role="status">{aoiMissingMessage}</section> : null}
      <ChartCanvas
        candles={visibleCandles}
        structure={visibleStructure}
        bos={bosVisible ? visibleBos : []}
        aois={visibleAois}
        aoiOverlaps={visibleAoiOverlaps}
      />
    </main>
  );
}

function TradingIntelligencePanel({
  intelligence,
  readiness,
  loading,
  error,
}: {
  intelligence: TradingIntelligenceDto | null;
  readiness: AnalysisReadinessDto | null;
  loading: boolean;
  error: string | null;
}) {
  const entry = intelligence?.entry_decision;
  const risk = intelligence?.risk_plan;
  const checklist = intelligence?.checklist;
  const setup = intelligence?.setup_score;
  const ai = intelligence?.ai_decision;
  const hasMissingData =
    intelligence !== null && (entry?.state === "WAIT" || checklist?.missing_count !== 0 || risk?.state === "INCOMPLETE");
  const effectiveReadiness = intelligence?.readiness ?? readiness;
  const readinessExplanation = readinessExplanationFor(entry?.state, effectiveReadiness?.overall_state);
  const reasons = [...(entry?.reasons ?? []), ...(risk?.reasons ?? []), ...(ai?.reasons.map((item) => item.message ?? item.evidence ?? "") ?? [])]
    .filter(Boolean)
    .slice(0, 5);

  return (
    <section className="intelligence-panel" aria-label="Trading intelligence panel">
      <div className="intelligence-header">
        <strong>Trading Intelligence</strong>
        <span>{loading ? "Loading intelligence" : "Backend intelligence loaded"}</span>
        {error ? <strong role="alert">Intelligence error: {error}</strong> : null}
        {hasMissingData ? <span className="muted-warning">Readiness: {effectiveReadiness?.overall_state ?? "missing"}</span> : null}
      </div>
      {intelligence === null && !loading && error === null ? (
        <div className="intelligence-empty">No trading intelligence response yet.</div>
      ) : null}
      {intelligence !== null ? (
        <>
          <div className="intelligence-grid">
            <Metric label="Entry state" value={entry?.state ?? "missing"} />
            <Metric label="Direction" value={entry?.direction ?? "missing"} />
            <Metric label="Confidence" value={formatPercent(entry?.confidence)} />
            <Metric label="Risk state" value={risk?.state ?? "missing"} />
            <Metric label="Entry price" value={formatNumber(risk?.entry_price)} />
            <Metric label="Stop loss" value={formatNumber(risk?.stop_loss)} />
            <Metric label="Take profit" value={formatNumber(risk?.take_profit)} />
            <Metric label="R:R" value={formatNumber(risk?.risk_reward_ratio)} />
            <Metric label="Checklist" value={checklist?.overall_status ?? "missing"} />
            <Metric label="Checklist counts" value={formatChecklistCounts(checklist)} />
            <Metric label="Setup score" value={formatPercentFromNumber(setup?.percentage)} />
            <Metric label="Setup grade" value={setup?.grade ?? "missing"} />
            <Metric label="AI recommendation" value={ai?.recommendation ?? "missing"} />
            <Metric label="AI confidence" value={formatPercent(ai?.confidence)} />
          </div>
          <p className="ai-explanation">{ai?.explanation ?? "AI explanation unavailable."}</p>
          {effectiveReadiness ? (
            <ReadinessPanel readiness={effectiveReadiness} explanation={readinessExplanation} />
          ) : null}
          {intelligence.aoi_gate ? <AoiReadinessPanel gate={intelligence.aoi_gate} /> : null}
          <div className="intelligence-reasons">
            {reasons.length > 0 ? reasons.map((reason) => <span key={reason}>{reason}</span>) : <span>No reasons supplied.</span>}
          </div>
        </>
      ) : null}
    </section>
  );
}

function ReadinessPanel({
  readiness,
  explanation,
}: {
  readiness: AnalysisReadinessDto;
  explanation: string;
}) {
  return (
    <div className="readiness-panel" aria-label="Data readiness panel">
      <div className="readiness-summary">
        <strong>Data readiness</strong>
        <span>{readiness.overall_state}</span>
        <span>{readiness.reason}</span>
        <span>{explanation}</span>
      </div>
      <div className="readiness-columns">
        <div>
          <span>Available timeframes</span>
          <strong>{readiness.available_timeframes.join(", ") || "none"}</strong>
        </div>
        <div>
          <span>Missing timeframes</span>
          <strong>{readiness.missing_timeframes.join(", ") || "none"}</strong>
        </div>
        <div>
          <span>Entry readiness</span>
          <strong>{readiness.entry_readiness ? "ready" : "not ready"}</strong>
        </div>
        <div>
          <span>Alignment</span>
          <strong>
            {readiness.alignment_readiness.ready
              ? `${readiness.alignment_readiness.alignment_score}/3`
              : `missing ${readiness.alignment_readiness.missing_timeframes.join(", ") || "alignment"}`}
          </strong>
        </div>
      </div>
      <div className="readiness-counts">
        {readiness.candle_counts_by_timeframe.map((item) => (
          <span key={item.timeframe}>
            {item.timeframe}: {item.candle_count}
          </span>
        ))}
      </div>
      <div className="readiness-counts">
        {readiness.trend_readiness_by_timeframe.map((item) => (
          <span key={item.timeframe}>
            {item.timeframe} trend: {item.ready ? item.state : "missing"}
          </span>
        ))}
      </div>
      <div className="readiness-counts">
        {readiness.structure_readiness_by_timeframe.map((item) => (
          <span key={item.timeframe}>
            {item.timeframe} structure: {item.swing_count} swings / {item.bos_count} BOS
          </span>
        ))}
      </div>
      {readiness.missing_reasons.length > 0 ? (
        <div className="readiness-reasons">
          {readiness.missing_reasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AoiReadinessPanel({ gate }: { gate: AoiGateDto }) {
  return (
    <div className="aoi-readiness" aria-label="AOI readiness panel">
      <div className="readiness-summary">
        <strong>AOI location gate</strong>
        <span>{gate.eligible ? "eligible" : "not eligible"}</span>
        <span>{gate.reason_codes.join(", ") || "no AOI reasons"}</span>
      </div>
      <div className="readiness-counts">
        {gate.active_aois.map((area) => (
          <span key={area.aoi_id}>
            {area.timeframe === "1w" ? "Weekly AOI" : "Daily AOI"} {area.state} {formatNumber(area.lower)}-{formatNumber(area.upper)}
          </span>
        ))}
        {gate.overlaps.map((overlap) => (
          <span key={`${overlap.weekly_aoi_id}-${overlap.daily_aoi_id}`}>
            W+D CONFLUENCE {formatNumber(overlap.lower)}-{formatNumber(overlap.upper)}
          </span>
        ))}
      </div>
    </div>
  );
}

function readinessExplanationFor(entryState: string | undefined, readinessState: string | undefined): string {
  if (entryState === "WAIT" && readinessState === "READY") {
    return "WAIT is from neutral or weak market conditions.";
  }
  if (entryState === "WAIT") {
    return "WAIT is from insufficient or warming-up historical data.";
  }
  if (readinessState !== "READY") {
    return "Historical data is still warming up required inputs.";
  }
  return "Required inputs are ready.";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function isReplayActive(status: ReplayStatusDto | null): boolean {
  return status !== null && status.source_type !== null && !["ready", "stopped"].includes(status.status);
}

function replayCursorTimestamp(candles: CandleDto[], status: ReplayStatusDto | null): number | null {
  if (!isReplayActive(status) || candles.length === 0 || status.processed_events <= 0) {
    return null;
  }
  const cursorIndex = Math.min(status.processed_events - 1, candles.length - 1);
  return candles[cursorIndex]?.close_time_ms ?? null;
}

function filterCandlesForReplayCursor(candles: CandleDto[], cursorTimeMs: number | null): CandleDto[] {
  if (cursorTimeMs === null) {
    return candles;
  }
  return candles.filter((candle) => candle.close_time_ms <= cursorTimeMs);
}

function filterStructureForReplayCursor(
  structure: StructureSnapshotDto,
  cursorTimeMs: number | null,
): StructureSnapshotDto {
  if (cursorTimeMs === null) {
    return structure;
  }
  return {
    swings: structure.swings.filter((swing) => swing.candle_close_time_ms <= cursorTimeMs),
    breaks_of_structure: structure.breaks_of_structure.filter((item) => item.candle_close_time_ms <= cursorTimeMs),
  };
}

function filterTrendForReplayCursor(trend: TrendSnapshotDto, cursorTimeMs: number | null): TrendSnapshotDto {
  if (cursorTimeMs === null || trend.update === null || trend.update.event_time_ms <= cursorTimeMs) {
    return trend;
  }
  return { update: null };
}

function filterAoisForReplayCursor(aois: AoiDto[], cursorTimeMs: number | null): AoiDto[] {
  if (cursorTimeMs === null) {
    return aois;
  }
  return aois.filter(
    (area) =>
      area.first_touch_time_ms <= cursorTimeMs &&
      (area.confirmation_time_ms === null || area.confirmation_time_ms <= cursorTimeMs),
  );
}

function filterAoiOverlaps(overlaps: AoiOverlapDto[], aois: AoiDto[], visible: boolean): AoiOverlapDto[] {
  if (!visible) {
    return [];
  }
  const visibleIds = new Set(aois.map((area) => area.aoi_id));
  return overlaps.filter(
    (overlap) => visibleIds.has(overlap.weekly_aoi_id) && visibleIds.has(overlap.daily_aoi_id),
  );
}

function ScannerPanel({
  symbols,
  bias,
  minimumAlignment,
  minimumScore,
  limit,
  summary,
  loading,
  error,
  onSymbolsChange,
  onBiasChange,
  onMinimumAlignmentChange,
  onMinimumScoreChange,
  onLimitChange,
  onRun,
  onSelectCandidate,
}: {
  symbols: string;
  bias: ScannerBiasFilter;
  minimumAlignment: number;
  minimumScore: number;
  limit: number;
  summary: ScannerSummaryDto | null;
  loading: boolean;
  error: string | null;
  onSymbolsChange: (value: string) => void;
  onBiasChange: (value: ScannerBiasFilter) => void;
  onMinimumAlignmentChange: (value: number) => void;
  onMinimumScoreChange: (value: number) => void;
  onLimitChange: (value: number) => void;
  onRun: () => void;
  onSelectCandidate: (candidate: SetupCandidateDto) => void;
}) {
  return (
    <details className="scanner-panel" aria-label="Scanner panel">
      <summary>
        <span>Scanner</span>
        <span>{summary ? `${summary.candidates.length}/${summary.total_symbols} candidates` : "ready"}</span>
      </summary>
      <div className="scanner-controls">
        <label>
          Symbols
          <input
            aria-label="Scanner symbols"
            value={symbols}
            onChange={(event) => onSymbolsChange(event.target.value)}
          />
        </label>
        <label>
          Bias
          <select
            aria-label="Scanner bias filter"
            value={bias}
            onChange={(event) => onBiasChange(event.target.value as ScannerBiasFilter)}
          >
            <option value="any">any</option>
            <option value="bullish">bullish</option>
            <option value="bearish">bearish</option>
            <option value="neutral">neutral</option>
          </select>
        </label>
        <label>
          Min alignment
          <input
            aria-label="Minimum alignment score"
            min={0}
            max={3}
            type="number"
            value={minimumAlignment}
            onChange={(event) => onMinimumAlignmentChange(Number(event.target.value))}
          />
        </label>
        <label>
          Min setup score
          <input
            aria-label="Minimum setup score"
            min={0}
            type="number"
            value={minimumScore}
            onChange={(event) => onMinimumScoreChange(Number(event.target.value))}
          />
        </label>
        <label>
          Top N
          <input
            aria-label="Scanner result limit"
            min={1}
            type="number"
            value={limit}
            onChange={(event) => onLimitChange(Number(event.target.value))}
          />
        </label>
        <button type="button" disabled={loading} onClick={onRun} title="Run scanner">
          <Search size={16} />
          Run scan
        </button>
      </div>
      <div className="scanner-status" aria-live="polite">
        <span>{loading ? "Scanner running" : "Scanner ready"}</span>
        <span>{summary ? `${summary.candidates.length}/${summary.total_symbols} candidates` : "no scan yet"}</span>
        {error ? <strong role="alert">Scanner error: {error}</strong> : null}
      </div>
      {summary && summary.candidates.length === 0 ? (
        <p className="scanner-empty">No scanner candidates match the current filters.</p>
      ) : null}
      {summary && summary.candidates.length > 0 ? (
        <table className="scanner-results">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Bias</th>
              <th>Alignment</th>
              <th>Setup score</th>
              <th>Trend strength</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {summary.candidates.map((candidate) => (
              <tr key={candidate.symbol}>
                <td>
                  <button type="button" onClick={() => onSelectCandidate(candidate)}>
                    {candidate.symbol}
                  </button>
                </td>
                <td>{candidate.bias}</td>
                <td>{candidate.alignment_score}/3</td>
                <td>{candidate.score.toFixed(1)}</td>
                <td>{candidate.trend_strength}</td>
                <td>{candidate.reasons.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </details>
  );
}

function ReplayControls({
  source,
  speed,
  startIndex,
  status,
  loading,
  error,
  onSourceChange,
  onSpeedChange,
  onStartIndexChange,
  onStart,
  onPause,
  onResume,
  onStop,
  onStep,
}: {
  source: ReplaySourceType;
  speed: number;
  startIndex: number;
  status: ReplayStatusDto | null;
  loading: boolean;
  error: string | null;
  onSourceChange: (value: ReplaySourceType) => void;
  onSpeedChange: (value: number) => void;
  onStartIndexChange: (value: number) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onStep: () => void;
}) {
  const progressPercent = Math.round((status?.progress ?? 0) * 100);
  const processed = status?.processed_events ?? 0;
  const total = status?.total_events ?? 0;
  return (
    <details className="replay-panel" aria-label="Replay controls">
      <summary>
        <span>Replay</span>
        <span>{status?.status ?? "ready"}</span>
        <span>{processed}/{total} events</span>
      </summary>
      <div className="replay-controls">
        <select
          aria-label="Replay source"
          value={source}
          onChange={(event) => onSourceChange(event.target.value as ReplaySourceType)}
        >
          <option value="trades">trades</option>
          <option value="candles">candles</option>
        </select>
        <select
          aria-label="Replay speed"
          value={speed}
          onChange={(event) => onSpeedChange(Number(event.target.value))}
        >
          <option value={0.5}>0.5x</option>
          <option value={1}>1x</option>
          <option value={2}>2x</option>
          <option value={5}>5x</option>
        </select>
        <label>
          Replay start candle
          <input
            aria-label="Replay start candle"
            min={0}
            type="number"
            value={startIndex}
            onChange={(event) => onStartIndexChange(Number(event.target.value))}
          />
        </label>
        <button type="button" disabled={loading} onClick={onStart}>Start</button>
        <button type="button" disabled={loading} onClick={onPause}>Pause</button>
        <button type="button" disabled={loading} onClick={onResume}>Resume</button>
        <button type="button" disabled={loading} onClick={onStop}>Stop</button>
        <button type="button" disabled={loading} onClick={onStep}>Step</button>
      </div>
      <div className="replay-status" aria-live="polite">
        <span>Replay: {status?.status ?? "unknown"}</span>
        <span>{processed}/{total} events</span>
        <span>{progressPercent}%</span>
        <span>{status?.source_type ?? "no source"}</span>
        {loading ? <span>Replay action running</span> : null}
        {error ? <strong role="alert">Replay error: {error}</strong> : null}
      </div>
    </details>
  );
}

function ChartCanvas({
  candles,
  structure,
  bos,
  aois,
  aoiOverlaps,
}: {
  candles: CandleDto[];
  structure: StructureSnapshotDto;
  bos: BreakOfStructureDto[];
  aois: AoiDto[];
  aoiOverlaps: AoiOverlapDto[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    if (containerRef.current === null) {
      return;
    }
    let chart: IChartApi | null = null;
    try {
      chart = createChart(containerRef.current, {
        autoSize: true,
        layout: {
          background: { color: "#0f172a" },
          textColor: "#d8dee9",
        },
        grid: {
          vertLines: { color: "#1f2937" },
          horzLines: { color: "#1f2937" },
        },
        rightPriceScale: { borderColor: "#334155" },
        timeScale: { borderColor: "#334155" },
      });
      const candlesSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#2fbf71",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#2fbf71",
        wickDownColor: "#ef4444",
      });
      chartRef.current = chart;
      candleSeriesRef.current = candlesSeries;
      setChartError(null);
    } catch (error) {
      chart?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      setChartError(error instanceof Error ? error.message : "Unable to initialize chart");
    }
    return () => chart?.remove();
  }, []);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (series === null) {
      return;
    }
    series.setData(candles.map(toChartCandle));
    removeAllPriceLines(series);
    for (const swing of structure.swings) {
      series.createPriceLine({
        price: swing.level,
        color: colorForStructureSource(swing.source_timeframe ?? swing.timeframe),
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: swing.display_label ?? swing.label,
      });
    }
    for (const item of bos) {
      series.createPriceLine({
        price: item.broken_level,
        color: item.direction === "bullish" ? "#22c55e" : "#f97316",
        lineWidth: 1,
        lineStyle: 0,
        axisLabelVisible: true,
        title: `BOS ${item.direction}`,
      });
    }
    for (const area of aois) {
      series.createPriceLine({
        price: area.upper,
        color: colorForAoi(area),
        lineWidth: area.timeframe === "1w" ? 2 : 1,
        lineStyle: 1,
        axisLabelVisible: true,
        title: area.timeframe === "1w" ? "WEEKLY AOI" : "DAILY AOI",
      });
      series.createPriceLine({
        price: area.lower,
        color: colorForAoi(area),
        lineWidth: area.timeframe === "1w" ? 2 : 1,
        lineStyle: 1,
        axisLabelVisible: true,
        title: area.timeframe === "1w" ? "WEEKLY AOI" : "DAILY AOI",
      });
    }
    chartRef.current?.timeScale().fitContent();
  }, [candles, structure, bos, aois]);

  return (
    <section className="chart-frame">
      {chartError ? <div className="chart-error" role="alert">Chart error: {chartError}</div> : null}
      <AoiOverlay aois={aois} overlaps={aoiOverlaps} />
      <div ref={containerRef} className="chart-surface" />
    </section>
  );
}

function AoiOverlay({ aois, overlaps }: { aois: AoiDto[]; overlaps: AoiOverlapDto[] }) {
  return (
    <div className="aoi-overlay" aria-label="AOI overlay">
      {aois.map((area) => (
        <div key={area.aoi_id} className={`aoi-box aoi-${area.timeframe} state-${area.state}`}>
          <strong>{area.timeframe === "1w" ? "WEEKLY AOI" : "DAILY AOI"}</strong>
          <span>{area.direction}</span>
          <span>{formatNumber(area.lower)}-{formatNumber(area.upper)}</span>
          <span>{area.confirmation_time_ms ? "tradable" : "candidate"}</span>
        </div>
      ))}
      {overlaps.map((overlap) => (
        <div key={`${overlap.weekly_aoi_id}-${overlap.daily_aoi_id}`} className="aoi-confluence">
          <strong>W+D CONFLUENCE</strong>
          <span>{formatNumber(overlap.lower)}-{formatNumber(overlap.upper)}</span>
        </div>
      ))}
    </div>
  );
}

function toChartCandle(candle: CandleDto): CandlestickData<Time> {
  return {
    time: Math.floor(candle.open_time_ms / 1000) as Time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}

function colorForStructureSource(timeframe: string): string {
  if (timeframe === "1w") return "#a855f7";
  if (timeframe === "1d") return "#38bdf8";
  if (timeframe === "4h") return "#f59e0b";
  return "#94a3b8";
}

function colorForAoi(area: AoiDto): string {
  if (area.timeframe === "1w") {
    return area.direction === "support" ? "#14b8a6" : "#f97316";
  }
  return area.direction === "support" ? "#a3e635" : "#facc15";
}

function selectVisibleBos(items: BreakOfStructureDto[], mode: BosMode): BreakOfStructureDto[] {
  if (mode === "auto-clean") {
    return items.slice(-1);
  }
  return items;
}

function parseScannerSymbols(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "missing";
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "missing";
  }
  return `${Math.round(value * 100)}%`;
}

function formatPercentFromNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "missing";
  }
  return `${value.toFixed(1)}%`;
}

function formatChecklistCounts(checklist: TradingIntelligenceDto["checklist"] | undefined): string {
  if (checklist === undefined) {
    return "missing";
  }
  return `${checklist.pass_count}P/${checklist.fail_count}F/${checklist.warning_count}W/${checklist.missing_count}M`;
}

function removeAllPriceLines(series: ISeriesApi<"Candlestick">): void {
  const priceLines = series.priceLines();
  for (const line of priceLines) {
    series.removePriceLine(line);
  }
}
