import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const root = process.cwd();
const appSource = readFileSync(join(root, "src", "visualization", "VisualizationApp.tsx"), "utf8");
const apiSource = readFileSync(join(root, "src", "api.ts"), "utf8");
const configSource = readFileSync(join(root, "src", "config.ts"), "utf8");
const typeSource = readFileSync(join(root, "src", "types.ts"), "utf8");

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

test("frontend API base URL and polling are configurable", () => {
  assert.match(configSource, /DEFAULT_API_BASE_URL = "http:\/\/127\.0\.0\.1:8000"/);
  assert.match(configSource, /VITE_TIP_API_BASE_URL/);
  assert.match(configSource, /VITE_TIP_POLL_INTERVAL_MS/);
  assert.match(appSource, /POLL_INTERVAL_MS/);
  assert.match(appSource, /setInterval/);
});

test("frontend does not calculate structure or trend labels", () => {
  assert.doesNotMatch(appSource, /body_high|body_low|bodyHigh|bodyLow|higher high|lower low/i);
  assert.doesNotMatch(appSource, /TrendEngine|StructureEngine|classify|detectBos|detectSwing/i);
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
