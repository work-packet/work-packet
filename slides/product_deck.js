// Builds slides/work-packet-product.pptx: the product in docs/product.md, told as what your
// work looks like, as an individual developer and as a member of a team.
// Run: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> \
//      PPTX_SKILL=<pptx skill dir> node slides/product_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = path.join(__dirname, "work-packet-product.pptx");

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
pres.title = "work-packet: what your work looks like";
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
      fontSize: 22, color: C.accent1, valign: "top", margin: 0 }, text: "" } },
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
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.45, w: CW, h: 0.9,
      fontSize: 38, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3 },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.85,
      fontSize: 34, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "work-packet · product design (docs/product.md)", options: { x: MX, y: 6.95, w: 6, h: 0.3,
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
function downArrow(slide, x, y, w, h, color) {
  slide.addShape(pres.shapes.DOWN_ARROW, { x, y, w, h, fill: { color: color || C.accent3 },
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
function code(slide, x, y, w, h, lines, fs, gap) {
  card(slide, x, y, w, h, C.text1);
  txt(slide, lines.map((l, i) => ({ text: l[0], options: { color: l[1] || HEX.lt1, paraSpaceAfter: gap || 0,
    breakLine: i < lines.length - 1 } })), { x: x + 0.3, y: y + 0.2, w: w - 0.5, h: h - 0.35,
    fontFace: MONO, fontSize: fs || 13 });
}
// A straight line between two points.
function seg(slide, x1, y1, x2, y2, color, width) {
  slide.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1),
    h: Math.abs(y2 - y1), flipV: (x2 - x1) * (y2 - y1) < 0, line: { color: color || C.accent3, width: width || 1.5 },
    objectName: "seg" + (++n) });
}
// A small pill label.
function pill(slide, text, x, y, w, fill, color) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.32, fill: { color: fill },
    line: { color: fill }, rectRadius: 0.16, objectName: "pill" + (++n) });
  txt(slide, text, { x, y, w, h: 0.32, fontSize: 11, bold: true, color: color || C.background1,
    align: "center", valign: "middle" });
}

