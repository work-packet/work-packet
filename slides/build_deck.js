// Builds slides/work-packet.pptx — work-packet ("Agents as Processes") concept + prior-art comparison.
// Run: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> node slides/build_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");
const PRIOR = require("./prior_art.js");
const UX = require("./ux.js");

const OUT = path.join(__dirname, "work-packet.pptx");

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
const MONO = "Courier New";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "work-packet: Agents as Processes";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ---------- icons ----------
async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: "#" + color, size: "256" }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// ---------- layouts ----------
const W = 13.333, H = 7.5, MX = 0.6;
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.2, w: 9.5, h: 1.6,
      fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.95, w: 9.0, h: 1.3,
      fontSize: 20, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.9, w: 10, h: 1.2,
      fontSize: 44, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 4.15, w: 10, h: 0.9,
      fontSize: 18, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.6, w: 12.1, h: 0.9,
      fontSize: 40, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 1.5, w: 12.1, h: 0.6,
      fontSize: 18, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: 12.1, h: 0.85,
      fontSize: 34, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "work-packet · Agents as Processes", options: { x: MX, y: 6.95, w: 4, h: 0.3,
      fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});

// ---------- helpers ----------
let n = 0;
function card(slide, x, y, w, h, fill, name) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.08,
    objectName: name || "card" + (++n),
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
function bullets(items, base) {
  return items.map((it, i) => {
    const o = Object.assign({ bullet: true, paraSpaceAfter: 6 }, base || {});
    if (i < items.length - 1) o.breakLine = true;
    if (typeof it === "string") return { text: it, options: o };
    return { text: it.text, options: Object.assign(o, it.options || {}) };
  });
}

