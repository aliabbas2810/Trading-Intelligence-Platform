import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const root = process.cwd();
const appSource = readFileSync(join(root, "src", "visualization", "VisualizationApp.tsx"), "utf8");
const apiSource = readFileSync(join(root, "src", "api.ts"), "utf8");
const configSource = readFileSync(join(root, "src", "config.ts"), "utf8");
const typeSource = readFileSync(join(root, "src", "types.ts"), "utf8");
const styleSource = readFileSync(join(root, "src", "styles.css"), "utf8");

test("visualization uses Lightweight Charts and renders backend overlays", () => {
  assert.match(appSource, /from "lightweight-charts"/);
  assert.match(appSource, /CandlestickSeries/);
  assert.match(appSource, /createChart/);
  assert.match(appSource, /addSeries\(CandlestickSeries/);
  assert.match(appSource, /createPriceLine/);
});

test("frontend fetches backend read endpoints", () => {
  assert.match(apiSource, /API_BASE_URL/);
  assert.match(apiSource, /\/candles/);
  assert.match(apiSource, /\/market-structure/);
  assert.match(apiSource, /\/trend-state/);
  assert.match(apiSource, /\/multi-timeframe-alignment/);
  assert.match(apiSource, /\/health/);
  assert.match(apiSource, /URLSearchParams/);
});

test("frontend calls replay control endpoints", () => {
  assert.match(apiSource, /\/replay\/start/);
  assert.match(apiSource, /\/replay\/pause/);
  assert.match(apiSource, /\/replay\/resume/);
  assert.match(apiSource, /\/replay\/stop/);
  assert.match(apiSource, /\/replay\/step/);
  assert.match(apiSource, /\/replay\/status/);
  assert.match(apiSource, /method: "POST"/);
});

test("frontend calls scanner API endpoints", () => {
  assert.match(apiSource, /runScanner/);
  assert.match(apiSource, /fetchScannerStatus/);
  assert.match(apiSource, /\/scanner\/run/);
  assert.match(apiSource, /\/scanner\/status/);
  assert.match(apiSource, /method: "POST"/);
});

test("frontend API base URL and polling are configurable", () => {
  assert.match(configSource, /DEFAULT_API_BASE_URL = "http:\/\/127\.0\.0\.1:8000"/);
  assert.match(configSource, /DEFAULT_POLL_INTERVAL_MS = 0/);
  assert.match(configSource, /VITE_TIP_API_BASE_URL/);
  assert.match(configSource, /VITE_TIP_POLL_INTERVAL_MS/);
  assert.match(appSource, /POLL_INTERVAL_MS/);
  assert.match(appSource, /setInterval/);
});

test("frontend does not calculate structure or trend labels", () => {
  assert.doesNotMatch(appSource, /body_high|body_low|bodyHigh|bodyLow|higher high|lower low/i);
  assert.doesNotMatch(appSource, /TrendEngine|StructureEngine|ReplayController|classify|detectBos|detectSwing/i);
  assert.doesNotMatch(appSource, /new Candle|new Trade|add_candle|add_event|ReplayRecord/i);
});

test("scanner UI does not calculate scanner scores locally", () => {
  assert.doesNotMatch(appSource, /score_candidate|ScannerEngine|setupScore|alignment.*\*|trend.*strength.*\+/i);
  assert.match(appSource, /candidate\.score/);
  assert.match(appSource, /candidate\.reasons/);
});

test("visualization controls required by M7 are present", () => {
  assert.match(appSource, /Symbol/);
  assert.match(appSource, /Timeframe/);
  assert.match(appSource, /Toggle BOS/);
  assert.match(appSource, /BOS mode/);
  assert.match(appSource, /Toggle trend background/);
  assert.match(appSource, /Toggle trend ribbon/);
  assert.match(appSource, /Refresh backend data/);
});

test("replay controls and status are present", () => {
  assert.match(appSource, /ReplayControls/);
  assert.match(appSource, /useState<ReplaySourceType>\("candles"\)/);
  assert.match(appSource, /Replay source/);
  assert.match(appSource, /Replay speed/);
  assert.match(appSource, /Replay start candle/);
  assert.match(appSource, /Start/);
  assert.match(appSource, /Pause/);
  assert.match(appSource, /Resume/);
  assert.match(appSource, /Stop/);
  assert.match(appSource, /Step/);
  assert.match(appSource, /processed_events/);
  assert.match(appSource, /total_events/);
  assert.match(appSource, /progress/);
});

test("replay demo UX defaults to visible candle replay", () => {
  assert.match(appSource, /useState<ReplaySourceType>\("candles"\)/);
  assert.match(appSource, /Replay has not produced completed candles yet\./);
  assert.match(appSource, /replayNoCandlesMessage/);
  assert.doesNotMatch(appSource, /setTimeframe\("1m"\)/);
});

test("TradingView-style replay filters displayed chart data without clearing backend data", () => {
  assert.match(apiSource, /start_index: startIndex/);
  assert.match(appSource, /replayCursorTimestamp/);
  assert.match(appSource, /filterCandlesForReplayCursor/);
  assert.match(appSource, /filterStructureForReplayCursor/);
  assert.match(appSource, /filterTrendForReplayCursor/);
  assert.match(appSource, /candle\.close_time_ms <= cursorTimeMs/);
  assert.match(appSource, /swing\.candle_close_time_ms <= cursorTimeMs/);
  assert.match(appSource, /item\.candle_close_time_ms <= cursorTimeMs/);
  assert.match(appSource, /Replay cursor:/);
  assert.match(appSource, /candles=\{visibleCandles\}/);
  assert.doesNotMatch(appSource, /resetAnalysis|clearCandles|setData\(\{\s*candles: \[\]/);
});

test("replay and scanner panels are collapsible so the chart stays primary", () => {
  assert.match(appSource, /<details className="replay-panel"/);
  assert.match(appSource, /<details className="scanner-panel"/);
  assert.doesNotMatch(appSource, /<details className="replay-panel" open/);
  assert.doesNotMatch(appSource, /<details className="scanner-panel" open/);
  assert.match(styleSource, /\.chart-frame/);
  assert.match(styleSource, /calc\(100vh - 230px\)/);
  assert.match(styleSource, /max\(420px/);
});

test("scanner controls and results are present", () => {
  assert.match(appSource, /ScannerPanel/);
  assert.match(appSource, /Scanner symbols/);
  assert.match(appSource, /Scanner bias filter/);
  assert.match(appSource, /Minimum alignment score/);
  assert.match(appSource, /Minimum setup score/);
  assert.match(appSource, /Scanner result limit/);
  assert.match(appSource, /Run scan/);
  assert.match(appSource, /scanner-results/);
  assert.match(appSource, /candidate\.symbol/);
  assert.match(appSource, /candidate\.bias/);
  assert.match(appSource, /candidate\.alignment_score/);
  assert.match(appSource, /candidate\.trend_strength/);
});

test("scanner filters are represented in request payload", () => {
  assert.match(appSource, /runScanner\(\{/);
  assert.match(appSource, /symbols: parseScannerSymbols\(scannerSymbols\)/);
  assert.match(appSource, /timeframe/);
  assert.match(appSource, /bias: scannerBias/);
  assert.match(appSource, /minimum_alignment_score: scannerMinimumAlignment/);
  assert.match(appSource, /minimum_setup_score: scannerMinimumScore/);
  assert.match(appSource, /limit: scannerLimit/);
});

test("scanner result selection updates chart symbol without local chart data assumptions", () => {
  assert.match(appSource, /selectScannerCandidate/);
  assert.match(appSource, /setSymbol\(candidate\.symbol\)/);
  assert.match(appSource, /No chart data available for/);
  assert.match(appSource, /data\.candles\.length === 0/);
});

test("visualization exposes loading and API error states", () => {
  assert.match(appSource, /loading/);
  assert.match(appSource, /Loading backend data/);
  assert.match(appSource, /Backend data loaded/);
  assert.match(appSource, /errorMessage/);
  assert.match(appSource, /role="alert"/);
  assert.match(appSource, /API error:/);
  assert.match(appSource, /chartError/);
  assert.match(appSource, /Chart error:/);
});

test("visualization exposes stabilization diagnostics", () => {
  assert.match(appSource, /lastRefreshTime/);
  assert.match(appSource, /Runtime:/);
  assert.match(appSource, /Candles:/);
  assert.match(appSource, /Structure:/);
  assert.match(appSource, /BOS:/);
  assert.match(appSource, /Trend:/);
  assert.match(appSource, /Replay:/);
  assert.match(appSource, /Last refresh:/);
  assert.match(appSource, /data\.candles\.length/);
  assert.match(appSource, /visibleStructure\.swings\.length/);
  assert.match(appSource, /visibleStructure\.breaks_of_structure\.length/);
});

test("structure overlays include HH, HL, LH, and LL horizontal labeled lines", () => {
  assert.match(typeSource, /"HH" \| "HL" \| "LH" \| "LL"/);
  assert.match(appSource, /label === "HH"/);
  assert.match(appSource, /label === "HL"/);
  assert.match(appSource, /label === "LH"/);
  assert.match(appSource, /label === "LL"/);
  assert.match(appSource, /axisLabelVisible: true/);
  assert.match(appSource, /title: swing\.label/);
});

test("BOS overlays support visibility and permanent or auto-clean modes", () => {
  assert.match(appSource, /bosVisible/);
  assert.match(appSource, /setBosVisible/);
  assert.match(appSource, /bosVisible \? visibleBos : \[\]/);
  assert.match(appSource, /value="permanent"/);
  assert.match(appSource, /value="auto-clean"/);
  assert.match(appSource, /items\.slice\(-1\)/);
  assert.match(appSource, /title: `BOS \$\{item\.direction\}`/);
});

test("trend background and ribbon are controlled by backend trend data", () => {
  assert.match(appSource, /fetchTrendState\(symbol, timeframe\)/);
  assert.match(appSource, /trendBackground \? trendState : "none"/);
  assert.match(appSource, /setTrendBackground/);
  assert.match(appSource, /trendRibbon \?/);
  assert.match(appSource, /setTrendRibbon/);
  assert.match(appSource, /data\.alignmentScore/);
  assert.match(appSource, /\/3 aligned/);
});

test("timeframe selector changes rendered backend data", () => {
  assert.match(appSource, /const TIMEFRAMES/);
  assert.match(typeSource, /"1w" \| "1d" \| "4h" \| "2h" \| "1h" \| "30m" \| "15m" \| "5m" \| "1m"/);
  assert.match(appSource, /\["1w", "1d", "4h", "2h", "1h", "30m", "15m", "5m", "1m"\]/);
  assert.match(appSource, /setTimeframe/);
  assert.match(appSource, /fetchCandles\(symbol, timeframe\)/);
  assert.match(appSource, /fetchMarketStructure\(symbol, timeframe\)/);
  assert.match(appSource, /\[symbol, timeframe, refreshKey\]/);
});
