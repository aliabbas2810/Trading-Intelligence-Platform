import { BarChart3, Eye, EyeOff, Layers, RefreshCw, Ribbon, ToggleLeft } from "lucide-react";
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
  fetchHealthStatus,
  fetchMarketStructure,
  fetchMultiTimeframeAlignment,
  fetchReplayStatus,
  fetchTrendState,
  pauseReplay,
  resumeReplay,
  startReplay,
  stepReplay,
  stopReplay,
} from "../api";
import { POLL_INTERVAL_MS } from "../config";
import type {
  BosMode,
  BreakOfStructureDto,
  CandleDto,
  HealthStatusDto,
  ReplaySourceType,
  ReplayStatusDto,
  StructureSnapshotDto,
  Timeframe,
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
}

export function VisualizationApp() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>("4h");
  const [bosVisible, setBosVisible] = useState(true);
  const [bosMode, setBosMode] = useState<BosMode>("permanent");
  const [trendBackground, setTrendBackground] = useState(true);
  const [trendRibbon, setTrendRibbon] = useState(true);
  const [replaySource, setReplaySource] = useState<ReplaySourceType>("trades");
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [replayStatus, setReplayStatus] = useState<ReplayStatusDto | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [data, setData] = useState<VisualizationData>({
    candles: [],
    structure: { swings: [], breaks_of_structure: [] },
    trend: { update: null },
    alignmentScore: 0,
    health: null,
  });

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setErrorMessage(null);
      try {
        const [candles, structure, trend, alignment, health] = await Promise.all([
          fetchCandles(symbol, timeframe),
          fetchMarketStructure(symbol, timeframe),
          fetchTrendState(symbol, timeframe),
          fetchMultiTimeframeAlignment(symbol),
          fetchHealthStatus(),
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
        });
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
  }, [symbol, timeframe, refreshKey]);

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

  const trendState = data.trend.update?.state ?? "transition";
  const visibleBos = useMemo(
    () => selectVisibleBos(data.structure.breaks_of_structure, bosMode),
    [data.structure.breaks_of_structure, bosMode],
  );

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
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} title="Refresh backend data">
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </section>
      <section className="status-strip" aria-live="polite">
        <span>{loading ? "Loading backend data" : "Backend data loaded"}</span>
        <span>{data.health?.state ?? "status unknown"}</span>
        {errorMessage ? <strong role="alert">API error: {errorMessage}</strong> : null}
      </section>
      {trendRibbon ? (
        <section className={`trend-ribbon state-${trendState}`}>
          <Layers size={16} />
          <span>{trendState}</span>
          <span>{data.alignmentScore}/3 aligned</span>
        </section>
      ) : null}
      <ReplayControls
        source={replaySource}
        speed={replaySpeed}
        status={replayStatus}
        loading={replayLoading}
        error={replayError}
        onSourceChange={setReplaySource}
        onSpeedChange={setReplaySpeed}
        onStart={() => runReplayAction(() => startReplay(replaySource, replaySpeed))}
        onPause={() => runReplayAction(pauseReplay)}
        onResume={() => runReplayAction(resumeReplay)}
        onStop={() => runReplayAction(stopReplay)}
        onStep={() => runReplayAction(stepReplay)}
      />
      <ChartCanvas
        candles={data.candles}
        structure={data.structure}
        bos={bosVisible ? visibleBos : []}
      />
    </main>
  );
}

function ReplayControls({
  source,
  speed,
  status,
  loading,
  error,
  onSourceChange,
  onSpeedChange,
  onStart,
  onPause,
  onResume,
  onStop,
  onStep,
}: {
  source: ReplaySourceType;
  speed: number;
  status: ReplayStatusDto | null;
  loading: boolean;
  error: string | null;
  onSourceChange: (value: ReplaySourceType) => void;
  onSpeedChange: (value: number) => void;
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
    <section className="replay-panel" aria-label="Replay controls">
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
    </section>
  );
}

function ChartCanvas({
  candles,
  structure,
  bos,
}: {
  candles: CandleDto[];
  structure: StructureSnapshotDto;
  bos: BreakOfStructureDto[];
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
        color: colorForStructureLabel(swing.label),
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: swing.label,
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
    chartRef.current?.timeScale().fitContent();
  }, [candles, structure, bos]);

  return (
    <section className="chart-frame">
      {chartError ? <div className="chart-error" role="alert">Chart error: {chartError}</div> : null}
      <div ref={containerRef} className="chart-surface" />
    </section>
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

function colorForStructureLabel(label: string): string {
  if (label === "HH") return "#38bdf8";
  if (label === "HL") return "#22c55e";
  if (label === "LH") return "#f59e0b";
  if (label === "LL") return "#ef4444";
  return "#94a3b8";
}

function selectVisibleBos(items: BreakOfStructureDto[], mode: BosMode): BreakOfStructureDto[] {
  if (mode === "auto-clean") {
    return items.slice(-1);
  }
  return items;
}

function removeAllPriceLines(series: ISeriesApi<"Candlestick">): void {
  const priceLines = series.priceLines();
  for (const line of priceLines) {
    series.removePriceLine(line);
  }
}
