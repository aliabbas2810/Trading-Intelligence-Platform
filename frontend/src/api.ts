import type {
  CandleDto,
  HealthStatusDto,
  MultiTimeframeAlignmentDto,
  ReplaySourceType,
  ReplayStatusDto,
  ScannerRunRequestDto,
  ScannerSummaryDto,
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

async function postJson<T>(path: string, payload?: object): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
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

export function startReplay(
  sourceType: ReplaySourceType,
  speedMultiplier: number,
  startIndex: number,
): Promise<ReplayStatusDto> {
  return postJson<ReplayStatusDto>("/replay/start", {
    source_type: sourceType,
    speed_multiplier: speedMultiplier,
    start_index: startIndex,
  });
}

export function pauseReplay(): Promise<ReplayStatusDto> {
  return postJson<ReplayStatusDto>("/replay/pause");
}

export function resumeReplay(): Promise<ReplayStatusDto> {
  return postJson<ReplayStatusDto>("/replay/resume");
}

export function stopReplay(): Promise<ReplayStatusDto> {
  return postJson<ReplayStatusDto>("/replay/stop");
}

export function stepReplay(): Promise<ReplayStatusDto> {
  return postJson<ReplayStatusDto>("/replay/step");
}

export function fetchReplayStatus(): Promise<ReplayStatusDto> {
  return getJson<ReplayStatusDto>("/replay/status");
}

export function runScanner(request: ScannerRunRequestDto): Promise<ScannerSummaryDto> {
  return postJson<ScannerSummaryDto>("/scanner/run", request);
}

export function fetchScannerStatus(): Promise<ScannerSummaryDto> {
  return getJson<ScannerSummaryDto>("/scanner/status");
}
