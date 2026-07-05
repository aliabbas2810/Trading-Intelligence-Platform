import type {
  CandleDto,
  MultiTimeframeAlignmentDto,
  StructureSnapshotDto,
  Timeframe,
  TrendSnapshotDto,
} from "./types";

const API_BASE = "/api";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchCandles(symbol: string, timeframe: Timeframe): Promise<CandleDto[]> {
  return getJson<CandleDto[]>(`/candles?symbol=${symbol}&timeframe=${timeframe}`);
}

export function fetchMarketStructure(
  symbol: string,
  timeframe: Timeframe,
): Promise<StructureSnapshotDto> {
  return getJson<StructureSnapshotDto>(`/market-structure?symbol=${symbol}&timeframe=${timeframe}`);
}

export function fetchTrendState(symbol: string, timeframe: Timeframe): Promise<TrendSnapshotDto> {
  return getJson<TrendSnapshotDto>(`/trend-state?symbol=${symbol}&timeframe=${timeframe}`);
}

export function fetchMultiTimeframeAlignment(symbol: string): Promise<MultiTimeframeAlignmentDto> {
  return getJson<MultiTimeframeAlignmentDto>(`/multi-timeframe-alignment?symbol=${symbol}`);
}
