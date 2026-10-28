// Builds slides/work-packet-pitch.pptx: a 12-slide pitch for an internal engineering audience.
// The problem for one engineer, then sharing work, then agents asking each other, then where
// we are and the roadmap. Sources: docs/product.md, docs/social.md, docs/context.md,
// docs/harness.md, docs/token-dashboard.md, docs/setup.md, docs/dash-tasks.md.
// Run: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> \
//      PPTX_SKILL=<pptx skill dir> node slides/pitch_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = path.join(__dirname, "work-packet-pitch.pptx");

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
const MUTED = "B8C2CC";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "work-packet: agent work you can track, share and ask about";
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
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 2.0, w: 11.5, h: 1.6,
      fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.8, w: 10.5, h: 1.4,
      fontSize: 24, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 32, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "work-packet · pitch for review", options: { x: MX, y: 6.95, w: 6, h: 0.3,
      fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CONTENT_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 32, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "work-packet · pitch for review", options: { x: MX, y: 6.95, w: 6, h: 0.3,
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
function content(title, section, dark) {
  const s = pres.addSlide({ masterName: dark ? "CONTENT_DARK" : "CONTENT", sectionTitle: section });
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
function code(slide, x, y, w, h, lines, fs, gap) {
  card(slide, x, y, w, h, C.text1);
  txt(slide, lines.map((l, i) => ({ text: l[0], options: { color: l[1] || HEX.lt1, paraSpaceAfter: gap || 0,
    breakLine: i < lines.length - 1 } })), { x: x + 0.3, y: y + 0.2, w: w - 0.5, h: h - 0.35,
    fontFace: MONO, fontSize: fs || 13 });
}
function pill(slide, text, x, y, w, fill, color) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.32, fill: { color: fill },
    line: { color: fill }, rectRadius: 0.16, objectName: "pill" + (++n) });
  txt(slide, text, { x, y, w, h: 0.32, fontSize: 11, bold: true, color: color || C.background1,
    align: "center", valign: "middle" });
}
// A dark banner with a bold lead-in and a sentence.
function banner(slide, y, lead, rest, h) {
  card(slide, MX, y, CW, h || 0.8, C.text1);
  txt(slide, [
    { text: lead, options: { bold: true, color: HEX.accent1 } },
    { text: rest, options: { color: HEX.lt1 } },
  ], { x: MX + 0.35, y, w: CW - 0.7, h: h || 0.8, fontSize: 17, valign: "middle" });
}
// An icon-headed card: icon in a circle, a title, then body text.
function iconCard(slide, x, y, w, h, img, title, body, opts) {
  const o = opts || {};
  card(slide, x, y, w, h, o.fill || C.background2, o.line);
  circleIcon(slide, img, x + 0.25, y + 0.25, 0.65, o.iconFill || C.accent2);
  txt(slide, title, { x: x + 1.05, y: y + 0.22, w: w - 1.25, h: 0.7, fontSize: o.titleSize || 16, bold: true,
    fontFace: THEME.headFontFace, valign: "middle", color: o.titleColor || C.text1 });
  txt(slide, body, { x: x + 0.25, y: y + 1.05, w: w - 0.5, h: h - 1.2, fontSize: o.bodySize || 13,
    color: o.bodyColor || C.text2 });
}
const BUILT = HEX.accent2, PLANNED = HEX.accent1, IDEA = HEX.accent3;

