# Prior art: front-ends for on-prem / non-cloud technical workflows with agents in the loop

Survey date: 2026-10-26. Angle: what exists for "agents + people + long-running tools sharing a durable unit of work, on the user's own hosts", especially for silicon DV.

Source marking:
- **[P]** primary source (vendor docs, press release, vendor page, paper)
- **[S]** secondary source (trade press, review site, blog, aggregator). Treat numbers and dates from [S] as unverified.
- **[S?]** a claim that came only from a search-engine summary or a low-quality aggregator and that I could not confirm on a page I read.

---

## 0. Bottom line

- **Nobody has a "packet".** That means a plain, portable directory that holds the instruction, plan, notes, an append-only journal, a recipe to rebuild the workspace, worktrees and kept derived artifacts, and that agents, people and batch tools all share. What exists today falls into three groups:
  1. **Session/chat-centric agent platforms that run on your hosts** (Coder Agents/Tasks, OpenHands Enterprise, Claude Code self-hosted runners, Ona, Tabnine, Devin Desktop self-hosted, Mistral Vibe, IBM Bob self-hosted). The unit of work is a chat or session plus an ephemeral workspace, and it usually ends in a PR. State lives in the vendor's DB, not in a folder you own.
  2. **Vendor-locked EDA agent stacks** (Cadence ChipStack/JedAI/AgentStack, Synopsys AgentEngineer/Autopilot, Siemens Questa One Agentic Toolkit/Fuse EDA AI Agent) and **DV-agent startups** (ChipAgents, Bronco, Cognichip, Silimate). They focus on autonomy inside a tool flow. On-prem model hosting is now standard. Hand-off goes to Jira or Slack, not to a shared work object.
  3. **Durable-unit predecessors without agents, or with agents only as add-ons**: regression managers (vManager/Verisium Manager, VC Execution Manager/Verdi VMS, Questa VRM/Regression Navigator), reproducible capsules (Code Ocean, Whole Tale), shareable debug sessions (Pernosco), ELNs (Benchling). These have the right "object" shape but are not general and not agent-native.
- **HPC portals** (Open OnDemand, JupyterHub) have not added any task/packet concept. Sites just make agent CLIs available inside VS Code in OnDemand and point them at site-hosted LLM endpoints.

---

## 1. HPC / on-prem portals and dev environments

