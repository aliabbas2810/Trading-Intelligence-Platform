import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const root = process.cwd();
const appSource = readFileSync(join(root, "src", "visualization", "VisualizationApp.tsx"), "utf8");
const apiSource = readFileSync(join(root, "src", "api.ts"), "utf8");
const typeSource = readFileSync(join(root, "src", "types.ts"), "utf8");

test("visualization uses Lightweight Charts and renders backend overlays", () => {
  assert.match(appSource, /from "lightweight-charts"/);
  assert.match(appSource, /createChart/);
  assert.match(appSource, /addCandlestickSeries/);
  assert.match(appSource, /createPriceLine/);
});

test("frontend fetches backend read endpoints", () => {
  assert.match(apiSource, /\/candles/);
  assert.match(apiSource, /\/market-structure/);
  assert.match(apiSource, /\/trend-state/);
  assert.match(apiSource, /\/multi-timeframe-alignment/);
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
  assert.match(appSource, /data\.alignmentScore\/3 aligned/);
});

test("timeframe selector changes rendered backend data", () => {
  assert.match(appSource, /const TIMEFRAMES/);
  assert.match(appSource, /setTimeframe/);
  assert.match(appSource, /fetchCandles\(symbol, timeframe\)/);
  assert.match(appSource, /fetchMarketStructure\(symbol, timeframe\)/);
  assert.match(appSource, /\[symbol, timeframe\]/);
});
