# Packets from the user's side: use-case sketches (draft, 2026-10-26)

Status: a sketch for review. Nothing here is built. It walks the
packet use cases in `docs/packet-shapes.md` from the user's seat: what
they type, what they see, and what they need to know. The verbs are
those of `docs/ergonomics.md` §4. The model underneath (record,
workspace, binding; landing; integration) is in `docs/packet-shapes.md`
§2–§5.

The test applied to every sketch: **would someone who has never read a
packet document get through it?** Wherever they would need to know a
concept, the sketch says so, under "Needs to know".

Contents:
- **U1–U10, the use cases:**
  - U1 my clone, interactively;
  - U2 hand off to the runner;
  - U3 keep editing while it runs;
  - U4 scratch research;
  - U5 new from a repo on the board;
  - U6 a failing test from CI;
  - U7 parallel sub-tasks;
  - U8 the compute farm;
  - U9 a colleague;
  - U10 when things go missing.
- **§11:** what every surface shows.
- **§12:** what users must learn.
- **§13:** questions the sketches raise.

---

## U1. Start on my clone, work interactively, resume tomorrow

**Who and where:** you, in a clone you have had for weeks. You have
never used packets.

```
~/work/fw-uart16550 (main)$ wpk work
No packet here. What are you working on?
> Add FIFO overrun handling to the RX path
You're on main. Work on a new branch, rx-overrun? [Y/n]
packet rx-overrun · yours · branch rx-overrun
Starting Claude Code with the brief…
```

You work with the agent as usual. When the context gets large, the agent
says so:

```
wpk: good point to end the shift (context 71%). Finish the item in hand, then /exit.
```

```
> /exit
Shift 1 saved: RX FIFO overrun flag added, tests 3/5 pass; next: clear on LSR read.
Resume with: wpk work
```

Next morning, from anywhere:

```
$ wpk work rx-overrun          # or just `wpk work` inside the clone
Resuming rx-overrun · shift 2
Last time: RX FIFO overrun flag added, tests 3/5 pass. Next: clear on LSR read.
```

**What happened underneath:**
- the record was created in `~/packets/rx-overrun/`;
- a pointer was written in the clone's git dir;
- hooks wrote the memento and a commit to the store at each shift-end.

The clone gained only the branch, which you agreed to.

**Needs to know:** `wpk work`. Nothing else.

**Variant: a plain folder.** In `~/notes/cache-ideas/`, which is not a
repo, the dialogue is the same without the branch question. A
one-line `.packet` file appears in the folder.

**Variant: a directory that isn't a workspace.** Typing `wpk work` in
`~` or `/tmp` asks instead:

```
~ is not a project directory. Start a scratch packet instead? [Y/n]
```

That leads to U4.

---

## U2. Hand it to the runner and walk away

```
~/work/fw-uart16550 (rx-overrun)$ wpk run -m "Finish items 3-5. Ask before changing the register map."
rx-overrun → runner · step 1 starting
This directory is the runner's until you take it back (`wpk work` or `wpk open`).
Want to keep editing here? Use `wpk run --split`.
```

Or from inside the agent session: `/run Finish items 3-5…`. That ends the
shift and hands off in one move.

Your shell prompt and VS Code status bar change:

```
[rx-overrun · runner · step 4 · $1.20] ~/work/fw-uart16550 (rx-overrun)$
```

VS Code shows the files read-only while the runner holds them. As each
step commits, it lands in your checkout:

```
$ git log --oneline -3
a91c2e0 step 4: clear overrun on LSR read; test_overrun passes   (Packet: rx-overrun)
77d0b13 step 3: add overrun counter to status register
5f2e8aa handoff: wip before run
```

**It needs you.** On your phone, the board shows the card under **Needs
you**:

```
┌ rx-overrun ─────────────────────────── Needs you · 12 min ┐
│ Step 6 asks: Item 5 needs a new bit in LSR (bit 7 is free).│
│ Change the register map?   recommend: yes, use bit 7       │
│ [ Take recommendation ]  [ Answer… ]  [ Note ]  [ Open ]   │
└────────────────────────────────────────────────────────────┘
```

You tap **Take recommendation**. The packet goes back to the runner,
and the next step sees the answer.

**Taking it back:**

