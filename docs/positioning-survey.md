# Positioning survey: what work-packet is, and who it is for (2026-10-26)

This follows `docs/industry-survey.md`, which compared work-packet with
coding agents tool by tool. This survey asks a different question: we
have an on-prem front-end, a method for agentic work, token savings and
metrics per task. Is the combination new, and who should it appeal to?

Four research passes back it. Each has its own file with source URLs and
marks for primary and secondary sources:

| File | Angle |
|---|---|
| `docs/positioning/onprem.md` | On-prem front-ends: HPC portals, Coder, EDA vendor agents, regression managers, air-gapped deployments |
| `docs/positioning/method.md` | Methods: long-running harnesses, the Ralph loop, ExecPlans, 12-Factor Agents, Beads, spec-driven development, non-AI work packages |
| `docs/positioning/cost.md` | Token cost research, FinOps and observability tools, cost per unit of work, engineering-productivity measurement |
| `docs/positioning/audience.md` | Segments: evidence, pain, constraints, reach |

Claims marked [S] in those files come from secondary sources. Check them
before quoting externally.

## 1. The thing you can't quite put your finger on

Every product surveyed makes one of three things the unit of agentic work:

- **the session**: a chat or thread (Claude Code, Amp, OpenHands, Coder Tasks, Devin);
- **the change**: a branch or PR (Codex, Copilot agent, Jules, Cursor, Sourcegraph Batch Changes);
- **the ticket**: a row in a tracker or regression database (Linear and Jira agents, Beads, Verisium AutoTriage, Questa Regression Navigator).

**work-packet makes the work itself the unit.** That unit outlives any
session, survives any tool and passes between owners. A session ends, a
PR merges and a ticket is a pointer. A packet holds the instruction, the
plan, the journal, the workspace recipe and the expensive artifacts, so
anyone can pick it up and carry on: a person, the runner or a different
harness.

The four features that seemed separate all follow from that one choice:

| What we built | Why it follows from "the work is the unit" |
|---|---|
| On-prem front-end (board, daemon, IDE drop-in) | If the unit is a directory on your disk, the UI has to go where the disk is. Nothing about the work needs to leave. |
| Method (fresh steps, one owner, recorded hand-off) | If the unit carries its own state, any worker can do the next bounded piece and leave, and the next worker needs no briefing. |
| Token savings | A step's context is bounded by what the packet holds, not by the history of one long chat. |
| Metrics per task | Cost can be charged to the unit that produced it: project → packet → step. |

The closest metaphor from outside software is the most useful one. In
nuclear, aerospace and aviation maintenance, a **work package** is a
self-contained instruction set. Crews work it shift by shift, with a
formal turnover briefing at each change, and it becomes the as-done
record (DOE, EPRI, FAA AC 120-16G; `method.md` §3). **Agents are shift
workers with no memory. work-packet is the turnover discipline.** That
is the one-sentence story. The PMBOK "work package" is a planning box
only and is the weaker analogy.

## 2. Is the combination new?

Each part has precedent. No surveyed system has all of them.

| Part | Nearest precedent | What it lacks |
|---|---|---|
| State in files, fresh context per step | Anthropic "Effective harnesses for long-running agents" (2025-11); Ralph loop; OpenAI ExecPlans | Single-repo, single owner, no board, no hand-off between people |
| Living plan plus journal | ExecPlans (Progress, Surprises, Decision Log) | Plan only; no separate append-only journal; nothing to rebuild the workspace |
| Work identity outside the session | Beads / Gas Town | The unit is an issue, not a workspace with artifacts |
| Self-hosted per-task workspace, board, IDE | Coder Tasks / Coder Agents (GA 2026-05) | Workspace rebuilt from a template, memory is a chat in Coder's database, needs a platform team, no hand-off, no "needs you" |
| Object per failure, with an owner | Verisium AutoTriage, Questa Regression Navigator | A database row, not a workspace you resume; vendor lock-in (Infineon DVCon paper) |
| Shareable repro session | Pernosco; Code Ocean capsules | One debug trace or cloud capsule, not live work with an owner |
| Cost per unit of work | Faros "cost per outcome", Jellyfish and LinearB cost per PR | Joined after the fact from Git and Jira; nothing inside the task, nothing fed back |
| Metrics that change behaviour | Claude Code `/usage` recommendations | Per user and machine, not per class of task |

