# Industry survey: how work-packet compares (October 2026)

This survey backs the Industry section of `slides/work-packet-overview.pptx`. The deck's data is in `slides/industry.js`.

The survey used about 20 web searches and three primary-source fetches: the Claude Code scheduled-tasks docs, the Claude Code Projects docs and the CovAgent paper. Items marked *(secondary)* come from third-party reviews. Check those against vendor docs before quoting them externally.

**Finding:** none of the tools surveyed makes a task-local, file-based "packet" the center of persistence. None ties per-step token metrics to how the next step runs. The nearest overlaps are:

- Claude Code Projects (2026 beta);
- Manus's principle of the file system as context;
- OpenHands' on-disk event log;
- the EDA vendors' agent suites.

## Tool by tool

### Coding agents

**Claude Code: scheduled tasks (formerly routines), Projects, OpenTelemetry**
- **Scheduled tasks** run a saved prompt with repos and connectors. They fire on cron (at most hourly), on an HTTP `/fire` call or on GitHub events. They are limited to 100 runs an hour. A green status "does not mean the work your prompt describes succeeded".
- **Projects** are one long conversation that starts parallel cloud threads, up to 200 threads a day. Each project has a `MEMORY.md` index, instructions of up to 16k characters, and a file Library under `/mnt/project-files`. An Overview pane shows Waiting on you, PRs and Scheduled tasks.
- **Persistence:** git-centric. Each run clones the repos and pushes a `claude/` branch or a PR.
- **Cost:** OpenTelemetry metrics `claude_code.cost.usage` and `claude_code.token.usage` (input, output, cacheRead, cacheCreation). They only report; nothing adapts to them.
- **Versus work-packet:** this is the closest product. It still re-clones for every run and keeps no derived artifacts. work-packet already uses Claude Code as its harness.
- Sources: [routines](https://code.claude.com/docs/en/routines), [Projects](https://code.claude.com/docs/en/claude-projects.md), [SigNoz guide](https://signoz.io/docs/claude-code-monitoring/) *(secondary)*.

**OpenAI Codex cloud**
- Each task runs on its own managed VM, copied from a cloud environment. Reusable environments were announced at DevDay on 2026-09-29.
- Unpushed changes stay with the task, and dependency caches survive refreshes.
- Many tasks can run in parallel. I found no recurring scheduler (uncertain). Cost is visible only at the plan level.
- Sources: [TechCrunch](https://techcrunch.com/2026/09/29/openai-gives-codex-reusable-cloud-environments-that-work-across-devices/), [agent37](https://www.agent37.com/blog/codex-cloud) *(secondary)*.

**GitHub Copilot coding agent**
- You assign it an issue. It works in an Actions runner and opens a draft PR.
- Each session costs one premium request plus Actions minutes. The user sees no tokens.
- There are no recurring tasks unless you write your own Actions cron.
- Sources: [blog](https://github.blog/news-insights/product-news/github-copilot-meet-the-new-coding-agent/), [changelog](https://github.blog/changelog/2025-07-10-github-copilot-coding-agent-now-uses-one-premium-request-per-session/).

**Devin**
- Runs in a hosted VM, with Knowledge (retrieved notes) and Playbooks (reusable procedures).
- Automations, which replace the older Scheduled Sessions, run on cron or on events.
- Each session has an ACU cap, which works as a ceiling. Nothing adapts to cost.
- Artifacts do not persist across sessions.
- Sources: [advanced capabilities](https://docs.devin.ai/work-with-devin/advanced-capabilities), [scheduled sessions](https://docs.devin.ai/product-guides/scheduled-sessions).

**Cursor Cloud Agents (formerly Background Agents)**
- Run in isolated VMs, work on a branch and open a PR.
- Since 2026-08-19 they can be triggered by events, including cron. An Environments API is in beta.
- Source: [morph](https://www.morphllm.com/cursor-background-agents) *(secondary)*.

**Google Jules**
- An asynchronous queue of tasks, each in its own VM, with scheduled tasks such as nightly lint and weekly audits, and a CI Fixer.
- Billed by task count, not tokens.
- Sources: [blog](https://blog.google/innovation-and-ai/models-and-research/google-labs/jules/), [review](https://www.digitalapplied.com/blog/google-jules-gemini-async-coding-agent-guide) *(secondary)*.

**Amp**
- Shared team threads stored on the server, pay-as-you-go pricing and routing across several models.
- No task packets, no scheduler and no adaptation.
- Source: [rywalker](https://rywalker.com/research/amp-sourcegraph) *(secondary)*.

**Factory Droids and Missions**
- Missions coordinate many workers over hours or days against features and milestones.
- It is hosted SaaS centered on the repo. It publishes no adaptation to token use (uncertain).
- Sources: [Factory](https://factory.com/news/software-factory), [Sid Bharath](https://sidbharath.com/blog/factory-ai-guide/) *(secondary)*.

**Aider**
- The git repo is the state: Aider commits automatically and keeps `.aider.chat.history.md`.
- `/tokens` shows usage. Chat history is summarized once it passes `--max-chat-history-tokens`.
- One session at a time.
- Source: [docs](https://aider.chat/docs/usage/commands.html).

**claude-task-master**
- Turns a PRD into a dependency graph in `tasks.json`, committed in the repo and served over MCP.
- It tracks tasks but does not execute them, and has no metrics.
- Source: [repo](https://github.com/eyaltoledano/claude-task-master).

**Vibe Kanban, Conductor, Claude Squad**
- Run parallel CLI agents in git worktrees, with a kanban board or tmux UI.
- No recurring tasks, token analytics or artifact management.
- Source: [augment roundup](https://www.augmentcode.com/tools/open-source-agent-orchestrators) *(secondary)*.

### Frameworks and research agents

**OpenHands SDK**
- Event-sourced on disk: `base_state.json` plus an append-only directory of JSON event files.
- Tracks cost per conversation and has a `max_budget_per_run` cap.
- Its unit is a conversation, not a task, and it has no runner for multiple projects.
- Of the frameworks, this is the closest in spirit to work-packet.
- Sources: [docs](https://docs.openhands.dev/sdk/guides/convo-persistence), [paper](https://arxiv.org/html/2511.03690v1).

**SWE-agent**
- Writes a `.traj` trajectory file for each instance.
- `per_instance_cost_limit` (default $3) is a hard cutoff.
- Batch-oriented, with no state between runs.
- Source: [docs](https://swe-agent.com/latest/usage/batch_mode/).

**LangGraph**
- Saves a checkpoint at every superstep, keyed by `thread_id`, in memory, SQLite or Postgres. Costs are reported through LangSmith.
- This is durable agent state, not durable engineering artifacts.
- Source: [fast.io](https://fast.io/resources/langgraph-persistence/) *(secondary)*.

**CrewAI**
- The `@persist` decorator saves state to SQLite, with a checkpoint for each task and replay from any of them.
- There is no ops dashboard for many projects.
- Source: [docs](https://docs.crewai.com/en/guides/flows/mastering-flow-state).

**AutoGen and Microsoft Agent Framework**
- AutoGen is in maintenance mode. Agent Framework 1.0 shipped in April 2026 *(secondary)*.
- State is kept as `save_state()` / `load_state()` snapshots that the user stores.

### Durable execution and observability

**Temporal**
- With the OpenAI Agents SDK integration, each LLM call runs as an Activity that is retried and replayed.
- It has first-class Schedules.
- It is generic: it holds no opinion about artifacts or token use.
- Source: [Temporal](https://temporal.io/blog/announcing-openai-agents-sdk-integration).

**LangSmith, Langfuse, Helicone, AgentOps**
- Traces, cost attribution and replay.
- They **observe** cost; nothing they report changes how the next step runs.
- Source: [latitude comparison](https://latitude.so/blog/best-ai-agent-observability-tools-2026-comparison) *(secondary)*.

### EDA and silicon

**Vendor agents**
- **Cadence ChipStack AI Super Agent:** goes from spec to RTL, testbenches and test plans. It orchestrates regressions and debugs and fixes failures. Cadence claimed "Level 5 autonomy" in June 2026.
- **Synopsys AgentEngineer:** specialized agents for RTL and verification *(secondary)*.
- **Siemens Questa One Agentic Toolkit:** five agents (RTL code, lint, CDC, verification planning, debug) that plug into Claude Code, Cursor and Fuse.
- **ChipAgents:** Series A extended to $134M (July 2026), with 120+ deployments.
- None of them discloses how it persists state.
- Sources: [AllAboutCircuits](https://www.allaboutcircuits.com/news/cadence-unwraps-agentic-ai-super-agent-for-chip-design-and-verification/), [Tom's Hardware](https://www.tomshardware.com/tech-industry/semiconductors/the-state-of-agentic-ai-in-chip-design-tools-in-2026-cadence-synopsys-and-siemens-all-pitch-autonomous-engineers), [BusinessWire](https://www.businesswire.com/news/home/20260729819576/en/ChipAgents-Expands-Series-A-Funding-to-$134-Million-as-Demand-Grows-for-Agentic-AI-in-Semiconductor-Design).

**Research**
- **CovAgent** ([arXiv 2604.15657](https://arxiv.org/html/2604.15657)): only 12–18% of tokens go to testbench code. Structured tools, curated coverage feedback and a state graph cut tokens 4–13×.
- **EDATracer** ([arXiv 2608.04032](https://arxiv.org/pdf/2608.04032), abstract only): 2–3× fewer tokens than Cursor when analyzing large EDA artifacts.
- **"Agentic EDA: A Handoff Perspective"** ([arXiv 2606.19795](https://arxiv.org/pdf/2606.19795)): not read.

### Context engineering

- **Anthropic, [effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents):** compaction, structured notes kept outside the context window, and sub-agents.
- **Manus, [context engineering lessons](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus):**
  - The KV-cache hit rate is "the single most important metric".
  - Input outweighs output about 100:1.
  - Keep prefixes stable and append-only.
  - Treat the file system as the ultimate context.
- **ACE** ([arXiv 2510.04618](https://arxiv.org/pdf/2510.04618)): contexts kept as incrementally merged playbooks.
- **"How do AI agents spend your money?"** ([arXiv 2604.22750](https://arxiv.org/html/2604.22750v3)): agentic tasks use about 1000× the tokens of code chat, and input dominates cost.

## Comparison matrix

| Tool | Persistence center | Many projects | Recurring | Token metrics / adaptation | Derived artifacts |
|---|---|---|---|---|---|
| **work-packet** | Task packet directory | Local registry + board | Built: resume in/at. Planned: `every:` | Per-step stats, advice, profiles | Kept in the packet |
| Claude Code scheduled / Projects | Branch/PR, cloud session, MEMORY.md + Library | Projects Overview (beta) | Cloud cron ≥1 h, API, GitHub | OTel, observe only | Re-cloned per run |
| Codex cloud | VM workspace, then PR | Parallel tasks | Not found | Plan level | Env/dependency cache |
| Copilot coding agent | PR branch | Per repo, via issues | Your own Actions cron | Opaque | Actions artifacts |
| Devin | Hosted VM, Knowledge, PR | Sessions, tags | Automations | ACU cap | Per session |
| Cursor Cloud Agents | Branch/PR, ephemeral VM | Many agents | Cron events | Usage billing | Per-task VM |
| Jules | Repo clone, PR | Task queue | Scheduled tasks | Task counts | Per-task VM |
| Amp | Server threads | Team workspace | No | Pass-through cost | None |
| Factory Missions | Platform, repo/PRs | Missions | Partial (?) | Not published | Not disclosed |
| OpenHands | On-disk event log | Conversation list | No | Cost + budget cap | Workspace per conversation |
| SWE-agent | Trajectory files | Batch | No | Per-instance cap | None |
| Aider | Git repo + chat file | No | No | /tokens | None |
| task-master | tasks.json in repo | Tags | No | No | None |
| Vibe Kanban / Conductor | Git worktree | Board | No | Minimal | None |
| LangGraph / CrewAI | Checkpoint DB | Threads / flows | Via platform | Via LangSmith | Not addressed |
| Temporal | Workflow history | Yes | Schedules | No | Not addressed |
| LangSmith / Langfuse / Helicone / AgentOps | Trace store | Dashboards | n/a | Rich, no feedback | n/a |
| EDA vendor agents | Vendor tool environment | Within the flow | Regressions (Cadence) | Not published | Closed |

## Gaps work-packet addresses

1. **Persist the task, not the repo.** Every mainstream agent ends a run as a branch or PR and re-clones the next time.
2. **Keep the expensive artifacts.** Elsewhere only dependency caches survive. In DV, compiled snapshots, regression results, coverage and waves cost more to regenerate than the LLM calls do.
3. **Close the cost loop.** Every product observes cost or caps it. None uses per-step metrics to size the next step. The research shows the gains can be large: 4–13× (CovAgent) and about 10× from caching (Manus).
4. **Local, recurring management work.** Scheduled agents are tied to the cloud and to GitHub, but EDA licences, simulators and IP are often on-prem.
5. **Board and statistics together.** Kanban orchestrators have no cost data. Observability tools have no idea of a project. task-master runs nothing.
6. **Context engineering as structure.** The packet layout builds in a stable prompt prefix, file-backed memory and an append-only journal.
7. **Neutral to the harness and portable.** A plain directory survives a change of harness or model and can be inspected. That suits IP-sensitive work.
