import type {
  CandleDto,
  HealthStatusDto,
  MultiTimeframeAlignmentDto,
  StructureSnapshotDto,
  Timeframe,
  TrendSnapshotDto,
} from "./types";
import { API_BASE_URL } from "./config";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string>): string {
  return new URLSearchParams(params).toString();
}

export function fetchCandles(symbol: string, timeframe: Timeframe): Promise<CandleDto[]> {
  return getJson<CandleDto[]>(`/candles?${query({ symbol, timeframe })}`);
}

export function fetchMarketStructure(
  symbol: string,
  timeframe: Timeframe,
): Promise<StructureSnapshotDto> {
  return getJson<StructureSnapshotDto>(`/market-structure?${query({ symbol, timeframe })}`);
}

export function fetchTrendState(symbol: string, timeframe: Timeframe): Promise<TrendSnapshotDto> {
  return getJson<TrendSnapshotDto>(`/trend-state?${query({ symbol, timeframe })}`);
}

export function fetchMultiTimeframeAlignment(symbol: string): Promise<MultiTimeframeAlignmentDto> {
  return getJson<MultiTimeframeAlignmentDto>(`/multi-timeframe-alignment?${query({ symbol })}`);
}

export function fetchHealthStatus(): Promise<HealthStatusDto> {
  return getJson<HealthStatusDto>("/health");
}