Four things showed up nowhere:

1. Agents, people **and non-agent batch tools** (simulators, dfm,
   SLURM/LSF) taking turns on the same unit, with one "needs you" lane
   across all of them.
2. A unit that can be handed over or exported **live**, with its recipe
   and artifacts: to the runner, to a colleague, or as a bug bundle to a
   vendor.
3. Per-step history from a class of tasks used to size the next one:
   step size, context budget, profile, model. One paper found runs of
   the same task vary by up to 30× in tokens, and that models predict
   their own usage poorly (r ≤ 0.39). That argues for sizing from
   history (`cost.md`).
4. Self-hosted with **no platform team**: one daemon per user, files and
   git. The market is moving the other way. Ona went to OpenAI, Daytona
   reportedly closed its source, Claude Code's self-hosted runners keep
   the queue and transcript on claude.ai, and "self-hosted" increasingly
   means only that execution runs on your hosts (`onprem.md`).

## 3. Where the claims stand

**On-prem.** Strong, and getting stronger. Keysight: design "will
continue to occur on-premises". EE Times on DAC 2026: "DIY AI runs inside
the user's walls". Every EDA vendor and DV startup leads with on-prem or
air-gapped deployment. One correction to the pitch: AWS now documents
Claude Code on Bedrock GovCloud for ITAR work (2026-10-05), so "the model
must be local" is weakening. The durable claim is **the workspace,
artifacts, job tracking and audit trail stay on your machines, whatever
model you are approved to use.**

**Method.** Aligned with where the field is going (state in files, living
plans, agents as assignable parties, human-question inboxes), and ahead
on an append-only journal and recorded ownership. **One trend runs
against us:** the field is moving toward better compaction, not fresh
context.

- Amp shipped Handoff to replace compaction (2025-10), then removed it
  (2026-05-06: "compaction made it obsolete").
- Anthropic's 2026-03 harness article dropped context resets for Opus 4.6.
- Most 2026 papers train models to compact better.
- One counterpoint: Min et al. (arXiv 2608.06503) find compaction makes
  runs less stable.

If fresh steps rest only on "context rot", the argument ages badly. Rest
them on what compaction can't give: auditability, interruptibility,
hand-off of ownership at step boundaries, a different model or budget
per step, parallel work and reproducible restarts.

**Token savings.** Credible and in the right range. The 1.4–1.7× matches
the best peer-reviewed results in billed cost:

- AgentDiet (FSE 2026): 1.27–1.56×.
- JetBrains "Complexity Trap": about 2× from simply hiding old tool output.
- CliffCompaction: up to 2×.

Two points in our favour:

- We report **billed dollars including cache**. "Token Reduction Is Not
  Cost Reduction" (arXiv 2607.12161) shows that cutting tokens can raise
  the bill.
- The 1.4× against **ideally timed** compaction has no published
  equivalent.

Caveats to deal with before the claim goes out:

- It is one project. Steps that are too small cost more.
- Cache reads on the 5.5 models are cheaper (0.05× of input), so the
  5.4× and 14.5× ratios will shrink. Measure again per model, and lead
  with 1.4× and 1.7×.

**Metrics per task.** This lane is open. Faros, Jellyfish and LinearB
join cost to PRs and tickets after the fact. Langfuse, LiteLLM and
Helicone have tags if you pass a task id through. Nobody shows cost
inside the task: per step, failed attempts, the context curve, which tool
results burned context. Nobody closes the loop. PRs are also a noisy
denominator: PR counts rise while review time grows.

## 4. Who it should appeal to, and why

Ranked by pain × fit with the constraints × how reachable they are. The
evidence is in `audience.md`.

### 1. Silicon DV teams: the first market

- **Pain:**
  - 14% of IC/ASIC projects reach first-silicon success, the lowest in
    more than 20 years, and 75% are behind schedule (Wilson Research
    Group 2024).
  - Verification is 60–70% of chip effort.
  - DV engineers spend about 47% of their time debugging [S].
- **Constraint:** IP can't leave. Samsung and SK Hynix banned ChatGPT
  after the 2023 leak, and customers won't even send a vendor a testcase.
