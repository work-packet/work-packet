# Prior-art survey: work-packet as a methodology

Date: 2026-10-26. Scope: methodology prior art (agentic workflows 2025-2026, human/agent ownership, and older non-AI "work package" ideas). Already covered elsewhere and skipped here: Manus "file system as context", task-master, Claude Code Projects, OpenHands event log.

Source key:
- [P] primary source (vendor or author page, repo, paper) that I fetched or that came up directly in search.
- [S] secondary source (blog, review, aggregator, or search-engine summary I did not check against the primary). Treat these claims with caution.
- [M] from background knowledge, not re-checked in this session.

---

## 1. Agentic methodologies, 2025-2026

### 1.1 Anthropic: "Effective harnesses for long-running agents" (2025-11-26) [P]
https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

- Two phases. An **initializer agent** writes `init.sh`, `claude-progress.txt`, a JSON feature list (200+ features, all marked failing to start with) and a first git commit. **Coding agent** sessions then each: read the progress file and the git log, run a smoke test, pick ONE failing feature, implement it, commit, and update the progress notes.
- Framing quote: "each new engineer arrives with no memory of what happened on the previous shift."
- **Overlap with work-packet: very high.** progress file ~ memento/notes; feature list ~ plan; init.sh ~ the recipe; one feature per session ~ one bounded step; git as the record ~ journal + worktrees. What it does not have: an ownership or hand-off model, a human question queue, a unit of work beyond one repo, kept derived artifacts, or a runner as a separate scheduler (the harness is a loop around the SDK).

### 1.2 Anthropic: "Effective context engineering for AI agents" (2025-09-29) [P]
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

- Names **context rot** ("as the number of tokens in the context window increases, the model's ability to accurately recall information ... decreases").
- Three long-horizon techniques: **compaction**, **structured note-taking** (NOTES.md, to-do files kept outside the window), and **sub-agent architectures**. Also "just-in-time" retrieval.
- Goal: "the smallest set of high-signal tokens that maximize the likelihood of some desired outcome."
- work-packet takes the note-taking line to its end: notes are the *only* carrier of state between steps, and compaction is never used.

### 1.3 Anthropic: "Harness design for long-running application development" (2026-03-24) [P]
https://www.anthropic.com/engineering/harness-design-long-running-apps

- Planner, generator and evaluator agents. "Communication was handled via files: one agent would write a file, another agent would read it and respond." Before each sprint, the generator and evaluator agree a **sprint contract**: what will be built and how it will be checked.
- **Context resets vs compaction:** "A reset provides a clean slate, at the cost of the handoff artifact having enough state for the next agent to pick up the work cleanly." Sonnet 4.5 showed "context anxiety" (it wrapped up early as the window filled), so resets were essential.
- **Important counter-signal:** with Opus 4.6 the author *removed* sprint scaffolding and resets, expecting newer models to "need less scaffolding." So Anthropic's own position is that resets are a workaround tied to a model generation, not a principle.
- Relevance: this confirms work-packet's file hand-off mechanism and its "contract before step" idea, but it is a warning that the core rationale (fresh context beats long context) may weaken as models improve. work-packet should argue for fresh steps on *other* grounds too: auditability, interruptibility, ownership transfer, cost control, model and tool swaps between steps, and parallelism.

### 1.4 Ralph Wiggum loop: Geoffrey Huntley (2025-07-14) [P]
https://ghuntley.com/ralph/

- `while :; do cat PROMPT.md | claude-code ; done`. "One item per loop. I need to repeat myself here—one item per loop." Each iteration gets a fresh context. Specs live in `specs/` as "single sources of truth"; `fix_plan.md` is a priority list that every loop rewrites; and "I have deleted the TODO list multiple times" when the loop drifts.
- Anthropic shipped an official `ralph-wiggum` Claude Code plugin: https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum [P/S]. Secondary write-ups say it uses a **Stop hook to re-feed the prompt inside the same session**, i.e. the loop runs *without* fresh context, unlike Huntley's original ([S] https://paddo.dev/blog/ralph-wiggum-autonomous-loops/, https://www.atcyrus.com/stories/ralph-wiggum-technique-claude-code-autonomous-loops).
- **Closest ancestor of the work-packet "step" idea.** A Ralph loop is a packet with one owner (the loop), a plan file, specs and fresh context per item. What Ralph lacks, and work-packet adds: a structured state schema (instruction / plan / memento / journal), an append-only journal kept separate from the mutable plan, a workspace recipe, explicit owner and hand-off, questions surfaced to a board, and many packets at once.