### Open OnDemand
- A web portal for files, job submission, interactive apps (Jupyter, RStudio, VS Code/code-server) and a shell. Releases 4.0 (Apr 2026) and 4.2 (Jul 2026) show no agent or task features [S?: search summary; https://discourse.openondemand.org/t/open-ondemand-4-1-release/4750].
- **How sites actually use agents:** Utah CHPC offers OpenCode, Codex, Claude Code and Gemini CLI as modules. Claude Code is used "through VS Code in Open OnDemand". The site LLM is Qwen. Policies: agents only in the General Environment, never in the Protected Environment. Autonomous agents such as OpenClaw are banned. Users must approve every command [P: https://www.chpc.utah.edu/documentation/software/codingagents.php].
- Virginia Tech ARC runs an OpenAI-compatible endpoint (DeepSeek-V4.1-Flash, GLM-5.3, gpt-oss-120b). It documents Claude Code SSHing to the login node to run Slurm, and warns: "Be very careful letting AI agents run commands on their own" [P: https://www.docs.arc.vt.edu/ai/040_coding_agents.html].
- **Takeaway:** OOD is the closest on-prem "front door" to compute, and agents are simply bolted into its IDE app. It has no durable unit, no board, and no hand-off. The site policies (approve each command, no autonomous agents in protected zones) show that oversight and audit matter on-prem.

### JupyterHub / Jupyter AI
- Jupyter AI v3.0 (by 2026-03-31) dropped its own agent ("Jupyternaut") in favour of hosting frontier agents (Claude, Codex, Gemini, Goose, Kiro, OpenCode) as named "personas" through the Agent Client Protocol (ACP) inside JupyterLab chat [P: https://github.com/jupyterlab/jupyter-ai/issues/1531; S: https://thenewstack.io/jupyter-ai-v3-could-it-generate-an-ecosystem-of-ai-personas/].
- The unit is still a notebook or chat. It has no task lifecycle. Notable as an **ACP-based multi-agent host** in a self-hostable server.

### Coder (self-hosted CDEs)
- **Coder Tasks** (launched about Dec 2025) is a sidebar "Tasks" view. You pick a workspace template, give a prompt, and an agent (Claude Code, Aider, ...) runs in its own Coder workspace. The UI tracks status and lets you download logs. A task-detail page shows the chat, workspace status and build logs, and you can open the workspace in an IDE to "take a task to completion". AgentAPI is Coder's open-source status/chat shim for any CLI agent [P: https://coder.com/docs/ai-coder/tasks; https://coder.com/blog/launch-dec-2025-coder-tasks].
- **Coder Agents** (GA May 2026) runs the agent loop itself on self-hosted infrastructure, air-gap capable and model-agnostic. Chat state is stored in the Coder DB, not the workspace, so a chat survives a workspace being stopped or deleted. Follow-ups are queued. "Nearly 70% of Coder Agents workloads were invoked through the API" in beta. Aimed at "regulated enterprises and government" [P: https://coder.com/blog/coder-agents-ga; P: https://www.globenewswire.com/news-release/2026/05/06/3288916/0/en/...; S: https://www.infoq.com/news/2026/05/coder-agents-self-hosted-ai/].
- **Closest generic overlap with work-packet** on "task + workspace + IDE drop-in, on your hosts". Differences:
  - The workspace is ephemeral and built from a template. The task's memory is the chat in Coder's DB.
  - There is no journal, plan or notes artifact that you own.
  - No kanban or "needs you" view is documented.
  - No hand-off to a colleague and no bug-bundle export.
  - It needs Kubernetes or Terraform platform ops, not a per-user daemon.

### Gitpod → Ona (→ OpenAI)
- Gitpod rebranded to Ona in Sep 2025 as "the platform for background agents". Environments are defined by devcontainer.json plus automations.yml, and agents can be triggered by PRs, schedules, webhooks or issues. Enterprise has self-hosted runners in your VPC [S: https://www.theregister.com/2025/09/03/gitpod_rebrands_as_ona/; P: https://ona.com/stories/migrating-from-classic-to-ona].
- OpenAI announced the acquisition of Ona on 2026-06-11 to give Codex persistent, long-running sandboxes. Reported close is 2026-08-10 [S: https://www.techtimes.com/articles/318338/...; S: https://bex.co/blog/2026/07/28/ona-openai-acquisition-self-hosted-agent-infra; close date S?].
- **Signal:** the self-hosted CDE was absorbed into a cloud agent vendor, so independent on-prem CDE options are shrinking.

### Daytona
- Pivoted in 2025 from dev environments to agent sandboxes. On-prem runs as "custom regions" on your Kubernetes, but the control plane stays with Daytona. Reportedly went closed-source in Jun 2026, so a fully self-hosted control plane is no longer possible [S: https://northflank.com/blog/best-on-premises-ai-sandbox-platforms].
- It is a sandbox primitive, not a front-end.

### code-server / openvscode-server, NICE/Amazon DCV
- Nothing agent- or task-specific found. These are delivery mechanisms: OOD and Coder embed code-server.

### HPC schedulers / portals: LSF, Altair, Run:ai
- **Altair HPCWorks 2026** (now Siemens) markets "agentic HPC": AI memory-resource prediction at job submission and Jupyter integration [P: https://news.siemens.com/en-us/altair-hpcworks-2026/].
- **NVIDIA Run:ai Agent** (NeMo Agent toolkit) is a conversational front-end for GPU provisioning, job submission and failure diagnosis. Run:ai supports self-hosted and air-gapped installs [P: https://run-ai-docs.nvidia.com/self-hosted/2.25/resources/blogs/nvidia-run-ai-agent-simplifies-gpu-provisioning-job-management-and-troubleshooting].
- **IBM LSF:** no agentic assistant found. IBM's agent push is IBM Bob (see section 3).
- **Takeaway:** scheduler vendors add natural-language job control. None model the job as one step inside a longer unit of human work.

---

## 2. EDA-specific agent and workflow products (2025-2026)

### Cadence
- **ChipStack acquisition:** a Seattle AI2-incubator startup with 20 people that raised more than $7M. The deal completed Nov 2025 [P: https://community.cadence.com/cadence_blogs_8/b/corporate-news/posts/cadence-welcomes-chipstack; S: https://www.geekwire.com/2025/...].
- **ChipStack AI Super Agent** (announced 2026-02-10, early access):
  - Covers design and testbench coding, test-plan creation, **regression orchestration**, debugging and auto-fix. Claims "up to 10X" productivity.
  - Works with Xcelium, Jasper and Verisium.
  - Supports cloud or on-prem deployment, with NVIDIA Nemotron/NeMo or OpenAI GPT models.
  - Early users: Altera, NVIDIA, Qualcomm, Tenstorrent.
  - [S: https://www.engineering.com/cadence-launches-chipstack-ai-super-agent-for-chip-verification/; S: https://siliconangle.com/2026/02/10/...; S: https://www.eetimes.com/cadence-unveils-chipstack-ai-agent-for-agentic-chip-design-and-verification/]
- **JedAI** is the data and AI layer: routing, security, embeddings, and private on-prem models. **AgentStack** (Cadence LIVE 2026) orchestrates multiple Super Agents. Jensen Huang said NVIDIA engineers work with Cadence "virtual engineers" **in Slack channels** [S: https://moorinsightsstrategy.com/research-notes/cadence-leans-into-eda-super-agents-at-cadence-live-2026/].
- A "fully autonomous virtual engineer" powered by NVIDIA was announced 2026-05-31 (BusinessWire, 403 on fetch, so details unread) [P, title only: https://www.businesswire.com/news/home/20260531072918/en/...].
- **Verisium Manager / vManager:**
  - Covers verification planning, job scheduling and multi-engine coverage on JedAI.
  - **Verisium AutoTriage** clusters failures by common root cause. It learns from engineers' manual failure-to-cluster assignments and predicts the cluster for future failures.
  - Claims up to 70% less debug time. There is a Jenkins plugin.
  - [P: https://community.cadence.com/cadence_blogs_8/b/fv/posts/automate-regression-failure-triage-with-the-cadence-verisium; P: https://www.jenkins.io/doc/pipeline/steps/vmanager-plugin/]

### Synopsys
- **Synopsys.ai Copilot:** air-gapped on-prem deployment on NVIDIA DGX was announced in 2024, with GA in 2025. "Bring their own LLMs and data and infrastructure" [P: https://news.synopsys.com/2024-03-18-...; P: https://investor.synopsys.com/news/news-details/2025/Synopsys-Announces-Expanding-AI-Capabilities-for-its-Leading-EDA-Solutions/default.aspx].
- **AgentEngineer + Autopilot Platform** (2026-09-28):
  - "Long-horizon agents" in six domains: verification, system validation, implementation, AMS, manufacturing, and simulation/analysis.
  - The platform provides "orchestration, skills, memory, telemetry, and governance".
  - Deployable on Synopsys Cloud, customer cloud or on-prem. Supports third-party agents in the same workflow.
  - Claims "significantly lower token cost/count".
  - More than 50 engagements, GA planned for end of 2026. Claims up to 50x faster verification closure.
  - Human approval checkpoints are retained [S: Tom's Hardware].
  - [P: https://news.synopsys.com/2026-09-28-Synopsys-Powers-Autonomous-Engineering-with-a-Broad-Portfolio-of-Long-Horizon-Agents-and-Autopilot-Platform; S: https://www.tomshardware.com/tech-industry/semiconductors/synopsys-debuts-autopilot-platform-...]
  - No details are public on workspaces, hand-off or dashboards. "Persistent memory" is the only durability claim.
- **VC Execution Manager / Verdi VMS / Verdi Regression Debug Automation (RDA) / VSO.ai:** regression execution and management, AI-assisted regression debug, and coverage-convergence optimization [P: https://www.synopsys.com/verification/soc-verification-automation/vc-execution-manager.html; P: https://www.synopsys.com/verification/debug/verdi.html].
- Community signal: a "Codex-ready skill for Synopsys VCS and Verdi workflows" on GitHub. Users are wiring generic agents to EDA tools themselves [P: https://github.com/Eriemon/vcs-verdi-developer].

### Siemens EDA
- **Questa One Agentic Toolkit** (early access 2026-03-02):
  - Agents: RTL Code, Lint, CDC, Verification Planning, and Debug. The Debug agent correlates waveforms, assertions, coverage and logs.
  - Tools are exposed via **MCP** through a governed "Gateway" ("Any LLM, any coding agent").
  - Works with mainstream coding agents in CLI or VS Code.
  - [P: https://www.siemens.com/en-us/products/ic/questa-one/agentic-toolkit/; S: https://www.digitalengineering247.com/article/siemens-debuts-agentic-ai-in-questa-one]
- **Fuse EDA AI Agent:**
  - Orchestrates Catapult, Questa, Aprisa, Solido, Veloce and Calibre.
  - Deployment is either **fully air-gapped on-prem with local GPUs** or hybrid (data on-site, LLM in Azure/AWS/GCP).
  - Has RBAC and audit trails "designed for air-gapped environments". Uses MCP for third-party tools.
  - A "long-running workflow orchestrating nine stages across seven multi-physics EDA tools".
  - [P: https://www.siemens.com/en-us/products/fuse-eda-ai-system/agent/]
- **Questa VRM + Questa One Verification IQ Regression Navigator:**
  - Rule-based and ML failure bucketing.
  - "Collaborative launching of regressions and ... analyze results across multiple regressions, from multiple users, across multiple projects".
  - Per-test results analysis decides what goes into a **triage database**.
  - [P: https://www.siemens.com/en-us/products/ic/questa-one/verification-iq/regression-navigator/; P: https://ww1.microchip.com/downloads/aemDocuments/documents/FPGA/swdocs/questasim/vrm_user_2024_2.pdf]
- **Important for work-packet:** Siemens' "bring your coding agent; we expose tools via MCP" stance fits naturally under a packet front-end. Questa One tools could be what an agent inside a packet calls.

### Regression managers as prior art for "a packet per failing test"
- Infineon, *What I Wish My Regression Run Manager's Vendor Knew!* (DVCon), describes moving from Questa VRM to vManager. They built an in-house **VMS** to get a vendor-agnostic "look and feel" of status and reporting. They note that "over-time (i.e. multi-session) regression tracking" and test planning are not handled, that vendor formats (RMDB XML+TCL vs VSIF) lock you in, and that "lacking a common setup across users and projects leads to a loss in efficiency" [P: https://dvcon-proceedings.org/wp-content/uploads/1109-What-I-Wish-My-Regression-Run-Managers-Vendor-Knew.pdf].
- What these tools have:
  - Failure clusters as first-class objects, with ML auto-assignment of clusters to owners (Verisium AutoTriage).
  - Triage DBs and cross-user, cross-project views.
- What they lack:
  - A per-failure *workspace* (rebuildable environment, notes, journal, kept waves).
  - A link to the code fix.
  - Any agent turn-taking.
- The **cluster is the right granularity for a packet**. Today it is a DB row, not a place you work in.

### DV-agent startups
- **ChipAgents:**
  - Describes itself as an "orchestration layer above the traditional EDA stack", connecting to simulators, formal engines, repos and **issue systems**.
  - Root-cause investigations cut "from days to 15–60 minutes" (Whalechip). More than 120 semiconductor customers and 6x ARR in H1 2026. Series A expanded to $134M (Jul 2026). SOC 2 Type II (Jun 2026).
  - [P: https://chipagents.ai/newsroom; S: https://semiwiki.com/eda/chipagents-ai/372067-chipagent-raises-130-million-and-why-it-matters/]
  - **Renoir** is a domain LLM fine-tuned from an open-weight MoE that "can run entirely on-premises ... without accessing external APIs, saving latency and per-token billing". Cost is reportedly about 22% of a frontier model [S: https://semiengineering.com/introducing-an-agentic-llm-for-chip-design/].
  - Self-hosting in the customer's AWS account or an on-prem GPU cluster is reported [S?].
- **Bronco AI:**
  - A debug agent that takes an overnight regression to an annotated root cause, "triage[s] ... down to decently confident localizations, and hand[s] off tickets to the appropriate teams".
  - Integrates **on-prem** with Jira and run managers.
  - Builds "reusable debug playbooks" by learning from past failures, tickets and human feedback. The vendor says it stores the "thinking layer" (methodology), not design data.
  - 70% first-pass end-to-end debug success presented at DAC 2026. Under 15 minutes per full-chip SoC debug.
  - [S: https://semiwiki.com/eda/bronco-ai/365567-verification-futures-with-bronco-ai-agents-for-dv-debug/; S: https://semiwiki.com/eda/bronco-ai/361877-scaling-debug-wisdom/; S: https://semiwiki.com/eda/bronco-ai/368908-...]
  - **The nearest DV-specific analogue of "packet per failing test"**, but the output is a ticket, not a resumable workspace.
- **Cognichip:** "Artificial Chip Intelligence" foundation model. Raised $60M in Apr 2026 ($93M total). Offers secure on-prem deployments for fine-tuning [S: https://techcrunch.com/2026/04/01/cognichip-...; S: https://siliconangle.com/2026/04/01/...].
- **Silimate:** a copilot customers can self-host so "everything can be kept on-prem" [S: https://tracxn.com/d/companies/silimate/...; P: https://www.silimate.com/].
- **Normal Computing:** listed as a competitor in the space. No product detail gathered.

### What the EDA offerings do and don't do about the four questions
- **On-prem:** universal. Every vendor offers on-prem or air-gapped model hosting (Synopsys DGX air-gap, Siemens local-GPU air-gap, Cadence private models in JedAI, ChipAgents Renoir, Cognichip, Silimate).
- **Persistence:**
  - "Memory", "playbooks" and "skills" are kept by the vendor platform (Synopsys Autopilot memory, Bronco playbooks).
  - Nobody exposes a user-owned, inspectable, append-only record of a unit of work.
- **Cost:**
  - Synopsys pitches "lower token cost/count". ChipAgents pitches avoiding per-token billing with a local model.
  - Nobody surfaces per-task cost to the engineer.
- **Hand-off between engineers:**
  - Via Jira tickets (Bronco, ChipAgents "issue systems") or Slack channels (Cadence/NVIDIA).
  - No shared work object you pass to a colleague with its environment intact.

---

## 3. Self-hosted / air-gapped agent deployments (general software)

| Product | On-prem story | Beyond chat/IDE? |
|---|---|---|
| **Claude Code self-hosted environments** (public beta, Aug 2026) | A runner on your hosts executes cloud sessions. The checkout, artifacts and secrets stay local. The **control plane, queue, transcript and UI remain on claude.ai**, and the conversation always goes to api.anthropic.com. Inference can be routed to Bedrock or Vertex, but the session content still flows to Anthropic. Not available with ZDR or HIPAA orgs. A runner locks to one owner [P: https://code.claude.com/docs/en/self-hosted-environments] | Sessions plus a picker, like CI runners. No user-owned work unit. The **Claude apps gateway** (Jun 2026) is a self-hosted SSO and credential control plane in front of Bedrock, Vertex or Foundry [S: https://chatforest.com/builders-log/claude-apps-gateway-...] |
| **OpenHands Enterprise** | Helm on your Kubernetes or VPC. v1.6 (Mar 2026) added K8s, RBAC, audit logs and data residency [P: https://docs.openhands.dev/enterprise/architecture; S: https://theaiagentindex.com/blog/openhands-review-2026] | **Conversation sharing**, an "Agent Control Plane" for concurrent agents, budgets, Slack and Jira. The unit is a conversation. |
| **Coder Agents / Tasks** | Fully self-hosted, air-gapped | Task list, logs, IDE drop-in (see section 1) |
| **Tabnine** (acquired by Tricentis Jul 2026 [S]) | On-prem K8s or fully air-gapped, "does not call home" [S: https://intuitionlabs.ai/articles/enterprise-ai-code-assistants-air-gapped-environments] | Enterprise Context Engine as a standalone context layer for any agent (Feb 2026) [P: https://www.globenewswire.com/news-release/2026/02/26/3245668/...]. CLI agent, MCP to Jira and CI. No task object. |
| **Sourcegraph** | Self-hosted 8.0 brings **Agentic Batch Changes** on-prem (Sep 2026). 8.1 queues workspaces while the agent is busy [P: https://sourcegraph.com/blog/agentic-batch-changes-public-beta; P: https://sourcegraph.com/changelog/releases/8.0.0] | A *batch change* is a durable, reviewable, multi-repo unit of work. It is the nearest "durable task object" in this category, but it is scoped to code changes. |
| **Devin Desktop (ex-Windsurf)** | Enterprise Cloud, Hybrid or Self-Hosted, GovCloud VPC, self-hosted inference for HIPAA, FedRAMP and CMMC [S: https://www.layer3labs.io/guides/windsurf-for-business; S: https://apidog.com/blog/whats-new-in-devin-2026/] | IDE plus the Devin agent. Hand-off is through Devin sessions. |
| **Mistral Vibe** (Le Chat renamed Aug 2026) | On-prem with open Devstral 2 weights. Mistral claims to be the only major assistant offered on-prem [S: https://www.datacamp.com/blog/mistral-vibe-2-0; S: https://colombani.ai/en/blog/mistral-for-business/] | Terminal agent plus remote agents (remote agents run in Mistral's cloud) |
| **Continue** | OSS, local models. Shareable "agents" defined as prompts, rules and tools, plus source-controlled AI checks [S: https://www.digitalapplied.com/blog/continue-dev-deep-dive-...] | Agents-as-config, not work units |
| **Mission Control** (Builderz Labs, OSS MIT) | Self-hosted, SQLite, Docker | **A web dashboard that dispatches tasks to Claude Code, Codex and OpenClaw, reviews runs and tracks spend**. Has REST, MCP and SSE interfaces [P: https://github.com/builderz-labs/mission-control/releases; P: https://mc.builderz.dev/]. It is the closest OSS "board over local agents", but it is agent-fleet-centric with no workspace recipe or journal. |
| **IBM Bob self-hosted** (2026-10-01) | On-prem, private cloud, sovereign or air-gapped. Local or hybrid models [P: https://newsroom.ibm.com/2026-10-01-ibm-introduces-self-hosted-deployment-for-ibm-bob-...] | Multi-agent modernization workflows and built-in cost/use analytics (Jul 2026) [P: https://newsroom.ibm.com/2026-07-09-...] |

**Pattern:** "self-hosted" usually means *execution* or *inference* on-prem, while the control plane and work record often stay with the vendor (Claude Code runners, Daytona). Where everything is on-prem (Coder, OpenHands, Tabnine, Bob), the durable unit is a chat or conversation in a server DB. Sourcegraph batch changes and Coder Tasks are the only ones with a first-class *task object*, and neither is a user-owned directory.

---

## 4. "Task container" front-ends and reproducible units

- **Code Ocean compute capsules:**
  - A capsule bundles code, data, environment and instructions into a one-click reproducible unit.
  - The Aqua AI assistant (Bedrock) gained tools in Release 4.3 (Feb 2026) to create and duplicate capsules, manage environments, do git operations and more.
  - "Code Ocean Agents / Trusted Agents" (v4) frames capsules as provenance for agent science.
  - Deploys into the customer's cloud or VPC. No on-prem (non-cloud) story found.
  - [P: https://docs.codeocean.com/user-guide/release-notes/release-notes/release-notes-4.3-february-2026; P: https://codeocean.com/; blog 403]
  - The **closest conceptual match to "packet = rebuildable workspace + kept artifacts"**, in research rather than engineering. It is cloud-hosted and not built around turn-taking.
- **Whole Tale:**
  - An NSF DIBBS project (2016 to about 2023).
  - A "tale" is data references, code, environment and *narrative*, in a standards-based package.
  - Seems dormant after its funding ended.
  - [P: https://wholetale.readthedocs.io/en/stable/README.html; P: https://wholetale.org/]
  - Its "narrative" is the analogue of notes and journal.
- **Pernosco:**
  - Record-and-replay debug sessions that are **shareable by URL**, with a notebook that is "continuously synchronized" so "information gathered by one developer can be recorded in the notebook to help another developer carry on the analysis".
  - Cloud-hosted. A community MCP server exists.
  - [P: https://pernos.co/about/overview/; P: https://pernos.co/about/notebook/; P: https://pernos.co/privacy/; S: https://glama.ai/mcp/servers/jnjaeschke/pernosco-mcp]
  - The best prior art for the **bug-report bundle / hand-off** idea: the recipient gets a reproducer and the investigator's annotations.
- **Benchling (ELN):** "Benchling AI, rebuilt inside the notebook". A single agent works in a notebook entry: it pulls related historical experiments, runs code and drafts entries with citations [P: https://www.benchling.com/blog/the-eln-is-dead-long-live-the-eln]. This is "notebook entry as the unit of work, with the agent inside it". Same shape as a packet, in a different domain, and SaaS.
- **Research:**
  - *From Trajectories to Evidence: Auditable Experimental Records for Industrial Research Agents* (arXiv 2608.05235, Aug 2026). It argues for turning agent trajectories into auditable records with explicit provenance [P: https://arxiv.org/abs/2608.05235]. This is academic support for the journal plus kept-artifacts design.
  - *The Dawn of Agentic EDA* survey [P: https://arxiv.org/abs/2512.23189] (not read in depth).

---

## 5. Evidence on who needs on-prem agentic workflows

- **Semiconductor IP:**
  - Niels Faché (Keysight): "Semiconductor design and development will continue to occur on-premises rather than in public cloud environments ... the industry's IP protection requirements will keep sensitive design work within company-controlled infrastructure" [P, vendor op-ed: https://semiengineering.com/how-the-eda-industry-will-evolve-in-2026/].
  - HTEC's 2025-26 semiconductor AI report blames slow enterprise-scale AI on "integration challenges across EDA toolchains ... IP-sensitive environments" [S: https://htec.com/insights/reports/executive-summary-the-state-of-ai-in-the-semiconductor-industry-in-2025-2026/].
  - All three big EDA vendors and every DV startup lead with on-prem or air-gapped deployment (section 2), which itself shows the demand.
  - The ChipAgents Renoir pitch is explicit that "many chip companies cannot send proprietary designs and logs to a public AI service" [S].
- **Regulated / government:**
  - Coder Agents targets "regulated enterprises and government organizations ... air-gapped" [P].
  - Devin Desktop offers self-hosted inference for HIPAA, FedRAMP and CMMC [S].
  - IBM Bob self-hosted targets financial services, telecom and healthcare [P].
- **Survey numbers:**
  - IBM IBV *Calculus of AI Sovereignty* (Jun 2026): 68% of executives say meeting data residency and sovereignty requirements is challenging [P via IBM newsroom].
  - Futurum: hybrid and edge will be 44% of the AI infrastructure market by 2030 [P via IBM newsroom].
  - Deloitte 2026: only 21% report mature agentic-AI governance, versus 74% expecting at least moderate agentic use within two years [S?].
- **Defense / export control:**
  - ITAR treats technical data sent to cloud AI with international operations as an export risk. CMMC L2+ CUI handling often pushes toward air-gapped AI [S: https://vso-inc.com/how-to-use-ai-without-breaking-cmmc-compliance-...; S: https://iternal.ai/ai-for-defense-aerospace].
  - CMMC third-party certification was suspended on 2026-07-13 pending review [S?]. That eases certification but not the CUI handling rules.
- **Academic HPC:** Utah CHPC bans external AI tools in its Protected Environment and bans autonomous agents. VT ARC hosts its own LLMs [P]. The same pattern holds on-prem: local models, human approval of commands, agents confined to the IDE.

---

## 6. Gaps: what none of them do (the space work-packet occupies)

1. **A user-owned, plain-directory unit of work** that holds the instruction, plan, notes, append-only journal, workspace recipe, worktrees and kept derived artifacts. Every competitor keeps the record in a server DB (Coder, OpenHands, Claude Code transcripts on Anthropic, vendor "memory" in Synopsys or Bronco) or in a cloud capsule (Code Ocean).
2. **Turn-taking between agents, people and long-running non-agent tools** (simulators, dv-flow-mgr, SLURM/LSF jobs) as peers on the same unit. EDA agents orchestrate tools internally. Regression managers run tools but have no agent or human turn model.
3. **A per-user daemon on the user's own hosts** with no platform team. Coder, OpenHands, Run:ai and Daytona all need Kubernetes or Terraform ops. Claude Code runners need the Anthropic control plane.
4. **A board with a "needs you" column across agents and batch jobs.** Coder Tasks has a status list and Mission Control has a dispatch dashboard. Neither treats "waiting on a human" as a lane, and neither spans tool jobs.
5. **Hand-off of a live unit to a colleague, or export as a bug bundle, with the environment rebuildable.** The closest are Pernosco's shared session plus notebook (debug only, cloud) and OpenHands conversation sharing (chat only). EDA hand-off goes through Jira or Slack.
6. **Packet per failure cluster.** Verisium AutoTriage, Regression Navigator and Bronco produce clusters or tickets, not a workspace someone or something resumes.
7. **Vendor neutrality across EDA.** Each EDA agent stack is tied to its vendor's tools (Infineon's DVCon paper shows lock-in pain even at the run-manager level). Siemens' MCP Gateway and Synopsys' "third-party agents" are openings to sit *above* them.
