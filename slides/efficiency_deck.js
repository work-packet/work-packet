// Builds slides/work-packet-efficiency.pptx: what the dvs-enh run says about splitting
// long work into steps (tokens, quota), plus the board's visibility and many projects.
// Data: slides/dvs-enh-series.json, from docs/experiments/dvs-enh-series.py.
// Run: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> \
//      PPTX_SKILL=<pptx skill dir> node slides/efficiency_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");
const DATA = require("./dvs-enh-series.json");

const OUT = path.join(__dirname, "work-packet-efficiency.pptx");

// Same theme as work-packet-overview.pptx, so the two decks sit together.
const THEME = {
  name: "Phosphor",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1C2128", lt1: "FFFFFF", dk2: "33414F", lt2: "EEF1F4",
    accent1: "E8A33D", accent2: "2A9D8F", accent3: "6B7B8C",
    accent4: "C8553D", accent5: "F6E3C1", accent6: "D5ECE9",
    hlink: "2A9D8F", folHlink: "6B7B8C",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "work-packet on dvs-enh: cheaper, visible, many projects";
pres.author = "Matthew Ballance";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: "#" + color, size: "256" }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// ---------- layouts ----------
const W = 13.333, MX = 0.6, CW = W - 2 * MX;
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 1.9, w: 11.5, h: 1.8,
      fontSize: 48, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.95, w: 11, h: 1.4,
      fontSize: 20, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 1.9, w: 11.5, h: 2.2,
      fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 4.35, w: 11, h: 0.9,
      fontSize: 18, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.5, w: CW, h: 0.9,
      fontSize: 40, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 34, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "work-packet · the dvs-enh run", options: { x: MX, y: 6.95, w: 5, h: 0.3,
      fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});

// ---------- helpers ----------
let n = 0;
function card(slide, x, y, w, h, fill, line) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, fill: { color: fill }, line: { color: line || fill, width: 0.75 }, rectRadius: 0.08,
    objectName: "card" + (++n),
  });
}
function txt(slide, text, opts) {
  slide.addText(text, Object.assign({ isTextBox: true, margin: 0, valign: "top",
    fontSize: 15, color: C.text1, objectName: "t" + (++n) }, opts));
}
function circleIcon(slide, data, x, y, d, fill) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill },
    line: { color: fill }, objectName: "ic" + (++n) });
  const p = d * 0.25;
  slide.addImage({ data, x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: "icimg" + (++n) });
}
function content(title, section) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  return s;
}
function divider(title, sub, section) {
  pres.addSection({ title: section });
  const s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "body" });
  return s;
}
function bullets(items, base) {
  return items.map((it, i) => {
    const o = Object.assign({ bullet: true, paraSpaceAfter: 6 }, base || {});
    if (i < items.length - 1) o.breakLine = true;
    if (typeof it === "string") return { text: it, options: o };
    return { text: it.text, options: Object.assign(o, it.options || {}) };
  });
}
function stat(slide, x, y, w, num, label, opts) {
  opts = opts || {};
  txt(slide, num, { x, y, w, h: 0.95, fontSize: opts.size || 48, bold: true,
    color: opts.color || C.accent1, fontFace: THEME.headFontFace, valign: "bottom" });
  txt(slide, label, { x, y: y + 1.0, w, h: opts.lh || 0.75, fontSize: 13, color: opts.lcolor || C.text2 });
}
function chartBase(extra) {
  return Object.assign({
    catAxisLabelColor: HEX.dk2, valAxisLabelColor: HEX.accent3,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt",
    titleFontFace: "+mn-lt", legendFontFace: "+mn-lt", catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
    dataLabelFontSize: 12, titleFontSize: 14, titleColor: HEX.dk1, dataLabelColor: HEX.dk1,
    legendFontSize: 12, legendColor: HEX.dk2,
    valGridLine: { color: "DDE2E7", size: 0.5 }, catGridLine: { style: "none" },
    showValue: false, showLegend: false, showTitle: true,
  }, extra);
}
// Icon rows: [[icon, head, body], ...] in a column at x.
function iconRows(slide, rows, x, y, w, gap, fill) {
  rows.forEach((r, i) => {
    const yy = y + i * gap;
    circleIcon(slide, r[0], x, yy, 0.62, fill || C.accent2);
    txt(slide, r[1], { x: x + 0.85, y: yy - 0.02, w: w - 0.85, h: 0.36, fontSize: 17, bold: true });
    txt(slide, r[2], { x: x + 0.85, y: yy + 0.36, w: w - 0.85, h: gap - 0.45, fontSize: 14, color: C.text2 });
  });
}

