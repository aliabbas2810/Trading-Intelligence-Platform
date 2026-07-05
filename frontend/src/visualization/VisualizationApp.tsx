import { BarChart3, Eye, EyeOff, Layers, Ribbon, ToggleLeft } from "lucide-react";
import {
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCandles,
  fetchMarketStructure,
  fetchMultiTimeframeAlignment,
  fetchTrendState,
} from "../api";
import type {
  BosMode,
  BreakOfStructureDto,
  CandleDto,
  StructureSnapshotDto,
  Timeframe,
  TrendSnapshotDto,
} from "../types";

const TIMEFRAMES: Timeframe[] = ["1m", "4h", "1d", "1w"];
const DEFAULT_SYMBOL = "BTCUSDT";

interface VisualizationData {
  candles: CandleDto[];
  structure: StructureSnapshotDto;
  trend: TrendSnapshotDto;
  alignmentScore: number;
}

export function VisualizationApp() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>("4h");
  const [bosVisible, setBosVisible] = useState(true);
  const [bosMode, setBosMode] = useState<BosMode>("permanent");
  const [trendBackground, setTrendBackground] = useState(true);
  const [trendRibbon, setTrendRibbon] = useState(true);
  const [data, setData] = useState<VisualizationData>({
    candles: [],
    structure: { swings: [], breaks_of_structure: [] },
    trend: { update: null },
    alignmentScore: 0,
  });

  useEffect(() => {
    let active = true;
    async function load() {
      const [candles, structure, trend, alignment] = await Promise.all([
        fetchCandles(symbol, timeframe),
        fetchMarketStructure(symbol, timeframe),
        fetchTrendState(symbol, timeframe),
        fetchMultiTimeframeAlignment(symbol),
      ]);
      if (!active) {
        return;
      }
      setData({
        candles,
        structure,
        trend,
        alignmentScore: alignment?.alignment_score ?? 0,
      });
    }
    void load();
    return () => {
      active = false;
    };
  }, [symbol, timeframe]);

  const trendState = data.trend.update?.state ?? "transition";
  const visibleBos = useMemo(
    () => selectVisibleBos(data.structure.breaks_of_structure, bosMode),
    [data.structure.breaks_of_structure, bosMode],
  );

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
        </div>
      </section>
      {trendRibbon ? (
        <section className={`trend-ribbon state-${trendState}`}>
          <Layers size={16} />
          <span>{trendState}</span>
          <span>{data.alignmentScore}/3 aligned</span>
        </section>
      ) : null}
      <ChartCanvas
        candles={data.candles}
        structure={data.structure}
        bos={bosVisible ? visibleBos : []}
      />
    </main>
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

  useEffect(() => {
    if (containerRef.current === null) {
      return;
    }
    const chart = createChart(containerRef.current, {
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
    const candlesSeries = chart.addCandlestickSeries({
      upColor: "#2fbf71",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#2fbf71",
      wickDownColor: "#ef4444",
    });
    chartRef.current = chart;
    candleSeriesRef.current = candlesSeries;
    return () => chart.remove();
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

  return <section ref={containerRef} className="chart-surface" />;
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