async function build() {
  const I = {};
  const ic = { folder: fa.FaFolderOpen, code: fa.FaCode, list: fa.FaClipboardList, box: fa.FaBoxOpen,
    clock: fa.FaHourglassHalf, git: fa.FaCodeBranch, comments: fa.FaComments, sync: fa.FaSyncAlt,
    user: fa.FaUserCheck, users: fa.FaUsers, bell: fa.FaBell, terminal: fa.FaTerminal, eye: fa.FaEye,
    bug: fa.FaBug, link: fa.FaLink, robot: fa.FaRobot, tasks: fa.FaTasks, server: fa.FaServer,
    cloud: fa.FaCloud, key: fa.FaKey, mobile: fa.FaMobileAlt, laptop: fa.FaLaptopCode,
    journal: fa.FaBook, recipe: fa.FaScroll, hand: fa.FaHandsHelping, chart: fa.FaChartBar,
    shield: fa.FaShieldAlt, play: fa.FaPlay, search: fa.FaSearch, check: fa.FaCheck, flag: fa.FaFlagCheckered };
  for (const k of Object.keys(ic)) I[k] = await icon(ic[k], HEX.lt1);

  let s;
  // ===================================================== Intro
  pres.addSection({ title: "Introduction" });
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Working in packets", { placeholder: "title" });
  s.addText("What your work looks like with work-packet: on your own, on a team, and across organizations",
    { placeholder: "body" });
  txt(s, "work-packet · wpkd · the board", { x: MX, y: 1.4, w: 8, h: 0.4, fontFace: MONO,
    fontSize: 16, color: C.accent2 });
  txt(s, "October 2026 · product design for review", { x: MX, y: 6.6, w: 6, h: 0.35, fontSize: 12, color: C.accent3 });
  s.addNotes("This deck walks through the product in docs/product.md from the user's side: a day as an individual developer, a week on a team, then how it grows from one user to many organizations. Nothing past today's board, runner, Compose and web shell is built yet; the release plan is at the end.");

  // --- the one idea
  s = content("Work you can leave, resume, hand over and watch", "Introduction");
  // centre packet
  card(s, 4.65, 2.35, 4.0, 2.6, C.text1);
  circleIcon(s, I.box, 6.25, 2.6, 0.8, C.accent1);
  txt(s, "packet", { x: 4.65, y: 3.5, w: 4.0, h: 0.5, fontSize: 24, bold: true, color: C.background1,
    align: "center", fontFace: THEME.headFontFace });
  txt(s, "wpk:7f3c…  ·  one owner at a time", { x: 4.65, y: 4.05, w: 4.0, h: 0.4, fontSize: 13,
    color: C.accent1, align: "center", fontFace: MONO });
  const parts = [
    [I.list, "Instruction", "the next thing to do (memento.md)", 0.6, 1.45],
    [I.folder, "Plan and notes", "state/: the outline, questions, decisions", 0.6, 3.25],
    [I.git, "Code", "worktrees of your repos, one commit per step", 0.6, 5.05],
    [I.tasks, "Jobs", "sims, regressions, builds, with progress", 9.05, 1.45],
    [I.journal, "Journal", "every step, hand-off, answer and cost", 9.05, 3.25],
    [I.recipe, "Recipe and address", "rebuilds its workspace anywhere; one URL", 9.05, 5.05],
  ];
  parts.forEach(p => {
    card(s, p[3], p[4], 3.7, 1.25, C.background2);
    circleIcon(s, p[0], p[3] + 0.2, p[4] + 0.25, 0.75, C.accent2);
    txt(s, p[1], { x: p[3] + 1.1, y: p[4] + 0.18, w: 2.45, h: 0.4, fontSize: 16, bold: true,
      fontFace: THEME.headFontFace });
    txt(s, p[2], { x: p[3] + 1.1, y: p[4] + 0.58, w: 2.45, h: 0.6, fontSize: 12, color: C.text2 });
  });
  s.addNotes("The packet replaces the repo, branch, chat and terminal as the unit of work. Everything about a piece of work is in it or reachable from it: the next instruction, the plan, the code as git worktrees, the jobs it started, a journal of everything, and the recipe to rebuild it elsewhere. It has one owner at a time, you or the runner, and an address.");

  // --- before / after
  s = content("Today the work is scattered; packets give it a home", "Introduction");
  const cols = [
    ["Today", C.accent4, [
      "Four terminals, three tmux sessions, two machines",
      "Agent sessions die while the sim runs",
      "The plan lives in a chat that is gone tomorrow",
      "Checking on background work means attaching to each one",
      "Handing over a bug is a wall of text and a revision number",
    ]],
    ["With packets", C.accent2, [
      "One board: what runs, what sleeps, what needs you",
      "Long jobs run in the packet and wake the agent when done",
      "Plan, notes and history survive a week away",
      "Notifications on the phone and in VS Code",
      "Assign the packet: they open it at the right revision, with its history",
    ]],
  ];
  cols.forEach((c, i) => {
    const x = MX + i * 6.2, w = 5.93;
    card(s, x, 1.45, w, 4.0, i ? C.accent6 : C.background2);
    pill(s, c[0], x + 0.35, 1.7, 1.9, c[1]);
    txt(s, bullets(c[2], { paraSpaceAfter: 10 }), { x: x + 0.35, y: 2.25, w: w - 0.7, h: 3.1, fontSize: 16 });
  });
  card(s, MX, 5.75, CW, 0.9, C.text1);
  txt(s, [
    { text: "The difference: ", options: { bold: true, color: HEX.accent1 } },
    { text: "the work has an address, one owner at a time, and a history, wherever you look at it from.",
      options: { color: HEX.lt1 } },
  ], { x: MX + 0.35, y: 5.75, w: CW - 0.7, h: 0.9, fontSize: 17, valign: "middle" });
  s.addNotes("The pain is not the agent itself, it is everything around it: where the work is, whether it is still running, and how to pass it on. The right column is what the rest of the deck shows.");

  // ===================================================== Individual
  divider("Your day, as an individual developer", "The board is where you look. The terminal and VS Code are where you work.", "Individual");

  // --- a day timeline
  s = content("A day with packets", "Individual");
  const day = [
    ["08:30", I.mobile, "Phone buzzes overnight: one packet needs you. Answer its question on the board over coffee"],
    ["09:00", I.list, "New from template: \"from issue\". Compose shows the checks; clone in the browser shell; hand off"],
    ["10:00", I.laptop, "Open your own packet in VS Code. The runner works three others meanwhile"],
    ["13:00", I.tasks, "A regression job runs in a packet; the board shows its graph filling in"],
    ["16:00", I.eye, "Review in VS Code: the runner's commits since your hand-off. Give it the next batch"],
    ["18:00", I.clock, "Go home. Packets run, sleep and wait; nothing is lost"],
  ];
  const lx = MX + 0.95;
  s.addShape(pres.shapes.LINE, { x: lx + 0.35, y: 1.6, w: 0, h: 5.0, line: { color: C.accent3, width: 1.5 },
    objectName: "tl" });
  day.forEach((d, i) => {
    const y = 1.45 + i * 0.86;
    txt(s, d[0], { x: MX, y: y + 0.15, w: 0.85, h: 0.4, fontSize: 15, bold: true, color: C.accent1,
      fontFace: MONO });
    circleIcon(s, d[1], lx, y + 0.02, 0.7, i % 2 ? C.accent2 : C.text2);
    card(s, lx + 0.95, y + 0.02, 9.6, 0.7, C.background2);
    txt(s, d[2], { x: lx + 1.2, y: y + 0.02, w: 9.2, h: 0.7, fontSize: 15, valign: "middle" });
  });
  s.addNotes("One illustrative day. The point: you spend the day in VS Code and a terminal as you do now. The board is the one place you look to see everything else, and notifications mean you do not have to keep looking.");

  // --- the board mock
  s = content("The board: every packet, and what is waiting for you", "Individual");
  const colsB = [
    ["Needs you", C.accent4, [["dvs-enh", "Allow Bash for builds?"], ["uart-rx", "failed 3×: timeout"]]],
    ["Setup", C.accent3, [["i2c-plan", "2 checks missing"]]],
    ["Held", C.accent3, [["fw-dma", "taken: reviewing"]]],
    ["Done", C.accent3, [["proto-chi", "batch 2 done · Next batch"]]],
    ["Running", C.accent2, [["fw-uart16550", "step 14 · pytest -q · 4 min"], ["dv-solve", "regress 61% · 1 job"]]],
    ["Ready", C.accent2, [["pyhdl-if", "next in 1 slot"]]],
    ["Sleeping", C.accent2, [["nightly", "wakes 02:00"], ["chi-sim", "wait job: formal"]]],
  ];
  const bw = 1.62, bg = 0.13;
  txt(s, "Yours", { x: MX, y: 1.35, w: 4 * bw + 3 * bg, h: 0.35, fontSize: 14, bold: true, color: C.text2 });
  txt(s, "The runner's", { x: MX + 4 * (bw + bg), y: 1.35, w: 3 * bw + 2 * bg, h: 0.35, fontSize: 14,
    bold: true, color: C.text2 });
  colsB.forEach((c, i) => {
    const x = MX + i * (bw + bg);
    card(s, x, 1.75, bw, 4.05, C.background2);
    txt(s, c[0], { x: x + 0.12, y: 1.85, w: bw - 0.24, h: 0.35, fontSize: 13, bold: true, color: c[1] });
    c[2].forEach((k, j) => {
      const y = 2.3 + j * 1.15;
      card(s, x + 0.1, y, bw - 0.2, 1.0, C.background1, i === 0 ? HEX.accent4 : "D5DBE1");
      txt(s, k[0], { x: x + 0.2, y: y + 0.08, w: bw - 0.4, h: 0.3, fontSize: 12, bold: true, fontFace: MONO });
      txt(s, k[1], { x: x + 0.2, y: y + 0.4, w: bw - 0.4, h: 0.55, fontSize: 11, color: C.text2 });
    });
  });
  card(s, MX, 6.0, CW, 0.75, C.text1);
  txt(s, [
    { text: "On every card: ", options: { bold: true, color: HEX.accent1 } },
    { text: "state, owner, how long it has waited, current activity, jobs and open shells. Across all your hosts, on one board.",
      options: { color: HEX.lt1 } },
  ], { x: MX + 0.3, y: 6.0, w: CW - 0.6, h: 0.75, fontSize: 15, valign: "middle" });
  s.addNotes("The board is today's board plus jobs, sessions and IDE buttons. Two lanes: on the left what is yours, with Needs you first; on the right what the runner owns. With several hosts, the hub or a peer list joins them into one board. Card contents here are illustrative.");

  // --- turns with the runner
  s = content("Clear turns: you or the runner, never both", "Individual");
  const lp = [
    [MX, 2.1, "You", "set up, write the instruction", C.text2, I.user],
    [MX + 4.4, 2.1, "Hand off", "checks pass; work repos committed", C.accent1, I.hand],
    [MX + 8.8, 2.1, "The runner", "one atomic step at a time", C.accent2, I.robot],
  ];
  lp.forEach(p => {
    card(s, p[0], p[1], 3.33, 1.5, C.background2);
    circleIcon(s, p[5], p[0] + 0.25, p[1] + 0.35, 0.8, p[4]);
    txt(s, p[2], { x: p[0] + 1.25, y: p[1] + 0.25, w: 1.95, h: 0.45, fontSize: 18, bold: true,
      fontFace: THEME.headFontFace });
    txt(s, p[3], { x: p[0] + 1.25, y: p[1] + 0.72, w: 1.95, h: 0.7, fontSize: 13, color: C.text2 });
  });
  arrow(s, MX + 3.5, 2.65, 0.75, 0.4);
  arrow(s, MX + 7.9, 2.65, 0.75, 0.4);
  downArrow(s, MX + 10.25, 3.75, 0.4, 0.55);
  const back = [
    ["Question", "answer on the board; grants in one click"],
    ["Failed or limit", "see why; fix; hand off again"],
    ["Done", "review, then give it the next batch"],
    ["You take over", "now, or at the end of the running step"],
  ];
  back.forEach((b, i) => {
    const x = MX + i * 3.08;
    card(s, x, 4.45, 2.9, 1.25, i === 3 ? C.accent5 : C.accent6);
    txt(s, b[0], { x: x + 0.2, y: 4.55, w: 2.5, h: 0.4, fontSize: 15, bold: true });
    txt(s, b[1], { x: x + 0.2, y: 4.95, w: 2.5, h: 0.7, fontSize: 13, color: C.text2 });
  });
  txt(s, "… and the packet comes back to you, with the reason recorded", { x: MX, y: 5.95, w: CW, h: 0.4,
    fontSize: 15, italic: true, color: C.accent3 });
  txt(s, "Notes reach the agent at any time, without taking the packet back", { x: MX, y: 6.35, w: CW, h: 0.4,
    fontSize: 15, italic: true, color: C.accent3 });
  s.addNotes("Ownership follows from the state: HELD and COMPLETED are yours, RUNNABLE and SLEEPING are the runner's. A step is never cut short; take during a step lands at its end. A failed step resets every work repo, so you never inherit half a change. Notes are the exception: they reach a running packet at its next tool call.");

  // --- one session every surface
  s = content("One shell per packet, reachable from every surface", "Individual");
  card(s, 4.9, 2.6, 3.55, 1.9, C.text1);
  circleIcon(s, I.terminal, 5.15, 2.85, 0.75, C.accent1);
  txt(s, "packet session", { x: 6.05, y: 2.85, w: 2.3, h: 0.4, fontSize: 17, bold: true, color: C.background1,
    fontFace: THEME.headFontFace });
  txt(s, "held by wpk (or tmux); survives a server restart", { x: 6.05, y: 3.3, w: 2.3, h: 1.0, fontSize: 12,
    color: MUTED });
  const surf = [
    [MX, 1.5, I.eye, "Board", "xterm.js in the browser, on the phone too"],
    [MX, 4.35, I.laptop, "VS Code", "terminal profile \"packet shell\""],
    [9.15, 1.5, I.terminal, "SSH", "wpk attach dvs-enh"],
    [9.15, 4.35, I.robot, "Idle or active?", "idle shells dim, then are reaped; running ones never"],
  ];
  surf.forEach(p => {
    card(s, p[0], p[1], 3.6, 1.6, C.background2);
    circleIcon(s, p[2], p[0] + 0.25, p[1] + 0.4, 0.75, C.accent2);
    txt(s, p[3], { x: p[0] + 1.15, y: p[1] + 0.3, w: 2.3, h: 0.4, fontSize: 16, bold: true });
    txt(s, p[4], { x: p[0] + 1.15, y: p[1] + 0.72, w: 2.3, h: 0.8, fontSize: 13, color: C.text2 });
  });
  arrow(s, 4.3, 2.75, 0.5, 0.35);
  arrow(s, 4.3, 4.0, 0.5, 0.35);
  s.addShape(pres.shapes.LEFT_ARROW, { x: 8.55, y: 2.75, w: 0.5, h: 0.35, fill: { color: C.accent3 },
    line: { color: C.accent3 }, objectName: "la1" });
  s.addShape(pres.shapes.LEFT_ARROW, { x: 8.55, y: 4.0, w: 0.5, h: 0.35, fill: { color: C.accent3 },
    line: { color: C.accent3 }, objectName: "la2" });
  txt(s, "Start a clone in the browser, finish it in VS Code, check it from SSH. Same shell, same history.",
    { x: MX, y: 6.2, w: CW, h: 0.45, fontSize: 16, italic: true, color: C.text2 });
  s.addNotes("This is the 'no terminal hopping' part. The session belongs to the packet, not to a window. The default holder is a small dtach-style process per session with a socket; tmux is an optional backend for people who live in it. Idle detection: the foreground process is the shell and nothing has been written for a while.");

  // --- long jobs
  s = content("Long jobs run in the packet, and you can see them", "Individual");
  // graph mock
  card(s, MX, 1.45, 6.9, 4.6, C.background2);
  txt(s, "dfm run regress  ·  job 3", { x: MX + 0.3, y: 1.6, w: 6.3, h: 0.35, fontSize: 14, bold: true,
    fontFace: MONO });
  const nodes = [
    ["fetch", 0.3, 2.3, "done"], ["build.rtl", 2.45, 2.3, "done"], ["build.tb", 2.45, 3.3, "skip"],
    ["sim.rx", 4.6, 2.05, "done"], ["sim.tx", 4.6, 2.9, "run"], ["sim.fifo", 4.6, 3.75, "fail"],
    ["cov.merge", 4.6, 4.6, "pend"],
  ];
  const col = { done: HEX.accent2, run: HEX.accent1, fail: HEX.accent4, skip: HEX.accent3, pend: "C9D1D9" };
  nodes.forEach(nd => {
    const x = MX + nd[1], y = nd[2];
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 1.85, h: 0.55, fill: { color: col[nd[3]] },
      line: { color: col[nd[3]] }, rectRadius: 0.1, objectName: "nd" + (++n) });
    txt(s, nd[0], { x, y, w: 1.85, h: 0.55, fontSize: 12, bold: true, fontFace: MONO, align: "center",
      valign: "middle", color: nd[3] === "pend" ? C.text1 : C.background1 });
  });
  [[2.15, 2.57, 2.45, 2.57], [2.15, 2.57, 2.45, 3.57], [4.3, 2.57, 4.6, 2.32], [4.3, 2.57, 4.6, 3.17],
   [4.3, 3.57, 4.6, 4.02], [4.3, 3.57, 4.6, 4.87]].forEach(e => {
    s.addShape(pres.shapes.LINE, { x: MX + e[0], y: Math.min(e[1], e[3]), w: e[2] - e[0],
      h: Math.abs(e[3] - e[1]), flipV: e[3] < e[1], line: { color: C.accent3, width: 1 }, objectName: "e" + (++n) });
  });
  // progress bar
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 0.3, y: 5.4, w: 6.3, h: 0.3, fill: { color: "D5DBE1" },
    line: { color: "D5DBE1" }, rectRadius: 0.15, objectName: "pb0" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 0.3, y: 5.4, w: 3.85, h: 0.3, fill: { color: C.accent2 },
    line: { color: C.accent2 }, rectRadius: 0.15, objectName: "pb1" });
  txt(s, "~61%  ·  sim.tx seed 42", { x: MX + 0.3, y: 5.72, w: 6.3, h: 0.3, fontSize: 12, color: C.text2 });
  // right column
  const jr = [
    ["Started by you or the agent", "wpk job start -- dfm run regress. It outlives the shell and the step"],
    ["Progress from any tool", "append JSON lines to $WPK_PROGRESS, or let a wpk adapter read the tool"],
    ["dv-flow-mgr as it is", "graph from dfm graph; state from its log and exec_data.json; no change upstream"],
    ["The agent waits, not burns", "resume: wait job:3. The packet sleeps and wakes with the exit code and log tail"],
  ];
  jr.forEach((j, i) => {
    const y = 1.45 + i * 1.17;
    txt(s, j[0], { x: 7.85, y, w: 4.9, h: 0.4, fontSize: 16, bold: true, fontFace: THEME.headFontFace });
    txt(s, j[1], { x: 7.85, y: y + 0.4, w: 4.9, h: 0.7, fontSize: 13, color: C.text2 });
  });
  pill(s, "Heavy jobs: SLURM backend, licence pools", 7.85, 6.2, 4.9, C.text2);
  s.addNotes("Jobs close the biggest gap: sims and regressions are a DV engineer's longest-running work. A job belongs to the packet, not to its owner, so hand-off does not kill it. The graph and states come from dv-flow-mgr's existing outputs; the percentage is approximate because runtime expansion adds tasks.");

  // --- review and steer
  s = content("Review and steer from VS Code", "Individual");
  const rv = [
    [I.laptop, "Open in VS Code", "Remote-SSH to the host that holds the packet, with its worktrees, plan and tasks. Read-only while the runner owns it"],
    [I.eye, "Review", "the runner's commits since your hand-off, as one diff; or open the code as it was at step N"],
    [I.comments, "Continue the conversation", "resume the step's session in a fork and ask why it did that; send what you learn as a note"],
    [I.bell, "Status bar", "this packet's owner and state, and the Needs-you count across every packet"],
  ];
  rv.forEach((r, i) => {
    const x = MX + (i % 2) * 6.2, y = 1.5 + Math.floor(i / 2) * 2.15;
    card(s, x, y, 5.93, 1.9, C.background2);
    circleIcon(s, r[0], x + 0.3, y + 0.35, 0.85, i < 2 ? C.accent2 : C.accent1);
    txt(s, r[1], { x: x + 1.4, y: y + 0.25, w: 4.3, h: 0.45, fontSize: 18, bold: true, fontFace: THEME.headFontFace });
    txt(s, r[2], { x: x + 1.4, y: y + 0.72, w: 4.3, h: 1.1, fontSize: 14, color: C.text2 });
  });
  code(s, MX, 5.95, CW, 0.75, [["vscode://vscode-remote/ssh-remote+a9550/…/dvs-enh/packets/7f3c…/.wpk/packet.code-workspace", HEX.accent1]], 13);
  s.addNotes("VS Code is the IDE; we do not build one. The workspace file is generated: the packet's worktrees labelled as the packet's, never your own clone. While the runner owns the packet the workspace turns off save, autofetch and format-on-save, as a guard against mistakes. A browser IDE under the board comes later, for the iPad.");

  // ===================================================== Team
  divider("Your week, as a member of a team", "Packets are how work moves between people, and between CI and people.", "Team");

  // --- step into the bug
  s = content("Step into the bug: from CI failure to open packet", "Team");
  const flow = [
    [I.bug, "CI fails", "ci/run.sh calls wpk export --from-ci: repo, commit, test, seed, command, log"],
    [I.box, "A bundle", "uploaded with the run's artifacts, on Forgejo and GitHub alike"],
    [I.flag, "A card", "\"uart_rx_overrun seed 42 failed at abc123\" on the owner's board"],
    [I.play, "Open", "worktree at abc123, recipe run; the smoke check is the reproduction"],
    [I.search, "Work it", "agent: find the root cause. Or VS Code at the failing line. Or assign it"],
  ];
  const fw = 2.2, fg = 0.28;
  flow.forEach((f, i) => {
    const x = MX + i * (fw + fg);
    card(s, x, 1.6, fw, 3.6, i === 3 ? C.accent6 : C.background2);
    circleIcon(s, f[0], x + (fw - 0.85) / 2, 1.85, 0.85, i === 0 ? C.accent4 : C.accent2);
    txt(s, f[1], { x: x + 0.15, y: 2.85, w: fw - 0.3, h: 0.45, fontSize: 17, bold: true, align: "center",
      fontFace: THEME.headFontFace });
    txt(s, f[2], { x: x + 0.2, y: 3.35, w: fw - 0.4, h: 1.8, fontSize: 13, color: C.text2 });
    if (i < flow.length - 1) arrow(s, x + fw + 0.02, 3.2, 0.24, 0.3);
  });
  card(s, MX, 5.5, CW, 1.15, C.text1);
  txt(s, [
    { text: "\"Reproduced in 3 minutes\" or \"did not reproduce\" ", options: { bold: true, color: HEX.accent1 } },
    { text: "is the first thing you learn, before anyone reads a log. First on featherweight-ip, then dv-solve, pyvsc and pyhdl-if.",
      options: { color: HEX.lt1 } },
  ], { x: MX + 0.35, y: 5.5, w: CW - 0.7, h: 1.15, fontSize: 16, valign: "middle" });
  s.addNotes("The flagship flow for a DV team. The bundle is written by the repo's own CI script, so the Forgejo and GitHub workflows of each pair both get it with no forge-specific action. Import uses the from-ci-failure template: the recipe rebuilds the workspace at the failing commit and runs the failing command as its smoke check.");

  // --- assign
  s = content("Assign, don't brief: the work arrives with its context", "Team");
  card(s, MX, 1.5, 5.6, 5.15, C.accent6);
  pill(s, "Travels with the packet", MX + 0.35, 1.75, 2.6, C.accent2);
  txt(s, bullets([
    "The instruction, plan, outline and notes",
    "Every step's summary, diff and cost",
    "Questions and the answers given",
    "The recipe: repos at their commits, unpushed work as a git bundle",
    "Your note: \"RX path looks wrong after step 9\"",
  ], { paraSpaceAfter: 10 }), { x: MX + 0.35, y: 2.3, w: 4.9, h: 4.2, fontSize: 15 });
  card(s, MX + 5.9, 1.5, 6.23, 5.15, C.background2);
  pill(s, "Stays with you, unless you choose", MX + 6.25, 1.75, 3.3, C.accent3);
  txt(s, bullets([
    "Step transcripts: the full conversations, where IP and secrets end up. Listed by hash; requested, and you approve",
    "Builds, sim output and waves: rebuilt by the recipe, or named files you add on purpose",
    "Export shows every outside path it refers to before anything leaves",
  ], { paraSpaceAfter: 10 }), { x: MX + 6.25, y: 2.3, w: 5.5, h: 3.0, fontSize: 15 });
  code(s, MX + 6.25, 5.35, 5.5, 1.0, [["$ wpk assign uart-rx rtl-owner \\", HEX.accent1],
    ["    -m \"RX path looks wrong after step 9\""]], 13);
  s.addNotes("Assign is the person-to-person transfer. The core tier always travels; transcripts and derived data stay unless you choose. The colleague's board shows it under Assigned to you; Open imports it on their own server and materializes it from the recipe. The transcript default (out, request and approve) is open decision D1.");

  // --- links, then a hub
  s = content("Link up as a team; add a hub when it pays", "Team");
  [[MX, "Small team: links", C.accent2], [MX + 6.23, "Organization: a hub", C.accent1]].forEach(h => {
    card(s, h[0], 1.45, 5.9, 4.35, C.background2);
    pill(s, h[1], h[0] + 0.3, 1.65, 2.6, h[2]);
  });
  // mesh of three
  const mesh = [[MX + 1.55, 2.75], [MX + 4.35, 2.75], [MX + 2.95, 4.15]];
  [[0, 1], [1, 2], [0, 2]].forEach(e => seg(s, mesh[e[0]][0], mesh[e[0]][1], mesh[e[1]][0], mesh[e[1]][1], C.accent2, 2));
  mesh.forEach(m => circleIcon(s, I.user, m[0] - 0.4, m[1] - 0.4, 0.8, C.text2));
  txt(s, [
    { text: "wpk link add <teammate>", options: { fontFace: MONO, bold: true, breakLine: true } },
    { text: "both sides agree; each shares what it chooses. No server" },
  ], { x: MX + 0.3, y: 4.85, w: 5.3, h: 0.85, fontSize: 13, color: C.text2 });
  // star around a hub
  const hc = [MX + 6.23 + 2.95, 3.45];
  const rim = [];
  for (let k = 0; k < 6; k++) {
    const a2 = -Math.PI / 2 + k * Math.PI / 3;
    rim.push([hc[0] + 2.0 * Math.cos(a2), hc[1] + 0.95 * Math.sin(a2)]);
  }
  rim.forEach(r => seg(s, hc[0], hc[1], r[0], r[1], C.accent1, 2));
  circleIcon(s, I.cloud, hc[0] - 0.5, hc[1] - 0.5, 1.0, C.accent1);
  rim.forEach(r => circleIcon(s, I.user, r[0] - 0.3, r[1] - 0.3, 0.6, C.text2));
  txt(s, [
    { text: "wpk link add https://hub.example.com", options: { fontFace: MONO, bold: true, breakLine: true } },
    { text: "the same command; nothing in a packet changes. The hub runs nothing" },
  ], { x: MX + 6.53, y: 4.85, w: 5.3, h: 0.85, fontSize: 13, color: C.text2 });
  card(s, MX, 6.0, CW, 0.75, C.text1);
  txt(s, [
    { text: "Links are not logins: ", options: { bold: true, color: HEX.accent1 } },
    { text: "a teammate or a hub reads what you share and drops bundles in your inbox. It never runs anything of yours.",
      options: { color: HEX.lt1 } },
  ], { x: MX + 0.3, y: 6.0, w: CW - 0.6, h: 0.75, fontSize: 15, valign: "middle" });
  s.addNotes("A small team needs no server: daemons link by mutual agreement, a full mesh that works up to about ten people. Past that, a hub pays for itself: one connection per daemon, a directory, a bundle store so the recipient need not be online, CI intake, sign-in, policy and audit. Joining the hub is the same command as linking a teammate. Either way, a link holds the peer scope: read what you share, deliver to your inbox, request a file. Never a step, a shell or an edit.");

  // --- shared resources
  s = content("Shared, scarce resources are scheduled, not fought over", "Team");
  const res = [["agent", 3, 2], ["xcelium", 4, 4], ["jasper", 2, 1], ["cpu", 32, 20]];
  res.forEach((r, i) => {
    const y = 1.6 + i * 1.0;
    txt(s, r[0], { x: MX, y, w: 1.5, h: 0.5, fontSize: 16, bold: true, fontFace: MONO, valign: "middle" });
    const bwid = 4.6, used = bwid * r[2] / r[1];
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 1.6, y: y + 0.1, w: bwid, h: 0.32, fill: { color: "D5DBE1" },
      line: { color: "D5DBE1" }, rectRadius: 0.16, objectName: "rb" + (++n) });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 1.6, y: y + 0.1, w: used, h: 0.32,
      fill: { color: r[2] === r[1] ? C.accent4 : C.accent2 }, line: { color: r[2] === r[1] ? C.accent4 : C.accent2 },
      rectRadius: 0.16, objectName: "rb" + (++n) });
    txt(s, r[2] + " / " + r[1], { x: MX + 6.35, y, w: 1.0, h: 0.5, fontSize: 14, color: C.text2, valign: "middle" });
  });
  card(s, MX, 5.75, 6.75, 0.85, C.accent5);
  txt(s, [
    { text: "chi-sim  ", options: { bold: true, fontFace: MONO } },
    { text: "waiting for xcelium (4 of 4 in use)", options: {} },
  ], { x: MX + 0.3, y: 5.75, w: 6.2, h: 0.85, fontSize: 15, valign: "middle" });
  card(s, 7.85, 1.5, 4.88, 5.1, C.background2);
  txt(s, "How it works", { x: 8.15, y: 1.7, w: 4.3, h: 0.45, fontSize: 18, bold: true, fontFace: THEME.headFontFace });
  txt(s, bullets([
    "Name pools in config: agent = 3, xcelium = 4",
    "A step uses an agent slot; a job declares what it needs",
    "Work starts only when its needs are free; the card says what it waits for",
    "Heavy jobs go to SLURM, with pools mapped to its licences",
  ], { paraSpaceAfter: 10 }), { x: 8.15, y: 2.25, w: 4.3, h: 4.2, fontSize: 15 });
  s.addNotes("On a DV host the scarce resources are simulator and formal licences, CPU and memory, not agent sessions. Named pools are a simple model that SLURM licences and GRES can back later. Pool sizes here are an example.");

  // --- a team's week
  s = content("A team's week in packets", "Team");
  const wk = [
    ["Mon", "Nightly CI fails 3 tests. Three packets appear on the owners' boards, each reproducing itself"],
    ["Tue", "Your runner finds the cause of two overnight. You review in VS Code and push the fix"],
    ["Wed", "The third is RTL. You assign it to the RTL owner with a note; they open it at the failing commit"],
    ["Thu", "The lead's hub board shows who holds what, and what has waited longest"],
    ["Fri", "A plan packet finishes batch 3; you give it batch 4 and go home. It runs over the weekend"],
  ];
  wk.forEach((d, i) => {
    const y = 1.45 + i * 0.97;
    card(s, MX, y, 1.1, 0.8, i % 2 ? C.accent2 : C.text2);
    txt(s, d[0], { x: MX, y, w: 1.1, h: 0.8, fontSize: 18, bold: true, color: C.background1, align: "center",
      valign: "middle", fontFace: THEME.headFontFace });
    card(s, MX + 1.3, y, 7.3, 0.8, C.background2);
    txt(s, d[1], { x: MX + 1.55, y, w: 6.9, h: 0.8, fontSize: 14, valign: "middle" });
  });
  card(s, 9.4, 1.45, 3.33, 4.68, C.text1);
  txt(s, "What the team can measure", { x: 9.65, y: 1.65, w: 2.85, h: 0.75, fontSize: 17, bold: true,
    color: C.background1, fontFace: THEME.headFontFace });
  txt(s, bullets(["cost of a triage", "time from failure to root cause", "how often the agent reproduced the bug",
    "what waits on people, and for how long"], { color: HEX.lt1, paraSpaceAfter: 8 }),
    { x: 9.65, y: 2.5, w: 2.85, h: 3.5, fontSize: 14, color: C.background1 });
  s.addNotes("An illustrative week, not measured results. Every packet carries its cost, duration, step count and outcome, so the measures on the right come from the journal, per template, with no extra tracking.");

  // ===================================================== Growing
  divider("Grow without migrating", "One user, a small team, an organization, the internet. Each step up is configuration, not a migration.", "Growing");

  // --- four scales
  s = content("Four scales, one protocol", "Growing");
  const scales = [
    [I.user, "One user", "wpk dash", "board, runner, sessions, jobs, VS Code. No account, no server", C.accent2],
    [I.users, "Small team", "wpk link add", "teammates' boards, assign directly. No server", C.accent1],
    [I.server, "Organization", "wpk hub", "directory, bundle store, CI intake, policy, audit", C.accent4],
    [I.cloud, "Across organizations", "wpk report", "bug reports that reproduce; questions come back", C.text2],
  ];
  const sw = 2.85, sg = 0.243;
  scales.forEach((c, i) => {
    const x = MX + i * (sw + sg), h = 2.6 + i * 0.7, y = 6.65 - h;
    card(s, x, y, sw, h, i % 2 ? C.background2 : C.accent6);
    circleIcon(s, c[0], x + 0.25, y + 0.25, 0.75, c[4]);
    txt(s, c[1], { x: x + 0.25, y: y + 1.1, w: sw - 0.5, h: 0.4, fontSize: 17, bold: true, fontFace: THEME.headFontFace });
    txt(s, c[2], { x: x + 0.25, y: y + 1.5, w: sw - 0.5, h: 0.35, fontSize: 13, bold: true, fontFace: MONO, color: c[4] });
    txt(s, c[3], { x: x + 0.25, y: y + 1.88, w: sw - 0.5, h: 0.7, fontSize: 13, color: C.text2 });
  });
  txt(s, bullets([
    "Each scale is worth having on its own",
    "Moving up adds configuration; packets never change",
    "Nothing depends on the scale above it",
  ], { paraSpaceAfter: 6 }), { x: MX, y: 1.45, w: 5.6, h: 1.4, fontSize: 15, color: C.text2 });
  s.addNotes("The product has to spread the way developer tools spread. One person installs it and gets value from wpk dash alone. A few colleagues link their daemons. An organization stands up a hub. Work then crosses organizations as reports. The packet format, the project layout and the journal are the same at every scale; with the hub down, links and local work carry on.");

  // --- REST API
  s = content("One REST API; what differs is the caller's scope", "Growing");
  code(s, MX, 1.45, 6.4, 4.3, [
    ["GET  /api/v1/packets?state=HELD", HEX.lt1],
    ["GET  /api/v1/packets/{wpid}", HEX.lt1],
    ["PUT  /api/v1/packets/{wpid}/owner", HEX.accent1],
    ["       {\"to\": \"runner\", \"note\": \"…\"}", MUTED],
    ["POST /api/v1/packets/{wpid}/answers", HEX.lt1],
    ["POST /api/v1/packets/{wpid}/jobs", HEX.lt1],
    ["GET  /api/v1/packets/{wpid}/bundle?profile=team", HEX.lt1],
    ["POST /api/v1/inbox", HEX.lt1],
    ["GET  /api/v1/events            (SSE)", HEX.lt1],
    ["POST /api/v1/reports           (intake)", HEX.lt1],
  ], 13, 9);
  txt(s, "Every action is a function, a CLI command and an endpoint. Retries are safe; stale edits are refused.",
    { x: MX, y: 5.95, w: 6.4, h: 0.7, fontSize: 14, italic: true, color: C.text2 });
  const scopes = [
    ["owner", "you, your other hosts, the local socket", "everything", C.text2],
    ["read", "dashboards and scripts", "every read except transcripts", C.accent3],
    ["ci", "a CI job", "deliver CI bundles", C.accent3],
    ["peer", "a teammate or a hub, over a link", "shared summaries, inbox, requests", C.accent2],
    ["public", "anyone, at an intake", "submit a report", C.accent1],
  ];
  scopes.forEach((c, i) => {
    const y = 1.45 + i * 0.86, x = 7.3;
    card(s, x, y, 5.43, 0.74, C.background2);
    pill(s, c[0], x + 0.15, y + 0.21, 1.0, c[3]);
    txt(s, [
      { text: c[1], options: { bold: true, breakLine: true } },
      { text: c[2], options: { color: C.text2 } },
    ], { x: x + 1.35, y, w: 3.95, h: 0.74, fontSize: 13, valign: "middle" });
  });
  txt(s, "Nothing below owner starts a step, opens a shell or changes a packet.", { x: 7.3, y: 5.85, w: 5.43, h: 0.8,
    fontSize: 14, italic: true, color: C.text2 });
  s.addNotes("The scales are only one protocol if there is one protocol. Everything a daemon or hub does is a resource in one versioned REST API, and every client uses it: the extension, scripts, CI, your other hosts, teammates, hubs, and the CLI with wpk --at. Hand-off and take are a PUT of the packet's owner. POSTs take idempotency keys because links retry from an outbox; packets carry ETags so an edit against a stale view is refused. Scopes are checked before any handler runs.");

  // --- a bug report is a packet
  s = content("A bug report is a stripped packet", "Growing");
  card(s, MX, 1.45, 3.7, 3.95, C.background2);
  circleIcon(s, I.bug, MX + 0.25, 1.7, 0.75, C.accent4);
  txt(s, "Reporter", { x: MX + 1.15, y: 1.82, w: 2.4, h: 0.45, fontSize: 18, bold: true, fontFace: THEME.headFontFace });
  txt(s, "wpk report uart-rx", { x: MX + 0.25, y: 2.65, w: 3.3, h: 0.35, fontSize: 13, bold: true, fontFace: MONO,
    color: C.accent4 });
  txt(s, [
    { text: "Carries: ", options: { bold: true } },
    { text: "what is wrong, the recipe, the failing command, tool versions, the log tail", options: { breakLine: true } },
    { text: "Leaves out: ", options: { bold: true } },
    { text: "history, transcripts, paths" },
  ], { x: MX + 0.25, y: 3.1, w: 3.25, h: 2.2, fontSize: 13, color: C.text2, paraSpaceAfter: 8 });
  const routes = [
    ["A file on an issue", "needs nothing on either side"],
    ["A public intake", "the project's .wpk/intake.toml"],
    ["Hub to hub", "partners, customers and vendors"],
  ];
  routes.forEach((r, i) => {
    const y = 1.45 + i * 1.42;
    card(s, 4.85, y, 3.65, 1.12, i ? C.background2 : C.accent6);
    txt(s, r[0], { x: 5.1, y: y + 0.15, w: 3.2, h: 0.4, fontSize: 16, bold: true });
    txt(s, r[1], { x: 5.1, y: y + 0.57, w: 3.2, h: 0.45, fontSize: 13, color: C.text2 });
  });
  arrow(s, 4.38, 3.25, 0.4, 0.35);
  arrow(s, 8.57, 3.25, 0.4, 0.35);
  card(s, 9.05, 1.45, 3.68, 3.95, C.background2);
  circleIcon(s, I.search, 9.3, 1.7, 0.75, C.accent2);
  txt(s, "Maintainer", { x: 10.2, y: 1.82, w: 2.4, h: 0.45, fontSize: 18, bold: true, fontFace: THEME.headFontFace });
  txt(s, "wpk import bug.wpk", { x: 9.3, y: 2.65, w: 3.3, h: 0.35, fontSize: 13, bold: true, fontFace: MONO,
    color: C.accent2 });
  txt(s, bullets([
    "arrives held, as data",
    "its text is never an instruction to the agent",
    "runs only when you say, in a sandbox",
    "reproduces, or says it did not",
  ], { paraSpaceAfter: 4 }), { x: 9.3, y: 3.1, w: 3.25, h: 2.2, fontSize: 13, color: C.text2 });
  s.addShape(pres.shapes.LEFT_ARROW, { x: MX + 0.4, y: 5.65, w: CW - 0.8, h: 0.4, fill: { color: C.accent1 },
    line: { color: C.accent1 }, objectName: "ret" });
  txt(s, "State and questions come back to the reporter's board: received · reproduced · fixed in <commit>",
    { x: MX, y: 6.15, w: CW, h: 0.45, fontSize: 15, italic: true, color: C.text2, align: "center" });
  s.addNotes("Across organizations the unit is the report: a stripped packet. It is not a description of how to reproduce a bug; it is the reproduction. It can travel as a file on an issue (nothing needed on either side), through a project's public intake, or between linked hubs. On arrival it is untrusted data: nothing runs, its permissions do not apply, and its text reaches an agent only as the reporter's words, which is the defence against prompt injection by bug report. The maintainer's questions come back to the reporter's Needs you. First target: pyvsc or pyhdl-if.");

  // ===================================================== Getting there
  divider("Getting there", "Eight releases, ordered by the scales, each ending with a live check on real work.", "Plan");

  s = content("Eight releases, ordered by the scales", "Plan");
  const SC = { "One user": C.accent2, "Small team": C.accent1, "Organization": C.accent4,
    "Between orgs": C.text2, "Any scale": C.accent3 };
  const rel = [
    ["R1", "One user", "Trustworthy ownership", "wpk dash is the entry point; v0.3 states, take; atomic work repos"],
    ["R2", "One user", "IDE and sessions", "Open in VS Code; one shell on every surface"],
    ["R3", "One user", "Jobs and the REST API", "progress, dv-flow-mgr graph, wait for job; /api/v1; notifications"],
    ["R4", "One user", "Step into the bug", "export and import, CI bundles, templates, reports as files, extension"],
    ["R5", "Small team", "Link up", "links, the peer scope, assign directly, one board across your hosts"],
    ["R6", "Organization", "The hub", "directory, store and relay, CI intake, sign-in, policy, audit"],
    ["R7", "Between orgs", "Across organizations", "public intake, hub to hub, signed reports, sandboxed reproduction"],
    ["R8", "Any scale", "Browser IDE, scale-out", "TLS, web VS Code, SLURM, licence pools"],
  ];
  rel.forEach((r, i) => {
    const y = 1.4 + i * 0.64, h = 0.54;
    card(s, MX, y, 0.8, h, SC[r[1]]);
    txt(s, r[0], { x: MX, y, w: 0.8, h, fontSize: 17, bold: true, color: C.background1, align: "center",
      valign: "middle", fontFace: THEME.headFontFace });
    card(s, MX + 0.95, y, CW - 0.95, h, i % 2 ? C.background1 : C.background2, i % 2 ? "E3E7EB" : null);
    txt(s, r[1], { x: MX + 1.15, y, w: 1.75, h, fontSize: 13, bold: true, color: SC[r[1]], valign: "middle" });
    txt(s, r[2], { x: MX + 2.95, y, w: 2.75, h, fontSize: 14, bold: true, valign: "middle" });
    txt(s, r[3], { x: MX + 5.75, y, w: CW - 5.95, h, fontSize: 13, color: C.text2, valign: "middle" });
  });
  s.addNotes("The order follows the scales. R1 first because everything after it makes a half-finished step visible to more people, and because wpk dash alone has to be worth installing. R4 brings export, which links and the hub build on, and reports as files, which need nothing on either side. R5 makes a team possible without a server; R6 adds only what a mesh of links cannot do well; R7 adds what needs a public endpoint. Built today: the board with actions, the runner in the server, Compose, the web shell, questions and notes (466 tests).");

  // --- close: decisions
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Plan" });
  s.addText("Decisions for review", { placeholder: "title" });
  const dec = [
    ["D1", "Transcripts in a bundle", "out; listed by hash; fetched on approval"],
    ["D2", "Person-to-person verb", "assign (or transfer)"],
    ["D5", "What others see", "state, title, owner, waiting time"],
    ["D8", "Link identity off a tailnet", "one-time code, then exchanged keys"],
    ["D9", "wpk dash runs the runner", "yes; --no-run to only view"],
    ["D10", "Running a received report", "on request, in a sandbox"],
    ["D11", "Signing reports", "a key per daemon or hub"],
    ["D3", "First CI test", "fw-uart16550, a seeded sim test"],
  ];
  dec.forEach((d, i) => {
    const x = MX + (i % 2) * 6.2, y = 1.55 + Math.floor(i / 2) * 1.2;
    card(s, x, y, 5.93, 1.05, C.text2);
    txt(s, d[0], { x: x + 0.25, y, w: 0.9, h: 1.05, fontSize: 22, bold: true, color: C.accent1, valign: "middle",
      fontFace: THEME.headFontFace });
    txt(s, d[1], { x: x + 1.25, y: y + 0.14, w: 4.5, h: 0.4, fontSize: 16, bold: true, color: C.background1 });
    txt(s, "default: " + d[2], { x: x + 1.25, y: y + 0.55, w: 4.5, h: 0.4, fontSize: 13, color: MUTED });
  });
  txt(s, "Details: docs/product.md §13 · D4, D6, D7 are in the document", { x: MX, y: 6.5, w: 8, h: 0.35,
    fontSize: 12, color: C.accent3 });
  s.addNotes("Each decision has the default the design assumes. D4 (matching dv-flow-mgr's log), D6 (session holder) and D7 (notification push channel) are in the document but not on this slide.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
}
build().catch(e => { console.error(e); process.exit(1); });