```
$ wpk work
rx-overrun is running step 7 (about 3 min left). Take it at the end of the step? [Y/n]
… step 7 committed and landed. rx-overrun · yours · shift 3
Since you handed off: 4 steps, $2.10, 6 commits. Summary:
  - LSR bit 7 = overrun (you said yes at step 6)
  - tests 5/5 pass
```

There is nothing to merge: your checkout already has every step.

**Needs to know:** `wpk run`, and that `wpk work` takes it back. Answering
is a button.

---

## U3. Keep editing while it runs (`--split`)

```
$ wpk run --split -m "Write the directed tests for items 3-5"
rx-overrun → runner (in a scratch copy) · you can keep editing here
```

You carry on in the same checkout, on the testbench. Each committed
step lands in your checkout as a fast-forward. Your uncommitted edits are
left alone, and VS Code refreshes the files that changed.

When a step touches a file you are editing:

```
wpk: rx-overrun step 9 changes tb/uart_tb.sv, which you've also changed (not committed).
     The step is waiting. Commit or stash your change and it will land, or:
     wpk note "leave tb/uart_tb.sv alone"   to have it redo the step without it
```

The board shows the same as a **Needs you** card, with buttons for
**Land after I commit** and **Redo without that file**.

**Needs to know:** that `--split` exists. Everything else is a prompt
when it matters.

---

## U4. Scratch research: no repo, ever

**From the terminal:**

```
$ wpk new "Survey RISC-V cache coherence verification, 2022 on: formal vs simulation. \
           Output: a comparison table and a reading list."
packet riscv-coherence-survey · scratch · ~/packets/riscv-coherence-survey/files/
$ wpk work riscv-coherence-survey
```

**From the board:** **New**, type the brief, then **Work** (a web
terminal) or **Run** (let the runner do it overnight).

Over a few shifts, or overnight on the runner, results land in
`files/`: `report.md`, `reading-list.md`, and `papers/` with the PDFs.
The agent's own notes and outline stay in the packet's `state/` and
don't clutter the results.

```
$ wpk status riscv-coherence-survey
riscv-coherence-survey · completed · 6 steps · $3.40
Results (files/):  report.md  reading-list.md  papers/ (14 PDFs, 22 MB)
Next: nothing; mark done or give it more work (wpk run -m "…")
```

```
$ wpk done riscv-coherence-survey
Results are in ~/packets/riscv-coherence-survey/files/.
  [k] keep them there (default)   [c] copy to a directory…   [a] archive the packet too
```

None of it is put in git unless you say so: a copy, or `git init` in
`files/` later.

**Needs to know:** `wpk new "…"` and `wpk work`/`run`. Where results
are is printed every time.

---

## U5. New from a repo, on the board

**New from…** takes a pasted URL, a URL@ref, or a branch.

```
┌ New packet ────────────────────────────────────────────────┐
│ From:  https://github.com/featherweight-ip/fw-hdl@main     │
│ Task:  Port the SPI master to the new bus wrapper          │
│ Run on: [this host ▾]    Start: (•) Run  ( ) Hold for me   │
│                                          [ Create ]        │
└────────────────────────────────────────────────────────────┘
```

The runner clones into a managed workspace, runs the repo's `setup:` if
the record names one (or `ivpm update` when it finds an `ivpm.yaml`), and
starts. Each card offers **Work**, **Open** (VS Code, desktop or web, on
the clone) and **Run**.

At the end, **Done** offers:

```
Branch spi-bus-port has 9 commits.  [ Push and open PR ]  [ Push only ]  [ Keep local ]
```

Steps never push. Only this button does.

**Needs to know:** nothing beyond the board. A user may never learn where
the managed clone lives, and doesn't need to: **Open** goes there.

---

## U6. A failing test from CI

**In CI**, a few lines after the test step:

```yaml
- if: failure()
  uses: dvkit/packet-on-failure@v1      # writes PACKET.md, uploads it, posts the link
  with:
    repro: dfm run uart.test_overrun
    artifacts: sim/**/*.log, sim/**/*.fst
```

A few KB arrive as a **dehydrated** packet: a brief, repo@sha, the repro
command and links to the artifacts. The board shows it in **Inbox**:

