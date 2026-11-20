import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
after(() => runtime.close());
const { geminiCard } = await runtime.load("src/cards/gemini.tsx");
const { ModelDisclosure, ModelDetailRow } = await runtime.load("src/ui/models.tsx");

test("Gemini model details preserve cache hit and show thinking as reasoning", () => {
  const model = {
    name: "Gemini Pro Orchestrator G1 Pro", in: 3_234_772, cached: 2_538_442,
    out: 17_810, thoughts: 16_348, cost: 7.0649682, pin: 2, pout: 10, pcr: 0.1,
  };
  const ctx = {
    usage: { gemini: { ranges: { week: { ...model, models: [model], sessions: 1 } } } },
    range: "week", rangeLabel: "本周", refreshing: false, pref: (_key, fallback) => fallback,
  };
  const element = geminiCard.render(ctx);
  const card = element.type(element.props);
  const disclosure = card.props.children.find(child => child?.type === ModelDisclosure);
  const [row] = disclosure.props.rows;
  assert.equal(row.total, 5_807_372);
  assert.ok(Math.abs(row.hit - 43.96930375350715) < 1e-9);
  assert.equal(row.tokCW, 0);
  assert.equal(row.tokReason, 16_348);
  const html = renderToStaticMarkup(createElement(ModelDetailRow, { row, tint: geminiCard.tint }));
  assert.match(html, /缓存读/);
  assert.match(html, /推理/);
  assert.doesNotMatch(html, /缓存写/);
});