async function build() {
  const I = {
    clock: await icon(fa.FaHourglassHalf, HEX.lt1),
    coins: await icon(fa.FaCoins, HEX.lt1),
    eye: await icon(fa.FaEyeSlash, HEX.lt1),
    cubes: await icon(fa.FaCube, HEX.lt1),
    note: await icon(fa.FaStickyNote, HEX.dk1),
    check: await icon(fa.FaCheck, HEX.lt1),
    warn: await icon(fa.FaExclamation, HEX.lt1),
    star: await icon(fa.FaStar, HEX.dk1),
    folder: await icon(fa.FaFolderOpen, HEX.lt1),
  };

  // ===== 1. Title =====
  pres.addSection({ title: "Concept" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Concept" });
  s.addText("work-packet", { placeholder: "title" });
  s.addText("Agents as processes: stored state, mementos and resumable LLM work. The concept, a prototype, and how it compares to prior art",
    { placeholder: "body" });
  txt(s, "packets/<WPID>/memento.md", { x: MX, y: 1.5, w: 8, h: 0.4, fontFace: MONO,
    fontSize: 16, color: C.accent2 });
  txt(s, "October 2026", { x: MX, y: 6.6, w: 4, h: 0.35, fontSize: 12, color: C.accent3 });
  s.addNotes("work-packet (command: wpk). Concept: make LLM agents behave like OS processes; a work packet is one such agent process. Each has an ID, a directory of state, and a 'memento' (next instruction) that lets any fresh, stateless model invocation resume the work.");

  // ===== 2. Problem =====
  s = content("Today, the context window is the process", "Concept");
  const probs = [
    [I.clock, "Ephemeral", "The working state lives in the conversation. When the session ends or is compacted, the state goes with it."],
    [I.coins, "Expensive", "Every turn re-reads the whole history. Long tasks overflow the window and get summarized lossily."],
    [I.eye, "Opaque", "You can't easily inspect, fork, pause or hand off a task halfway through."],
    [I.cubes, "Monolithic", "One long chat instead of small units that can be scheduled, retried and composed."],
  ];
  probs.forEach((p, i) => {
    const y = 1.55 + i * 1.3;
    circleIcon(s, p[0], MX, y, 0.75, C.text2);
    txt(s, p[1], { x: MX + 1.0, y: y - 0.02, w: 6.2, h: 0.4, fontSize: 18, bold: true });
    txt(s, p[2], { x: MX + 1.0, y: y + 0.38, w: 6.4, h: 0.8, fontSize: 14, color: C.text2 });
  });
  card(s, 8.6, 1.55, 4.13, 4.9, C.accent5, "mementoCard");
  circleIcon(s, I.note, 8.95, 1.9, 0.75, C.accent1);
  txt(s, "The Memento model", { x: 8.95, y: 2.85, w: 3.5, h: 0.45, fontSize: 20, bold: true,
    fontFace: THEME.headFontFace });
  txt(s, "Like Leonard in Memento, the model has no long-term memory. So before it \"forgets\", it writes down notes it will trust when it wakes up: what is true, and what to do next.",
    { x: 8.95, y: 3.4, w: 3.5, h: 1.9, fontSize: 15 });
  txt(s, "Context is a cache. The directory holds the truth.", { x: 8.95, y: 5.4, w: 3.5, h: 0.8,
    fontSize: 15, italic: true, bold: true, color: C.text2 });
  s.addNotes("The core move: stop treating context as the place where state lives. Move state into files and treat each model call as a stateless worker.");

  // ===== 3. Anatomy =====
  s = content("A work packet is an agent process in a directory", "Concept");
  card(s, MX, 1.5, 6.0, 4.95, C.text1, "treeCard");
  const tree = [
    ["packets/<WPID>/", "uuid = packet ID", HEX.accent1],
    ["  identity/", "symlinks: deps (ivpm), cache (dv-flow)", HEX.lt1],
    ["  state/", "local files, cloned from parent", HEX.lt1],
    ["  memento.md", "what to do on wake", HEX.accent1],
    ["  status.md", "result, RUNNING / COMPLETED", HEX.lt1],
    ["  stack/", "frames for nested tasks", HEX.lt1],
    ["  children/", "child WPIDs", HEX.lt1],
  ];
  tree.forEach((t, i) => {
    const y = 1.85 + i * 0.6;
    txt(s, t[0], { x: MX + 0.35, y, w: 2.6, h: 0.4, fontFace: MONO, fontSize: 15, bold: true, color: t[2] });
    txt(s, t[1], { x: MX + 2.95, y, w: 2.9, h: 0.5, fontSize: 13, color: "B8C2CC" });
  });
  const map = [
    ["OS concept", "Work packet"],
    ["PID", "WPID (directory name)"],
    ["Program counter", "memento.md"],
    ["Process state / exit code", "status.md"],
    ["Address space", "state/ files"],
    ["cwd, env, mounts", "identity/ symlinks"],
    ["Call stack", "stack/"],
    ["fork()", "spawn child, clone selected state"],
  ];
  s.addTable(map.map((r, i) => r.map(c => ({ text: c, options: {
    bold: i === 0, color: i === 0 ? C.background1 : C.text1,
    fill: { color: i === 0 ? C.text2 : (i % 2 ? C.background2 : C.background1) },
    fontSize: 14, fontFace: (i > 0 && c.match(/[-/.]|APID/)) ? undefined : undefined,
  } }))), { x: 7.0, y: 1.5, w: 5.73, colW: [2.5, 3.23], rowH: 0.52, margin: [0, 0.12, 0, 0.12],
    border: { type: "solid", pt: 0.5, color: "D5DBE1" }, valign: "middle", objectName: "osMap" });
  s.addNotes("Directory layout from Design.md. The mapping table is the mental model: everything an OS keeps in a process control block, the agent keeps as files.");

  // ===== 4. Execution loop =====
  s = content("Each evaluation is one stateless step", "Concept");
  const steps = [
    ["1", "Schedule", "Pick a runnable packet whose wake time has passed"],
    ["2", "Launch", "Start a fresh model call: no memory of earlier steps"],
    ["3", "Restore", "Read next-instr.md, status and state/"],
    ["4", "Work", "Do one bounded unit of work"],
    ["5", "Yield", "Write state, status, next instruction and resume time"],
  ];
  const sw = 2.25, gap = 0.21;
  steps.forEach((st, i) => {
    const x = MX + i * (sw + gap);
    card(s, x, 1.6, sw, 2.5, i === 4 ? C.accent5 : C.background2, "step" + i);
    txt(s, st[0], { x: x + 0.25, y: 1.8, w: 0.8, h: 0.6, fontSize: 32, bold: true,
      color: C.accent1, fontFace: THEME.headFontFace });
    txt(s, st[1], { x: x + 0.25, y: 2.45, w: sw - 0.5, h: 0.4, fontSize: 18, bold: true });
    txt(s, st[2], { x: x + 0.25, y: 2.9, w: sw - 0.45, h: 1.1, fontSize: 14, color: C.text2 });
  });
  txt(s, "↺  repeat until status is COMPLETED", { x: MX, y: 4.3, w: 12, h: 0.4, fontSize: 15,
    italic: true, color: C.accent2, bold: true });
  card(s, MX, 4.95, 12.13, 1.55, C.text1, "cmdCard");
  txt(s, [
    { text: "# executor (test/agent-proc.md)", options: { color: "8A97A5", breakLine: true } },
    { text: "claude -p --model {{model}} \\", options: { color: HEX.lt1, breakLine: true } },
    { text: "  \"Read agent-proc.md. Evaluate process in {{APID}}, returning its status\"", options: { color: HEX.accent1 } },
  ], { x: MX + 0.35, y: 5.15, w: 11.5, h: 1.2, fontFace: MONO, fontSize: 15 });
  s.addNotes("Each step can use a different, cheaper model (the prototype ran on Haiku 4.5). The packet only has to fit its next unit of work in context, not its whole history.");

  // ===== 4b. Scheduled resumption =====
  s = content("A packet can sleep for days, then resume", "Concept");
  const tl = [
    ["step", "Step", "day 0: writes resume: in 10 days"],
    ["sleep", "Asleep, 0 tokens", "just a directory on disk"],
    ["step", "Wake and step", "day 10: writes resume: on 10 Jan"],
    ["sleep", "Asleep, 0 tokens", "a human can read or edit wake_at"],
    ["step", "Wake and step", "10 Jan, or early on a message"],
  ];
  let tx = MX;
  tl.forEach((t, i) => {
    const w = t[0] === "step" ? 1.97 : 2.9;
    card(s, tx, 1.45, w, 1.15, t[0] === "step" ? C.text1 : C.background2, "tl" + i);
    txt(s, t[1], { x: tx + 0.18, y: 1.58, w: w - 0.3, h: 0.35, fontSize: 15, bold: true,
      color: t[0] === "step" ? C.accent1 : C.text1 });
    txt(s, t[2], { x: tx + 0.18, y: 1.95, w: w - 0.3, h: 0.6, fontSize: 12,
      color: t[0] === "step" ? C.background1 : C.text2 });
    tx += w + 0.1;
  });
  txt(s, "The agent writes when, in its memento", { x: MX, y: 2.9, w: 6, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  [["resume: in 10 days", "One-shot, relative to when the step commits"],
   ["resume: on 10 Jan", "One-shot, absolute: the next 10 Jan to come"],
   ["every: monday 08:00", "Recurring: the executor re-arms it, even after a failed step"]].forEach((e, i) => {
    const x = MX + i * 4.115;
    card(s, x, 3.35, 3.9, 1.2, C.accent5, "ex" + i);
    txt(s, e[0], { x: x + 0.2, y: 3.47, w: 3.5, h: 0.4, fontFace: MONO, fontSize: 15, bold: true });
    txt(s, e[1], { x: x + 0.2, y: 3.9, w: 3.55, h: 0.6, fontSize: 13, color: C.text2 });
  });
  txt(s, "The executor makes it reliable", { x: MX, y: 4.8, w: 6, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  [["Code resolves the date", "The model never does date arithmetic; status.md keeps both the expression and the UTC wake_at"],
   ["Missed wakes catch up once", "Machine off on 10 Jan? Run once at the next tick and say \"3 days late\" (like systemd Persistent=)"],
   ["The wake prompt has context", "Now, when it was due, why it slept, and what changed in identity/ meanwhile"],
   ["A fake clock for tests", "WPK_NOW lets \"every Monday for a month\" run in seconds"]].forEach((r, i) => {
    const x = MX + (i % 2) * 6.17, y = 5.25 + Math.floor(i / 2) * 0.8;
    txt(s, [{ text: r[0] + ": ", options: { bold: true } }, { text: r[1], options: { color: C.text2 } }],
      { x, y, w: 5.95, h: 0.75, fontSize: 13 });
  });
  s.addNotes("Scheduled resumption makes work packets periodic: a nightly regression triage, a weekly dependency check, a follow-up on a PR in three days. While asleep the packet costs nothing and is only files, unlike a server-resident agent. Design detail is in docs/roadmap.md, 'Scheduled resumption'.");

  // ===== 5. Spawn =====
  s = content("Packets spawn packets", "Concept");
  txt(s, "Prototype run: test/sub", { x: MX, y: 1.4, w: 6, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  card(s, MX, 1.95, 5.6, 4.5, C.background2, "parentCard");
  txt(s, "parent  APID=sub", { x: MX + 0.3, y: 2.15, w: 5, h: 0.4, fontFace: MONO, fontSize: 15, bold: true });
  txt(s, bullets([
    "next-instr.md: evaluate add_one.md",
    "Read count.md, add 1, write it back",
    "While count < 8: re-evaluate after 1 s (a new model call each time)",
    "Then spawn a child that writes \"Hello World\" to p.md",
  ]), { x: MX + 0.3, y: 2.7, w: 5.0, h: 2.6, fontSize: 15 });
  txt(s, "status.md: COMPLETED  ·  count.md = 9", { x: MX + 0.3, y: 5.75, w: 5.0, h: 0.4,
    fontFace: MONO, fontSize: 13, color: C.text2 });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 6.45, y: 3.85, w: 0.75, h: 0.5,
    fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "spawnArrow" });
  card(s, 7.35, 1.95, 5.38, 1.75, C.text1, "childCard");
  txt(s, "child  APID=3550d964-…", { x: 7.65, y: 2.15, w: 4.9, h: 0.4, fontFace: MONO, fontSize: 15, bold: true, color: C.accent1 });
  txt(s, "next-instr.md: write \"Hello World\" to p.md\nstatus.md: COMPLETED  (Claude Haiku 4.5)",
    { x: 7.65, y: 2.7, w: 4.9, h: 1.1, fontSize: 14, color: C.background1 });
  txt(s, "Spawn inputs (prototype spec)", { x: 7.35, y: 4.35, w: 5, h: 0.4, fontSize: 16, bold: true });
  txt(s, bullets([
    "Parent ID",
    "What to run: the child's first next-instr.md",
    "Which parent state to copy into the child",
  ]), { x: 7.35, y: 4.8, w: 5.3, h: 1.6, fontSize: 15 });
  s.addNotes("This is the fork/exec analogue. The parent's loop survives across many model calls only because the counter and the instruction live in files.");

  // ===== 6. Findings =====
  s = content("What the prototype already shows", "Concept");
  const goods = [
    "A loop survives across separate model calls using only files",
    "Children get their own ID and run to completion",
    "status.md gives a readable audit trail, including which model ran",
    "A small model (Haiku 4.5) is enough for each step",
  ];
  const bads = [
    "Last step ran twice: count reached 9 against a limit of 8, and two identical children exist, one never run",
    "Claimed vs actual: \"5 times\" reported, 6 lines written to log2.out",
    "File names drift: next-instr.md, next_instructions, instructions.txt, completion_status.txt",
    "Steps sleep and loop inside one call instead of yielding",
  ];
  const col = (x, title, items, ic, fill) => {
    circleIcon(s, ic, x, 1.5, 0.6, fill);
    txt(s, title, { x: x + 0.8, y: 1.55, w: 5, h: 0.5, fontSize: 20, bold: true });
    items.forEach((t, i) => {
      card(s, x, 2.3 + i * 1.07, 5.9, 0.92, C.background2);
      txt(s, t, { x: x + 0.25, y: 2.3 + i * 1.07, w: 5.45, h: 0.92, fontSize: 14, valign: "middle" });
    });
  };
  col(MX, "Works", goods, I.check, C.accent2);
  col(6.83, "Gaps it exposes", bads, I.warn, C.accent4);
  s.addNotes("Evidence: test/sub/count.md = 9 while add_one.md stops at 8; children 860b5f22 (never evaluated, no p.md) and 3550d964 (completed) both carry the same instruction. bf474803: completion_status says 5 writes; log2.out has 6. These are classic at-least-once / non-idempotent step problems that durable-execution systems solve.");

  // ===== Prior art =====
  pres.addSection({ title: "Prior art" });
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "Prior art" });
  s.addText("Prior art", { placeholder: "title" });
  s.addText("Agent operating systems, durable execution, file-based memory and actors", { placeholder: "body" });

  // landscape
  s = content("Six families have tackled parts of this", "Prior art");
  PRIOR.families.forEach((f, i) => {
    const cw = 3.9, chh = 2.45, x = MX + (i % 3) * (cw + 0.215), y = 1.4 + Math.floor(i / 3) * (chh + 0.2);
    card(s, x, y, cw, chh, i === PRIOR.closestFamily ? HEX.accent5 : C.background2, "fam" + i);
    txt(s, f.name, { x: x + 0.25, y: y + 0.18, w: cw - 0.5, h: 0.4, fontSize: 17, bold: true,
      fontFace: THEME.headFontFace });
    txt(s, f.examples, { x: x + 0.25, y: y + 0.62, w: cw - 0.5, h: 0.65, fontSize: 12, color: C.accent2, bold: true });
    txt(s, f.idea, { x: x + 0.25, y: y + 1.3, w: cw - 0.5, h: 1.05, fontSize: 14, color: C.text2 });
  });
  s.addNotes(PRIOR.familiesNotes);

  // matrix
  s = content("How the closest systems compare", "Prior art");
  const hdr = PRIOR.matrix.columns;
  const rows = [hdr].concat(PRIOR.matrix.rows);
  s.addTable(rows.map((r, i) => r.map((c, j) => ({ text: c, options: {
    bold: i === 0 || j === 0,
    color: i === 0 ? C.background1 : C.text1,
    fill: { color: i === 0 ? C.text2 : (i === rows.length - 1 ? HEX.accent5 : (i % 2 ? C.background2 : C.background1)) },
    fontSize: 14,
  } }))), { x: MX, y: 1.4, w: 12.13, colW: PRIOR.matrix.colW, rowH: 0.47, margin: [0, 0.1, 0, 0.1],
    border: { type: "solid", pt: 0.5, color: "D5DBE1" }, valign: "middle", objectName: "matrix" });
  s.addNotes(PRIOR.matrix.notes);

  // timers
  s = content("Who else can resume work later?", "Prior art");
  const trows = [PRIOR.timers.columns].concat(PRIOR.timers.rows);
  s.addTable(trows.map((r, i) => r.map((c, j) => ({ text: c, options: {
    bold: i === 0 || j === 0,
    color: i === 0 ? C.background1 : C.text1,
    fill: { color: i === 0 ? C.text2 : (i === trows.length - 1 ? HEX.accent5 : (i % 2 ? C.background2 : C.background1)) },
    fontSize: 14, fontFace: (i > 0 && (j === 1 || j === 2) && /^[a-z]/.test(c)) ? MONO : undefined,
  } }))), { x: MX, y: 1.4, w: 12.13, colW: PRIOR.timers.colW, rowH: 0.55, margin: [0, 0.1, 0, 0.1],
    border: { type: "solid", pt: 0.5, color: "D5DBE1" }, valign: "middle", objectName: "timers" });
  txt(s, "Durable platforms have timers but need a server. Agent frameworks leave it to cron. work-packet lets the agent pick its own wake time, with nothing running while it sleeps.",
    { x: MX, y: 6.0, w: 12.1, h: 0.7, fontSize: 15, italic: true, color: C.accent2 });
  s.addNotes(PRIOR.timers.notes);

  // closest neighbours
  s = content("Closest neighbours, and what to borrow", "Prior art");
  PRIOR.neighbours.forEach((nb, i) => {
    const cw = 5.9, chh = 2.4, x = MX + (i % 2) * (cw + 0.33), y = 1.45 + Math.floor(i / 2) * (chh + 0.25);
    card(s, x, y, cw, chh, C.background2, "nb" + i);
    txt(s, nb.name, { x: x + 0.25, y: y + 0.2, w: cw - 0.5, h: 0.4, fontSize: 18, bold: true });
    txt(s, nb.what, { x: x + 0.25, y: y + 0.65, w: cw - 0.5, h: 0.95, fontSize: 13, color: C.text2 });
    txt(s, [{ text: "Borrow: ", options: { bold: true, color: C.accent2 } }, { text: nb.borrow }],
      { x: x + 0.25, y: y + 1.6, w: cw - 0.5, h: 0.7, fontSize: 13 });
  });
  s.addNotes(PRIOR.neighboursNotes);

  // ===== Positioning =====
  pres.addSection({ title: "Positioning" });
  s = content("What is distinctive about work-packet", "Positioning");
  PRIOR.distinctive.forEach((d, i) => {
    const y = 1.5 + i * 1.0;
    circleIcon(s, I.star, MX, y + 0.05, 0.6, C.accent1);
    txt(s, d[0], { x: MX + 0.85, y, w: 11.2, h: 0.4, fontSize: 17, bold: true });
    txt(s, d[1], { x: MX + 0.85, y: y + 0.4, w: 11.2, h: 0.55, fontSize: 14, color: C.text2 });
  });

  s = content("Risks that prior art has already hit", "Positioning");
  PRIOR.risks.forEach((r, i) => {
    const cw = 3.9, chh = 2.4, x = MX + (i % 3) * (cw + 0.215), y = 1.45 + Math.floor(i / 3) * (chh + 0.25);
    card(s, x, y, cw, chh, i % 2 ? C.background2 : HEX.accent5, "risk" + i);
    txt(s, r[0], { x: x + 0.25, y: y + 0.2, w: cw - 0.5, h: 0.65, fontSize: 16, bold: true });
    txt(s, r[1], { x: x + 0.25, y: y + 0.75, w: cw - 0.5, h: 1.55, fontSize: 15, color: C.text2 });
  });

  // ===== User experience =====
  pres.addSection({ title: "User experience" });
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "User experience" });
  s.addText("Using work-packet day to day", { placeholder: "title" });
  s.addText("One command to start a project, one runner to keep it going, one board to watch", { placeholder: "body" });

  const SC = { run: C.accent2, sleep: C.accent3, wait: C.text2, ask: C.accent1, fail: C.accent4, done: C.accent6 };
  const SN = { run: "Running", sleep: "Sleeping", wait: "Waiting", ask: "Needs you", fail: "Failed", done: "Done" };
  function dot(slide, x, y, d, key) {
    slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: SC[key] },
      line: { color: key === "done" ? C.accent2 : SC[key], width: 1 }, objectName: "dot" + (++n) });
  }
  function pill(slide, label, x, y, w, h, opts) {
    opts = opts || {};
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: h / 2,
      fill: { color: opts.fill || C.background1 }, line: { color: opts.line || C.accent3, width: 0.75 },
      objectName: "pill" + (++n) });
    txt(slide, label, { x, y, w, h, fontSize: opts.fontSize || 10, align: "center", valign: "middle",
      color: opts.color || C.text1, bold: !!opts.bold, fontFace: opts.mono ? MONO : undefined });
  }
  // A browser window mock; returns the content area.
  function browser(slide, x, y, w, h, url, right) {
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08,
      fill: { color: C.background2 }, line: { color: "C9D1D9", width: 0.75 }, objectName: "win" + (++n) });
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.42, rectRadius: 0.08,
      fill: { color: C.text2 }, line: { color: C.text2 }, objectName: "winbar" + (++n) });
    slide.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.3, w, h: 0.12,
      fill: { color: C.text2 }, line: { color: C.text2 }, objectName: "winbar" + (++n) });
    [C.accent4, C.accent1, C.accent2].forEach((c, i) =>
      slide.addShape(pres.shapes.OVAL, { x: x + 0.18 + i * 0.2, y: y + 0.14, w: 0.13, h: 0.13,
        fill: { color: c }, line: { color: c }, objectName: "wdot" + (++n) }));
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.95, y: y + 0.08, w: 4.2, h: 0.26, rectRadius: 0.13,
      fill: { color: C.text1 }, line: { color: C.text1 }, objectName: "url" + (++n) });
    txt(slide, url, { x: x + 1.1, y: y + 0.08, w: 4.0, h: 0.26, fontSize: 10, fontFace: MONO,
      color: "B8C2CC", valign: "middle" });
    if (right) txt(slide, right, { x: x + w - 4.2, y: y + 0.08, w: 4.0, h: 0.26, fontSize: 10,
      color: C.background1, align: "right", valign: "middle" });
    return { x: x + 0.15, y: y + 0.55, w: w - 0.3, h: h - 0.7 };
  }

  // --- journey ---
  s = content("A day with work-packet", "User experience");
  const jI = [await icon(fa.FaTerminal, HEX.lt1), await icon(fa.FaCogs, HEX.lt1), await icon(fa.FaColumns, HEX.lt1),
    await icon(fa.FaBell, HEX.lt1), await icon(fa.FaSearch, HEX.lt1)];
  const jw = 2.226, jg = 0.25;
  UX.journey.forEach((j, i) => {
    const x = MX + i * (jw + jg);
    circleIcon(s, jI[i], x + jw / 2 - 0.42, 1.5, 0.84, i === 3 ? C.accent1 : C.accent2);
    if (i < 4) s.addShape(pres.shapes.CHEVRON, { x: x + jw + 0.03, y: 1.8, w: 0.19, h: 0.26,
      fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: "jarr" + i });
    txt(s, (i + 1) + ". " + j[0], { x, y: 2.55, w: jw, h: 0.4, fontSize: 16, bold: true, align: "center" });
    txt(s, j[1], { x, y: 3.0, w: jw, h: 1.25, fontSize: 13, color: C.text2, align: "center" });
    card(s, x, 4.1, jw, 1.3, C.text1, "jcmd" + i);
    txt(s, j[2], { x: x + 0.15, y: 4.2, w: jw - 0.3, h: 1.1, fontSize: 10.5, fontFace: MONO,
      color: C.accent1, valign: "middle" });
  });
  txt(s, "You start a project with one command, then mostly watch. It comes to you when it needs a decision.",
    { x: MX, y: 5.8, w: 12.1, h: 0.45, fontSize: 15, italic: true, color: C.accent2 });
  s.addNotes("The whole user experience in five steps. Everything here is designed in docs/runner.md: wpk new, the per-user runner (a systemd user service), the local web board, the ask/inbox flow, and the per-step record that makes transcripts browsable.");

  // --- board ---
  s = content("The board: every project at a glance", "User experience");
  let a = browser(s, MX, 1.3, 12.13, 5.05, "127.0.0.1:7878/board", "2 running · 1 needs you · $3.10 today");
  const bcw = (a.w - 5 * 0.12) / 6;
  UX.board.forEach((col, i) => {
    const x = a.x + i * (bcw + 0.12);
    card(s, x, a.y, bcw, a.h, C.background1, "col" + i);
    dot(s, x + 0.15, a.y + 0.15, 0.14, col[1]);
    txt(s, [{ text: col[0], options: { bold: true } }, { text: "  " + col[2].length, options: { color: C.accent3 } }],
      { x: x + 0.37, y: a.y + 0.07, w: bcw - 0.45, h: 0.3, fontSize: 12, valign: "middle" });
    col[2].forEach((c, k) => {
      const cy = a.y + 0.48 + k * 1.12, cx = x + 0.1, cwid = bcw - 0.2;
      const hi = col[1] === "ask";
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: cy, w: cwid, h: 1.0, rectRadius: 0.06,
        fill: { color: hi ? HEX.accent5 : C.background2 }, line: { color: hi ? C.accent1 : "D5DBE1", width: hi ? 1.25 : 0.5 },
        objectName: "bcard" + i + "_" + k });
      txt(s, c[0], { x: cx + 0.1, y: cy + 0.08, w: cwid - 0.2, h: 0.25, fontSize: 11, bold: true });
      txt(s, c[1], { x: cx + 0.1, y: cy + 0.34, w: cwid - 0.2, h: 0.4, fontSize: 9.5, color: C.text2 });
      txt(s, c[2], { x: cx + 0.1, y: cy + 0.74, w: cwid - 0.2, h: 0.2, fontSize: 8.5, color: C.accent3 });
    });
  });
  txt(s, "The runner sets the column from packet state. Ready and Paused columns are hidden here when empty.",
    { x: MX, y: 6.45, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: C.accent2 });
  s.addNotes("Mock-up of the home page. Cards are not dragged between columns: each column is derived from the root packet state, and the buttons on a card (Pause, Resume, Wake now, Reply) run the same code as the CLI. A badge appears if anything below the root has failed or needs input. Live updates come over server-sent events from events.jsonl.");

  // --- project page ---
  s = content("Project page: tree, timeline and files", "User experience");
  a = browser(s, MX, 1.3, 12.13, 5.05, "127.0.0.1:7878/p/nightly-triage", "nightly-triage · daily 06:00");
  const lw = 3.7;
  card(s, a.x, a.y, lw, a.h, C.background1, "treepanel");
  txt(s, "Packet tree", { x: a.x + 0.15, y: a.y + 0.1, w: lw - 0.3, h: 0.3, fontSize: 12, bold: true });
  UX.tree.forEach((t, i) => {
    const ty = a.y + 0.5 + i * 0.55, tx = a.x + 0.2 + t[0] * 0.3;
    if (t[0]) txt(s, i === UX.tree.length - 1 ? "└" : "├", { x: tx - 0.22, y: ty, w: 0.2, h: 0.25, fontSize: 11,
      fontFace: MONO, color: C.accent3 });
    dot(s, tx, ty + 0.06, 0.13, t[2]);
    txt(s, t[1], { x: tx + 0.22, y: ty, w: lw - 0.6, h: 0.25, fontSize: 11, fontFace: MONO, bold: true });
    txt(s, SN[t[2]] + " · " + t[3], { x: tx + 0.22, y: ty + 0.24, w: lw - 0.6 - t[0] * 0.3, h: 0.22, fontSize: 9.5, color: C.text2 });
  });
  txt(s, "status.md", { x: a.x + 0.15, y: a.y + 2.8, w: lw - 0.3, h: 0.25, fontSize: 11, bold: true });
  card(s, a.x + 0.15, a.y + 3.08, lw - 0.3, a.h - 3.23, C.text1, "statusbox");
  txt(s, UX.statusPreview, { x: a.x + 0.27, y: a.y + 3.15, w: lw - 0.5, h: a.h - 3.35, fontSize: 9.5,
    fontFace: MONO, color: C.accent1 });
  const rx = a.x + lw + 0.15, rw = a.w - lw - 0.15;
  card(s, rx, a.y, rw, a.h, C.background1, "tlpanel");
  txt(s, "Timeline, last 24 hours", { x: rx + 0.15, y: a.y + 0.1, w: rw - 0.3, h: 0.3, fontSize: 12, bold: true });
  const tlx = rx + 1.5, tlw = rw - 1.7, hx = h => tlx + tlw * h / 24;
  ["06:00", "12:00", "18:00", "00:00", "06:00"].forEach((l, i) => {
    txt(s, l, { x: hx(i * 6) - 0.3, y: a.y + 0.45, w: 0.6, h: 0.2, fontSize: 9, color: C.accent3, align: "center" });
    s.addShape(pres.shapes.LINE, { x: hx(i * 6), y: a.y + 0.68, w: 0, h: 2.2, line: { color: "D5DBE1", width: 0.5 },
      objectName: "tick" + i });
  });
  UX.lanes.forEach((ln, i) => {
    const ly = a.y + 0.8 + i * 0.52;
    txt(s, ln[0], { x: rx + 0.15, y: ly, w: 1.3, h: 0.32, fontSize: 9.5, fontFace: MONO, valign: "middle" });
    ln[1].forEach(([h0, h1, k], j) => {
      if (k === "step") s.addShape(pres.shapes.RECTANGLE, { x: hx(h0), y: ly + 0.04, w: Math.max(hx(h1) - hx(h0), 0.06), h: 0.24,
        fill: { color: C.accent2 }, line: { color: C.accent2 }, objectName: "blk" + i + "_" + j });
      else {
        s.addShape(pres.shapes.LINE, { x: hx(h0) + 0.05, y: ly + 0.16, w: hx(h1) - hx(h0) - 0.05, h: 0,
          line: { color: k === "ask" ? C.accent1 : C.accent3, width: 1.5, dashType: "dash" }, objectName: "gap" + i + "_" + j });
        txt(s, k === "ask" ? "waiting for your answer" : "sleeping until Thu 06:00", { x: hx(h0) + 1.6, y: ly + 0.05, w: 2.6, h: 0.22, valign: "middle",
          fontSize: 9, color: k === "ask" ? C.accent4 : C.accent3, fill: { color: C.background1 }, align: "center" });
      }
    });
  });
  txt(s, "Actions", { x: rx + 0.15, y: a.y + 3.1, w: 2, h: 0.25, fontSize: 11, bold: true });
  let bx = rx + 0.15;
  UX.actions.forEach((l, i) => {
    const bw = 0.35 + l.length * 0.075;
    pill(s, l, bx, a.y + 3.42, bw, 0.32, i === 1 ? { fill: C.accent2, line: C.accent2, color: C.background1, bold: true } : {});
    bx += bw + 0.12;
  });
  txt(s, "Click a packet to see its state/, memento.md and steps. Fork from step arrives with P4 snapshots.",
    { x: rx + 0.15, y: a.y + 3.9, w: rw - 0.3, h: 0.3, fontSize: 10, color: C.text2 });
  txt(s, "The timeline answers \"what happened overnight?\" for the whole tree, sleeps included.",
    { x: MX, y: 6.45, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: C.accent2 });
  s.addNotes("Mock-up of one project. The tree on the left comes from parent links in status.md; the timeline shows every step across the tree, with sleeps and waits as dashed gaps. Actions run CLI commands; Fork from step needs Phase 4 snapshots.");

  // --- step viewer ---
  s = content("Step viewer: what the model saw and did", "User experience");
  a = browser(s, MX, 1.3, 12.13, 5.05, "127.0.0.1:7878/p/nightly-triage/triage-dma/7");
  txt(s, "nightly-triage  ›  triage-dma  ›  step 7 of 7", { x: a.x + 0.05, y: a.y, w: 7, h: 0.32, fontSize: 13, bold: true, valign: "middle" });
  pill(s, "◂ Step 6", a.x + a.w - 2.2, a.y, 1.0, 0.3);
  pill(s, "Step 8 ▸", a.x + a.w - 1.1, a.y, 1.0, 0.3, { color: C.accent3, line: "D5DBE1" });
  const vw = 7.55, KC = { prompt: C.accent3, model: C.accent2, tool: C.text2, proposal: C.accent1 };
  UX.transcript.forEach((t, i) => {
    const ty = a.y + 0.45 + i * 0.75;
    card(s, a.x, ty, vw, 0.65, t[0] === "proposal" ? HEX.accent5 : C.background1, "tr" + i);
    pill(s, t[0], a.x + 0.12, ty + 0.17, 0.95, 0.3, { fill: KC[t[0]], line: KC[t[0]],
      color: t[0] === "proposal" ? C.text1 : C.background1, bold: true, fontSize: 9.5 });
    txt(s, t[1], { x: a.x + 1.2, y: ty + 0.05, w: vw - 1.35, h: 0.55, fontSize: (t[0] === "tool" || t[0] === "proposal") ? 10 : 11, valign: "middle",
      fontFace: (t[0] === "tool" || t[0] === "proposal") ? MONO : undefined });
  });
  const mx = a.x + vw + 0.2, mw = a.w - vw - 0.2;
  card(s, mx, a.y + 0.45, mw, a.h - 0.45, C.background1, "metapanel");
  UX.meta.forEach((m, i) => {
    txt(s, m[0], { x: mx + 0.15, y: a.y + 0.6 + i * 0.3, w: 1.1, h: 0.28, fontSize: 10.5, color: C.accent3 });
    txt(s, m[1], { x: mx + 1.25, y: a.y + 0.6 + i * 0.3, w: mw - 1.4, h: 0.28, fontSize: 10.5, bold: true });
  });
  txt(s, "Changes", { x: mx + 0.15, y: a.y + 1.9, w: 2, h: 0.25, fontSize: 11, bold: true });
  txt(s, UX.diff.map((d, i) => ({ text: (d[0] === " " ? "" : d[0] + " ") + d[1], options: {
    color: d[0] === "+" ? C.accent2 : d[0] === "-" ? C.accent4 : C.text1, bold: d[0] === " ",
    breakLine: i < UX.diff.length - 1 } })), { x: mx + 0.15, y: a.y + 2.18, w: mw - 0.3, h: 1.25, fontSize: 9.5, fontFace: MONO });
  pill(s, "Open in Claude Code", mx + 0.15, a.y + 3.55, 2.0, 0.32, { fill: C.accent2, line: C.accent2, color: C.background1, bold: true });
  txt(s, "claude --resume 9c1e… --fork-session", { x: mx + 0.15, y: a.y + 3.95, w: mw - 0.3, h: 0.25, fontSize: 9, fontFace: MONO, color: C.text2 });
  txt(s, "Every step's prompt, transcript, diff and cost is in steps/<n>/, written by the executor, not the model.",
    { x: MX, y: 6.45, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: C.accent2 });
  s.addNotes("Mock-up of the step viewer. Prompt and long tool outputs are collapsed. 'Open in Claude Code' forks the step's session for debugging, so the recorded history is never changed. Steps are kept until pruned by hand with wpk prune; journal.jsonl keeps one line per step after pruning.");

  // --- inbox + upcoming ---
  s = content("When a packet needs you, and what wakes next", "User experience");
  const pw2 = 5.9, ph2 = 4.75, py = 1.4;
  [[MX, "Inbox", "1 waiting"], [MX + pw2 + 0.33, "Upcoming wakes", "all projects"]].forEach(([x, t, sub], i) => {
    card(s, x, py, pw2, ph2, C.background2, "panel" + i);
    txt(s, [{ text: t, options: { bold: true } }, { text: "   " + sub, options: { color: C.accent3, fontSize: 11 } }],
      { x: x + 0.2, y: py + 0.15, w: pw2 - 0.4, h: 0.35, fontSize: 15, valign: "middle" });
  });
  let ix = MX + 0.2, iy = py + 0.65, iw = pw2 - 0.4;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: ix, y: iy, w: iw, h: 3.0, rectRadius: 0.06,
    fill: { color: C.background1 }, line: { color: C.accent1, width: 1.25 }, objectName: "askcard" });
  txt(s, "regress-bisect  ›  triage-dma  ·  asked 2 h ago", { x: ix + 0.2, y: iy + 0.15, w: iw - 0.4, h: 0.25, fontSize: 10.5, color: C.accent3 });
  txt(s, "Three new failures look like the same AXI timeout. File one bug or three?",
    { x: ix + 0.2, y: iy + 0.45, w: iw - 0.4, h: 0.65, fontSize: 15, bold: true });
  pill(s, "one", ix + 0.2, iy + 1.2, 0.9, 0.34, { fill: C.accent2, line: C.accent2, color: C.background1, bold: true, fontSize: 11 });
  pill(s, "three", ix + 1.2, iy + 1.2, 0.9, 0.34, { fontSize: 11 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: ix + 0.2, y: iy + 1.7, w: iw - 0.4, h: 0.45, rectRadius: 0.05,
    fill: { color: C.background2 }, line: { color: "D5DBE1", width: 0.75 }, objectName: "replybox" });
  txt(s, "Or type a reply…", { x: ix + 0.35, y: iy + 1.7, w: iw - 0.7, h: 0.45, fontSize: 11, color: C.accent3, valign: "middle", italic: true });
  txt(s, "No answer by Thu 18:00? It wakes anyway and is told nobody replied.",
    { x: ix + 0.2, y: iy + 2.3, w: iw - 0.4, h: 0.5, fontSize: 11, color: C.text2 });
  // notification toast
  const tY = py + 3.85;
  card(s, ix, tY, iw, 0.7, C.text1, "toast");
  circleIcon(s, jI[3], ix + 0.15, tY + 0.13, 0.44, C.accent1);
  txt(s, [{ text: "work-packet", options: { bold: true, color: C.background1 } },
    { text: "   regress-bisect needs you: one bug or three?", options: { color: "B8C2CC" } }],
    { x: ix + 0.75, y: tY, w: iw - 0.9, h: 0.7, fontSize: 11, valign: "middle" });
  const ux0 = MX + pw2 + 0.53, uw = pw2 - 0.4;
  UX.upcoming.forEach((u, i) => {
    const uy = py + 0.65 + i * 0.6, clash = u[0] === "Mon 26 Oct 08:00";
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: ux0, y: uy, w: uw, h: 0.5, rectRadius: 0.05,
      fill: { color: clash ? HEX.accent5 : C.background1 }, line: { color: clash ? C.accent1 : "D5DBE1", width: 0.5 },
      objectName: "up" + i });
    txt(s, u[0], { x: ux0 + 0.15, y: uy, w: 1.9, h: 0.5, fontSize: 11, fontFace: MONO, valign: "middle" });
    txt(s, u[1], { x: ux0 + 2.1, y: uy, w: 1.8, h: 0.5, fontSize: 11, bold: true, valign: "middle" });
    txt(s, u[2], { x: ux0 + 3.9, y: uy, w: uw - 4.0, h: 0.5, fontSize: 10.5, color: C.text2, valign: "middle", align: "right" });
  });
  txt(s, "Two projects wake at Mon 08:00: the list makes clashes easy to spot.",
    { x: ux0, y: py + 0.65 + 6 * 0.6 + 0.05, w: uw, h: 0.4, fontSize: 11, color: C.accent4 });
  txt(s, "A reply is written to the packet's mailbox/ and wakes it within seconds.",
    { x: MX, y: 6.35, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: C.accent2 });
  s.addNotes("A packet writes 'ask:' in its memento to stop and ask a question; it moves to NEEDS_INPUT, a notification goes out (desktop or webhook), and the question appears in the inbox. The Upcoming view lists every scheduled wake across all projects.");

  // --- rules ---
  s = content("What the user can rely on", "User experience");
  const rI = [await icon(fa.FaEye, HEX.lt1), await icon(fa.FaColumns, HEX.lt1), await icon(fa.FaBed, HEX.lt1),
    I.coins, await icon(fa.FaLock, HEX.lt1), jI[0]];
  UX.rules.forEach((r, i) => {
    const cw = 3.9, chh = 1.95, x = MX + (i % 3) * (cw + 0.215), y = 1.5 + Math.floor(i / 3) * (chh + 0.3);
    card(s, x, y, cw, chh, i % 2 ? C.background2 : HEX.accent6, "rule" + i);
    circleIcon(s, rI[i], x + 0.25, y + 0.25, 0.6, i % 2 ? C.text2 : C.accent2);
    txt(s, r[0], { x: x + 1.0, y: y + 0.25, w: cw - 1.2, h: 0.6, fontSize: 16, bold: true, valign: "middle" });
    txt(s, r[1], { x: x + 0.25, y: y + 1.05, w: cw - 0.5, h: 1.15, fontSize: 14, color: C.text2 });
  });
  s.addNotes("These follow from three design rules in docs/runner.md: files are the source of truth, the executor knows nothing about the runner, and the dashboard and CLI share one code path for every change.");

  // ===== Roadmap =====
  pres.addSection({ title: "Roadmap" });
  s = content("From prior art to roadmap", "Roadmap");
  const brows = [["Idea", "Borrowed from", "Lands in"]].concat(PRIOR.borrow);
  s.addTable(brows.map((r, i) => r.map((c, j) => ({ text: c, options: {
    bold: i === 0 || j === 0,
    color: i === 0 ? C.background1 : (j === 2 ? C.accent2 : C.text1),
    fill: { color: i === 0 ? C.text2 : (i % 2 ? C.background2 : C.background1) },
    fontSize: 14,
  } }))), { x: MX, y: 1.4, w: 12.13, colW: [5.3, 4.6, 2.23], rowH: 0.52, margin: [0, 0.1, 0, 0.1],
    border: { type: "solid", pt: 0.5, color: "D5DBE1" }, valign: "middle", objectName: "borrow" });
  s.addNotes("Every phase reuses a design someone else has already proven. The research also gives regression tests (known failure modes), benchmark baselines (Ralph loop, LangGraph) and a build-or-buy fallback (DBOS or Temporal under the same directory layout).");

  s = content("Roadmap: durable steps, then time, then trees", "Roadmap");
  const pw = 1.93, pg = 0.11;
  PRIOR.roadmap.forEach((ph, i) => {
    const x = MX + i * (pw + pg);
    s.addShape(i === 0 ? pres.shapes.PENTAGON : pres.shapes.CHEVRON, { x, y: 1.45, w: i === 5 ? pw : pw + 0.1, h: 0.6,
      fill: { color: i === 2 ? C.accent4 : C.accent1 }, line: { color: i === 2 ? C.accent4 : C.accent1 }, objectName: "chev" + i });
    txt(s, ph[0], { x: x + 0.3, y: 1.45, w: pw - 0.5, h: 0.6, fontSize: 18, bold: true, color: C.background1,
      valign: "middle", align: "center", fontFace: THEME.headFontFace });
    card(s, x, 2.25, pw, 3.45, i === 2 ? HEX.accent5 : C.background2, "phase" + i);
    txt(s, ph[1], { x: x + 0.15, y: 2.4, w: pw - 0.3, h: 0.4, fontSize: 17, bold: true });
    txt(s, ph[2], { x: x + 0.15, y: 2.85, w: pw - 0.3, h: 1.2, fontSize: 13, color: C.text2 });
    txt(s, "Done when", { x: x + 0.15, y: 4.15, w: pw - 0.3, h: 0.3, fontSize: 12, bold: true, color: C.accent2 });
    txt(s, ph[3], { x: x + 0.15, y: 4.45, w: pw - 0.3, h: 1.15, fontSize: 13 });
  });
  txt(s, "Time (P2) depends on P1: a recurring job that double-runs is worse than no job at all.",
    { x: MX, y: 6.0, w: 12.1, h: 0.45, fontSize: 15, italic: true, color: C.accent2 });
  s.addNotes("P2 (time) is highlighted: scheduled resumption is the feature that makes work packets periodic. It depends on P1, because a recurring job that double-runs is worse than none. Full checklist with exit tests in docs/roadmap.md.");

  // ===== Next steps =====
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Roadmap" });
  s.addText("Next steps", { placeholder: "title" });
  s.addText("Move the bookkeeping out of the model and into a small executor", { placeholder: "body" });
  PRIOR.nextSteps.forEach((t, i) => {
    const y = 2.45 + i * 0.85;
    txt(s, String(i + 1), { x: MX, y, w: 0.6, h: 0.6, fontSize: 28, bold: true, color: C.accent1,
      fontFace: THEME.headFontFace });
    txt(s, t[0], { x: MX + 0.8, y: y + 0.02, w: 11.2, h: 0.35, fontSize: 17, bold: true, color: C.background1 });
    txt(s, t[1], { x: MX + 0.8, y: y + 0.38, w: 11.2, h: 0.4, fontSize: 14, color: "B8C2CC" });
  });
  s.addNotes("These are the Phase 0 to Phase 2 tasks from docs/roadmap.md. The thin executor is the key change: in the prototype the model counted, spawned and slept for itself, which is where every bug came from.");

  // references
  s = content("References", "Roadmap");
  const half = Math.ceil(PRIOR.refs.length / 2);
  [PRIOR.refs.slice(0, half), PRIOR.refs.slice(half)].forEach((list, k) => {
    const runs = [];
    list.forEach((r, i) => {
      runs.push({ text: r[0], options: { bold: true, breakLine: true } });
      runs.push({ text: r[1].replace(/^https:\/\/(www\.)?/, ""), options: { color: C.accent2, fontSize: 10, hyperlink: { url: r[1] },
        breakLine: i < list.length - 1, paraSpaceAfter: 6 } });
    });
    txt(s, runs, { x: MX + k * 6.2, y: 1.45, w: 5.9, h: 5.4, fontSize: 14 });
  });
  s.addNotes("Most 2026 sources were found via web search; check the details of arXiv preprints before citing externally.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
}
build().catch(e => { console.error(e); process.exit(1); });