```
┌ uart.test_overrun failed ──────────────────── Inbox · CI #8812 ┐
│ main @ 3f0c9a2 · 41/67 checks · "overrun flag still set after  │
│ LSR read" · waves (38 MB) · log                                │
│ [ Triage ]  [ Open ]  [ Run ]  [ Assign… ]  [ Close ]          │
└────────────────────────────────────────────────────────────────┘
```

| Button | What happens | Hydrated? |
|---|---|---|
| **Triage** | an agent step with no workspace: it reads the brief and the log, then writes a likely cause and whether it duplicates an open packet | no |
| **Open** | hydrate, then VS Code. It asks where (below) | yes |
| **Run** | hydrate on the runner, reproduce, then try a fix | yes |
| **Assign…** | send to a person (U9) | no |
| **Close** | archive with a reason (flaky, duplicate, known) | no |

**Hydrating into your own clone** is offered first when one matches:

```
$ wpk get https://ci.example/run/8812/packet
uart.test_overrun failed (main @ 3f0c9a2)
Where should the workspace be?
  [1] your clone ~/work/fw-uart16550 (new branch fix-test-overrun from 3f0c9a2)
  [2] a fresh managed clone
> 1
Running setup (ivpm update)… done. Reproducing (dfm run uart.test_overrun)… fails as reported.
packet fix-test-overrun · yours. Start with: wpk work
```

The received brief is shown as **data**. It becomes an instruction only
when you `wpk work` or `wpk run` it.

When it is fixed, **Done** offers the PR, and also **Reply to CI #8812**:
a comment on the run or issue with the summary and the branch.

**Needs to know:** nothing for triage. `wpk get` or **Open** to work on
it.

---

## U7. Parallel sub-tasks

**The agent proposes, the user sees.** Midway through a packet, the agent
spawns three children: one per bus protocol.

```
$ wpk status
spi-bus-port · runner · waiting for 3 sub-tasks
  ├ sub/apb    running · step 3 · $0.40
  ├ sub/axi    completed · 5 steps · ready to integrate
  └ sub/wb     needs you: "Wishbone pipelined or classic?"
Your checkout is unchanged until the parent integrates them.
```

On the board, the parent card shows the children as a mini-tree, and a
**Needs you** child surfaces as its own card.

**Looking at a child's work before it is integrated:**

```
$ wpk open spi-bus-port/sub/axi          # read-only view of the child's result
$ git log --oneline packets/spi-bus-port/axi   # its result ref, in your repo
```

**Integration, when the parent finishes** (`packet-shapes.md` §5.4):

```
wpk: spi-bus-port integrating 3 sub-tasks (apb, axi, wb)
  apb  merged · check passed
  axi  merged · check passed
  wb   conflict in rtl/bus_if.sv → parent step 14 resolves it
  …
  step 14: kept wb's pipelined handshake, adapted apb's wrapper; check passed
Integrated and landed in ~/work/fw-hdl (spi-bus-port): 3 merges, 1 fix-up.
```

You are asked only if the parent can't resolve a conflict itself. The
question then names both children and offers each one's version.

**Needs to know:** nothing new. `wpk status` shows the tree. Children
are packets with the same verbs.

---

## U8. Running on the compute farm

**One-time setup:**
```
$ wpk doctor --host farm
farm: shared store /proj/packets ✓  git 2.49 (relative worktrees) ✓  lease heartbeat ✓
```
The store and the clone must be on the shared filesystem. `wpk doctor`
says so if they are not.

**Then:**
```
$ wpk run --on farm
rx-overrun → runner on farm · step 1 starting
```

Steps run on the farm and land in your checkout through the share,
exactly as locally. The prompt and the board name the host:

```
[rx-overrun · farm · step 4]
```

Big build and simulation output goes to the farm's local scratch, not
the share. **Open** on a farm packet opens VS Code over Remote-SSH on
the farm host.

**Needs to know:** `--on <host>`, once. Setup problems are `wpk doctor`'s
job.

---

## U9. Hand it to a colleague

**With a server** (the board is multi-user):
```
$ wpk send rx-overrun --to alex -m "Can you take the FIFO depth question?"
rx-overrun → alex. You keep a read-only view.
```
Alex sees it on their board. **Open** asks where to hydrate: their own
clone, if they have one, or a fresh one.