- **Willingness to pay:** ChipAgents raised a $134M Series A with more
  than 120 chip-company deployments. Bronco sells "overnight regression
  failure to root-cause ticket".
- **Why us:** a regression failure becomes a packet that rebuilds
  itself, with agents, engineers and LSF/simulator jobs taking turns in
  it, waves and coverage kept, and nothing leaving your network unless
  you send a bundle. It is neutral across vendors: Siemens' Questa MCP
  toolkit and Synopsys' support for third-party agents invite a layer
  above the tools, not a rival to them.
- **People:**
  - **Champion:** a senior DV engineer or DV lead, who uses the board and
    the packets daily.
  - **Buyer:** the verification manager. They budget per block or
    milestone, which maps onto project → packet.
- **Reach:** DVCon, DAC, Verification Academy, and the founder's own
  tools (dv-flow-mgr, IVPM, DVKit).

### 2. Engineering leads and platform teams: the feature that wins the manager

- **Evidence:**
  - 43% are over their AI budget, and only 5% are confident they can see
    what AI tools are doing (Retool, 2026-07).
  - A quarter of tech leaders spend $200–500 per developer per month on
    tokens (Gartner [S]).
  - Cursor (2025-06) and Copilot (2026-06) now meter usage, and FinOps
    FOCUS 1.5 adds token labelling in 2026-12.
- **Why us:** cost per unit of work, across harnesses, measured inside
  the task, and used to set up the next run. "This class of triage costs
  $3 and takes 4 steps" is something no FinOps tool can say.
- This is not a segment of its own. It is what turns a champion's tool
  into a team purchase in segment 1.

### 3. Agent power users: the adoption channel, not the revenue

- **Evidence:**
  - The weekly-limits backlash: GitHub issue #9424, and quotas burned in
    a day or two.
  - Vibe Kanban has 28.5k stars, and Conductor raised $22M.
- **Why us:** packets that wait hours on real jobs without polling,
  resume in fresh, cheaper context, and show what each task cost. That
  stretches the weekly quota.
- **Why it ranks low:** the space is crowded, worktrees are now the
  standard, and these users won't pay much. One gap: "cost tracking
  isn't native to any OSS tool" (Augment survey).
- **Use:** an open-source `wpk dash` for credibility and feedback.

### 4. Next markets: HPC, automotive embedded and firmware, defense

- **HPC is the closest fit:**
  - Aalto's cluster guidance asks users to keep agents from polling
    `squeue`/`sacct`, sets a minimum of 15 seconds between queue polls,
    and discourages many agents at once.
  - Utah bans autonomous agents in its Protected Environment.
  - A daemon that tracks the job and wakes the agent when it finishes
    fixes this directly.
- **Automotive:**
  - 89% use AI assistants, and IP is the leading barrier (Black Duck 2025).
  - ISO 26262 traceability fits the journal.
- **Defense:** a real need, but hard to reach (clearances, long sales
  cycles).
- **Pharma and quant:** weak evidence or they build their own.
  Deprioritise.

### 5. Customer-to-vendor repro bundles: the wedge inside segment 1