async function build() {
  const I = {};
  const ic = { tasks: fa.FaTasks, windows: fa.FaWindowRestore, brain: fa.FaBrain, eye: fa.FaEye,
    chart: fa.FaChartBar, redo: fa.FaRedo, folder: fa.FaFolderOpen, user: fa.FaUserCheck, book: fa.FaBook,
    lock: fa.FaLock, shield: fa.FaShieldAlt, search: fa.FaSearch, question: fa.FaQuestionCircle,
    bulb: fa.FaLightbulb, bug: fa.FaBug, users: fa.FaUsers, handshake: fa.FaHandshake, globe: fa.FaGlobe,
    server: fa.FaServer, clock: fa.FaHourglassHalf, cal: fa.FaCalendarAlt, box: fa.FaBoxOpen,
    export: fa.FaFileExport, send: fa.FaPaperPlane, filter: fa.FaFilter, inbox: fa.FaInbox,
    ushield: fa.FaUserShield, check: fa.FaCheckCircle, money: fa.FaMoneyBillWave, sun: fa.FaSun,
    grad: fa.FaGraduationCap, chip: fa.FaMicrochip, tools: fa.FaTools, comments: fa.FaComments,
    branch: fa.FaCodeBranch, clip: fa.FaClipboardCheck, vial: fa.FaVial, person: fa.FaUser,
    robot: fa.FaRobot, net: fa.FaNetworkWired };
  for (const k of Object.keys(ic)) I[k] = await icon(ic[k], HEX.lt1);

  let s;
  // ===================================================== 1. Title
  pres.addSection({ title: "Introduction" });
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("work-packet", { placeholder: "title" });
  s.addText("Agent work an engineering team can track, share and ask about", { placeholder: "body" });
  txt(s, "one engineer  →  a team  →  a network of agents", { x: MX, y: 1.4, w: 9, h: 0.4, fontFace: MONO,
    fontSize: 16, color: C.accent2 });
  txt(s, "October 2026 · pitch for review · internal engineering", { x: MX, y: 6.6, w: 7, h: 0.35,
    fontSize: 12, color: C.accent3 });
  s.addNotes("The pitch in three steps. First, what is hard for one engineer running several agents at once, and how work-packet handles it today: most of that is built and in use. Second, what is hard about sharing agent work with a colleague, and the designed features that make a packet something you can hand over. Third, the network: agents that share what they found and ask each other questions, without going around anyone's permissions. It ends with where we are and the roadmap, including where else this technique could go inside an engineering organization.");

  // ===================================================== 2. Problem: one engineer
  pres.addSection({ title: "One engineer" });
  s = content("Agents made tasks faster; tracking them became the job", "One engineer");
  const pains = [
    [I.tasks, "Which tasks are open?", "Open, waiting on me, blocked, done: the state lives in my head and in tab titles."],
    [I.windows, "Too many windows", "Five terminals, tmux panes, two machines. Each agent session is its own silo."],
    [I.brain, "Context and compaction", "When to compact, when to start fresh? Long sessions get slow, costly and forgetful."],
    [I.eye, "Progress is invisible", "To see how a task is going I attach to its session and scroll back."],
    [I.chart, "Metrics I can't act on", "A bill or a quota bar, not \"this task burned it, change this setting\"."],
    [I.cal, "Periodic work", "Nightly triage, weekly bumps, \"retry Monday\": cron, glue scripts and memory."],
  ];
  pains.forEach((p, i) => {
    const x = MX + (i % 3) * 4.1, y = 1.45 + Math.floor(i / 3) * 2.15;
    iconCard(s, x, y, 3.93, 1.95, p[0], p[1], p[2], { iconFill: C.accent4, bodySize: 14 });
  });
  banner(s, 5.9, "The problem: ", "agent sessions are disposable, but the work is not. Nothing holds a task's state, plan, history and cost between sessions.");
  s.addNotes("This is the day of one engineer who already uses agents well. Each agent is fast. The overhead moved to the person: remembering which of six sessions is waiting for an answer, deciding when a session is too long and should be compacted or restarted, attaching to each window to see progress, and reading a monthly bill or a quota bar that does not say which task used it or what to change. Work that should recur, like nightly regression triage or a weekly dependency bump, needs cron plus glue plus remembering where the previous run left off. The root cause is that the session is the unit of work, and sessions are disposable.");

  // ===================================================== 3. The packet
  s = content("A packet gives each task a home, an owner and a history", "One engineer");
  code(s, MX, 1.45, 6.1, 4.3, [
    ["fix-uart-fifo/          wpk:7f3c…", HEX.accent1],
    ["  memento.md     the next instruction", null],
    ["  state/         plan, questions, findings", null],
    ["  work/          clones, a commit per step", null],
    ["  journal.jsonl  steps, hand-offs, cost", null],
    ["  steps/0007/    prompt, transcript,", null],
    ["                 summary, meta.json", null],
    ["", null],
    ["resume: every monday 09:00", HEX.accent2],
  ], 15, 4);
  txt(s, "A directory you can read, diff, back up and recover after a crash. The board is a view of it.",
    { x: MX, y: 5.95, w: 6.1, h: 0.6, fontSize: 14, color: C.text2, italic: true });
  const princ = [
    [I.redo, "Steps, not sessions", "A small deterministic executor runs one step, commits it atomically, then decides when the packet runs next: now, at 9:00, or every Monday."],
    [I.user, "One owner at a time", "You or the runner, never both. Control moves only by hand-off, so nothing changes under you."],
    [I.server, "One daemon, one board", "wpkd runs every packet and serves the board, on your machine or your tailnet, with your login."],
  ];
  princ.forEach((p, i) => {
    const y = 1.45 + i * 1.75;
    card(s, 7.0, y, 5.73, 1.6, C.background2);
    circleIcon(s, p[0], 7.2, y + 0.42, 0.75, C.accent2);
    txt(s, p[1], { x: 8.15, y: y + 0.18, w: 4.4, h: 0.4, fontSize: 17, bold: true, fontFace: THEME.headFontFace });
    txt(s, p[2], { x: 8.15, y: y + 0.6, w: 4.4, h: 0.9, fontSize: 14, color: C.text2 });
  });
  s.addNotes("A packet is a directory. memento.md is the next instruction; state holds the plan, open questions and findings; work holds git clones with one commit per step; the journal records every step, hand-off and its cost; each step folder keeps the prompt, transcript, summary and metrics. The executor runs one step at a time with claude -p (other harnesses are surveyed), commits it, and reads the step's resume line to decide when to run it next. A packet has one owner at a time, you or the runner, and control moves by hand-off. One daemon per user runs everything and serves the board.");

  // ===================================================== 4. What changes for one engineer
  s = content("For one engineer, every one of these is built and in use", "One engineer");
  const rows = [
    [I.tasks, "Open tasks", "The board: each packet running, sleeping, needs you, done or failed; boards per area; wpk ps"],
    [I.windows, "Many windows", "One daemon runs them all. New task, Compose and a browser shell on the board; Open in VS Code"],
    [I.brain, "Context", "A budget hook stops a step at its context limit with hand-off files; warm sessions carry over; small steps"],
    [I.eye, "Progress", "Live view, step summaries and the journal; questions arrive as \"Needs you\"; send a note any time"],
    [I.chart, "Metrics", "wpk stats: tokens, cost and weekly quota per project, task and step, with advice on what to change"],
    [I.cal, "Periodic work", "resume: every monday 09:00. The runner wakes the packet with its plan and its history"],
  ];
  rows.forEach((r, i) => {
    const y = 1.4 + i * 0.88, h = 0.78;
    card(s, MX, y, CW, h, i % 2 ? C.background1 : C.background2, i % 2 ? "E3E7EB" : null);
    circleIcon(s, r[0], MX + 0.15, y + 0.12, 0.54, C.accent2);
    txt(s, r[1], { x: MX + 0.85, y, w: 2.0, h, fontSize: 16, bold: true, valign: "middle", fontFace: THEME.headFontFace });
    txt(s, r[2], { x: MX + 2.9, y, w: 7.6, h, fontSize: 14, color: C.text2, valign: "middle" });
    pill(s, "built", MX + CW - 1.35, y + 0.23, 1.1, BUILT);
  });
  s.addNotes("Each pain from slide 2 maps to something built. The board (wpk dash) shows every packet's state, grouped on boards, with a live view of the running step. New task, Compose and a shell in the browser replace most terminal windows, and Open in VS Code works both on the desktop over Remote-SSH and in the browser. Context controls C1 to C4 are built and measured: a PostToolUse hook tells the model to finish the item, write hand-off files and stop when it reaches the step's context budget; a step that follows within the cache TTL resumes the warm session. Structured questions show as Needs you and are answered from the board; notes reach a packet at any time. wpk stats reports tokens, cost and the subscription's weekly quota per project, packet and step, and its advice rules name a setting to change. Scheduled resumption is in the packet format: resume now, at a time, or on a schedule. About 466 tests pass.");

  // ===================================================== 5. Metrics
  s = content("Metrics that say what to change, not just what it cost", "One engineer");
  s.addChart(pres.charts.BAR, [{ name: "Cost of the run", labels: ["Fresh session each step", "Warm session carried over"],
    values: [0.191, 0.131] }], {
    x: MX, y: 1.45, w: 5.6, h: 3.6, barDir: "col", chartColors: [HEX.accent3, HEX.accent2],
    showTitle: true, title: "Same task (E7, 9 steps): cost in US$", titleFontSize: 14, titleColor: HEX.dk1,
    titleFontFace: "+mn-lt",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "$0.000", dataLabelFontSize: 13,
    dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
    catAxisLabelColor: HEX.dk2, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: false, barGapWidthPct: 60, valAxisMinVal: 0, valAxisMaxVal: 0.22,
  });
  txt(s, "31% cheaper and 75 s instead of ~110 s, from one setting (carry_session) that wpk stats can recommend.",
    { x: MX, y: 5.15, w: 5.6, h: 0.7, fontSize: 13, color: C.text2 });
  const stats = [
    ["97%", "of 51.8M context tokens came from the cache on a real project (dvs-enh)"],
    ["100×", "input over output: cost is calls × context, so keep context small and steps short"],
    ["13%", "of all tokens went on failed attempts: a number to drive down"],
    ["11%", "of the weekly quota for a week of that project, shown per step on the board"],
  ];
  stats.forEach((st, i) => {
    const y = 1.45 + i * 1.1;
    card(s, 6.6, y, 6.13, 0.95, C.background2);
    txt(s, st[0], { x: 6.8, y, w: 1.5, h: 0.95, fontSize: 28, bold: true, color: C.accent2, valign: "middle",
      fontFace: THEME.headFontFace });
    txt(s, st[1], { x: 8.35, y, w: 4.25, h: 0.95, fontSize: 13, color: C.text2, valign: "middle" });
  });
  banner(s, 5.95, "Advice, with its evidence: ", "\"stops early on 40% of steps → sizing = persistent\", \"carried steps near the reset cost more → lower carry_factor\".", 0.75);
  s.addNotes("Every step's meta.json records tokens split by cache read, cache write and output, context per call, cost, and the subscription quota reading where the account has one. The chart is experiment E7, the same nine-step task run twice: carrying the warm session over between steps cost $0.131 instead of $0.191 and took 75 seconds instead of about 110. The numbers on the right are from dvs-enh, a real project: almost all context came from the cache, input outweighs output about a hundred to one, and 13% of tokens went on failed attempts. wpk stats has advice rules with a minimum sample of 30 steps; each piece of advice prints the numbers that triggered it. For an engineering manager, this is the first view of agent spend per task rather than per seat.");

  // ===================================================== 6. Sharing problem
  pres.addSection({ title: "Sharing work" });
  s = content("Sharing agent work today costs a day and exposes too much", "Sharing work");
  const share = [
    [I.tools, "Long setup", "Setting up one real project took 11 hand steps. A colleague who picks it up repeats every one."],
    [I.comments, "Context in one head", "Hand-over is a wall of chat text and a revision number. The plan and dead ends stay behind."],
    [I.lock, "All or nothing", "Transcripts hold paths, secrets and customer names. You send everything, or nothing."],
    [I.bug, "CI failures", "A nightly failure means rebuilding the environment by hand before anyone can look."],
    [I.question, "Asking for help", "Ask a colleague: paste context into chat. The answer stays in that chat."],
    [I.users, "No team view", "\"What did the agents do this week?\" is asked in stand-up and answered from memory."],
  ];
  share.forEach((p, i) => {
    const x = MX + (i % 3) * 4.1, y = 1.45 + Math.floor(i / 3) * 2.15;
    iconCard(s, x, y, 3.93, 1.95, p[0], p[1], p[2], { iconFill: C.accent4, bodySize: 14 });
  });
  banner(s, 5.9, "The problem: ", "work moves between people only if its setup, history and boundaries move with it.");
  s.addNotes("Setting up dvs-enh for an agent took eleven hand steps, most of them about finding things and knowing rules (docs/setup.md). When the work moves to a colleague, the setup is repeated and the context is retyped. The data question is the blocker in an internal environment: a transcript can contain anything the agent read, so people either share everything or nothing. CI failures are the most common hand-over and the slowest: someone rebuilds the environment at the right revision before anyone can debug. Asking for help means pasting context into chat, and the answer is lost there. Managers get status from stand-up, not from the work.");

  // ===================================================== 7. Sharing with packets
  s = content("Share the packet, not a paste", "Sharing work");
  const flow = [
    [I.box, "Your packet", "plan, journal, worktrees"],
    [I.filter, "Export profile", "you see each file first"],
    [I.send, "Link or hub", "signed, to an inbox"],
    [I.inbox, "Their board", "accept, then it runs as them"],
    [I.branch, "Open at the revision", "VS Code, same history"],
  ];
  flow.forEach((f, i) => {
    const x = MX + i * 2.5, w = 2.1;
    card(s, x, 1.45, w, 1.75, C.text1);
    circleIcon(s, f[0], x + (w - 0.6) / 2, 1.6, 0.6, C.accent2);
    txt(s, f[1], { x: x + 0.1, y: 2.27, w: w - 0.2, h: 0.4, fontSize: 14, bold: true, color: C.background1, align: "center" });
    txt(s, f[2], { x: x + 0.1, y: 2.65, w: w - 0.2, h: 0.45, fontSize: 11, color: MUTED, align: "center" });
    if (i < flow.length - 1) arrow(s, x + w + 0.08, 2.15, 0.24, 0.32, C.accent1);
  });
  const feats = [
    ["Setup travels", "wpk doctor checks a project and gives the fix for each gap; a recipe rebuilds the workspace on another host.", "doctor built · recipe R4", BUILT],
    ["You choose what leaves", "Profiles full, team and report. Transcripts are out by default; secrets scanned; export shows each file before it goes.", "R4", PLANNED],
    ["Assign or consult", "Assign moves ownership. Consult sends copies; replies come back with answers and changes to apply or forward.", "R5 · no server needed", PLANNED],
    ["CI failure → packet", "The failing run becomes a packet at the right revision, on the right person's board, ready to reproduce.", "R4 · R6 via the hub", PLANNED],
  ];
  feats.forEach((f, i) => {
    const x = MX + i * 3.08, w = 2.9, y = 3.45;
    card(s, x, y, w, 2.4, C.background2);
    txt(s, f[0], { x: x + 0.22, y: y + 0.15, w: w - 0.44, h: 0.45, fontSize: 16, bold: true, fontFace: THEME.headFontFace });
    txt(s, f[1], { x: x + 0.22, y: y + 0.6, w: w - 0.44, h: 1.25, fontSize: 13, color: C.text2 });
    pill(s, f[2], x + 0.22, y + 1.9, w - 0.44, f[3]);
  });
  banner(s, 6.05, "The rule: ", "nothing leaves without being shown to you, and nothing received runs with the sender's permissions.", 0.7);
  s.addNotes("The unit of sharing is the packet. Export writes a bundle under a profile: full for your own hosts, team for a colleague, report for another organization. The core tier (plan, journal, memento) always goes; transcripts default out and are fetched only on approval; export lists every file before anything leaves, and a secret scan runs first. Links connect two daemons directly, so a small team needs no server; the hub adds org sign-in, policy, audit and CI intake. Assign transfers ownership. Consult sends copies; each reply comes back with answers and changes, which the owner applies or forwards to the agent. The received packet runs under the recipient's account with the recipient's limits. Setup is the part that exists today: wpk doctor and the setup wizard. The rest is designed in docs/product.md, releases R4 to R6.");

  // ===================================================== 8. Agents asking agents
  pres.addSection({ title: "A network of agents" });
  s = content("Agents share what they found and ask before they guess", "A network of agents");
  const objs = [
    [I.bulb, "Findings", "While it works, the agent records root causes, workarounds and dead ends, each with scope and evidence. A finding with a verify command is checkable: anyone can re-run it at their revision."],
    [I.search, "Search first", "Findings go into a signed local index; links and the hub merge them by share level. wpk search, and an MCP tool, so an agent searches before it asks anyone."],
    [I.question, "Questions", "To a person, a team, a topic or a project's intake. The sender pays: it attaches what it searched and ruled out. An agent's question is a draft its owner approves."],
    [I.check, "Answers", "Credited to their author. Accepted by the asker; verified when its check passes on the asker's side. Verified answers become findings: knowledge accumulates without a wiki."],
  ];
  objs.forEach((o, i) => {
    const x = MX + (i % 2) * 4.0, y = 1.45 + Math.floor(i / 2) * 2.45, w = 3.85, h = 2.3;
    iconCard(s, x, y, w, h, o[0], o[1], o[2], { bodySize: 13 });
  });
  code(s, 8.75, 1.45, 3.98, 4.75, [
    ["state/findings/drain0.md", HEX.accent1],
    ["", null],
    ["claim: Questa 2025.3", null],
    ["  hangs in run_phase when", null],
    ["  drain time is 0", null],
    ["scope:", null],
    ["  repos: [pyhdl-if]", null],
    ["  tools: [questa@2025.3]", null],
    ["evidence:", null],
    ["  packet: wpk:01J…", null],
    ["  steps: [12, 14]", null],
    ["verify: make sim TEST=drain0", HEX.accent2],
    ["share: team", HEX.accent2],
  ], 12, 2);
  s.addNotes("This is the social layer in docs/social.md. Findings are small Markdown files the agent writes in state/findings while it works: a claim, its scope (repos, tool versions, tags), the evidence (packet, steps, commit) and optionally a verify command that exits 0 while the claim holds. They are indexed locally in a signed SQLite FTS file. Snapshots of that index travel over links at the share level each entry allows, and the hub merges them into an organization snapshot. Agents search through an MCP tool before they ask. A question goes to an audience, and the sender's daemon attaches the search it already did, so the receiver sees what was ruled out. Questions written by an agent are drafts until the owner approves them: agents never message strangers on their own. An accepted answer is credited; one whose check passes becomes a finding in the asker's packet. Inside a company, the valuable outcome is 'we have seen this before', routed to the person who has.");

  // ===================================================== 9. Security
  s = content("Secure by construction: nothing goes around a permission", "A network of agents", true);
  const pipe = [
    ["1  Gate", "allowlist, quotas, size, signature, dedupe", "no model"],
    ["2  Queue", "files in an inbox", "no model"],
    ["3  Triage", "2–3× a day, batched", "model with no tools, no private data, no outbound"],
    ["4  Person", "accept, answer, decline", "one batch, a few minutes"],
    ["5  Agent", "only what a person sends on", "a new packet, its own budget"],
  ];
  pipe.forEach((p, i) => {
    const x = MX + i * 2.5, w = 2.15;
    card(s, x, 1.45, w, 1.85, i === 2 ? C.accent2 : C.text2);
    txt(s, p[0], { x: x + 0.15, y: 1.55, w: w - 0.3, h: 0.4, fontSize: 16, bold: true, color: C.background1, fontFace: THEME.headFontFace });
    txt(s, p[1], { x: x + 0.15, y: 1.97, w: w - 0.3, h: 0.6, fontSize: 12, color: C.background1 });
    txt(s, p[2], { x: x + 0.15, y: 2.6, w: w - 0.3, h: 0.65, fontSize: 11, color: i === 2 ? C.text1 : C.accent1, italic: true });
    if (i < pipe.length - 1) arrow(s, x + w + 0.07, 2.2, 0.21, 0.32, C.accent1);
  });
  txt(s, "Every inbound question, consult, report or mention goes through one pipeline. The receiver's main agent never reads it directly.",
    { x: MX, y: 3.42, w: CW, h: 0.4, fontSize: 13, color: MUTED, italic: true });
  const rules = [
    [I.ushield, "Answers carry the source's permissions", "The answerer's daemon answers from what the answerer may see. Each index entry keeps its share level; the hub shows it only to people the source allows."],
    [I.person, "Work runs as the person who owns it", "An assigned packet runs under the recipient's account and limits. Imported permissions are shown for approval, never applied."],
    [I.shield, "Nothing remote is an instruction", "Remote text reaches an agent only quoted, under its owner's instruction, after a person sent it on. Outbound actions from remote input need a person."],
    [I.lock, "Links are not logins", "Peers and the hub see summaries and inboxes, never shells or credentials. Secret scan before any share level. No metrics about people."],
  ];
  rules.forEach((r, i) => {
    const x = MX + (i % 2) * 6.15, y = 3.95 + Math.floor(i / 2) * 1.45, w = 5.98;
    card(s, x, y, w, 1.3, C.text2);
    circleIcon(s, r[0], x + 0.2, y + 0.3, 0.65, C.accent1);
    txt(s, r[1], { x: x + 1.05, y: y + 0.1, w: w - 1.25, h: 0.4, fontSize: 14, bold: true, color: C.background1 });
    txt(s, r[2], { x: x + 1.05, y: y + 0.48, w: w - 1.25, h: 0.8, fontSize: 11.5, color: MUTED });
  });
  s.addNotes("Security is what makes this acceptable inside an engineering organization. Inbound traffic goes through a five-stage pipeline: a deterministic gate, a file queue, a triage model that runs a few times a day with no tools, no private data and no outbound channel, then a person who sees one batch, and only then, optionally, an agent in a new packet with its own budget. That keeps private data, untrusted content and an outbound channel from ever meeting in one unsupervised context: the 'lethal trifecta'. Permissions are never widened: an answer is computed by the answerer's daemon over what the answerer can see, and every index entry carries the share level and the source's permissions, as Glean does. Received work runs under the recipient's account. Links and the hub hold summaries and bundles, never credentials or shells. No metrics about people: the stats are about tasks.");

  // ===================================================== 10. Opportunities
  pres.addSection({ title: "Where we are" });
  s = content("Where this can go inside an engineering organization", "Where we are");
  const opps = [
    [I.bug, "Nightly regression triage", "Each failure a packet, deduplicated against findings, a likely cause on the owner's board before stand-up."],
    [I.vial, "Knowledge that tests itself", "Scheduled packets re-run findings' verify commands on new tool versions and flag the stale ones."],
    [I.clip, "Status from the journal", "Weekly team notes drafted from what the packets did. Shorter stand-ups; the same for public weekly posts."],
    [I.money, "Agent spend you can steer", "Budgets per team, cost per finished task, models and harnesses compared on real work, not benchmarks."],
    [I.chip, "Vendor cases as packets", "A reduced, reproducing testcase to the EDA or IP vendor; their progress shows on your board."],
    [I.sun, "Follow-the-sun hand-off", "Packets cross time zones with owner, plan and history; the next site starts where the last stopped."],
    [I.grad, "Onboarding by example", "Finished packets as worked examples: \"fork this investigation\" on my repo."],
    [I.net, "The org's agent memory", "The hub's merged findings served over MCP to any agent or tool, kept current as a side effect of work."],
  ];
  opps.forEach((o, i) => {
    const x = MX + (i % 4) * 3.07, y = 1.45 + Math.floor(i / 4) * 2.7, w = 2.92, h = 2.5;
    card(s, x, y, w, h, C.background2);
    circleIcon(s, o[0], x + 0.22, y + 0.22, 0.6, C.accent1);
    txt(s, o[1], { x: x + 0.22, y: y + 0.92, w: w - 0.44, h: 0.6, fontSize: 15, bold: true, fontFace: THEME.headFontFace });
    txt(s, o[2], { x: x + 0.22, y: y + 1.5, w: w - 0.44, h: 0.95, fontSize: 12, color: C.text2 });
  });
  s.addNotes("A brainstorm beyond the release plan, each built from pieces already designed. Regression triage: the CI bundle plus a search of the organization's findings attaches likely causes before anyone opens the failure, across projects rather than inside one tool. Findings with verify commands can be re-checked on a schedule as tools and repos move; that is verified knowledge built from work, not curation. The journal already has steps, commits, cost and summaries, so a weekly status note (and the public weekly post, K0) is a digest plus a short edit. Spend: per-task costs make team budgets and model comparisons possible on real work. Vendor support: a report bundle with a smoke check is a reproducing testcase; an agent-driven HDL testcase reducer would shrink it, and the vendor's progress comes back to the customer's board. Hand-off across sites is the same as hand-off between people. Finished packets become templates. And the hub's merged index is the organization's knowledge layer for any MCP client.");

  // ===================================================== 11. Where we are
  s = content("Where we are: one engineer's tool works", "Where we are");
  const nums = [["466", "tests pass"], ["C1–C4", "context controls, measured live"], ["$0.48", "three live runs on the board"], ["36", "steps on dvs-enh in one week"]];
  nums.forEach((m, i) => {
    const x = MX + i * 3.07, w = 2.92;
    card(s, x, 1.45, w, 1.05, C.text1);
    txt(s, m[0], { x: x + 0.2, y: 1.45, w: 1.3, h: 1.05, fontSize: 24, bold: true, color: C.accent1, valign: "middle", fontFace: THEME.headFontFace });
    txt(s, m[1], { x: x + 1.5, y: 1.45, w: w - 1.65, h: 1.05, fontSize: 12, color: C.background1, valign: "middle" });
  });
  const cols = [
    ["Built", BUILT, [
      "Packet format v0.2 and wpk check; atomic steps, crash recovery",
      "Scheduler: resume now, later or on a schedule; projects and registry",
      "The board: boards, live view, transcripts, questions, notes, hand-off, next batch",
      "New task, Compose, a shell in the browser; VS Code desktop and web",
      "Context hook and carry-over; wpk stats with tokens, quota and advice",
      "wpk doctor and the setup wizard; the board on a tailnet with its login",
    ]],
    ["Designed, not built", PLANNED, [
      "Long-running work: work/ repos atomic per step, take and HELD (R1)",
      "Persistent sessions; jobs with progress, dv-flow-mgr adapter; REST API (R2–R3)",
      "Export profiles, CI failure → packet, reports (R4)",
      "Links, assign and consult (R5); the hub with OIDC, policy, audit (R6)",
      "Findings, index, questions, triage inbox, channels (K1–K4)",
      "Weekly post from the journal (K0): the first social feature",
    ]],
  ];
  cols.forEach((c, i) => {
    const x = MX + i * 6.15, w = 5.98, y = 2.75;
    card(s, x, y, w, 3.95, i ? C.accent5 : C.accent6);
    pill(s, c[0], x + 0.3, y + 0.22, 2.2, c[1]);
    txt(s, bullets(c[2], { paraSpaceAfter: 6 }), { x: x + 0.3, y: y + 0.7, w: w - 0.55, h: 3.1, fontSize: 14 });
  });
  s.addNotes("Built and tested: the packet format and its checker, the step executor with atomic commits and crash recovery, scheduled resumption, projects, the web board with its actions and live view, New task, Compose and the browser shell, VS Code links, the context controls, the Claude Code harness adapter with stats and advice, the setup checker and wizard, and the board on a tailnet using the tailnet login. The live checks so far are E7 (three runs on the board for $0.48) and the dvs-enh trial; fw-uart16550 is the next long-running candidate. Everything about moving work between people, and the social layer, is designed in docs/product.md and docs/social.md but not built. Much of the recent work is not yet committed.");

  // ===================================================== 12. Roadmap
  s = content("Roadmap: one engineer, then a team, then the organization", "Where we are");
  const lanes = [
    ["Now", "One engineer, every day", HEX.accent2, [
      "R1 trustworthy ownership: steps atomic in work/ repos; take",
      "R2 sessions that last; IDE from the board",
      "K0 weekly notes and posts drafted from the journal",
      "Pilot: 2–3 engineers on real DV projects",
    ], "Exit: a step fails midway and the worktree is clean"],
    ["Next", "Step into the bug", HEX.accent1, [
      "R3 jobs and the API: regressions wake packets; phone alerts",
      "R4 export profiles; CI failure → packet; reports",
      "K1 findings, wpk search, the MCP tool",
    ], "Exit: a real CI failure reproduces from the board"],
    ["Later", "A team, then the org", HEX.accent4, [
      "R5 links: assign and consult, no server",
      "K2 questions and snapshots over links; triage inbox",
      "R6 hub: OIDC, policy, audit, team boards, CI intake",
      "K3–K4 channels; \"who has solved this\"",
    ], "Exit: a CI failure lands on the right person's board"],
    ["Horizon", "Beyond the plan", HEX.accent3, [
      "R7 vendor and customer reports, reproduction gate",
      "R8 browser IDE, SLURM, licence pools",
      "Triage farm, verify farm, spend governance",
    ], "Decide after the pilot"],
  ];
  lanes.forEach((l, i) => {
    const x = MX + i * 3.07, w = 2.92, y = 1.45;
    card(s, x, y, w, 0.95, l[2]);
    txt(s, l[0], { x: x + 0.2, y: y + 0.08, w: w - 0.4, h: 0.45, fontSize: 20, bold: true, color: C.background1, fontFace: THEME.headFontFace });
    txt(s, l[1], { x: x + 0.2, y: y + 0.52, w: w - 0.4, h: 0.35, fontSize: 12, color: C.background1 });
    card(s, x, y + 1.05, w, 3.45, C.background2);
    txt(s, bullets(l[3], { paraSpaceAfter: 6 }), { x: x + 0.15, y: y + 1.2, w: w - 0.3, h: 2.6, fontSize: 12 });
    txt(s, l[4], { x: x + 0.2, y: y + 3.8, w: w - 0.4, h: 0.6, fontSize: 11, italic: true, color: C.text2 });
  });
  banner(s, 6.05, "The ask: ", "two pilot teams, a host for a team hub, and a default for what others may see (D5).", 0.7);
  s.addNotes("The order follows the scales: each release is usable alone and ends with a live check on real work. Now: make one engineer's daily use trustworthy (R1, R2) and start the weekly post from the journal, which needs nothing from anyone else and doubles as status reporting inside a team. Next: jobs and the API, so regressions and builds wake packets, and R4, the flagship: a CI failure becomes a packet that reproduces at the right revision; findings and search arrive alongside, because they also need nobody else. Later: links make a team possible without a server, then the hub adds organization sign-in, policy and audit, and the knowledge layer merges across the team. Horizon: across organizations (vendor and customer reports with a reproduction gate), the browser IDE and SLURM, and the opportunities on slide 10. The ask is pilots, a hub host, and a decision on default visibility. No dates are given: each stage's exit check decides when the next starts.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
}
build().catch(e => { console.error(e); process.exit(1); });