**Without a server:**
```
$ wpk send rx-overrun rx-overrun.pkt
Wrote rx-overrun.pkt (record + 2 unpushed commits as a bundle, 41 KB).
Not included: build output, waves (derived).
```
```
alex$ wpk get rx-overrun.pkt
rx-overrun from matt · held for you. Brief and history shown below as received.
Where should the workspace be? …
```

What you send is the record, plus whatever in the workspace can't be
rebuilt: unpushed commits, or a scratch folder's files. Before anything
large or unusual goes, it is listed and you are asked.

**Needs to know:** `send` and `get`.

---

## U10. When things go missing

| What happened | What the user sees | What fixes it |
|---|---|---|
| Deleted or re-cloned the directory | `wpk status`: `rx-overrun · workspace missing (was ~/work/fw-uart16550)` | `wpk work rx-overrun` offers to re-hydrate from the record, or to attach a clone you name |
| `wpk work` in a fresh clone of the same repo | `This clone matches packet rx-overrun (same remote, branch rx-overrun exists). Attach? [Y/n]` | one keypress |
| Switched branch while the runner holds it | `Needs you: you're on main, rx-overrun lands on rx-overrun. Switch back, or land on main?` | a choice |
| Machine rebooted mid-step | nothing: the step is rolled back or forward on restart | automatic |
| The farm lost its runner mid-step | `rx-overrun · lease on farm expired 5 min ago · recovering` | automatic after the grace period |

---

## 11. What every surface shows

The same four facts, everywhere: **which packet, who has it, how far
along, and what it has cost.**

| Surface | Form |
|---|---|
| Shell prompt (`wpk prompt`) | `[rx-overrun · runner · step 4 · $1.20]` |
| VS Code status bar | `rx-overrun · runner · step 4 · $1.20`, with a lock icon while files are read-only |
| `wpk status` | the git-status-like page: state, owner, last summary, next, questions, children, results |
| Board card | title, column (Inbox, Yours, Running, Sleeping, **Needs you**, Done), the last line of the summary, and buttons for the verbs |
| Notification (phone, desktop) | only for Needs you, and for completions you asked about |

## 12. What a user must learn

| Use case | Verbs | Concepts |
|---|---|---|
| U1 my clone | `work` | none |
| U2 runner | `run`, `work` | "the runner has it" |
| U3 keep editing | `run --split` | none: conflicts arrive as prompts |
| U4 scratch | `new`, `work`/`run`, `done` | where results are, which is always printed |
| U5 board, from a repo | buttons | none |
| U6 CI failure | buttons, `get` | dehydrated vs hydrated, shown as Triage vs Open |
| U7 parallel | `status` | sub-tasks integrate when the parent finishes |
| U8 farm | `run --on` | none after `doctor` |
| U9 colleague | `send`, `get` | none |

That is about seven verbs and three ideas: **the runner has it**,
**sub-tasks integrate at the end**, and **dehydrated packets need
opening**.

## 13. Questions the sketches raise

| # | Question | Suggested default |
|---|---|---|
| X1 | Does `wpk work` outside any workspace (in `~`, `/tmp`) offer a scratch packet? | Yes (U1 variant) |
| X2 | Should `get` prefer hydrating into a matching existing clone? | Yes: offered first when the remote matches (U6) |
| X3 | A **Triage** step with no workspace: is it a normal step type? | Yes: a step whose workspace kind is "none"; it can't land anything, only write the summary and memento |
| X4 | Does a re-clone re-attach automatically when the remote and branch match? | Ask once (U10) |
| X5 | Inbox column for dehydrated packets? | Yes, separate from Yours, so CI noise doesn't bury real work |
| X6 | Is `--split` the default when you have uncommitted changes at `wpk run`? | Ask: "You have uncommitted changes. Hand off a split copy and keep editing? [Y/n]" |
| X7 | Child names in paths: `spi-bus-port/sub/axi`, or `spi-bus-port/axi`? | `spi-bus-port/axi`. Shorter, and `sub` adds nothing |
| X8 | Should the reply to CI (U6) be part of `done`, or a separate `send --reply`? | A button on **Done** when the packet came from CI; `send --reply` underneath |