### 1.5 12-Factor Agents: HumanLayer / Dex Horthy (2025) [P]
https://github.com/humanlayer/12-factor-agents

The factors closest to work-packet:
- F3 **Own your context window.**
- F5 **Unify execution state and business state.** In work-packet the packet directory *is* both.
- F6 **Launch/pause/resume with simple APIs.**
- F7 **Contact humans with tool calls.** Questions become first-class outputs (~ the board's question queue).
- F8 **Own your control flow.** The runner, not the model, decides what runs next.
- F10 **Small, focused agents.**
- F12 **Make your agent a stateless reducer.** A step is literally `next_state = step(packet_state)`.

work-packet reads like a concrete, file-system realisation of factors 3/5/6/7/8/12 for coding work.

### 1.6 HumanLayer "Advanced context engineering" / Research-Plan-Implement (2025-2026) [S, partly P]
- ACE-FCA doc: https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/ace-fca.md (linked via [S] https://www.treycausey.com/commonplace/2025-09-24-github-com-humanlayer-advanced-context-engineering-for-coding-agents-blob-main-ace-fca-md/)
- Talk "No Vibes Allowed": https://ai.engineer/talks/context-engineering-for-complex-codebases
- **Frequent intentional compaction:** write the verified state (decisions, defects, plan) to Markdown, have a human or a fresh session check it, and restart from that file. Keep context use at about 40-60% ("the dumb zone" lies above that). Phases are research, then plan, then implement, each handing only the needed context to the next.
- [S] Horthy has said a fully automated "dark factory" corrupted a codebase in three months (https://finance.biggo.com/news/15099f5634f5ab9a). This argues for human checkpoints, which work-packet has through owner hand-offs and board questions.
- HumanLayer itself has pivoted: the classic approvals SDK (`require_approval`, `human_as_tool`) is marked deprecated, and the company now ships **CodeLayer**, a desktop app and daemon that orchestrates parallel Claude Code sessions ([S] https://starlog.is/articles/ai-agents/humanlayer-humanlayer/, https://deepwiki.com/humanlayer/humanlayer).
- **Overlap: very high on method.** RPI with intentional compaction is close to work-packet's plan/memento steps. Difference: in HumanLayer these are phases within a human-driven session. In work-packet the restart from file is the *default* for every step and is run by a runner.

### 1.7 Amp (Sourcegraph spin-out): Handoff, then its reversal [P]
- 2025-10-23, "Handoff (No More Compaction)": https://ampcode.com/news/handoff. Compaction is "lossy" and "encourages long, meandering threads"; Handoff writes a goal-directed starting prompt plus a file list for a *new* thread, and the user edits it before it is sent.
- **2026-05-06, "Amp, Rebuilt": https://ampcode.com/news/neo. "Handoff is gone ... compaction made it obsolete."** Auto-compaction now runs at 90% full, and threads can reference earlier threads.
- **This is the most important counter-evidence in the survey.** A leading product tried explicit fresh-context hand-off and went back to compaction once models and compaction got better. With the Anthropic 2026 note (§1.3), this suggests the field is moving *away* from fresh context as a fix for context rot inside an interactive session. work-packet's fresh steps are still defensible, but as a property of *scheduled, owned, auditable* work, not as a context-rot workaround.

### 1.8 Steve Yegge: Beads and Gas Town (2025-10 to 2026) [P for Beads; S for Gas Town]
- Beads: https://github.com/steveyegge/beads. A git-synced issue graph for agents, now on **Dolt** (with a JSONL export). `bd ready` lists unblocked work. `bd update --claim` atomically sets the assignee and in-progress status. Sessions are recorded on close. "Memory decay" summarises old closed issues. `bd prime` injects context at session start.
- Gas Town ([S] https://maggieappleton.com/gastown, https://steve-yegge.medium.com/gas-town-from-clown-show-to-v1-0-c239d9a407ec). A "Mayor" agent talks to the human and never codes. "Polecats" are throwaway workers that take one task and vanish. A "hook" points each worker at its current work. **Sessions are disposable by design; roles and tasks persist in git.** "Seancing" lets a new session ask its predecessor about unfinished work. Work goes out by assignment, and workers coordinate by mail. Successor platform: "Gas City" (https://blog.gascity.com/).
- **Overlap: high on ownership and persistence.** "Disposable sessions, persistent work identity in git" is exactly the work-packet stance. Atomic claim ~ the explicit owner. Differences: Beads' unit is an *issue* (a small record) and the workspace is shared, whereas work-packet's unit is a *directory* carrying workspace recipe, worktrees, journal and artifacts. Gas Town aims at massive parallelism (20-30 agents); work-packet aims at a few long-running pieces of technical work with an accountable owner.

### 1.9 Spec-driven development (SDD) toolkits
- **GitHub Spec Kit** (2025-09, still active in 2026) [P] https://github.com/github/spec-kit. `constitution.md` in `.specify/memory/`; `/speckit-specify`, then `plan`, `tasks`, `implement` and (newer) `converge`, giving spec.md, plan.md and tasks.md per feature. Newer extensions cover bug workflows (`.specify/bugs/<name>/`) and idea assessments.
- **AWS Kiro** [P] https://kiro.dev/docs/specs/feature-specs/. `.kiro/specs/<feature>/{requirements.md (EARS), design.md, tasks.md}`, plus *steering* files (persistent context) and *hooks* (event-triggered agents). Independent tasks are grouped into "waves" ([S] codemyspec).
- **Tessl** (2025-09) [P] https://tessl.io/blog/tessl-launches-spec-driven-framework-and-registry. Specs kept as long-term memory in the repo; a Spec Registry of 10k+ library usage specs ("npm for knowledge").
- **Agent OS** (Builder Methods / Brian Casel) [P] https://github.com/buildermethods/agent-os. Three context layers: standards, product, specs. v3 (2026) narrowed to standards injection and leaves planning to the host tools ([S] discussion #310).
- **BMAD Method** [S] https://codemyspec.com/blog/bmad-method-explained, https://devlabs.angelhack.com/blog/bmad-method/. Role agents (Analyst, PM, Architect, PO, Scrum Master, Dev, QA). The PO "shards" the PRD into epics; the Scrum Master writes **self-contained story files (~500-1000 words)** holding everything the Dev agent needs. A fresh Dev agent per story.
- Taxonomy: Birgitta Böckeler (Thoughtworks), "Understanding Spec-Driven-Development: Kiro, spec-kit, and Tessl", martinfowler.com, Oct 2025: **spec-first / spec-anchored / spec-as-source**. Most tools claim the higher levels but deliver only spec-first ([S] summary via https://daily.dev/posts/understanding-spec-driven-development-kiro-spec-kit-and-tessl-wbu9w3aj6; primary at https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html [M URL]).
- **Overlap: medium.** All of these use a per-feature directory of Markdown artifacts (spec, plan, tasks) that feed a fresh agent, which matches work-packet's instruction + plan. BMAD's self-contained story file is the closest to a packet's instruction + memento. **None of them model execution state** (journal, owner, hand-off, workspace recipe, kept artifacts). They are *planning* methodologies; work-packet is an *execution and ownership* methodology that could sit underneath any of them. Spec Kit's recent bug and assessment directories show it drifting toward "a folder per piece of work, not only per feature."

### 1.10 Superpowers: Jesse Vincent (obra) [P]
https://github.com/obra/superpowers

- A skills-based methodology: brainstorming leads to a design doc, then `writing-plans` (tasks of a few minutes each, with exact file paths and verification steps), then `executing-plans` or **subagent-driven development** (a *fresh subagent per task* followed by a two-stage review: spec compliance, then code quality), then commit.
- Overlap: fresh context per task plus a plan file. The difference is that Superpowers lives inside one parent session, which is the orchestrator and holds the long context; work-packet's orchestrator is a non-LLM runner reading files.

### 1.11 OpenAI: ExecPlans / PLANS.md and "Harness engineering" [P]
- Cookbook, "Using PLANS.md for multi-hour problem solving": https://developers.openai.com/cookbook/articles/codex_exec_plans. An ExecPlan is a *living document* whose sections **Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective** must be kept current. "Either a person or an agent can resume from the file instead of relying on chat history." Credited with letting Codex work for 7+ hours from one prompt.
- "Harness engineering" (Ryan Lopopolo, 2026-02-11): https://openai.com/index/harness-engineering/. About 1M LOC written entirely by Codex. The repo knowledge base has `docs/exec-plans/{active,completed,tech-debt}`, design docs, product specs and references ([S] structure via summaries).
- **Overlap: very high on the plan-as-state-carrier idea.** The ExecPlan sections map almost one-to-one onto work-packet's plan + notes + journal (Decision Log ~ journal; Surprises ~ notes). `exec-plans/active` vs `completed` ~ packet lifecycle. But an ExecPlan is one file in the code repo; a packet is a directory *outside* the repo that owns worktrees *of* repos.

### 1.12 Cline Memory Bank (2025) [P]
https://docs.cline.bot/best-practices/memory-bank

- `memory-bank/{projectbrief, productContext, activeContext, systemPatterns, techContext, progress}.md`. Because "context is wiped between tasks", the agent re-reads all of it at task start and updates `activeContext.md` at the end.
- Overlap: the read-state, work, write-state protocol of a work-packet step, but per *project*, not per *unit of work*, and with no owner or journal.

### 1.13 AGENTS.md (2025-08) [P]
https://openai.com/index/agentic-ai-foundation/

- Repo-level guidance file. On 2025-12-09 it was donated (by OpenAI) to the Linux Foundation's **Agentic AI Foundation** (co-founded by OpenAI, Anthropic and Block; Anthropic contributed MCP, Block contributed goose). Reported adoption is 40k+ projects. Note: one search summary wrongly says that "OpenAI and Anthropic donated AGENTS.md"; AGENTS.md came from OpenAI.
- Relevance: this is the convergence point for *static* repo instructions. work-packet's instruction file is *dynamic, per unit of work*. It complements AGENTS.md rather than competing with it, and the packet should reference the repo's AGENTS.md rather than copy it.

### 1.14 Task-per-worktree orchestrators (adjacent)
- **Vibe Kanban** (BloopAI) [S] https://starlog.is/articles/developer-tools/bloopai-vibe-kanban/. Every task card is a git worktree plus an agent terminal, with columns To do / In progress / In review / Done. [S] One review headline mentions a "shutdown" (https://vibecoding.app/blog/vibe-kanban-review); not verified.
- **Backlog.md** [P] https://github.com/MrLesk/Backlog.md. Tasks as Markdown files in the repo, a terminal and web kanban, and a "human + AI collaboration" framing.
- Overlap: board + worktree per task matches work-packet's board and worktrees. These tools have no step/fresh-context discipline, no journal and no recipe.

### 1.15 Research on fresh context vs compaction
- **Chroma, "Context Rot"** (2025-07; Hong, Troynikov, Huber) [P] https://www.trychroma.com/research/context-rot, code at https://github.com/chroma-core/context-rot. Tested 18 models; all degrade as input grows, even on simple tasks and well below the window limit.
- **Compaction is now the mainstream research direction** [P, arXiv abstracts]:
  - CompactionRL (2607.05378): RL-trained summarisation, 66.4% SWE-bench Verified with GLM-4.5-Air.
  - AutoCompact (2610.02163): the model learns *when* to compact; +9.2 points on SWE-bench Verified.
  - Self-Compacting LM Agents (2606.23525).
  - Slipstream (2605.08580) states "compaction has emerged as the dominant approach".
  - Min et al., "Towards Reliable Context Compression for Long-Horizon Agents" (2608.06503, rev. 2026-10-14): compression "can weaken the influence of recent interactions, increasing blocked actions, repeated exploration, and instability across runs". This supports file-based resets as a more *reproducible* option.
- **Gap:** I found no controlled study comparing "fresh context + structured state files" against "compaction" on long-horizon coding at equal cost. The evidence for resets is practitioner reports (Anthropic 2025/2026, Huntley, HumanLayer, Amp 2025), and the reversals (Amp 2026, Anthropic with Opus 4.6) are also practitioner reports. **work-packet could own this comparison** as an experiment, with E-series style runs and cost and token accounting.

---

## 2. Human/agent hand-off and ownership models

| System | Ownership model | Human-question channel | Notes |
|---|---|---|---|
| **Linear for Agents** [P/S] https://linear.app/docs/assigning-issues, https://x.com/linear/status/1950923480045674849 | **Delegation does not transfer ownership.** The human stays assignee and the agent is a "delegate"/contributor. Principle: "An agent cannot be held accountable." | Agent sessions show activity in the issue; [S] coding sessions launched 2026-06 (Claude Code or Codex in a sandbox, then a PR). | Philosophically opposite to a single owner that may be a runner. |
| **Jira, agents in Jira** (open beta 2026-02-25) [S] https://getsliq.com/blog/jira-ai-agents, https://techinformed.com/atlassian-adds-ai-agents-to-jira-under-existing-permissions/ | **Agent can be the Assignee**, like a person, under existing permissions and approval workflows. Rovo agents or third-party MCP agents. | Comments, @mentions, workflow transitions. Actions are logged in the issue history. | Closest to work-packet's "owner may be a runner", but a ticket, not a workspace. |
| **GitHub Agent HQ / Mission Control** (Universe 2025-10) [S] https://venturebeat.com/ai/githubs-agent-hq-aims-to-solve-enterprises-biggest-ai-coding-problem-too | Assign an issue to @copilot or a third-party agent (Claude, Codex). Custom agents in `.github/agents/*.md`. | PR review comments; sessions and logs in Mission Control. | Ownership ends at the PR. The hand-off back to the human is the review. |
| **LangChain Agent Inbox / ambient agents** [P] https://github.com/langchain-ai/agent-inbox | Agent runs in the background; LangGraph `interrupt()` pauses it with full persisted state. | An inbox of interrupts: accept, edit, respond or ignore. | Closest analogue to work-packet's **board of questions**. It uses a persisted graph checkpoint where work-packet uses files. |
| **HumanLayer (classic SDK)** [S] | `require_approval` / `human_as_tool` routed to Slack or email. | Approvals as tool calls (12-Factor F7). | Deprecated in favour of CodeLayer. The *idea* survives as a standard. |
| **Gas Town / Beads** | Atomic claim sets assignee + in-progress; the Mayor assigns; hooks point workers at work. | Mail between agents; the Mayor is the human interface. | Most explicit *agent-to-agent* ownership; human is the strategist. |
| **Older human practice** (nuclear/aero; §3.2) | Signed work package; formal **job turnover briefings** with as-left conditions. | Hold points, QC sign-offs. | The original source of "recorded hand-off". |

**Convergence:** every major tracker (Linear, Jira, GitHub) now treats agents as assignable or delegable parties with a session log attached to the ticket. They differ on whether the agent can *own* the work: Linear says no, Jira says yes, GitHub says it owns until the PR. work-packet's model (one owner, human *or* runner, with a recorded hand-off) is the Jira position. It goes further by putting the hand-off in the journal and letting the runner hand back to a human mid-work, not just at PR time. Nobody else formalises the hand-off *record* (who gave it, why, what state) as a first-class artifact; the nuclear "job turnover briefing" is the nearest precedent.

---

## 3. Older, non-AI prior art for "work packet"

### 3.1 PMBOK work package / WBS [P/S]
https://www.pmi.org/learning/library/practice-standard-work-breakdown-structures-8063
- A work package is "the work defined at the lowest level of the WBS for which cost and duration can be estimated and managed." It is assignable to *one* responsible organisation or person. The **WBS dictionary** gives each package its scope, deliverables, milestones, resources and acceptance criteria. Heuristic: the 8/80 rule ([S]).
- Inherited: the name; the idea of a bounded, estimable, assignable unit with a *single responsible owner*; the instruction file ~ WBS dictionary entry. Not inherited: PMBOK packages are planning records, not executable workspaces.

### 3.2 Nuclear and aerospace maintenance work packages [P]
- US DOE Nuclear Facility Maintenance Management guide: https://www.directives.doe.gov/directives-documents/400-series/0433.EGuide-1-1a/@@images/file
- Entergy EN-WM-105 work planning (NRC ADAMS ML090410148): https://www.nrc.gov/docs/ML0904/ML090410148.pdf
- EPRI Nuclear Work Planning Training (2019): https://restservice.epri.com/publicdownload/000000003002015496/0/Product
- FAA AC 120-16G (work/task cards): https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC_120-16G.pdf
- A nuclear work package is "a compilation of documents including the work order task, work instructions, and any other supporting material such as drawings, vendor manuals ... safety analysis, and permits."
  - It is **planned in advance**, covering prerequisites, initial conditions, QC hold points and post-maintenance testing.
  - Work is done *against* it and **recorded in it**: the completed package is the quality record.
  - **Job turnover briefings** "provide as-left conditions and job-site hazards" to the next crew.
- FAA work cards serve two functions: (1) the "what to do / how to do it", and (2) *documenting* what was done, for records compliance.
- **Inherited (strongly):** the packet as a self-contained folder of instruction + references + plan that also becomes the as-done record; append-only sign-offs (~ journal); explicit hand-off between shifts with state (~ memento + hand-off record); prerequisites and initial conditions (~ recipe). This is the deepest root of the concept, and the shift-change metaphor is the same one Anthropic uses ("previous shift").

### 3.3 Lab notebooks and ELNs [M]
- Classic practice (e.g. Kanare, *Writing the Laboratory Notebook*, ACS 1985; NIH and USPTO guidance): bound, dated, chronological, **no erasures** (strike through, never delete), and record the *why* and the dead ends as well as the result; signed and witnessed. ELNs (Benchling, LabArchives, eLabFTW) keep this as audit-trailed entries linked to samples and data.
- Inherited: **the append-only journal** that records negative results and decisions, separate from the polished outputs. The ExecPlan "Surprises & Discoveries" and "Decision Log" sections reinvent this.

### 3.4 Reproducible research compendia and capsules [P]
- Marwick, Boettiger & Mullen, "Packaging Data Analytical Work Reproducibly Using R (and Friends)", *The American Statistician* 72(1), 2018: https://peerj.com/preprints/3192/. The compendium is "a single container for ... the underlying analysis, data, and even the required software environment"; conventional folder layout; rrtools.
- Code Ocean Compute Capsules: https://codeocean.com/blog/what-is-a-compute-capsule. Code + data + environment + results, versioned and verified-reproducible.
- Whole Tale (arXiv 1805.00400): https://arxiv.org/pdf/1805.00400
- Inherited: the **recipe to rebuild the workspace** plus **kept derived artifacts** alongside the work. The difference is that compendia are packaged at the *end* of work for others to reproduce, whereas a packet is a *live* container that is rebuilt at each step and handed between owners mid-flight.

### 3.5 Bug-report repro bundles: rr / Pernosco [M]
- rr (https://rr-project.org/) records a deterministic execution trace; Pernosco (https://pernos.co/) turns it into a shareable, queryable debugging session, so a bug report becomes a self-contained, replayable artifact.
- Inherited: "a unit of work should carry what is needed to reproduce its context for the next person." It is narrower: an execution trace, not a plan or ownership.

### 3.6 Environment-as-code: devcontainers, Nix flakes, DVC [M]
- Dev Containers spec (https://containers.dev/): `devcontainer.json` describes a reproducible dev environment per repo.
- Nix flakes (https://nix.dev/concepts/flakes): pinned, hermetic inputs (`flake.lock`) that rebuild the same environment.
- DVC (https://dvc.org/): versions data and pipeline stages (`dvc.yaml`, `dvc.lock`) next to git, and caches derived outputs.
- Inherited: the **recipe** (rebuild, don't snapshot) and **kept derived artifacts with provenance** (DVC's cache ~ kept artifacts). work-packet applies these per *unit of work* across several repos (worktrees), not per repo.

---

## 4. Synthesis

### What work-packet inherits, and from where
| work-packet element | Main ancestor(s) |
|---|---|
| Packet as the unit of work, single responsible owner | PMBOK work package; nuclear/aero work packages; Jira-style agent assignee |
| Instruction file | WBS dictionary entry; BMAD story file; Spec Kit spec.md |
| Plan (mutable) | Ralph `fix_plan.md`; Anthropic feature list; ExecPlan; Spec Kit/Kiro tasks.md |
| Memento / notes | Anthropic `claude-progress.txt`; Cline `activeContext.md`; HumanLayer intentional compaction doc |
| Append-only journal | Lab notebook; nuclear work-package sign-offs; ExecPlan Decision Log |
| Recipe to rebuild workspace | Anthropic `init.sh`; devcontainer; Nix flake; research compendium |
| Git worktrees of the code | Vibe Kanban / Conductor-style worktree-per-task |
| Kept derived artifacts | DVC cache; Code Ocean capsule results |
| Fresh-context bounded steps | Ralph loop; Anthropic harness; Superpowers subagents; BMAD fresh dev agent; 12-Factor "stateless reducer" |
| Runner schedules the next step | Ralph bash loop; Gas Town; 12-Factor "own your control flow" |
| Recorded hand-offs | Nuclear job turnover briefings; Beads session-on-close; Amp Handoff (2025) |
| Questions to the human on a board | LangChain Agent Inbox; HumanLayer human-as-tool; 12-Factor F7 |

### Is the combination new?
Every individual element has a precedent. I found no system or published methodology that combines all of the following:
- (a) a **directory-per-unit-of-work that lives outside the code repo** and owns worktrees of one or more repos;
- (b) a **typed state schema** (instruction / plan / memento / append-only journal) rather than a single plan file;
- (c) a **recipe** so the workspace can be thrown away and rebuilt at every step;
- (d) **fresh-context steps scheduled by a non-LLM runner**;
- (e) **single explicit owner, human or runner, with hand-offs recorded in the journal**;
- (f) a **board of human questions** spanning packets.

The nearest wholes are the Anthropic long-running harness (a, b and e missing), Ralph (b, c, e and f missing), Gas Town/Beads (a, c and the typed packet missing; issue-centric), and the nuclear work package (no agents, of course).

### Where the field is converging
1. **State in files, not in the chat.** Everyone agrees: Anthropic, OpenAI ExecPlans, Spec Kit/Kiro, Cline, Beads, HumanLayer. work-packet is *aligned*.
2. **Plan as a living document with progress and decisions.** OpenAI's ExecPlan sections are the clearest statement. work-packet is *aligned*, and ahead in separating the append-only journal from the mutable plan.
3. **Per-feature/per-task folders.** Spec Kit, Kiro and Agent OS do this for *planning*. work-packet is *ahead* in also packaging execution state, ownership and environment.
4. **Agents as assignable parties in trackers** (Linear, Jira, GitHub). work-packet is *aligned*. It is ahead on recorded mid-work hand-offs, and behind on integration: it has no Linear/Jira/GitHub bridge, and that is where teams will expect to see ownership.
5. **Disposable sessions, persistent work identity** (Gas Town, Anthropic, Ralph). *Aligned.*
6. **Fresh context vs compaction: the field is diverging, and moving toward compaction for interactive work** (Amp reversed Handoff in 2026-05; Anthropic dropped resets with Opus 4.6; a wave of 2026 papers trains models to compact). On the narrow claim "fresh context is needed because of context rot", work-packet is *at risk of being behind*. It should rest fresh steps on durable arguments: auditability, reproducibility (cf. Min et al. 2026 on compaction instability), interruptibility, ownership transfer at step boundaries, swapping cost and model per step, and parallel packets. It could also run a controlled comparison, which nobody seems to have published.
7. **Human-in-the-loop as an inbox** (Agent Inbox, Mission Control, HumanLayer then CodeLayer). *Aligned.* The board of questions is the same pattern, but local-first and file-backed.

### What remains distinctive
- **The packet sits outside and above repos.** It is a unit of *technical work* (possibly spanning several repos, sims and derived data), not a unit of *code change*. That fits hardware/DV and research-style work far better than PR-centric tools.
- **A rebuild recipe plus kept artifacts per unit of work.** This brings research-compendium and DVC ideas into agentic work; none of the agent methodologies do it.
- **An append-only journal distinct from the mutable plan and memento.** This keeps the lab-notebook discipline that ExecPlans approximate in a single file.
- **Ownership as a first-class, recorded state machine** (human ⇄ runner) at step boundaries. It is closer to nuclear job turnover than to any software tool.
- **Methodology and tool together, local-first:** plain directories, no server-side state. Most competitors are either a methodology (Ralph, 12-Factor, BMAD) or a hosted tool (Linear, Jira, Mission Control).

### Suggested citations for the methodology doc
Anthropic 2025-11 and 2026-03; Huntley 2025-07; 12-Factor Agents; OpenAI ExecPlans; Amp 2025-10 and 2026-05 (as the counterpoint); Chroma Context Rot; Min et al. 2026; Linear AIG Principle 06; the DOE/EPRI work-package guidance; Marwick et al. 2018.
