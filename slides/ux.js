// User-experience content for build_deck.js (design in docs/runner.md).
module.exports = {
  journey: [
    ["Start a project", "One command creates the root packet from a prompt or template and registers it.",
      "wpk new triage\n  -t nightly-triage\n  --every daily"],
    ["Runner takes over", "One runner per user wakes every project on time, within limits and budget.",
      "systemctl --user \\\n  enable --now \\\n  wpkd"],
    ["Watch the board", "A local web board shows every project. Cards move as states change.",
      "wpk dash\n→ 127.0.0.1:7878"],
    ["Answer when asked", "A packet that needs a decision notifies you. Your reply wakes it.",
      "wpk send triage\n  'one bug'"],
    ["Dig into any step", "Every step keeps its prompt, transcript, change and cost on disk.",
      "wpk show triage\n  --step 7"],
  ],

  // Kanban mock: [column, colour key, cards: [name, line, footer]]
  board: [
    ["Running", "run", [
      ["uvm-port-research", "child 3 of 5 surveying pyhdl-if", "step 14 · 4 min · $1.12"],
      ["lint-cleanup", "fixing verilator warnings", "step 3 · 1 min · $0.08"]]],
    ["Sleeping", "sleep", [
      ["nightly-triage", "next: Thu 06:00 · daily", "31 steps · $0.84 today"],
      ["dep-watch", "next: Sat 31 Oct · in 10 days", "4 steps · $0.02"],
      ["weekly-report", "next: Mon 08:00 · weekly", "12 steps · $0.00 today"]]],
    ["Waiting", "wait", [
      ["fpga-timing", "waiting for 2 children", "until: in 3 days"]]],
    ["Needs you", "ask", [
      ["regress-bisect", "\"File one bug or three?\"", "asked 2 h ago · Reply"]]],
    ["Failed", "fail", [
      ["doc-sync", "pip install failed in step 6", "Retry · Open step"]]],
    ["Done", "done", [
      ["cov-merge", "merged 48 coverage DBs", "finished yesterday · $0.61"]]],
  ],

  tree: [
    [0, "nightly-triage", "sleep", "root · step 31 · wakes Thu 06:00"],
    [1, "run-suite", "done", "12 steps · ran regress/full"],
    [1, "triage-axi", "done", "5 steps · bug filed"],
    [1, "triage-dma", "ask", "step 7 · asked you 2 h ago"],
  ],
  // timeline lanes: [label, [[startHour, endHour, kind]]], hours from 06:00
  lanes: [
    ["nightly-triage", [[0, 0.3, "step"], [2.6, 2.9, "step"], [2.9, 24, "sleep"]]],
    ["run-suite", [[0.1, 0.4, "step"], [0.5, 0.9, "step"], [1.0, 1.5, "step"]]],
    ["triage-axi", [[1.6, 1.9, "step"], [2.0, 2.3, "step"]]],
    ["triage-dma", [[1.6, 1.9, "step"], [2.0, 2.4, "step"], [2.4, 24, "ask"]]],
  ],
  statusPreview: "state: SLEEPING\nstep: 31\nevery: daily 06:00\nwake_at: 2026-10-22T06:00Z\nspend_today: $0.84",
  actions: ["Pause", "Wake now", "Edit wake time", "Send message", "Fork from step"],

  transcript: [
    ["prompt", "Prompt sent: memento, status, agent.md, mailbox  ·  3.1k tokens  ▸"],
    ["model", "Reading state/failures.md and the three new failure logs."],
    ["tool", "Bash   dfm run regress/axi_dma -k timeout   →  exit 1, 212 lines  ▸"],
    ["model", "All three stop at the same AXI write-response timeout in dma_ch2. Probably one root cause, but the stimulus differs."],
    ["proposal", "ask: File one bug or three?   choices: [one, three]   until: in 2 days"],
  ],
  meta: [["Duration", "2 min 41 s"], ["Tokens", "38.2k in · 2.1k out"], ["Cost", "$0.21"], ["Model", "claude-sonnet-5"]],
  diff: [
    [" ", "state/failures.md"],
    ["+", "axi_dma_timeout_1  same root cause?"],
    ["+", "axi_dma_timeout_2"],
    [" ", "memento.md"],
    ["-", "triage the three new failures"],
    ["+", "ask: one bug or three?"],
  ],

  upcoming: [
    ["Thu 22 Oct 06:00", "nightly-triage", "daily"],
    ["Thu 22 Oct 18:00", "regress-bisect", "answer deadline"],
    ["Mon 26 Oct 08:00", "weekly-report", "every monday"],
    ["Mon 26 Oct 08:00", "dep-audit", "every monday"],
    ["Sat 31 Oct 09:00", "dep-watch", "in 10 days"],
    ["Sun 10 Jan 09:00", "license-check", "on 10 Jan"],
  ],

  rules: [
    ["Nothing is hidden", "Every step's prompt, transcript, change and cost is on disk, one click from the board."],
    ["The board cannot drift", "Columns come from packet state. Buttons run the same code as the CLI; nothing is dragged."],
    ["Safe to walk away", "Kill the runner or reboot. Leases expire, and each missed wake runs once on restart."],
    ["Spend is visible", "Spend per project per day against a budget. A looping packet is paused, with the reason shown."],
    ["Local and private", "The board binds to localhost. Projects live in any directory you choose."],
    ["Everything from the CLI too", "new, ps, show, send, pause, wake, prune: the board is a view, not a requirement."],
  ],
};