async function build() {
  const I = {};
  const ic = { coins: fa.FaCoins, layers: fa.FaLayerGroup, chart: fa.FaChartLine, eye: fa.FaEye,
    list: fa.FaClipboardList, terminal: fa.FaTerminal, comments: fa.FaComments, sitemap: fa.FaSitemap,
    redo: fa.FaRedo, book: fa.FaBookOpen, clock: fa.FaHourglassHalf, gauge: fa.FaTachometerAlt,
    server: fa.FaServer, lock: fa.FaLock, folder: fa.FaFolderOpen, bolt: fa.FaBolt, search: fa.FaSearch,
    hand: fa.FaHandPaper, compress: fa.FaCompressAlt, flag: fa.FaFlagCheckered };
  for (const k of Object.keys(ic)) I[k] = await icon(ic[k], HEX.lt1);

  let s;
  // ===================================================== Intro
  pres.addSection({ title: "Introduction" });
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Many short steps beat one long session", { placeholder: "title" });
  s.addText("What the dvs-enh run says about work-packet: cost and quota, visibility, and many projects",
    { placeholder: "body" });
  s.addNotes("dvs-enh: six items of a dv-solve enhancement plan, run by work-packet as 31 Claude Code "
    + "steps (Sonnet 5) between 23 and 24 October 2026.");

  s = content("The run: six enhancement items, 31 steps, about a day", "Introduction");
  const st = [["31", "steps passed\n(plus 7 failed attempts)"], ["1,857", "model calls"],
    ["$46", "reported cost"], ["11%", "of the weekly quota"]];
  st.forEach((v, i) => stat(s, MX + i * 3.05, 1.55, 2.8, v[0], v[1]));
  card(s, MX, 3.75, CW, 2.75, C.background2);
  txt(s, "The task", { x: MX + 0.35, y: 3.98, w: 5, h: 0.4, fontSize: 18, bold: true });
  txt(s, bullets([
    "Items 0–5 of the dv-solve enhancement plan, on a branch of a git clone",
    "Step 1 planned: an outline of sub-items, each one or two steps of 20–40 minutes",
    "Each later step read the outline and state, did one sub-item, and committed code and tests",
    "Elapsed time 16:05 on 23 Oct to 17:08 on 24 Oct, including waits for my answers",
  ]), { x: MX + 0.35, y: 4.45, w: CW - 0.7, h: 1.95, fontSize: 15 });

  // ===================================================== Tokens
  divider("Cost: steps against one monolithic session",
    "Replaying the same calls as one long conversation", "Tokens and quota");

  s = content("Every call re-reads its context, so context size is the cost", "Tokens and quota");
  // Every 4th call, to keep the chart light.
  const every = (a, k) => a.filter((_, i) => i % k === 0);
  const wp = every(DATA.ctx_wp, 4).map(v => v / 1000);
  const m200 = every(DATA.ctx_m200, 4).map(v => v / 1000);
  const m900 = every(DATA.ctx_m900, 4).map(v => v / 1000);
  const labels = wp.map((_, i) => (i * 4) % 200 === 0 ? String(i * 4) : "");
  s.addChart(pres.charts.LINE, [
    { name: "Monolithic, 1M model default (compacts near 1M)", labels, values: m900 },
    { name: "Monolithic, auto-compacts at 200k", labels, values: m200 },
    { name: "work-packet steps", labels, values: wp },
  ], chartBase({
    x: MX, y: 1.35, w: 8.4, h: 5.4, title: "Context per call (k tokens)",
    chartColors: [HEX.accent4, HEX.accent1, HEX.accent2], lineSize: 1.5, lineDataSymbol: "none",
    showLegend: true, legendPos: "b", catAxisTitle: "call",
    showCatAxisTitle: true, catAxisTitleFontSize: 12, catAxisTitleColor: HEX.accent3,
    catAxisTitleFontFace: "+mn-lt", objectName: "ctxchart",
  }));
  txt(s, bullets([
    { text: "Every call pays to re-read everything in context (mostly from the cache, but paid all the same)." },
    { text: "A step starts again at about 24k tokens: the prompt, the outline and the state." },
    { text: "A long session only shrinks when it compacts, so its calls carry far more." },
  ], { paraSpaceAfter: 12 }), { x: 9.35, y: 1.6, w: 3.4, h: 4.8, fontSize: 15 });
  s.addNotes("Simulated from the 31 passing steps: each step's calls are replayed on top of everything "
    + "carried from earlier steps; at the threshold the context compacts to a 20k summary.");

  s = content("Over the run, the gap keeps widening", "Tokens and quota");
  const sl = DATA.wp.map((_, i) => String(i + 1));
  s.addChart(pres.charts.LINE, [
    { name: "Monolithic, 1M model default", labels: sl, values: DATA.m900 },
    { name: "Monolithic, auto-compacts at 200k", labels: sl, values: DATA.m200 },
    { name: "work-packet steps", labels: sl, values: DATA.wp },
  ], chartBase({
    x: MX, y: 1.35, w: 8.4, h: 5.4, title: "Estimated cumulative cost of context and output ($)",
    chartColors: [HEX.accent4, HEX.accent1, HEX.accent2], lineSize: 2.5, lineDataSymbol: "none",
    showLegend: true, legendPos: "b", catAxisLabelFrequency: 5, catAxisTitle: "step",
    showCatAxisTitle: true, catAxisTitleFontSize: 12, catAxisTitleColor: HEX.accent3,
    catAxisTitleFontFace: "+mn-lt", valAxisLabelFormatCode: "$0", objectName: "cumchart",
  }));
  stat(s, 9.35, 1.5, 3.4, "1.7×", "the cost of one session that auto-compacts at 200k");
  stat(s, 9.35, 3.65, 3.4, "5.4×", "on a 1M model left at its default: a bigger window costs more, not less", { color: C.accent4 });
  s.addNotes("Estimated at Sonnet-class price ratios: cache read 0.30, cache write 3.75, output 15 per "
    + "million tokens. The steps' own estimate ($42) is close to the reported $46.");

  s = content("Every monolithic setup costs more", "Tokens and quota");
  const hdr = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text1 } } });
  const rows = [
    ["work-packet, 31 steps", "111M", "$42", "1.0×"],
    ["Monolithic, compacts at 200k", "190M", "$71", "1.7×"],
    ["Monolithic, compacts at 400k", "341M", "$114", "2.7×"],
    ["Monolithic, compacts near 1M (1M model default)", "727M", "$228", "5.4×"],
    ["Monolithic, never compacts", "2,019M", "$614", "14.5×"],
  ];
  s.addTable([[hdr("Run as"), hdr("Context read"), hdr("Est. cost"), hdr("vs. steps")]].concat(
    rows.map((r, i) => r.map((c, j) => ({ text: c, options: {
      bold: i === 0, color: i === 0 ? C.accent2 : C.text1, align: j ? "right" : "left",
      fill: { color: i % 2 ? C.background2 : C.background1 } } })))), {
    x: MX, y: 1.5, w: 8.2, colW: [4.3, 1.4, 1.2, 1.3], fontSize: 15, rowH: 0.55,
    border: { type: "solid", pt: 0.5, color: "DDE2E7" }, margin: [0, 0.1, 0, 0.1], valign: "middle",
    objectName: "costtable",
  });
  card(s, 9.2, 1.5, 3.53, 3.3, C.accent6);
  circleIcon(s, I.gauge, 9.5, 1.8, 0.62, C.accent2);
  txt(s, "Quota follows cost", { x: 9.5, y: 2.6, w: 3.0, h: 0.4, fontSize: 17, bold: true });
  txt(s, "On a subscription, the weekly quota is what runs out. It tracks cost, so the same ratios apply: "
    + "the run used 11% of the week where one session would have used 19% or more.",
    { x: 9.5, y: 3.05, w: 3.0, h: 1.7, fontSize: 14, color: C.text2 });
  txt(s, "Output tokens are the same in every row; the difference is all in context.",
    { x: MX, y: 4.95, w: 8.2, h: 0.4, fontSize: 13, italic: true, color: C.accent3 });

  s = content("Better than compaction, however it is timed", "Tokens and quota");
  const pol = [
    ["work-packet steps", 42.47], ["Ideal: compact at each natural break near 80k", 61.57],
    ["Compact at each sub-item, + auto at 200k", 67.66], ["Auto-compact at 200k", 71.27],
    ["Compact at each sub-item (needs 1M)", 91.68], ["Compact at each top-level item (needs 1M)", 134.52],
    ["1M model default", 227.6],
  ].reverse();
  s.addChart(pres.charts.BAR, [{ name: "Est. cost", labels: pol.map(p => p[0]), values: pol.map(p => p[1]) }],
    chartBase({
      x: MX, y: 1.35, w: 7.4, h: 5.3, barDir: "bar", title: "Estimated cost of dvs-enh by compaction policy ($)",
      chartColors: [HEX.accent4, HEX.accent3, HEX.accent3, HEX.accent1, HEX.accent3, HEX.accent3, HEX.accent2],
      showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "$0", valAxisHidden: true,
      valGridLine: { style: "none" }, barGapWidthPct: 45, catAxisLabelFontSize: 12, objectName: "polchart",
    }));
  card(s, 8.35, 1.45, 4.38, 5.2, C.background2);
  txt(s, "And a more accurate hand-off", { x: 8.65, y: 1.7, w: 3.8, h: 0.4, fontSize: 18, bold: true });
  iconRows(s, [
    [I.compress, "Compaction", "Fires at a token count, often mid-task. Claude Code writes a summary that no one reviews."],
    [I.list, "A step", "Ends at a sub-item boundary. It carries the outline, state files and memento, written on purpose, kept on disk and shown on the board."],
  ], 8.65, 2.3, 3.85, 1.65);
  txt(s, "Even ideal timing, a compaction at every natural break near 80k, costs 1.4×: each compaction is an extra call, and its summary rides along in every later call.",
    { x: 8.65, y: 5.75, w: 3.85, h: 0.75, fontSize: 12, italic: true, color: C.accent3 });
  s.addNotes("Claude Code auto-compacts by default near the model's window; on a 1M model that is near 1M "
    + "unless set lower with --autocompact, /autocompact or autoCompactWindow. The ideal case compacts where each work-packet step ended (about 80k, at a clean point); a user would have to watch the context counter to come close. Plan items: 14 sub-items "
    + "under 7 top-level items; item 1b alone grew to 389k, so item-only policies need a 1M window. "
    + "Simulation details: docs/experiments/dvs-enh-monolithic.md, 'When to compact'.");

  s = content("What splitting costs, and what the model leaves out", "Tokens and quota");
  card(s, MX, 1.45, 5.9, 5.2, C.background2);
  txt(s, "Costs of splitting", { x: MX + 0.35, y: 1.7, w: 5, h: 0.4, fontSize: 20, bold: true });
  iconRows(s, [
    [I.book, "Re-reading files: about $1",
      "141k of the 282k tokens of file reads were files an earlier step had read. A long session "
      + "re-reads too, after each compaction."],
    [I.redo, "Failed attempts: 12% of tokens",
      "7 attempts were thrown away, mostly 30-minute timeouts. That is the biggest cost to cut."],
  ], MX + 0.35, 2.35, 5.3, 1.95, C.accent4);
  card(s, 6.83, 1.45, 5.9, 5.2, C.background2);
  txt(s, "Not in the model", { x: 7.18, y: 1.7, w: 5, h: 0.4, fontSize: 20, bold: true });
  iconRows(s, [
    [I.compress, "Lossy summaries",
      "A compaction keeps a 20k summary; a step keeps state it wrote on purpose."],
    [I.search, "Fewer calls?",
      "One session might have needed fewer calls. This data cannot say."],
    [I.clock, "Simulated, not run",
      "The figures replay the real calls; no monolithic run was made."],
  ], 7.18, 2.35, 5.3, 1.4, C.accent3);

  // ===================================================== Visibility
  divider("Visibility: the board shows what each step is doing",
    "A long session shows one terminal. The board shows the plan, the work and the spend.", "Visibility");

  s = content("Four levels, from all projects down to a single call", "Visibility");
  const lv = [
    [I.sitemap, "Board", ["Every project as a card in its state column", "Questions waiting for you", "Tokens and quota for the last 7 days"]],
    [I.folder, "Project", ["Timeline and packets", "Recent steps: outcome, time, cost", "Tokens per day and per plan item"]],
    [I.list, "Packet", ["Status, next instruction, state files", "Steps table: cost, context, item", "The journal of every event"]],
    [I.search, "Step", ["Context curve per call", "Summary, memento, state changes", "Transcript and a fork command"]],
  ];
  lv.forEach((l, i) => {
    const x = MX + i * 3.05;
    card(s, x, 1.5, 2.8, 4.9, i % 2 ? C.background2 : C.accent6);
    circleIcon(s, l[0], x + 0.3, 1.8, 0.7, C.accent2);
    txt(s, l[1], { x: x + 0.3, y: 2.7, w: 2.2, h: 0.5, fontSize: 22, bold: true, fontFace: THEME.headFontFace });
    txt(s, bullets(l[2], { paraSpaceAfter: 10 }), { x: x + 0.3, y: 3.35, w: 2.3, h: 2.9, fontSize: 15, color: C.text2 });
    if (i < 3) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 2.84, y: 3.75, w: 0.18, h: 0.4,
      fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: "arr" + (++n) });
  });

  s = content("The live view: a running step, refreshed every 3 seconds", "Visibility");
  const pan = [
    [I.bolt, "What it is doing", "The newest 80 events: tool calls, results, messages", MX, 1.45],
    [I.terminal, "Processes", "The step's process tree from /proc: PID, command, CPU, memory, age", 6.83, 1.45],
    [I.list, "Tasks and outline", "This step's to-do list, and the packet's outline checklist with progress", MX, 4.1],
    [I.coins, "Steps done", "Each finished step with its cost; the header shows calls and tokens so far", 6.83, 4.1],
  ];
  pan.forEach(p => {
    card(s, p[3], p[4], 5.9, 2.45, C.background2);
    circleIcon(s, p[0], p[3] + 0.35, p[4] + 0.35, 0.7, C.accent2);
    txt(s, p[1], { x: p[3] + 1.3, y: p[4] + 0.38, w: 4.3, h: 0.45, fontSize: 20, bold: true });
    txt(s, p[2], { x: p[3] + 1.3, y: p[4] + 0.9, w: 4.3, h: 1.3, fontSize: 17, color: C.text2 });
  });
  s.addNotes("A log view of each step shows the transcript as a numbered console, one collapsible "
    + "group per tool call, with log.txt and the raw JSONL to download.");

  s = content("And you can act from the board, not only watch", "Visibility");
  iconRows(s, [
    [I.comments, "Answer questions", "A step that needs a decision asks on the board, with choices and its recommendation filled in. One click takes the recommendations."],
    [I.hand, "Send a note at any time", "A note reaches a running step after its next tool call, or goes into the next step's prompt."],
    [I.redo, "Hand off or pause", "Hand a paused or failed packet back to the runner; pause one that is ready or sleeping."],
    [I.lock, "Change settings", "Allowed tools, limits and the model, per project. Forms are CSRF-protected."],
  ], MX, 1.5, 7.4, 1.3);
  card(s, 8.6, 1.5, 4.13, 4.95, C.text1);
  txt(s, "In one long session", { x: 8.95, y: 1.8, w: 3.5, h: 0.45, fontSize: 18, bold: true, color: C.accent1 });
  txt(s, bullets([
    "You see one terminal, and only while you watch it",
    "A question waits until you come back",
    "Spend shows only as the session's running total",
  ], { paraSpaceAfter: 12 }), { x: 8.95, y: 2.4, w: 3.5, h: 3.8, fontSize: 15, color: "D8DEE4" });

  // ===================================================== Many projects
  divider("Many projects on one board",
    "Each project is one file; the board and the scheduler cover them all", "Many projects");

  s = content("One board for every project, by state", "Many projects");
  const cols = ["Needs you", "Running", "Ready", "Sleeping", "Paused", "Failed", "Done"];
  const cw = 1.12, cg = 0.1;
  cols.forEach((c, i) => {
    const x = MX + i * (cw + cg);
    card(s, x, 1.5, cw, 3.4, C.background2);
    txt(s, c, { x: x + 0.08, y: 1.6, w: cw - 0.16, h: 0.35, fontSize: 12, bold: true,
      color: i === 0 ? C.accent4 : C.text1, align: "center" });
    const k = [1, 1, 1, 0, 0, 1, 2][i];
    for (let j = 0; j < k; j++) {
      card(s, x + 0.1, 2.05 + j * 0.75, cw - 0.2, 0.62, i === 0 ? C.accent5 : C.background1, "C9D1D9");
      s.addShape(pres.shapes.RECTANGLE, { x: x + 0.2, y: 2.2 + j * 0.75, w: cw - 0.5, h: 0.1,
        fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: "bar" + (++n) });
      s.addShape(pres.shapes.RECTANGLE, { x: x + 0.2, y: 2.4 + j * 0.75, w: cw - 0.7, h: 0.08,
        fill: { color: "C9D1D9" }, line: { color: "C9D1D9" }, objectName: "bar" + (++n) });
    }
  });
  txt(s, "Illustration of the board's columns; each card is a project.",
    { x: MX, y: 5.0, w: 8.4, h: 0.35, fontSize: 12, italic: true, color: C.accent3 });
  txt(s, bullets([
    "A card in Needs you shows the question and links to the answer panel",
    "A Running card shows the latest event and links to the live view",
    "Tokens and quota for all projects sit under the columns",
  ]), { x: MX, y: 5.45, w: 8.4, h: 1.3, fontSize: 15 });
  card(s, 9.35, 1.5, 3.38, 3.4, C.accent6);
  txt(s, "Instead of", { x: 9.65, y: 1.75, w: 2.8, h: 0.4, fontSize: 17, bold: true });
  txt(s, "one terminal per project, each to be checked for a question, a failure or its spend.",
    { x: 9.65, y: 2.2, w: 2.8, h: 1.5, fontSize: 15, color: C.text2 });
  txt(s, "You look at", { x: 9.65, y: 3.4, w: 2.8, h: 0.4, fontSize: 17, bold: true });
  txt(s, "one page, sorted by what needs you first.",
    { x: 9.65, y: 3.85, w: 2.8, h: 0.9, fontSize: 15, color: C.text2 });

  s = content("How the projects are run: built today, and next", "Many projects");
  card(s, MX, 1.45, 5.9, 5.2, C.background2);
  txt(s, "Built", { x: MX + 0.35, y: 1.7, w: 5, h: 0.4, fontSize: 20, bold: true, color: C.accent2 });
  iconRows(s, [
    [I.folder, "A registry of projects", "One file per project in ~/.work-packet/projects/; wpk new, adopt and rm."],
    [I.clock, "One scheduler pass for all", "wpk tick advances every registered project, for example from cron."],
    [I.lock, "The board on the tailnet", "wpk dash --tailnet admits only your own Tailscale login."],
  ], MX + 0.35, 2.3, 5.3, 1.4);
  card(s, 6.83, 1.45, 5.9, 5.2, C.background2);
  txt(s, "Planned", { x: 7.18, y: 1.7, w: 5, h: 0.4, fontSize: 20, bold: true, color: C.accent1 });
  iconRows(s, [
    [I.server, "One daemon", "wpkd runs the runner and the board in one process under systemd."],
    [I.gauge, "Budgets", "The runner enforces a daily budget and an hourly step limit across projects."],
    [I.terminal, "A TUI", "wpk tui: the same questions and actions in the terminal."],
  ], 7.18, 2.3, 5.3, 1.4, C.accent1);

  // ===================================================== Close
  pres.addSection({ title: "Close" });
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Close" });
  s.addText("Takeaways", { placeholder: "title" });
  const take = [
    [I.coins, "Cheaper", "1.7× less than auto-compacting at 200k, 1.4× even against ideally timed compaction, and the same against the weekly quota."],
    [I.eye, "Visible", "The outline, processes, logs and spend of every step are on the board as they happen."],
    [I.sitemap, "Many projects", "One board for every project, sorted by what needs you, reachable on the tailnet."],
    [I.flag, "Next", "Cut failed attempts (timeouts) first, and watch quota per step now that it is recorded."],
  ];
  take.forEach((t, i) => {
    const x = MX + i * 3.05;
    card(s, x, 1.75, 2.85, 3.9, C.text2);
    circleIcon(s, t[0], x + 0.3, 2.05, 0.75, i === 3 ? C.accent4 : C.accent2);
    txt(s, t[1], { x: x + 0.3, y: 3.05, w: 2.3, h: 0.5, fontSize: 22, bold: true, color: C.background1,
      fontFace: THEME.headFontFace });
    txt(s, t[2], { x: x + 0.3, y: 3.65, w: 2.3, h: 2.5, fontSize: 15, color: "D8DEE4" });
  });

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
}

build().catch(e => { console.error(e); process.exit(1); });
