// Builds slides/work-packet-overview.pptx: the work-packet concept (task-centric packets,
// many projects, token tuning) and how it compares with the industry.
// Run: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> \
//      PPTX_SKILL=<pptx skill dir> node slides/overview_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");
const IND = require("./industry.js");

const OUT = path.join(__dirname, "work-packet-overview.pptx");

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
const MUTED = "B8C2CC"; // light grey text on dark

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "work-packet: task-centric AI automation";
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
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.1, w: 11, h: 1.6,
      fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.9, w: 10, h: 1.4,
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
    { text: { text: "work-packet · task-centric AI automation", options: { x: MX, y: 6.95, w: 5, h: 0.3,
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
function arrow(slide, x, y, w, h, color) {
  slide.addShape(pres.shapes.RIGHT_ARROW, { x, y, w, h, fill: { color: color || C.accent3 },
    line: { color: color || C.accent3 }, objectName: "arr" + (++n) });
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
// Big number with a label underneath.
function stat(slide, x, y, w, num, label, opts) {
  opts = opts || {};
  txt(slide, num, { x, y, w, h: 0.95, fontSize: opts.size || 48, bold: true,
    color: opts.color || C.accent1, fontFace: THEME.headFontFace, valign: "bottom" });
  txt(slide, label, { x, y: y + 1.0, w, h: opts.lh || 0.75, fontSize: 13, color: opts.lcolor || C.text2 });
}
// Monospace code block on a dark card. lines: [text, color?]
function code(slide, x, y, w, h, lines, fs) {
  card(slide, x, y, w, h, C.text1);
  txt(slide, lines.map((l, i) => ({ text: l[0], options: { color: l[1] || HEX.lt1,
    breakLine: i < lines.length - 1 } })), { x: x + 0.3, y: y + 0.22, w: w - 0.5, h: h - 0.4,
    fontFace: MONO, fontSize: fs || 13 });
}
function chartBase(extra) {
  return Object.assign({
    catAxisLabelColor: HEX.dk2, valAxisLabelColor: HEX.accent3,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt",
    titleFontFace: "+mn-lt", catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, dataLabelFontSize: 12,
    titleFontSize: 14, titleColor: HEX.dk1, dataLabelColor: HEX.dk1,
    valGridLine: { color: "DDE2E7", size: 0.5 }, catGridLine: { style: "none" },
    showValue: true, showLegend: false, showTitle: true,
  }, extra);
}

async function build() {
  const I = {};
  const ic = { folder: fa.FaFolderOpen, code: fa.FaCode, list: fa.FaClipboardList, box: fa.FaBoxes,
    clock: fa.FaHourglassHalf, coins: fa.FaCoins, layers: fa.FaLayerGroup, chart: fa.FaChartLine,
    chip: fa.FaMicrochip, git: fa.FaCodeBranch, comments: fa.FaComments, sync: fa.FaSyncAlt,
    user: fa.FaUserCheck, cal: fa.FaCalendarAlt, sitemap: fa.FaSitemap, check: fa.FaCheck,
    shield: fa.FaShieldAlt, eye: fa.FaEye, sliders: fa.FaSlidersH, search: fa.FaSearch,
    star: fa.FaStar, bolt: fa.FaBolt, db: fa.FaDatabase, robot: fa.FaRobot, flag: fa.FaFlagCheckered };
  for (const k of Object.keys(ic)) I[k] = await icon(ic[k], HEX.lt1);
  I.starDk = await icon(fa.FaStar, HEX.dk1);

  let s;
  // ===================================================== Intro
  pres.addSection({ title: "Introduction" });
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("work-packet", { placeholder: "title" });
  s.addText("Task-centric persistence for AI-automated projects: many projects, built-in tracking, and token use tuned from measurement",
    { placeholder: "body" });
  txt(s, "wpk new · wpk tick · wpk dash · wpk stats", { x: MX, y: 1.4, w: 8, h: 0.4, fontFace: MONO,
    fontSize: 16, color: C.accent2 });
  txt(s, "October 2026 · pre-alpha", { x: MX, y: 6.6, w: 5, h: 0.35, fontSize: 12, color: C.accent3 });
  s.addNotes("work-packet (command: wpk) runs LLM agents as resumable, scheduled units of work. This deck covers three ideas: the packet as the unit of persistence, many projects under one runner, and token use tuned from measurements. It then compares the approach with the rest of the industry.");

  // --- exec summary
  s = content("Three ideas, one system", "Introduction");
  const pillars = [
    [I.folder, "Task-centric packets", "A packet holds the subject data, the instructions and tracking, and the temporary artifacts for one task. The packet is the center of persistence, not the git repo."],
    [I.layers, "Many projects, one runner", "Feature work, nightly triage and weekly 'management' tasks all run as packets. A scheduler wakes each one when it is due; sleeping costs nothing."],
    [I.chart, "Tuned by measurement", "Every step records its context, cache and cost. wpk stats turns that into advice on how to size and chain steps for each model."],
  ];
  pillars.forEach((p, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    card(s, x, 1.5, w, 3.7, C.background2);
    circleIcon(s, p[0], x + 0.3, 1.8, 0.8, i === 2 ? C.accent1 : C.accent2);
    txt(s, p[1], { x: x + 0.3, y: 2.8, w: w - 0.6, h: 0.45, fontSize: 19, bold: true, fontFace: THEME.headFontFace });
    txt(s, p[2], { x: x + 0.3, y: 3.3, w: w - 0.6, h: 1.8, fontSize: 14, color: C.text2 });
  });
  card(s, MX, 5.5, CW, 1.1, C.text1);
  txt(s, [
    { text: "The result: ", options: { bold: true, color: HEX.accent1 } },
    { text: "an easy-to-use system for managing many AI-automated projects and workflows, with tracking and statistics built in.", options: { color: HEX.lt1 } },
  ], { x: MX + 0.35, y: 5.5, w: CW - 0.7, h: 1.1, fontSize: 17, valign: "middle" });
  s.addNotes("This is the whole deck on one slide. Each pillar gets its own section, then the industry comparison shows that nobody else combines the three.");

  // ===================================================== Problem
  divider("Why the session-in-a-repo model falls short", "Agents assume a chat session for state and a git repo for persistence", "The problem");

  // --- the default model
  s = content("Today's default: a session, inside a repo", "The problem");
  const def = [
    ["Chat session", "Holds the plan, decisions and progress. Lost or summarized lossily when it ends or is compacted.", C.accent4],
    ["Git repository", "The only durable store. Plans and notes are committed to it or lost; one repo per task is assumed.", C.text2],
    ["Workspace / VM", "Builds, simulation results, caches. Thrown away with the sandbox, or left lying around untracked.", C.accent3],
  ];
  def.forEach((d, i) => {
    const y = 1.5 + i * 1.6;
    card(s, MX, y, 6.6, 1.35, C.background2);
    s.addShape(pres.shapes.OVAL, { x: MX + 0.3, y: y + 0.45, w: 0.45, h: 0.45, fill: { color: d[2] },
      line: { color: d[2] }, objectName: "dd" + i });
    txt(s, d[0], { x: MX + 1.0, y: y + 0.15, w: 5.4, h: 0.4, fontSize: 17, bold: true });
    txt(s, d[1], { x: MX + 1.0, y: y + 0.55, w: 5.4, h: 0.75, fontSize: 13.5, color: C.text2 });
  });
  txt(s, "What this assumes", { x: 7.7, y: 1.5, w: 5, h: 0.45, fontSize: 19, bold: true, color: C.accent2 });
  txt(s, bullets([
    "Code is the only output worth keeping",
    "Re-creating everything else is cheap",
    "A person is watching the session",
    "One task at a time, started by hand",
    "Cost is someone else's problem",
  ]), { x: 7.7, y: 2.05, w: 5.0, h: 3.5, fontSize: 16, paraSpaceAfter: 10 });
  txt(s, "None of these hold for long-running silicon-design work.", { x: 7.7, y: 5.6, w: 5.0, h: 0.8,
    fontSize: 15, italic: true, bold: true, color: C.accent4 });
  s.addNotes("Most coding agents (Claude Code, Codex, Copilot agent, Devin) assume the repo is where durable state lives and the session is where working state lives. That works for short software tasks.");

  // --- silicon
  s = content("In silicon design, the artifacts outweigh the code", "The problem");
  stat(s, MX, 1.4, 3.9, "GBs", "one clone plus its packages/ with Verilator, Yosys and more");
  stat(s, MX + 4.1, 1.4, 3.6, "17 min", "for one full formal run");
  stat(s, MX + 8.2, 1.4, 3.6, "~2 h", "for the upstream verification bench");
  card(s, MX, 3.6, CW, 2.9, C.background2);
  circleIcon(s, I.chip, MX + 0.35, 3.9, 0.8, C.accent2);
  txt(s, "What that means for an agent", { x: MX + 1.4, y: 3.9, w: 10, h: 0.45, fontSize: 19, bold: true });
  txt(s, bullets([
    "Re-creating the work tree, tool installs and run directories often costs more than the AI step itself",
    "A sandbox that is thrown away after each task throws that investment away too",
    "Plans, notes and triage logs belong to the task, not the design repo's history",
    "A step that waits for a 2-hour regression must be able to sleep and resume, not hold a session open",
  ]), { x: MX + 1.4, y: 4.45, w: 10.6, h: 2.0, fontSize: 15 });
  s.addNotes("Numbers from docs/long-running.md: gigabyte packages/ directories fetched by IVPM, a 17-minute formal run and a bench of up to two hours. The cost of rebuilding the environment dominates, so the environment must persist with the task.");

  // --- long sessions
  s = content("One long session gets expensive fast", "The problem");
  txt(s, "A real fw-proto-chi development session, run interactively in Claude Code", { x: MX, y: 1.3, w: CW, h: 0.4,
    fontSize: 15, color: C.text2, italic: true });
  [["665", "API calls in the main session"], ["620k", "peak context tokens"], ["168M", "cache-read tokens"],
   ["6×", "manual /compact to keep going"]].forEach((st, i) => {
    stat(s, MX + i * 3.05, 1.8, 2.8, st[0], st[1], { color: i === 3 ? C.accent4 : C.accent1 });
  });
  card(s, MX, 4.1, CW, 2.4, C.text1);
  txt(s, "Why", { x: MX + 0.35, y: 4.3, w: 3, h: 0.4, fontSize: 18, bold: true, color: HEX.accent1 });
  txt(s, bullets([
    "Every call re-reads the whole context: average ~250k tokens per call",
    "So cost grows roughly with the square of the session's length",
    "Compaction saves tokens but loses detail that has to be re-discovered",
  ], { color: HEX.lt1 }), { x: MX + 0.35, y: 4.8, w: CW - 0.7, h: 1.6, fontSize: 15 });
  s.addNotes("From docs/stack-experiment.md section 2. A second session for docs had 154 calls, a 428k peak and 45M cache reads. This is the cost profile that work-packet's step model is designed to avoid.");

  // --- many projects
  s = content("Real work is many projects, not one chat", "The problem");
  const kinds = [
    [I.code, "Feature work", "Implement a block, extend a testbench: days of steps"],
    [I.cal, "Nightly triage", "Look at last night's regression, file what broke"],
    [I.list, "Weekly reports", "Summarize progress, chase open questions"],
    [I.search, "Research", "Survey a protocol or tool, write up findings"],
    [I.sync, "Upkeep", "Bump dependencies, re-run benches, prune runs"],
    [I.user, "Waiting on people", "Questions parked until someone answers"],
  ];
  kinds.forEach((k, i) => {
    const cw = 3.85, ch = 1.75, x = MX + (i % 3) * (cw + 0.275), y = 1.45 + Math.floor(i / 3) * (ch + 0.3);
    card(s, x, y, cw, ch, C.background2);
    circleIcon(s, k[0], x + 0.25, y + 0.3, 0.65, C.accent2);
    txt(s, k[1], { x: x + 1.1, y: y + 0.3, w: cw - 1.3, h: 0.4, fontSize: 17, bold: true });
    txt(s, k[2], { x: x + 1.1, y: y + 0.75, w: cw - 1.3, h: 0.9, fontSize: 13.5, color: C.text2 });
  });
  txt(s, "Who schedules these, tracks them, and knows what each one has cost?", { x: MX, y: 5.75, w: CW, h: 0.5,
    fontSize: 17, italic: true, bold: true, color: C.accent4 });
  s.addNotes("Management-like periodic tasks are as important as feature work, and today they are cron jobs, reminders or nothing.");

  // ===================================================== Packets
  divider("The packet is the unit of work and of persistence", "Everything a task needs, in one directory that outlives any session", "Task-centric packets");

  // --- three parts
  s = content("A packet holds three kinds of thing", "Task-centric packets");
  const parts = [
    [I.code, "Subject data", "The code and design being worked on", ["work/: git clones edited in place", "identity/: read-only links to outside resources"], C.accent2],
    [I.list, "Instructions and tracking", "What to do next and what has happened", ["memento.md: the next instruction", "status.md, journal.jsonl, steps/NNNN/"], C.accent1],
    [I.box, "Temporary artifacts", "Everything expensive to re-create", ["packages/, rundir/, build output kept across steps", "state/: plans and notes, versioned per step"], C.text2],
  ];
  parts.forEach((p, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    card(s, x, 1.45, w, 4.4, C.background2);
    circleIcon(s, p[0], x + 0.3, 1.75, 0.8, p[4]);
    txt(s, p[1], { x: x + 0.3, y: 2.75, w: w - 0.6, h: 0.45, fontSize: 19, bold: true, fontFace: THEME.headFontFace });
    txt(s, p[2], { x: x + 0.3, y: 3.2, w: w - 0.6, h: 0.6, fontSize: 14, color: C.text2, italic: true });
    txt(s, bullets(p[3]), { x: x + 0.3, y: 3.9, w: w - 0.5, h: 1.8, fontSize: 13.5 });
  });
  txt(s, "Nothing a step needs points outside the packet. Copy it, archive it or delete it as one unit.",
    { x: MX, y: 6.1, w: CW, h: 0.5, fontSize: 16, italic: true, bold: true, color: C.accent2 });
  s.addNotes("This is the key reframing: subject data plus instructions and tracking plus temporary artifacts. The repo is one of the things inside the packet, not the other way round.");

  // --- anatomy
  s = content("Anatomy of a packet", "Task-centric packets");
  card(s, MX, 1.4, 7.3, 5.2, C.text1);
  const tree = [
    ["packets/<WPID>/", "one directory per task", HEX.accent1],
    ["  memento.md", "next instruction, written by the model", HEX.accent1],
    ["  status.md", "state, step, wake_at: executor only", HEX.lt1],
    ["  state/", "plans and notes, versioned per step", HEX.lt1],
    ["  work/<repo>/", "git clones, one commit per step", HEX.lt1],
    ["  identity/", "read-only links to the outside", HEX.lt1],
    ["  children/", "links to spawned packets", HEX.lt1],
    ["  mailbox/", "notes from the owner", HEX.lt1],
    ["  journal.jsonl", "append-only, fsynced", HEX.lt1],
    ["  steps/NNNN/", "prompt, transcript, diff, meta.json", HEX.accent1],
  ];
  tree.forEach((t, i) => {
    const y = 1.62 + i * 0.49;
    txt(s, t[0], { x: MX + 0.3, y, w: 2.9, h: 0.4, fontFace: MONO, fontSize: 14, bold: true, color: t[2] });
    txt(s, t[1], { x: MX + 3.3, y: y + 0.02, w: 3.9, h: 0.4, fontSize: 13, color: MUTED });
  });
  txt(s, "Who writes what", { x: 8.3, y: 1.4, w: 4.4, h: 0.45, fontSize: 19, bold: true, color: C.accent2 });
  [["Executor", "everything committed, through the commit protocol"],
   ["Model", "only .pending/ during a step: a proposal"],
   ["Person", "only through wpk commands and the board"]].forEach((r, i) => {
    const y = 2.0 + i * 1.05;
    card(s, 8.3, y, 4.43, 0.9, i === 1 ? HEX.accent5 : C.background2);
    txt(s, r[0], { x: 8.5, y: y + 0.1, w: 4, h: 0.35, fontSize: 15, bold: true });
    txt(s, r[1], { x: 8.5, y: y + 0.45, w: 4.1, h: 0.4, fontSize: 13, color: C.text2 });
  });
  txt(s, "Each step leaves a full record: prompt, system prompt, transcript, state.diff, work.diff and its token and cost figures.",
    { x: 8.3, y: 5.3, w: 4.43, h: 1.2, fontSize: 14, italic: true, color: C.text2 });
  s.addNotes("From docs/spec.md. The WPID is a UUID; children get uuid5 of parent:step:index so a retried step cannot create duplicate children.");

  // --- repo-centric vs packet-centric
  s = content("The repo becomes a passenger, not the center", "Task-centric packets");
  const cols = [
    ["Repo-centric", C.text2, [
      "State lives in branches, PRs and the session",
      "Plans and notes get committed or lost",
      "Workspace rebuilt for each task or session",
      "One task, one repo, one session",
      "History is git log plus whatever the chat kept",
    ]],
    ["Packet-centric (work-packet)", C.accent2, [
      "State lives in the packet; repos are clones in work/",
      "Plans live in state/ and never touch the code's history",
      "Builds, packages and run dirs persist across steps",
      "One task may span several repos, or none",
      "Journal, per-step record and cost for every step",
    ]],
  ];
  cols.forEach((c, k) => {
    const x = MX + k * 6.2, w = 5.93;
    card(s, x, 1.45, w, 0.65, c[1]);
    txt(s, c[0], { x: x + 0.3, y: 1.45, w: w - 0.6, h: 0.65, fontSize: 18, bold: true, color: C.background1, valign: "middle" });
    c[2].forEach((b, i) => {
      const y = 2.3 + i * 0.83;
      card(s, x, y, w, 0.7, k ? HEX.accent6 : C.background2);
      txt(s, b, { x: x + 0.3, y, w: w - 0.6, h: 0.7, fontSize: 14.5, valign: "middle" });
    });
  });
  s.addNotes("The repo is still where code is delivered. But the packet decides what persists, and the packet's lifetime is the task's lifetime.");

  // --- work/ flow
  s = content("work/ repos: edited in place, atomic per step", "Task-centric packets");
  const wf = [["Base", "commit at the start of the step"], ["Step", "model edits files in work/"], ["Validate", "memento and summary present"]];
  wf.forEach((f, i) => {
    const x = MX + i * 3.0;
    card(s, x, 1.6, 2.5, 1.3, i === 1 ? HEX.accent5 : C.background2);
    txt(s, f[0], { x: x + 0.2, y: 1.72, w: 2.1, h: 0.4, fontSize: 17, bold: true });
    txt(s, f[1], { x: x + 0.2, y: 2.15, w: 2.15, h: 0.7, fontSize: 13, color: C.text2 });
    if (i < 2) arrow(s, x + 2.6, 2.1, 0.3, 0.3);
  });
  arrow(s, 9.15, 1.75, 0.45, 0.3, C.accent2);
  arrow(s, 9.15, 2.55, 0.45, 0.3, C.accent4);
  card(s, 9.7, 1.45, 3.03, 0.85, HEX.accent6);
  txt(s, [{ text: "Success", options: { bold: true, breakLine: true } }, { text: "git commit \"step N: …\"", options: { fontFace: MONO, fontSize: 11 } }],
    { x: 9.85, y: 1.45, w: 2.8, h: 0.85, fontSize: 14, valign: "middle" });
  card(s, 9.7, 2.4, 3.03, 0.85, HEX.accent5);
  txt(s, [{ text: "Failure", options: { bold: true, breakLine: true } }, { text: "reset --hard; clean -fd", options: { fontFace: MONO, fontSize: 11 } }],
    { x: 9.85, y: 2.4, w: 2.8, h: 0.85, fontSize: 14, valign: "middle" });
  code(s, MX, 3.6, 6.3, 2.0, [
    ["step 12: add CHI snoop response checks", HEX.accent1],
    ["", null],
    ["Wpk-Packet: 3f9c…e21a", MUTED],
    ["Wpk-Step: 12", MUTED],
  ], 14);
  txt(s, bullets([
    "Ignored files (packages/, rundir/, build output) survive a failed step: no re-fetch, no rebuild",
    "Every commit is traceable back to its packet and step through trailers",
    "The diff is also kept in steps/NNNN/work.diff",
    "Never put a clone under state/: state/ is read in full at each step",
  ]), { x: 7.3, y: 3.6, w: 5.4, h: 3.0, fontSize: 14 });
  txt(s, "Design L2: in the dv-solve trial the model commits each item itself.", { x: MX, y: 5.8, w: 6.3, h: 0.4, fontSize: 12, italic: true, color: C.text2 });
  s.addNotes("From docs/long-running.md section 2. The design is part-built: the trial uses work/, and the executor-level commits are milestone L2.");

  // --- step loop
  s = content("One step: a fresh model run, committed by the executor", "Task-centric packets");
  const loop = [
    ["1", "Lease", "take the lease, log step-start"],
    ["2", "Prepare", "copy state/ to .pending/, build the prompt"],
    ["3", "Run", "claude -p with hooks; optionally carry the session"],
    ["4", "Validate", "memento + summary; nudge once if missing"],
    ["5", "Commit", "children, state, memento, status, journal"],
    ["6", "Schedule", "resolve resume: to a state and wake_at"],
  ];
  const lw = 1.85, lg = 0.21;
  loop.forEach((l, i) => {
    const x = MX + i * (lw + lg);
    card(s, x, 1.5, lw, 2.6, i === 4 ? HEX.accent5 : C.background2);
    txt(s, l[0], { x: x + 0.2, y: 1.65, w: 0.8, h: 0.6, fontSize: 30, bold: true, color: C.accent1, fontFace: THEME.headFontFace });
    txt(s, l[1], { x: x + 0.2, y: 2.3, w: lw - 0.3, h: 0.4, fontSize: 17, bold: true });
    txt(s, l[2], { x: x + 0.2, y: 2.75, w: lw - 0.35, h: 1.3, fontSize: 13, color: C.text2 });
  });
  txt(s, "The model's memento ends every step:", { x: MX, y: 4.45, w: 6, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  code(s, MX, 4.9, 6.0, 1.75, [
    ["---", MUTED], ["resume: in 1 day", HEX.accent1], ["reason: waiting for nightly regression", HEX.lt1],
    ["---", MUTED], ["Check rundir/nightly for failures in …", HEX.lt1],
  ], 13);
  txt(s, bullets([
    "Each step starts fresh: no hidden memory, only files",
    "Any model can take any step: Haiku for routine, a bigger model for design",
    "A step that fails is retried with a 'Last attempt' section; after 3 the packet is FAILED",
  ]), { x: 7.0, y: 4.5, w: 5.7, h: 2.2, fontSize: 14 });
  s.addNotes("From docs/runner.md and spec section 7. resume can be now, done, fail, in N units or at an ISO time. every/on/wait are reserved.");

  // --- crash safety
  s = content("Crash-safe by construction", "Task-centric packets");
  const jr = ["commit-begin", "children", "state swap", "memento", "status.md", "commit-end"];
  const jw = 1.88;
  jr.forEach((j, i) => {
    const x = MX + i * (jw + 0.17);
    card(s, x, 1.55, jw, 0.85, i === 0 || i === 5 ? C.text1 : C.background2);
    txt(s, j, { x, y: 1.55, w: jw, h: 0.85, fontSize: 14, bold: true, align: "center", valign: "middle",
      fontFace: MONO, color: i === 0 || i === 5 ? HEX.accent1 : C.text1 });
  });
  txt(s, "The whole decision is journaled and fsynced first. Every sub-step can tell whether it already happened, so wpk recover redoes only what is missing.",
    { x: MX, y: 2.6, w: CW, h: 0.7, fontSize: 15, color: C.text2 });
  const cs = [
    [I.shield, "Lease", ".lease created O_CREAT|O_EXCL: one runner per packet, with host, pid and expiry"],
    [I.db, "Journal", "journal.jsonl: step-start, step-failed, nudge, commit, hand-off, note"],
    [I.sitemap, "Idempotent children", "child IDs are uuid5(parent:step:index): a retry can't duplicate them"],
  ];
  cs.forEach((c, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    card(s, x, 3.6, w, 2.7, C.background2);
    circleIcon(s, c[0], x + 0.3, 3.85, 0.7, C.accent2);
    txt(s, c[1], { x: x + 0.3, y: 4.7, w: w - 0.6, h: 0.4, fontSize: 17, bold: true });
    txt(s, c[2], { x: x + 0.3, y: 5.1, w: w - 0.6, h: 1.1, fontSize: 13.5, color: C.text2 });
  });
  s.addNotes("This is the durable-execution idea (Temporal, Restate, DBOS) applied to files on disk instead of a database. Lesson from the prototype: when the model kept its own books, the last step ran twice, a count went to 9 of 8 and two identical children appeared. The executor now owns the clock, step numbers, commits, scheduling and spawning; the model does one unit of work.");

  // ===================================================== Many projects
  divider("Many projects under one runner", "Scheduling, periodic management tasks, hand-offs and a board to watch them", "Many projects");

  // --- architecture
  s = content("Four layers, and files are the truth", "Many projects");
  const layers = [
    ["CLI and board", "wpk new · ps · show · handoff · answer · wpk dash", C.accent2],
    ["Runner", "registry · scheduler · worker pool · reaper · event log", C.text2],
    ["Executor", "wpk step <WPID>: one step, committed atomically", C.text1],
    ["Files", "~/.work-packet/projects/*.toml  →  <project>/packets/<WPID>/", C.accent3],
  ];
  layers.forEach((l, i) => {
    const y = 1.45 + i * 1.15, w = 7.4;
    card(s, MX, y, w, 0.95, l[2]);
    txt(s, l[0], { x: MX + 0.3, y, w: 2.2, h: 0.95, fontSize: 17, bold: true, color: C.background1, valign: "middle" });
    txt(s, l[1], { x: MX + 2.5, y, w: w - 2.7, h: 0.95, fontSize: 13, color: HEX.lt1, valign: "middle", fontFace: MONO });
  });
  txt(s, "Design rules", { x: 8.5, y: 1.45, w: 4.2, h: 0.45, fontSize: 19, bold: true, color: C.accent2 });
  txt(s, bullets([
    "The runner holds no state that can't be rebuilt by scanning directories",
    "The executor knows nothing about the runner",
    "Today: wpk tick (one scheduler pass), from cron or by hand",
    "Next: a per-user runner daemon that starts a hand-off within about a second",
  ]), { x: 8.5, y: 2.0, w: 4.23, h: 4.0, fontSize: 14.5, paraSpaceAfter: 10 });
  s.addNotes("From docs/runner.md. The runner daemon (L3) and the merged server wpkd are designed but not built; today wpk tick -j N runs due packets oldest first.");

  // --- time
  s = content("Time is the executor's job; sleeping is free", "Many projects");
  const tl = [["step", "Step", "writes resume: in 10 days"], ["sleep", "Asleep: 0 tokens", "just a directory on disk"],
    ["step", "Wake + step", "writes resume: in 3 days"], ["sleep", "Asleep: 0 tokens", "wake_at is visible and editable"],
    ["step", "Wake + step", "on time, or early on a note"]];
  let tx = MX;
  tl.forEach((t, i) => {
    const w = t[0] === "step" ? 2.25 : 2.56;
    card(s, tx, 1.45, w, 1.2, t[0] === "step" ? C.text1 : C.background2);
    txt(s, t[1], { x: tx + 0.18, y: 1.58, w: w - 0.3, h: 0.4, fontSize: 15, bold: true,
      color: t[0] === "step" ? C.accent1 : C.text1 });
    txt(s, t[2], { x: tx + 0.18, y: 1.98, w: w - 0.3, h: 0.6, fontSize: 12, color: t[0] === "step" ? C.background1 : C.text2 });
    tx += w + 0.08;
  });
  const tr = [
    ["The model never does date arithmetic", "It writes an expression; the executor resolves it to a UTC wake_at in the project's time zone and stores both."],
    ["Recurrence belongs to the executor", "With every: (designed, Stage 2), the timer is re-armed even after a failed step, so a periodic task can't silently stop."],
    ["Missed wakes catch up once", "Like systemd Persistent=true or anacron: a laptop that slept runs the job once, not ten times."],
  ];
  tr.forEach((r, i) => {
    const y = 3.0 + i * 1.2;
    circleIcon(s, I.clock, MX, y + 0.1, 0.65, C.accent2);
    txt(s, r[0], { x: MX + 0.95, y, w: 11, h: 0.4, fontSize: 17, bold: true });
    txt(s, r[1], { x: MX + 0.95, y: y + 0.42, w: 11, h: 0.6, fontSize: 14, color: C.text2 });
  });
  s.addNotes("From clock.py and the scheduled-resumption section of the roadmap. DST rules are in spec section 5.");

  // --- management tasks
  s = content("Management-like work is a first-class packet", "Many projects");
  code(s, MX, 1.45, 6.4, 1.4, [
    ["$ wpk new nightly-triage --template nightly-triage \\", HEX.lt1],
    ["    --every \"daily 06:00\"", HEX.accent1],
    ["# designed: templates, --every", MUTED],
  ], 13);
  const tmpl = [["blank", "the prompt is the first instruction (built)"], ["periodic", "a recurring check that writes one report per run"],
    ["research", "plan, fan out a child per sub-question, merge"], ["nightly-triage", "run the dv-flow regression, triage new failures"]];
  tmpl.forEach((t, i) => {
    const y = 3.0 + i * 0.85;
    card(s, MX, y, 6.4, 0.72, C.background2);
    txt(s, t[0], { x: MX + 0.25, y, w: 2.2, h: 0.72, fontSize: 14, bold: true, fontFace: MONO, valign: "middle" });
    txt(s, t[1], { x: MX + 2.5, y, w: 3.8, h: 0.72, fontSize: 13.5, color: C.text2, valign: "middle" });
  });
  card(s, 7.4, 1.45, 5.33, 5.0, HEX.accent6);
  txt(s, "Packets can manage packets", { x: 7.7, y: 1.65, w: 4.8, h: 0.45, fontSize: 19, bold: true });
  txt(s, bullets([
    { text: "spawn: in a memento creates children with their own instruction, copied state and model" },
    { text: "A project is a root packet and everything it spawns; the board shows the tree" },
    { text: "Planned: an outline with a cursor; items are work, research or gates" },
    { text: "Gates collect questions with provisional answers, so work goes on while a person decides" },
  ]), { x: 7.7, y: 2.25, w: 4.8, h: 4.0, fontSize: 14.5, paraSpaceAfter: 10 });
  s.addNotes("Templates and --every are designed in docs/runner.md; today wpk new uses the blank template, and a packet re-arms itself with resume: in/at. spawn is built. The outline, cursor and gates are a candidate shape in docs/stack-experiment.md section 1a; the dv-solve trial runs the outline by hand in state/outline.md. Triage templates: direct, list or project, by how much structure a task needs.");

  // --- hand-off
  s = content("A packet belongs to one party at a time", "Many projects");
  card(s, MX, 1.6, 3.4, 2.0, C.text2);
  circleIcon(s, I.user, MX + 1.3, 1.8, 0.8, C.accent1);
  txt(s, "Person", { x: MX, y: 2.75, w: 3.4, h: 0.5, fontSize: 19, bold: true, color: C.background1, align: "center" });
  card(s, 9.33, 1.6, 3.4, 2.0, C.accent2);
  circleIcon(s, I.robot, 9.33 + 1.3, 1.8, 0.8, C.text1);
  txt(s, "Runner", { x: 9.33, y: 2.75, w: 3.4, h: 0.5, fontSize: 19, bold: true, color: C.background1, align: "center" });
  arrow(s, 4.3, 1.85, 4.7, 0.45, C.accent2);
  txt(s, "wpk handoff -m \"…\"", { x: 4.3, y: 1.35, w: 4.7, h: 0.4, fontSize: 13, fontFace: MONO, align: "center" });
  s.addShape(pres.shapes.LEFT_ARROW, { x: 4.3, y: 2.85, w: 4.7, h: 0.45, fill: { color: C.accent1 },
    line: { color: C.accent1 }, objectName: "larr" });
  txt(s, "ask: → NEEDS_INPUT · wpk take", { x: 4.3, y: 3.35, w: 4.7, h: 0.4, fontSize: 13, fontFace: MONO, align: "center" });
  const ho = [
    ["Structured questions", "ask: items carry id, question, a recommendation, choices and tool grants. Answer one, or take all the recommendations."],
    ["Notes in any state", "wpk note drops a message in mailbox/; a hook delivers it mid-step, or the next prompt shows it."],
    ["Everything is journaled", "Hand-offs, answers and notes appear in the journal and in the next step's prompt."],
  ];
  ho.forEach((h, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    card(s, x, 4.2, w, 2.3, C.background2);
    txt(s, h[0], { x: x + 0.3, y: 4.35, w: w - 0.6, h: 0.4, fontSize: 16, bold: true });
    txt(s, h[1], { x: x + 0.3, y: 4.8, w: w - 0.6, h: 1.6, fontSize: 13.5, color: C.text2 });
  });
  s.addNotes("From docs/long-running.md section 1 and docs/interaction.md. handoff, answer, allow, deny, set and note are built; take is designed.");

  // --- board
  s = content("The board: every project and packet at a glance", "Many projects");
  const colsB = [["Running", C.accent2, 2], ["Ready", C.accent6, 1], ["Sleeping", C.accent3, 3], ["Needs you", C.accent1, 2],
    ["Failed", C.accent4, 1], ["Done", C.text2, 3]];
  card(s, MX, 1.4, CW, 3.6, C.background2, "C9D1D9");
  colsB.forEach((c, i) => {
    const w = 1.9, x = MX + 0.2 + i * (w + 0.07);
    txt(s, c[0], { x, y: 1.55, w, h: 0.35, fontSize: 13, bold: true });
    for (let k = 0; k < c[2]; k++) {
      const y = 2.0 + k * 0.95;
      card(s, x, y, w, 0.82, C.background1, "D5DBE1");
      s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: y + 0.14, w: 0.18, h: 0.18, fill: { color: c[1] },
        line: { color: c[1] }, objectName: "bd" + (++n) });
      txt(s, ["uart16550", "chi-snoop", "nightly-triage", "weekly-report", "dvs-enh", "proto-survey"][(i + k) % 6],
        { x: x + 0.38, y: y + 0.08, w: w - 0.45, h: 0.3, fontSize: 11, bold: true, fontFace: MONO });
      txt(s, ["step 12 · $0.41", "wakes 06:00", "2 questions", "step 3 · $0.05"][(i * 2 + k) % 4],
        { x: x + 0.38, y: y + 0.42, w: w - 0.45, h: 0.3, fontSize: 10.5, color: C.text2 });
    }
  });
  const bv = [["Project page", "packet tree, timeline, Tokens panel"], ["Live view", "what it is doing now, its tasks, processes, steps done"],
    ["Step viewer", "transcript, console log, raw JSONL, a resumable session"]];
  bv.forEach((b, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    txt(s, [{ text: b[0] + ": ", options: { bold: true } }, { text: b[1], options: { color: HEX.dk2 } }],
      { x, y: 5.25, w, h: 0.8, fontSize: 14 });
  });
  txt(s, "wpk dash serves it locally; --tailnet shares it over Tailscale with an identity check.", { x: MX, y: 6.15, w: CW, h: 0.4,
    fontSize: 14, italic: true, color: C.accent2 });
  s.addNotes("Columns follow the packet's state; dragging a card doesn't change it. Actions (answer, hand off, pause, settings) are POSTs guarded by Host/Origin checks and a CSRF token. The card contents here are illustrative.");

  // ===================================================== Tokens
  divider("Tuned for tokens, by measurement", "Record what every step costs, then change how steps are sized and chained", "Token efficiency");

  // --- cost model
  s = content("What a step really pays for", "Token efficiency");
  stat(s, MX, 1.4, 2.8, "0.1×", "input price for a cache read");
  stat(s, MX + 3.0, 1.4, 2.8, "2×", "input price for a 1-hour cache write");
  stat(s, MX + 6.0, 1.4, 2.8, "~100×", "more input than output tokens in practice");
  stat(s, MX + 9.0, 1.4, 3.0, "97%", "of context tokens served from the cache (dvs-enh)");
  card(s, MX, 3.75, CW, 2.75, C.text1);
  txt(s, "Consequences", { x: MX + 0.35, y: 3.95, w: 5, h: 0.4, fontSize: 18, bold: true, color: HEX.accent1 });
  txt(s, bullets([
    "Input, not output, is the bill: every call re-reads the context",
    "A session's cost grows roughly with the square of its length",
    "Carrying a session on beats starting fresh only while it is small: break-even near C ≈ 4–7 × the orientation context O",
    "Getting oriented costs 20–45k tokens: a third to half of an 80k step budget",
  ], { color: HEX.lt1 }), { x: MX + 0.35, y: 4.45, w: CW - 0.7, h: 2.0, fontSize: 15 });
  s.addNotes("From docs/context.md section 1 and docs/token-dashboard.md. Carry on while (C − O) × turns × 0.1 < 2·O + orientation turns; with 3–6 tool calls per piece of work this tips over at C ≈ 4–7·O.");

  // --- where context goes
  s = content("Measure first: where the context went", "Token efficiency");
  s.addChart(pres.charts.BAR, [{ name: "Share", labels: ["The prompt", "Model turns", "Bash results", "Read results", "Edit, Write, etc."],
    values: [36, 33, 18, 13, 1] }], chartBase({
    x: MX, y: 1.4, w: 7.2, h: 4.6, barDir: "bar", chartColors: [HEX.accent2],
    title: "Share of carried context, dvs-enh, 24 attempts (Oct 24)", dataLabelFormatCode: "0\"%\"",
    valAxisHidden: true, valGridLine: { style: "none" }, catAxisOrientation: "maxMin", dataLabelPosition: "outEnd",
  }));
  txt(s, "dvs-enh totals at 19 attempts", { x: 8.2, y: 1.4, w: 4.5, h: 0.4, fontSize: 16, bold: true, color: C.accent2 });
  [["51.8M", "context tokens"], ["$20.70", "total spend"], ["13%", "of tokens on failed attempts"]].forEach((t, i) => {
    const y = 1.9 + i * 1.3;
    txt(s, t[0], { x: 8.2, y, w: 2.3, h: 0.9, fontSize: 36, bold: true, color: C.accent1, fontFace: THEME.headFontFace, valign: "middle" });
    txt(s, t[1], { x: 10.55, y, w: 2.2, h: 0.9, fontSize: 14, color: C.text2, valign: "middle" });
  });
  txt(s, "The ~23k-token prompt is read on every call: the biggest single lever.", { x: MX, y: 6.15, w: CW, h: 0.45,
    fontSize: 15, italic: true, bold: true, color: C.accent4 });
  s.addNotes("From docs/token-dashboard.md, view 5. Tool attribution (toolcost.py) charges each tool result its size times the number of calls that remain after it, since it is re-read on each.");

  // --- case study
  s = content("Case study: what dvs-enh's first steps taught us", "Token efficiency");
  txt(s, "A real packet: the dv-solve enhancement plan, Sonnet 5, an 80k context limit, a clone of dv-solve in work/", { x: MX, y: 1.3, w: CW, h: 0.4,
    fontSize: 15, italic: true, color: C.text2 });
  const cases = [
    ["The context limit set the step boundary", "fired in 6 of 8 steps; no step did exactly one item", "Size outline items to one step and one commit when planning"],
    ["Orientation cost 20–45k tokens", "a third to half of each step's budget, re-reading the same files", "Memento names the exact next action and file ranges; cap ~2 KB"],
    ["Research handed on as prose was redone", "twice, the next step read everything again", "Stopping rule: start the next item only under half the limit"],
    ["Environment facts got lost or went wrong", "solver path, venv, build flags rediscovered", "state/env.md: verified facts only, shown in every prompt"],
    ["The prompt grew from 15k to 25k", "outline.md passed the 4 KB inline limit", "Results go to state/log.md; answered questions archived"],
  ];
  txt(s, "What we saw", { x: MX, y: 1.85, w: 6.4, h: 0.35, fontSize: 15, bold: true, color: C.accent4 });
  txt(s, "What changed", { x: 7.4, y: 1.85, w: 5.3, h: 0.35, fontSize: 15, bold: true, color: C.accent2 });
  cases.forEach((c, i) => {
    const y = 2.3 + i * 0.86;
    card(s, MX, y, 6.4, 0.76, C.background2);
    txt(s, c[0], { x: MX + 0.2, y: y + 0.06, w: 6.0, h: 0.35, fontSize: 14, bold: true });
    txt(s, c[1], { x: MX + 0.2, y: y + 0.4, w: 6.0, h: 0.32, fontSize: 12, color: C.text2 });
    arrow(s, 7.05, y + 0.25, 0.3, 0.26, C.accent2);
    card(s, 7.4, y, 5.33, 0.76, HEX.accent6);
    txt(s, c[2], { x: 7.6, y, w: 5.0, h: 0.76, fontSize: 13, valign: "middle" });
  });
  s.addNotes("From docs/experiments/dvs-enh-steps.md. Steps 1-8 cost $0.53-$1.13 each. The changes went into prompts/protocol.md and the sizing text, and the limit was raised to 120k (docs/trial-dv-solve.md section 10). This is the loop the system is built for: measure, read the numbers, change how steps are sized.");

  // --- controls
  s = content("Five controls on context", "Token efficiency");
  const ctl = [
    ["C1", "Measure", "meta.json records first, peak and last context, calls, base, cache breaks", "Built"],
    ["C2", "Protocol in the system prompt", "the step protocol goes in a cacheable system slot", "Built"],
    ["C3", "Context budget hook", "ctxhook asks the model to finish the item in hand at 80k; hard stop at 1.2×", "Built"],
    ["C4", "Session carry-over", "resume and fork the previous step's session while it is still cheap", "Built, opt-in"],
    ["C5", "work/ digest", "a summary of the work repos in the prompt instead of re-reading", "Planned"],
  ];
  ctl.forEach((c, i) => {
    const y = 1.45 + i * 1.0;
    card(s, MX, y, CW, 0.85, i % 2 ? C.background1 : C.background2, "DDE2E7");
    txt(s, c[0], { x: MX + 0.25, y, w: 0.8, h: 0.85, fontSize: 22, bold: true, color: C.accent1, fontFace: THEME.headFontFace, valign: "middle" });
    txt(s, c[1], { x: MX + 1.1, y, w: 3.4, h: 0.85, fontSize: 16, bold: true, valign: "middle" });
    txt(s, c[2], { x: MX + 4.5, y, w: 5.8, h: 0.85, fontSize: 13.5, color: C.text2, valign: "middle" });
    const done = c[3].startsWith("Built");
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 10.45, y: y + 0.2, w: 1.5, h: 0.45, rectRadius: 0.22,
      fill: { color: done ? C.accent2 : C.background1 }, line: { color: done ? C.accent2 : C.accent3, width: 0.75 }, objectName: "pill" + (++n) });
    txt(s, c[3], { x: MX + 10.45, y: y + 0.2, w: 1.5, h: 0.45, fontSize: 12, bold: true, align: "center", valign: "middle",
      color: done ? C.background1 : C.text2 });
  });
  txt(s, "Prompt trimming too: state files over 4 KB are listed, not shown; state/archive/ is never shown; the memento is capped near 2 KB.",
    { x: MX, y: 6.5, w: CW, h: 0.4, fontSize: 13, italic: true, color: C.text2 });
  s.addNotes("From docs/context.md. Also bghook refuses background Bash calls, after two dv-solve steps ended their turn waiting on a background task and never wrote a memento.");

  // --- metrics to strategy
  s = content("From metrics to execution strategy", "Token efficiency");
  code(s, MX, 1.45, 6.2, 2.2, [
    ["$ wpk stats --by model", HEX.lt1],
    ["claude-haiku@1  27 steps  4 calls median", HEX.accent1],
    ["  base 10.9k  $0.0164/step  15% short", HEX.accent1],
    ["  no advice", MUTED],
  ], 13);
  txt(s, "Advice is printed, never applied. The packet files stay the source of truth.", { x: MX, y: 3.85, w: 6.2, h: 0.7,
    fontSize: 14, italic: true, color: C.text2 });
  txt(s, "Profiles carry the tuning per harness and model", { x: MX, y: 4.6, w: 6.2, h: 0.4, fontSize: 15, bold: true });
  ["built-in", "profile", "config.toml", "project.toml"].forEach((p, i) => {
    const x = MX + i * 1.6;
    card(s, x, 5.1, 1.42, 0.6, i === 3 ? HEX.accent5 : C.background2);
    txt(s, p, { x, y: 5.1, w: 1.42, h: 0.6, fontSize: 11.5, fontFace: MONO, align: "center", valign: "middle" });
    if (i < 3) txt(s, "<", { x: x + 1.42, y: 5.1, w: 0.18, h: 0.6, fontSize: 16, bold: true, align: "center", valign: "middle", color: C.accent3 });
  });
  txt(s, "sizing · step_context_tokens · carry_factor · price", { x: MX, y: 5.85, w: 6.2, h: 0.4, fontSize: 12, fontFace: MONO, color: C.text2 });
  const rules = [
    ["Short rate > 40%", "steps stop early → sizing = persistent, carry_session = true"],
    ["Hook fires > 25%", "steps run long → smaller items or a bigger budget"],
    ["Retry rate > 10%", "harness or protocol trouble: look at the failures"],
    ["Least-squares fit", "re-estimates the carry_factor break-even per model"],
  ];
  rules.forEach((r, i) => {
    const y = 1.45 + i * 1.25;
    card(s, 7.2, y, 5.53, 1.05, C.background2);
    txt(s, r[0], { x: 7.45, y: y + 0.12, w: 5.1, h: 0.4, fontSize: 15, bold: true, color: C.accent2 });
    txt(s, r[1], { x: 7.45, y: y + 0.52, w: 5.1, h: 0.45, fontSize: 13.5, color: C.text2 });
  });
  s.addNotes("A 'short' step has 3 or fewer API calls and 4 or fewer changed state lines. Sizing is bounded (one item per step, start another only below half the budget) or persistent (finish the instruction before stopping). Only carry_factor may be tuned automatically.");

  // --- results
  s = content("Results so far", "Token efficiency");
  s.addChart(pres.charts.BAR, [{ name: "Total cost", labels: ["Fresh each step", "Carried session"], values: [0.191, 0.131] }],
    chartBase({ x: MX, y: 1.4, w: 3.9, h: 4.3, barDir: "col", chartColors: [HEX.accent3, HEX.accent2],
      title: "E7 run cost, USD", dataLabelFormatCode: "$0.000", valAxisHidden: true, valGridLine: { style: "none" },
      dataLabelPosition: "outEnd", valAxisMinVal: 0, valAxisMaxVal: 0.22 }));
  s.addChart(pres.charts.BAR, [{ name: "Input-equivalent", labels: ["Real sessions", "Steps, 80k", "Steps, 150k"], values: [28.4, 19.6, 16.4] }],
    chartBase({ x: MX + 4.2, y: 1.4, w: 4.0, h: 4.3, barDir: "col", chartColors: [HEX.accent3, HEX.accent2, HEX.accent2],
      title: "fw-proto-chi, M input-equivalent tokens", dataLabelFormatCode: "0.0\"M\"", valAxisHidden: true,
      valGridLine: { style: "none" }, dataLabelPosition: "outEnd", valAxisMinVal: 0, valAxisMaxVal: 32 }));
  const res = [["−31%", "carry-over vs fresh steps; 75 s vs ~110 s wall time"], ["3× smaller", "context per call when simulated as steps; input −31 to −42%. So: carry within a phase, fresh at boundaries"],
    ["$0.48", "three live E7 runs, 27 steps, 0 failed attempts"]];
  res.forEach((r, i) => {
    const y = 1.45 + i * 1.5;
    card(s, 9.0, y, 3.73, 1.3, i === 1 ? HEX.accent5 : C.background2);
    txt(s, r[0], { x: 9.2, y: y + 0.08, w: 3.4, h: 0.6, fontSize: 26, bold: true, color: C.accent1, fontFace: THEME.headFontFace });
    txt(s, r[1], { x: 9.2, y: y + 0.62, w: 3.4, h: 0.65, fontSize: 11.5, color: C.text2 });
  });
  txt(s, "Early numbers on small runs; the fw-proto-chi figures are a paper simulation, not a live run.", { x: MX, y: 6.0, w: CW, h: 0.4,
    fontSize: 13, italic: true, color: C.text2 });
  s.addNotes("Sources: docs/context.md status log (fresh $0.191 vs carried $0.131), docs/stage1-plan.md (E7: $0.48 over three runs, about $0.018 a step), docs/experiments/stack-fw-proto-chi/simulation.md 7.2 (28.4M real vs 19.6M and 16.4M simulated; context per call drops 3–4×).");

  // ===================================================== Industry
  divider("How the industry approaches it", "Coding agents, orchestration frameworks, durable execution, observability and EDA", "Industry");

  // --- landscape
  s = content("The landscape in six families", "Industry");
  IND.families.forEach((f, i) => {
    const y = 1.4 + i * 0.88, h = 0.78;
    card(s, MX, y, CW, h, i ? (i % 2 ? C.background2 : C.background1) : HEX.accent5, "DDE2E7");
    txt(s, f[0], { x: MX + 0.25, y, w: 3.35, h, fontSize: 15, bold: true, valign: "middle", color: C.accent2 });
    txt(s, f[1], { x: MX + 3.7, y, w: 4.2, h, fontSize: 12.5, valign: "middle" });
    txt(s, f[2], { x: MX + 8.05, y, w: 3.95, h, fontSize: 12.5, valign: "middle", color: C.text2, italic: true });
  });
  s.addNotes(IND.notes.families);

  // --- persistence
  s = content("Where each one keeps its state", "Industry");
  IND.persistence.forEach((p, i) => {
    const cw = 3.85, ch = 2.35, x = MX + (i % 3) * (cw + 0.275), y = 1.4 + Math.floor(i / 3) * (ch + 0.25);
    const ours = i === IND.persistence.length - 1;
    card(s, x, y, cw, ch, ours ? C.text1 : C.background2);
    txt(s, p[0], { x: x + 0.25, y: y + 0.18, w: cw - 0.5, h: 0.45, fontSize: 17, bold: true, color: ours ? HEX.accent1 : C.text1 });
    txt(s, p[1], { x: x + 0.25, y: y + 0.62, w: cw - 0.5, h: 0.4, fontSize: 12, italic: true, color: ours ? HEX.accent6 : C.accent2 });
    txt(s, p[2], { x: x + 0.25, y: y + 1.05, w: cw - 0.5, h: 1.25, fontSize: 13, color: ours ? HEX.lt1 : C.text2 });
  });
  s.addNotes(IND.notes.persistence);

  // --- matrix
  s = content("Side by side", "Industry");
  const hdr = IND.matrix.cols;
  const mark = v => ({ Y: "Yes", P: "Partly", N: "–" }[v] || v);
  const markColor = v => ({ Y: C.accent2, P: C.accent1, N: C.accent3 }[v] || C.text1);
  const rows = [hdr.map(h => ({ text: h, options: { bold: true, color: C.background1, fill: { color: C.text2 }, fontSize: 12, align: h === hdr[0] ? "left" : "center" } }))];
  IND.matrix.rows.forEach((r, i) => {
    const ours = i === IND.matrix.rows.length - 1;
    rows.push(r.map((c, k) => ({ text: k === 0 ? c : mark(c), options: {
      bold: ours || k === 0 || c === "Y", fontSize: 11.5, align: k === 0 ? "left" : "center",
      color: k === 0 ? C.text1 : (ours && c === "P" ? C.text2 : markColor(c)),
      fill: { color: ours ? HEX.accent5 : (i % 2 ? HEX.lt1 : HEX.lt2) } } })));
  });
  s.addTable(rows, { x: MX, y: 1.35, w: CW, colW: IND.matrix.colW, rowH: 0.3, margin: [0, 0.1, 0, 0.1],
    border: { type: "solid", pt: 0.5, color: "D5DBE1" }, valign: "middle", objectName: "matrix" });
  txt(s, "Yes / Partly / – (little or none). Judgments from public docs and reviews, October 2026; work-packet rates itself on what is built.", { x: MX, y: 6.55, w: CW, h: 0.3,
    fontSize: 11, color: C.text2, italic: true });
  s.addNotes(IND.notes.matrix);

  // --- EDA
  s = content("In EDA, agents come from tool vendors", "Industry");
  IND.eda.forEach((e, i) => {
    const cw = 3.85, ch = 2.2, x = MX + (i % 3) * (cw + 0.275), y = 1.4 + Math.floor(i / 3) * (ch + 0.25);
    card(s, x, y, cw, ch, C.background2);
    circleIcon(s, I.chip, x + 0.25, y + 0.25, 0.55, C.accent2);
    txt(s, e[0], { x: x + 0.95, y: y + 0.25, w: cw - 1.15, h: 0.55, fontSize: 15, bold: true, valign: "middle" });
    txt(s, e[1], { x: x + 0.25, y: y + 0.95, w: cw - 0.5, h: 1.2, fontSize: 12.5, color: C.text2 });
  });
  txt(s, IND.edaTakeaway, { x: MX, y: 6.25, w: CW, h: 0.5, fontSize: 14.5, italic: true, bold: true, color: C.accent2 });
  s.addNotes(IND.notes.eda);

  // --- gaps
  s = content("The gaps work-packet fills", "Industry");
  IND.gaps.forEach((g, i) => {
    const cw = 5.93, x = MX + (i % 2) * (cw + 0.275), y = 1.4 + Math.floor(i / 2) * 1.3;
    circleIcon(s, I.starDk, x, y + 0.1, 0.55, C.accent1);
    txt(s, g[0], { x: x + 0.8, y, w: cw - 0.85, h: 0.4, fontSize: 16, bold: true });
    txt(s, g[1], { x: x + 0.8, y: y + 0.4, w: cw - 0.85, h: 0.8, fontSize: 13, color: C.text2 });
  });
  txt(s, IND.gapsFooter, { x: MX, y: 5.6, w: CW, h: 0.5, fontSize: 15, italic: true, bold: true, color: C.accent2 });
  s.addNotes(IND.notes.gaps);

  // ===================================================== Close
  pres.addSection({ title: "Close" });
  s = content("Where it stands", "Close");
  const rm = [
    ["Built", C.accent2, ["Executor, commit protocol, recovery", "wpk tick scheduler, clock", "ask:, answer, handoff, note", "Board, live view, Tailscale sharing", "Context controls C1–C4, wpk stats", "Claude Code harness, profiles"]],
    ["Next", C.accent1, ["L2: executor-owned work/ commits", "L3: runner daemon (systemd user unit)", "Spec v0.3: HELD state, every:", "Outline, items and gates", "C5: work/ digest"]],
    ["Later", C.accent3, ["Codex and OpenCode harnesses", "job: and wait for long runs", "Daily budgets, rate limits", "Benchmark: dv-flow regression triage"]],
  ];
  rm.forEach((r, i) => {
    const w = 3.85, x = MX + i * (w + 0.275);
    card(s, x, 1.45, w, 0.6, r[1]);
    txt(s, r[0], { x: x + 0.3, y: 1.45, w: w - 0.6, h: 0.6, fontSize: 18, bold: true, color: C.background1, valign: "middle" });
    card(s, x, 2.15, w, 4.4, C.background2);
    txt(s, bullets(r[2]), { x: x + 0.25, y: 2.35, w: w - 0.45, h: 4.1, fontSize: 14, paraSpaceAfter: 8 });
  });
  s.addNotes("Status from the README: pre-alpha. Stage 1 works and E7 passed live with Haiku. Long-running L1 is partly done. Codex 0.147.0 and OpenCode 1.18.18 have been surveyed as harnesses.");

  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Close" });
  s.addText("Takeaways", { placeholder: "title" });
  const tk = [
    [I.folder, "Persist the task, not just the code", "A packet carries subject data, instructions, tracking and the expensive artifacts together."],
    [I.layers, "Run many projects as one fleet", "Feature work and periodic management tasks share one scheduler, one board and one record."],
    [I.chart, "Let the numbers size the steps", "Every step is measured; the stats say how to size and chain steps for each model."],
    [I.flag, "Built for silicon-scale work", "Long runs, big environments and many concurrent tasks are the design point, not an edge case."],
  ];
  tk.forEach((t, i) => {
    const y = 1.75 + i * 1.2;
    circleIcon(s, t[0], MX, y, 0.8, i === 3 ? C.accent1 : C.accent2);
    txt(s, t[1], { x: MX + 1.1, y: y + 0.02, w: 11, h: 0.4, fontSize: 19, bold: true, color: C.background1 });
    txt(s, t[2], { x: MX + 1.1, y: y + 0.45, w: 11, h: 0.45, fontSize: 15, color: MUTED });
  });
  s.addNotes("Close on the three ideas plus the design point. Invite questions on the comparison and the token numbers.");

  // --- references
  s = content("References", "Close");
  const half = Math.ceil(IND.refs.length / 2);
  [IND.refs.slice(0, half), IND.refs.slice(half)].forEach((list, k) => {
    const runs = [];
    list.forEach((r, i) => {
      runs.push({ text: r[0], options: { bold: true, breakLine: true } });
      runs.push({ text: r[1].replace(/^https:\/\/(www\.)?/, "").split("/")[0], options: { color: C.accent2, fontSize: 10,
        hyperlink: { url: r[1] }, breakLine: i < list.length - 1, paraSpaceAfter: 4 } });
    });
    txt(s, runs, { x: MX + k * 6.2, y: 1.35, w: 5.9, h: 5.5, fontSize: 12 });
  });
  s.addNotes("Project facts come from the work-packet docs (spec.md, context.md, long-running.md, runner.md, token-dashboard.md, stage1-plan.md, experiments/). Industry facts come from public product docs and blogs as of October 2026; check them before citing externally.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
}
build().catch(e => { console.error(e); process.exit(1); });
