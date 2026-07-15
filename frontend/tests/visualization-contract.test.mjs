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
  assert.match(apiSource, /\/data-readiness/);
  assert.match(apiSource, /\/aois/);
  assert.match(apiSource, /\/aoi-location/);
  assert.match(apiSource, /\/health/);
  assert.match(apiSource, /URLSearchParams/);
});

test("frontend fetches and renders backend AOI overlays", () => {
  assert.match(apiSource, /fetchAois/);
  assert.match(apiSource, /fetchAoiLocation/);
  assert.match(typeSource, /AoiReadDto/);
  assert.match(typeSource, /AoiGateDto/);
  assert.match(appSource, /fetchAois\(symbol, aoiStateFilter\)/);
  assert.match(appSource, /fetchAoiLocation\(symbol\)/);
  assert.match(appSource, /AoiOverlay/);
  assert.match(appSource, /WEEKLY AOI/);
  assert.match(appSource, /DAILY AOI/);
  assert.match(appSource, /W\+D CONFLUENCE/);
});

test("AOI controls and diagnostics are present", () => {
  assert.match(appSource, /Toggle AOI visibility/);
  assert.match(appSource, /Toggle Weekly AOI/);
  assert.match(appSource, /Toggle Daily AOI/);
  assert.match(appSource, /Toggle AOI overlap/);
  assert.match(appSource, /AOI state filter/);
  assert.match(appSource, /active only/);
  assert.match(appSource, /active\+broken/);
  assert.match(appSource, /AOIs:/);
  assert.match(appSource, /AOI gate:/);
});

test("AOI replay visibility uses backend timestamps without local detection", () => {
  assert.match(appSource, /filterAoisForReplayCursor/);
  assert.match(appSource, /area\.first_touch_time_ms <= cursorTimeMs/);
  assert.match(appSource, /area\.confirmation_time_ms === null/);
  assert.match(appSource, /filterAoiOverlaps/);
  assert.doesNotMatch(appSource, /detectAoi|calculateAoi|findAoi|AoiEngine|ActiveStructureLeg/);
  assert.doesNotMatch(appSource, /touch_count\s*[+*/-]|ranking\.score\s*[+*/-]/);
});

test("missing AOI readiness message renders", () => {
  assert.match(appSource, /aoiMissingMessage/);
  assert.match(appSource, /Weekly\/Daily AOI inputs are not ready/);
  assert.match(appSource, /AOI readiness panel/);
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

test("frontend calls trading intelligence endpoint", () => {
  assert.match(apiSource, /evaluateTradingIntelligence/);
  assert.match(apiSource, /\/trading-intelligence\/evaluate/);
  assert.match(apiSource, /symbol,\s*timeframe/);
  assert.match(apiSource, /method: "POST"/);
  assert.match(appSource, /evaluateTradingIntelligence\(symbol, timeframe\)/);
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

test("trading intelligence panel does not calculate intelligence locally", () => {
  assert.doesNotMatch(appSource, /EntrySignalEngine|RiskEngine|ChecklistEngine|SetupScoringEngine|AiDecisionEngine/i);
  assert.doesNotMatch(appSource, /calculateEntry|calculateRisk|calculateChecklist|calculateScore|generateAi/i);
  assert.doesNotMatch(appSource, /stop_loss\s*[<>=]|take_profit\s*[<>=]|risk_reward_ratio\s*[+\-*/]/);
  assert.match(appSource, /entry_decision/);
  assert.match(appSource, /risk_plan/);
  assert.match(appSource, /checklist/);
  assert.match(appSource, /setup_score/);
  assert.match(appSource, /ai_decision/);
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
  assert.match(styleSource, /calc\(100vh - 350px\)/);
  assert.match(styleSource, /max\(380px/);
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

test("trading intelligence panel renders consolidated backend fields", () => {
  assert.match(appSource, /TradingIntelligencePanel/);
  assert.match(appSource, /Trading intelligence panel/);
  assert.match(appSource, /Entry state/);
  assert.match(appSource, /Direction/);
  assert.match(appSource, /Confidence/);
  assert.match(appSource, /Risk state/);
  assert.match(appSource, /Entry price/);
  assert.match(appSource, /Stop loss/);
  assert.match(appSource, /Take profit/);
  assert.match(appSource, /R:R/);
  assert.match(appSource, /Checklist counts/);
  assert.match(appSource, /Setup score/);
  assert.match(appSource, /Setup grade/);
  assert.match(appSource, /AI recommendation/);
  assert.match(appSource, /AI confidence/);
  assert.match(appSource, /ai\?\.explanation/);
});

test("trading intelligence panel updates with symbol timeframe and refresh", () => {
  assert.match(appSource, /const \[intelligence, setIntelligence\]/);
  assert.match(appSource, /const \[intelligenceLoading, setIntelligenceLoading\]/);
  assert.match(appSource, /const \[intelligenceError, setIntelligenceError\]/);
  assert.match(appSource, /\[symbol, timeframe, refreshKey\]/);
  assert.match(appSource, /setRefreshKey\(\(value\) => value \+ 1\)/);
  assert.match(appSource, /setSymbol\(candidate\.symbol\)/);
});

test("trading intelligence panel exposes loading error missing and valid states", () => {
  assert.match(appSource, /Loading intelligence/);
  assert.match(appSource, /Backend intelligence loaded/);
  assert.match(appSource, /Intelligence error:/);
  assert.match(appSource, /Readiness:/);
  assert.match(appSource, /No trading intelligence response yet\./);
  assert.match(appSource, /role="alert"/);
});

test("frontend renders backend readiness diagnostics for historical warm-up", () => {
  assert.match(apiSource, /fetchDataReadiness/);
  assert.match(apiSource, /\/data-readiness/);
  assert.match(typeSource, /AnalysisReadinessDto/);
  assert.match(appSource, /ReadinessPanel/);
  assert.match(appSource, /Data readiness/);
  assert.match(appSource, /Available timeframes/);
  assert.match(appSource, /Missing timeframes/);
  assert.match(appSource, /candle_counts_by_timeframe/);
  assert.match(appSource, /structure_readiness_by_timeframe/);
  assert.match(appSource, /trend_readiness_by_timeframe/);
  assert.match(appSource, /WAIT is from insufficient or warming-up historical data\./);
  assert.match(appSource, /WAIT is from neutral or weak market conditions\./);
});

test("readiness UI does not calculate analysis algorithms locally", () => {
  assert.doesNotMatch(appSource, /MarketStructureEngine|TrendEngine|EntrySignalEngine|RiskEngine/i);
  assert.doesNotMatch(appSource, /detectSwing|detectBos|calculateTrend|calculateEntry|calculateRisk/i);
  assert.doesNotMatch(appSource, /body_high|body_low|bodyHigh|bodyLow/i);
  assert.match(appSource, /readiness\.missing_timeframes/);
  assert.match(appSource, /readiness\.missing_reasons/);
  assert.match(appSource, /No trading intelligence response yet\./);
  assert.match(appSource, /role="alert"/);
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
