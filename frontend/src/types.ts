export type Timeframe = "1w" | "1d" | "4h" | "2h" | "1h" | "30m" | "15m" | "5m" | "1m";
export type StructureLabel = "HH" | "HL" | "LH" | "LL";
export type BosDirection = "bullish" | "bearish";
export type TrendState = "bullish" | "bearish" | "transition";
export type DirectionalBias = "bullish" | "bearish" | "neutral";
export type ScannerBiasFilter = DirectionalBias | "any";
export type BosMode = "permanent" | "auto-clean";
export type ReplaySourceType = "trades" | "candles";

export interface CandleDto {
  symbol: string;
  timeframe: Timeframe;
  open_time_ms: number;
  close_time_ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StructureSwingDto {
  symbol: string;
  timeframe: Timeframe;
  kind: "high" | "low";
  label: StructureLabel;
  level: number;
  candle_open_time_ms: number;
  candle_close_time_ms: number;
}

export interface BreakOfStructureDto {
  symbol: string;
  timeframe: Timeframe;
  direction: BosDirection;
  broken_label: StructureLabel;
  broken_level: number;
  candle_close: number;
  candle_open_time_ms: number;
  candle_close_time_ms: number;
}

export interface StructureSnapshotDto {
  swings: StructureSwingDto[];
  breaks_of_structure: BreakOfStructureDto[];
}

export interface TrendSnapshotDto {
  update: {
    symbol: string;
    timeframe: Timeframe;
    state: TrendState;
    previous_state: TrendState | null;
    strength: {
      confirming_structure_count: number;
    };
    reason: string;
    event_time_ms: number;
  } | null;
}

export interface MultiTimeframeAlignmentDto {
  symbol: string;
  mode: "voting" | "hierarchical";
  bias: DirectionalBias;
  alignment_score: number;
  reason: string;
}

export interface TimeframeCandleReadinessDto {
  timeframe: Timeframe;
  candle_count: number;
  available: boolean;
}

export interface StructureTimeframeReadinessDto {
  timeframe: Timeframe;
  ready: boolean;
  swing_count: number;
  bos_count: number;
}

export interface TrendTimeframeReadinessDto {
  timeframe: Timeframe;
  ready: boolean;
  state: TrendState | null;
}

export interface AlignmentReadinessDto {
  ready: boolean;
  alignment_score: number | null;
  missing_timeframes: Timeframe[];
}

export interface AnalysisReadinessDto {
  symbol: string;
  required_timeframes: Timeframe[];
  available_timeframes: Timeframe[];
  missing_timeframes: Timeframe[];
  candle_counts_by_timeframe: TimeframeCandleReadinessDto[];
  structure_readiness_by_timeframe: StructureTimeframeReadinessDto[];
  trend_readiness_by_timeframe: TrendTimeframeReadinessDto[];
  alignment_readiness: AlignmentReadinessDto;
  entry_readiness: boolean;
  overall_state: "READY" | "WARMING_UP" | "INSUFFICIENT_DATA";
  reason: string;
  missing_reasons: string[];
}

export interface HealthStatusDto {
  state: string;
  mode: string;
  components: Record<string, string>;
}

export interface ReplayStatusDto {
  source_type: ReplaySourceType | null;
  status: string;
  processed_events: number;
  total_events: number;
  current_timestamp_ms: number | null;
  speed_multiplier: number;
  progress: number;
  running: boolean;
  paused: boolean;
  stopped: boolean;
}

export interface ScannerRunRequestDto {
  symbols?: string[];
  timeframe?: Timeframe;
  bias?: ScannerBiasFilter;
  minimum_alignment_score?: number;
  minimum_setup_score?: number;
  limit?: number;
}

export interface SetupCandidateDto {
  symbol: string;
  bias: DirectionalBias;
  score: number;
  alignment_score: number;
  trend_state: TrendState | null;
  trend_strength: number;
  has_structure: boolean;
  has_bos: boolean;
  latest_price: number | null;
  reasons: string[];
}

export interface SymbolScanResultDto {
  symbol: string;
  candidate: SetupCandidateDto | null;
  excluded_reasons: string[];
}

export interface ScannerSummaryDto {
  scanned_symbols: string[];
  total_symbols: number;
  filtered_symbols: number;
  candidates: SetupCandidateDto[];
  results: SymbolScanResultDto[];
}

export interface EvidenceDto {
  code?: string;
  category?: string;
  description?: string;
  message?: string;
  evidence?: string;
  severity?: string;
  timeframe?: Timeframe | null;
}

export interface TradingIntelligenceDto {
  symbol: string;
  timeframe: Timeframe;
  entry_decision: {
    state: string;
    direction: string;
    confidence: number;
    reasons: string[];
    evidence: EvidenceDto[];
    missing_confirmations: string[];
    invalidation_conditions: string[];
    trigger_timeframe: Timeframe | null;
  };
  risk_plan: {
    direction: string;
    state: string;
    entry_price: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    risk_reward_ratio: number | null;
    invalidation_level: number | null;
    risk_level: string | null;
    reasons: string[];
    warnings: string[];
  };
  checklist: {
    overall_status: string;
    pass_count: number;
    fail_count: number;
    warning_count: number;
    missing_count: number;
    summary: string;
  };
  setup_score: {
    total_score: number;
    max_score: number;
    percentage: number;
    grade: string;
    summary: string;
    warnings: string[];
  };
  ai_decision: {
    recommendation: string;
    confidence: number;
    explanation: string;
    reasons: EvidenceDto[];
    provider: string;
  };
  readiness: AnalysisReadinessDto | null;
  metadata: Record<string, string | number | boolean | null>;
}
