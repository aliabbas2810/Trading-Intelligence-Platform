export type Timeframe = "1w" | "1d" | "4h" | "2h" | "1h" | "30m" | "15m" | "5m" | "1m";
export type StructureLabel = "HH" | "HL" | "LH" | "LL";
export type BosDirection = "bullish" | "bearish";
export type TrendState = "bullish" | "bearish" | "transition";
export type DirectionalBias = "bullish" | "bearish" | "neutral";
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
