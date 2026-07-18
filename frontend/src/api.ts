import type {
  CandleDto,
  AoiReadDto,
  AoiStateFilter,
  AoiGateDto,
  AnalysisReadinessDto,
  HealthStatusDto,
  MultiTimeframeAlignmentDto,
  ReplaySourceType,
  ReplayStatusDto,
  ScannerRunRequestDto,
  ScannerSummaryDto,
  StructureSnapshotDto,
  Timeframe,
  TradingIntelligenceDto,
  TrendSnapshotDto,
} from "./types";
import { API_BASE_URL } from "./config";

interface RequestOptions {
  signal?: AbortSignal;
}

async function getJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`, { signal: options.signal });
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

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  return search.toString();
}

export function fetchCandles(
  symbol: string,
  timeframe: Timeframe,
  options: RequestOptions & { limit?: number } = {},
): Promise<CandleDto[]> {
  return getJson<CandleDto[]>(`/candles?${query({ symbol, timeframe, limit: options.limit })}`, options);
}

export function fetchMarketStructure(
  symbol: string,
  timeframe: Timeframe,
  options: RequestOptions & { limit?: number } = {},
): Promise<StructureSnapshotDto> {
  return getJson<StructureSnapshotDto>(
    `/market-structure?${query({ symbol, timeframe, limit: options.limit })}`,
    options,
  );
}

export function fetchTrendState(
  symbol: string,
  timeframe: Timeframe,
  options: RequestOptions = {},
): Promise<TrendSnapshotDto> {
  return getJson<TrendSnapshotDto>(`/trend-state?${query({ symbol, timeframe })}`, options);
}

export function fetchMultiTimeframeAlignment(
  symbol: string,
  options: RequestOptions = {},
): Promise<MultiTimeframeAlignmentDto> {
  return getJson<MultiTimeframeAlignmentDto>(`/multi-timeframe-alignment?${query({ symbol })}`, options);
}

export function fetchDataReadiness(symbol: string, options: RequestOptions = {}): Promise<AnalysisReadinessDto> {
  return getJson<AnalysisReadinessDto>(`/data-readiness?${query({ symbol })}`, options);
}

export function fetchAois(
  symbol: string,
  stateFilter: AoiStateFilter,
  options: RequestOptions = {},
): Promise<AoiReadDto> {
  return getJson<AoiReadDto>(`/aois?${query({ symbol, state_filter: stateFilter })}`, options);
}

export function fetchAoiLocation(symbol: string, options: RequestOptions = {}): Promise<AoiGateDto> {
  return getJson<AoiGateDto>(`/aoi-location?${query({ symbol })}`, options);
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

export function evaluateTradingIntelligence(
  symbol: string,
  timeframe: Timeframe,
): Promise<TradingIntelligenceDto> {
  return postJson<TradingIntelligenceDto>("/trading-intelligence/evaluate", {
    symbol,
    timeframe,
  });
}