- **Evidence:**
  - About 17% of bug reports can't be reproduced, and they stay open
    about 3 months longer (MSR '14).
  - In EDA, large customers keep vendor AEs on site because a testcase
    can't leave.
- **Why us:** one bundle carries the instruction, recipe, worktrees and
  failing artifacts. It replays on the vendor's side or on-site.
- **Where to prove it:** in public on open-source EDA (Verilator,
  cocotb). Open-source maintainers in general are not a market.

## 5. Threats

| Threat | Why it matters | Response |
|---|---|---|
| Better compaction | Weakens "fresh steps are cheaper" | Argue on hand-off, audit and model choice per step; run the controlled experiment (§6) |
| Coder Agents | Self-hosted, a workspace per task and a board, already in enterprises | No platform team; files, not a database; hand-off and the "needs you" lane; batch jobs as first-class |
| EDA vendors' own agents (ChipStack, AgentEngineer, Questa One, Fuse) | Own the tools and the customer relationship | Sit above them as the neutral layer; adopt their MCP gateways |
| Regression managers adding agents (AutoTriage) | Already own the "failure object" | A packet is the workspace that a failure row points to; integrate rather than replace |
| Faros and friends adding cost per task | Already sell to the VP | Their data is per PR, after the fact; ours is per step, inside the task, and fed back |
| Claude Code self-hosted runners and Projects | The harness vendor moving toward packet-like features | Neutral to the harness; data stays on your machines; non-agent jobs |

## 6. What this suggests doing

1. **Change the message.** Lead with "the work is the unit" and the
   shift-turnover story. Present token savings and metrics as
   consequences, not as the headline.
2. **Run the experiment nobody has published:** fresh steps against
   compaction at equal cost, on two or three projects, on the current
   models, in billed dollars. The 1.4× against ideal compaction is the
   most defensible number we have; make it robust.
3. **Build the DV wedge first:** CI or regression failure → packet → triage
   steps → hand-off or vendor bundle (R4 in `docs/product.md` §14). Add
   bridges to Questa's MCP toolkit and to the regression managers'
   failure records.
4. **Close the cost loop in the product.** Measured history per class of
   task sets the step size, budget and profile. That is the lane no one
   else is in.
5. **Add tracker bridges** (Jira, Linear, GitHub issues) so a packet can
   appear where leads already look. This is the gap the method survey
   flagged.

## 7. Strategy (2026-10-26)

Messaging refined on 2026-10-27 in `docs/positioning/messaging.md`:
tracking many agents' work is the way in; the packet is the product.

Success is measured by adoption and user success, not revenue. That
favours a format and cheap ways in over a broad product build-out.

**The move: make the packet a format, not just a product, and seed it
through distribution we already have.**

1. **Publish the packet layout and lifecycle as an open spec,
   independent of wpk.**
   - Containers spread because the image format was open; AGENTS.md
     spread because it was trivially easy to adopt.
   - If producers (CI, plugins, tool vendors) and receivers (vendors,
     maintainers) can speak the format without running `wpkd`, adoption
     of the format counts even where wpk doesn't run.
   - Harness vendors will absorb features that only concern agents. They
     won't own an open, vendor-neutral format that also covers batch jobs
     and hand-off between people.
   - Outline: `docs/packet-format.md`.
2. **Cheap ways in.** The daemon is the biggest step to ask of a new
   user. Ahead of it, offer:
   - a Claude Code plugin or skill that keeps a Level 0 packet (the
     method with no daemon);
   - a CI action that creates a packet when a test fails, so the packet
     arrives in someone's hands without them choosing to adopt anything.
3. **Narrow the build until outside users show up.** `docs/product.md`
   §14 plans eight releases. Make one user on one machine excellent
   first. Treat R5–R8 (links, the hub, across organizations, the browser
   IDE) as speculative until outside users pull for them.

**Opportunities not yet in the plan:**

- **Open-source silicon** (OpenTitan, CHIPS Alliance, cocotb, Verilator)
  as a public proving ground. Their nightly regressions produce real
  failures, which become public packets and public report bundles with
  no NDA.
- **Open OnDemand.** A board-plus-runner app there reaches hundreds of
  HPC centers, which are now writing rules about agents flooding the job
  queue.
- **Our own ecosystem** (dv-flow-mgr, IVPM, DVKit). Native progress
  reporting from dfm, and "run this flow as a packet", turn existing
  users into packet users.
- **Publish the experiment:** fresh steps vs compaction at equal cost, in
  billed dollars, on current models. No one has; it would settle our
  biggest open risk.
- **The method as content:** "Agents are shift workers; here is the
  turnover discipline", as a talk, a post or a Verification Academy
  session.

**Measures of user success**, to record (opt-in) from the start:

- packets that finish without a human rescue;
- time to resume a packet left by someone else, or a week ago;
- hand-offs accepted, by colleagues or vendors;
- cost per finished packet, and whether it falls over time for a class
  of tasks.

**Checkpoint: 2026-12-21.**

- 5–10 outside users have finished real packets.
- At least one hand-off has gone between people.
- The compaction experiment has been rerun on two or three projects.

If people come back to it unprompted, build R5 onward. If not, the spec,
the checker and the plugin are still worth publishing on their own.
