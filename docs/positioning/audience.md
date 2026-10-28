# Who should work-packet appeal to, and why: audience survey

Web research done 2026-10-26. Each claim is tagged by how reliable its source is:

- **[P]** primary: the original survey, the vendor's own announcement, or the paper itself.
- **[S]** secondary: a press article, blog, or summary quoting a primary source I did not read myself.
- **[W]** weak: SEO, marketing, or staffing blog content. Treat these as signals only.

## Scoring

Each segment gets a score from 1 to 5 on four axes:

- **Pain**: how much the segment hurts from the problems work-packet addresses.
- **Constraint fit**: how far the segment's limits favour a local-first, self-hosted, harness-neutral tool.
- **Reach**: whether we can get to these buyers at all.
- **WTP**: willingness to pay.

| # | Segment | Pain | Constraint fit | Reach | WTP | Overall |
|---|---------|------|----------------|-------|-----|---------|
| 1 | Semiconductor DV teams (incl. FPGA, system-company silicon teams) | 5 | 5 | 4 (founder is native; DVCon/DAC/Verification Academy) | 4 | **First** |
| 5 | Eng leads / platform teams (cost & visibility), *as a feature for 1 and 2* | 4 | 3 | 3 | 4 | Second (feature, not segment) |
| 4 | Power users of Claude Code/Codex running parallel long tasks | 4 | 2 | 5 | 2 | Third (adoption channel, not revenue) |
| 2 | Other IP-sensitive / regulated engineering (defense, auto, HPC, pharma) | 4 | 4 | 2 | 4 | Fourth (adjacent expansion; HPC/national labs nearest) |
| 3 | OSS maintainers / vendor support (repro bundles) | 3 | 3 | 3 | 1 (OSS) / 4 (EDA vendor support) | Wedge only within segment 1 (EDA customer to vendor) |

---

## 1. Semiconductor / EDA design-verification teams

### Pain: verification dominates, and debug dominates verification

- In the 2024 Wilson Research Group / Siemens study, only **14% of IC/ASIC projects reached first-silicon success**. That is the lowest figure in more than 20 years of tracking. **75% of projects were behind schedule**, against roughly 67% historically. [P] (Siemens report landing pages; numbers as quoted in the [S] sources)
  - https://resources.sw.siemens.com/en-US/white-paper-2024-wilson-research-group-ic-asic-functional-verification-trend-report/
  - https://semiengineering.com/first-time-silicon-success-plummets/ [S] Harry Foster: "What we're doing is not working. We need to significantly increase productivity... move away from siloed sets of tools to something that's much more connected and integrated." He adds that flows are "tool-centric, without accounting for the feedback loops."
- Verification engineers spend **47% of their time on debug**, which is the largest category of their time. [S] Sigasi, summarising WRG 2024: https://www.sigasi.com/news/verification-blog/
- On FPGA projects, **87% had at least one non-trivial bug escape** into production. [S] Same source.
- Siemens (Sept 2025) says **60–70% of chip engineering effort belongs in verification**. It singles out system companies (automotive OEMs, hyperscalers, consumer brands) for underestimating that effort and lacking the experience. ISO 26262 adds to the verification scope. [P] https://blogs.sw.siemens.com/verificationhorizons/2025/09/03/why-first-silicon-success-is-getting-harder-for-system-companies/
- Two weaker sources put verification at ">70% of total project effort" (Medium recap of DAC 2026) and Bronco AI at "60–70% of design cost". [W]

### Pain: there are not enough people

- Deloitte projects a need for more than 1M additional semiconductor workers by 2030. The SIA estimates the US needs about 115k more semiconductor jobs by 2030 and that more than half may go unfilled. [S] https://www.deloitte.com/us/en/industries/tmt/articles/2025-global-semiconductor-industry-outlook.html
- A staffing firm says UVM, formal, emulation and coverage-closure DV engineers are the scarcest roles, at about 3 openings per qualified candidate. [W] https://www.game7staffing.com/resources/blog/semiconductor-hiring-in-2026-the-tapeout-bottleneck

### Market heat in agentic DV, 2025–2026

- At DAC 2026, about 28% of the agenda was agentic AI. Synopsys showed an "autonomous DV agent", Cadence its AuraStack super-agent, and Siemens self-verifying Fuse agents. [S] https://futurumgroup.com/insights/synopsys-cadence-and-siemens-take-agentic-chip-design-autonomous-at-dac/ and https://dac.com/2026/press-release/... [P]
  - Futurum analyst view: engineers treat "autonomy-level labels as marketing until proven." That favours tools that are deterministic and auditable.
- At DVCon US 2026, Cadence ran the workshop "Verification in the Agentic AI era". It covered agent-driven regression orchestration, AI failure triage and waveform root-cause analysis. [P] https://dvcon.org/program/2026/2026-tutorials-workshops
- The DVCon India 2026 paper list includes LLM-guided regression reduction and agentic formal bug-hunting. [P] https://dvcon-india.org/wp-content/uploads/2026/09/DVCon-India-2026-Selected-Paper-List-Final.pdf
- **ChipAgents** raised a $134M Series A (expanded July 2026). It reports **6x ARR growth in H1 2026 and more than 120 deployments at semiconductor companies**. [P] https://www.businesswire.com/news/home/20260729819576/en/ChipAgents-Expands-Series-A-Funding-to-$134-Million-as-Demand-Grows-for-Agentic-AI-in-Semiconductor-Design
  - This is strong evidence that DV teams will pay for agentic tooling.
- SemiEngineering, "Toward Agentic Verification" (May 28, 2026). [S] https://semiengineering.com/toward-agentic-verification/
  - Siemens: agents do "running an engine, collecting the data, analyzing that data, recommending the next steps". That is exactly a packet step loop.
  - Cadence: SoC-scale context queries "may take hours... if it even comes back".
  - On token cost, teams get "budget surprises because you didn't plan for it".
  - Engineers "need to be in the driving seat".
  - Moores Lab AI: AXI-to-APB bridge verification in 48 hours instead of 2 months.
- Arxiv survey "Agentic EDA: A Handoff Perspective" (June 2026). It classifies 115 systems by where handoffs happen between humans, artifacts and tools. This matches the packet as the unit that people, agents and batch tools take turns in, which is useful for positioning. [P] https://arxiv.org/abs/2606.19795

### Constraint: IP must stay inside the walls

- **Samsung** banned ChatGPT and other generative-AI tools in May 2023 after semiconductor-division engineers pasted source code into ChatGPT. **SK Hynix** blocked ChatGPT on its internal network. [S] https://techcrunch.com/2023/05/02/samsung-bans-use-of-generative-ai-tools-like-chatgpt-after-april-internal-data-leak/ and https://www.eenewseurope.com/en/chatgpt-leaking-samsung-chip-secrets-is-icebergs-tip/
- EE Times, "DAC 2026: DIY AI Is Now in Vogue; Users Are Not Waiting". [S] https://www.eetimes.com/dac-2026-users-are-not-waiting-diy-ai-is-now-in-vogue/
  - Quote: "The confidentiality requirements of semiconductor design mean the user's DIY AI runs inside the user's walls."
  - **IBM**: agentic verification-failure triage cut manual effort by 15–40%. An agentic framework cut EDA utility development from about 4 person-weeks to under 30 minutes.
  - **Samsung**: on-prem LLMs for emulation regression, plus multi-agent pipelines that keep design data confidential.
  - EE Times' split: proprietary problems get homegrown, on-prem AI; problems common to everyone get vendor-embedded AI.
  - **This is the key point.** Big chip companies are building their own agent flows on-prem and need the plumbing: workspaces, hand-off, long job tracking and cost accounting. work-packet is that plumbing, and it does not compete with the EDA vendors' engines.
- SemiEngineering covers an on-prem/air-gapped agentic LLM for chip design ("Renoir"). Vendors are clearly selling into this constraint. [S] https://semiengineering.com/introducing-an-agentic-llm-for-chip-design/

### Pain: getting a testcase to the EDA vendor

- SemiWiki (Daniel Payne): "Even supplying a test case to reproduce a software bug is an issue because IC designers don't want any piece of their IP to leave the facility." He adds: "Some of the largest EDA customers will have AEs on site at the customer to help reproduce the bugs." [S, forum] https://semiwiki.com/forum/threads/should-eda-follow-a-foundry-model.10435/
  - This directly supports the customer-to-vendor repro bundle, especially a bundle with controlled, inspectable contents that can be sanitised or replayed on-site.
- Cadence Verisium AutoTriage / PinDown: vendor ML triage claims "up to 10x" less debug time and a 3x reduction in post-regression triage. This shows triage is a recognised, budgeted pain. [P, vendor marketing] https://community.cadence.com/cadence_blogs_8/b/fv/posts/automate-regression-failure-triage-with-the-cadence-verisium

### Willingness to pay and access

- **WTP: high.** Teams already pay for EDA licences, emulation and on-prem GPUs, and ChipAgents' traction shows budget for agentic DV. Watch out: procurement is slow, often 6–12 months with a security review. A free, self-hosted per-user tool, adopted bottom-up by individual engineers on their own machines, sidesteps that at first.
- **Access: good.** DVCon (US, EU, India, China), DAC, Verification Academy, SemiWiki and the cocotb/pyuvm/Verilator/FuseSoC open-source community. The founder's own tools (dv-flow-manager, IVPM, DVKit) are already a channel.

**Why us:** Agents, people and simulator/LSF regressions already take turns on a DV bug. A packet is a self-hosted place that holds all of it (plan, worktrees, waves, coverage, rebuild recipe). It never leaves your network, and when it has to cross the wall it ships as a repro bundle.

---

## 2. Other IP-sensitive and regulated engineering

### Defense and aerospace (ITAR/CMMC)

- CMMC 2.0 Level 2 began phasing into DoD contracts in late 2025. A cluster of vendors now sell air-gapped coding assistants into this market (Tabnine Enterprise, AirgapAI and others). [W, vendor/SEO] https://intuitionlabs.ai/articles/enterprise-ai-code-assistants-air-gapped-environments and https://vdf.ai/blog/cmmc-ai-chatgpt-copilot-cui-defense-contractors/
- The constraint has loosened somewhat. **AWS published guidance on 2026-10-05 for running Claude Code on Bedrock in GovCloud (US) for ITAR workloads.** Claude also holds FedRAMP High and IL4/5 on Bedrock. [S] https://www.unite.ai/aws-details-claude-code-deployment-on-amazon-bedrock-in-govcloud-us/ and https://www.anthropic.com/news/claude-in-amazon-bedrock-fedramp-high [P]
  - **Implication:** for ITAR/CUI the model can now live in GovCloud, but the workspace, artifacts and orchestration still need to be self-hosted. That is a good fit for a harness-neutral, local-first runner pointed at a Bedrock endpoint.
  - Truly air-gapped programmes need local models. Harness-neutrality matters here.
- **Reach: poor.** Sales are cleared-personnel, compliance-heavy and long-cycle. Better reached through primes' internal tooling groups, or later on.

### Automotive embedded (ISO 26262)

- Black Duck, State of Embedded Software Quality & Safety 2025 [S]:
  - 89.3% of respondents use AI coding assistants.
  - IP concerns are the leading barrier to open-source use, up 14 points year on year.
  - More than 21% are not confident they can stop AI from injecting flaws.
  - Shadow AI against company policy is an identified risk.
  - https://www.blackduck.com/content/dam/black-duck/en-us/reports/state-of-embedded-software-quality-and-safety.pdf
- Perforce's 2025 automotive report: meeting every ISO 26262 requirement remains the top safety concern. [S] https://www.perforce.com/blog/sca/automotive-industry-trends-ai
- Fit:
  - The packet journal and plan, with per-step records, give an **audit trail** that supports traceability arguments.
  - Automotive OEMs designing their own silicon are a bridge from segment 1 (Siemens blog above).

### HPC and national labs / scientific computing

- Aalto Scientific Computing published explicit guidance on AI agents on its Triton cluster. [P] https://scicomp.aalto.fi/triton/usage/ai-agents/
  - Agents spawn runaway processes and hammer `squeue`/`sacct`, so the guidance asks for at least 15 seconds between queue polls.
  - Agents submit thousands of tiny jobs and destabilise login nodes.
  - Agents send code and errors to external providers, and confidential data must never go through them.
  - Agents must run on a dedicated login server, and users should avoid running many concurrent agents.
  - **Evidence of pain**: centres need a tool that runs agents politely beside SLURM jobs, without polling. work-packet's daemon already does this: it tracks the job and wakes the agent on completion.
- Arxiv 2026 work on agentic workflows as first-class SLURM citizens (RASER, Diamond Agent) shows active research demand. [P] https://arxiv.org/pdf/2609.03598 and https://arxiv.org/pdf/2609.06181
- **Reach: medium.** RSE (research software engineer) communities, SC/ISC BoFs, and centre documentation pages. **WTP: low to medium** (grant-funded). Open source matters a lot here.

### Pharma / biotech computational science

- There is a lot of vendor/SEO content on private on-prem LLMs for GxP/HIPAA. Agents for SAS/R/Python appear at PharmaSUG 2026 (biometrics "vibe coding agents"). [W] https://intuitionlabs.ai/articles/private-llm-pharma-compliance-architecture and [P] https://pharmasug.org/conferences/pharmasug-2026-us/paper-presentations/
- Fit is plausible: long pipeline runs, reproducibility and validation records. I found no primary evidence of pain for the long-running-job and handoff problem specifically. **Low confidence.**

### Finance (quant)

- I found no evidence of quant firms banning cloud coding agents. Firms build internal gateways instead, for example D.E. Shaw's LLM Gateway with central prompt logging and Citadel's in-house assistant. [W] https://www.ai-street.co/p/how-hedge-funds-and-market-makers
- These firms tend to build their own tools. **Deprioritise.**

### Firmware / embedded generally

- Academic work on closed-loop agent evaluation for embedded firmware (build, test, repair loops). Specialised agents such as Embedder are emerging. [P] https://arxiv.org/abs/2610.11447v1
- HIL test benches look like simulators: long-running, expensive, shared resources. Same fit as DV.

**Why us:** The model can now live in GovCloud or on-prem, but the work cannot leave. work-packet keeps the workspace, artifacts, job tracking and audit journal on your own machines. It drives whichever harness or model you are approved to use, and it does not hammer the scheduler.

---

## 3. OSS maintainers and vendor support teams (repro bundles)

- About **17% of bug reports are non-reproducible**, and they stay open about 3 months longer than other reports. [P, academic] Joorabchi et al., MSR'14: https://people.ece.ubc.ca/amesbah/resources/papers/mona-msr14.pdf. A large-scale follow-up: https://web.cs.dal.ca/~masud/papers/masud-EMSE2022.pdf
- Tidelift 2024: 60% of maintainers are unpaid, and about 60% have quit or considered quitting. Late-2025 surveys say about half are considering stepping back. [S] https://itsfoss.com/news/open-source-developers-are-exhausted/ and https://yoo.be/open-source-maintainer-burnout-foundations-2026/ [W]
- **Assessment:**
  - The pain is real, but OSS maintainers do not pay, and generic repro tools already exist (devcontainers, Nix, rr/Pernosco, Replay.io).
  - The **EDA customer-to-vendor** variant is much stronger. Testcases are IP-restricted (SemiWiki above), a sim-plus-waves bundle with a rebuild recipe is exactly what an EDA AE needs, and vendors pay.
  - Open-source EDA (Verilator, cocotb, Yosys, OpenROAD) is a cheap place to prove the bundle format publicly.

**Why us:** A bug bundle captures the instruction, rebuild recipe, worktrees and failing artifacts together. It replays on the vendor's side, or on-site, without a back-and-forth asking for a testcase.

---

## 4. Power users running many parallel long-running agent tasks

- Weekly limits on Claude Code were announced 2025-07-28 and took effect 2025-08-28, aimed at users running "continuously in the background, 24/7". There was strong backlash (HN, GitHub issue #9424, "Weekly Usage Limits Making Claude Subscriptions Unusable"). [P/S] https://news.ycombinator.com/item?id=44713757 and https://github.com/anthropics/claude-code/issues/9424
- In March–April 2026 some Max users burned their weekly quota in 1–2 days, and Anthropic reset limits after bug fixes. 5-hour limits were doubled 2026-05-06. Parallel fan-out drains weekly quota fastest. [W] https://explainx.ai/blog/claude-usage-limits-2026-timeline-explained and https://redreamality.com/blog/claude-code-usage-limits-cost-2026/
- **Orchestrator popularity** (GitHub stars, fetched 2026-10-26 via `gh api`) [P]:
  - BloopAI/vibe-kanban: 28.5k (now community-maintained after Bloop shut down)
  - OrchestratorInc/agent-orchestrator: 13.6k
  - smtg-ai/claude-squad: 8.7k
  - generalaction/emdash: 6.1k
  - stravu/crystal (Nimbalyst): 3.1k
- **Conductor** (Melty Labs) raised a $22M Series A in March 2026, grew 10x since January, lists Linear, Vercel, Notion and Ramp as users, and launched Conductor Cloud (hosted VMs) in May 2026. [S] https://aiturnpoint.com/conductor-raises-22m-series-a
- Augment's survey of 9 OSS orchestrators: "git worktrees became the consensus isolation primitive". **"Cost tracking isn't native to any OSS tool."** [S] https://www.augmentcode.com/tools/open-source-agent-orchestrators
- Context rot and compaction are widely discussed. The consensus advice is to avoid long sessions and use fresh contexts. This supports the measured ~1.7x saving from short fresh-context steps. [W] https://codex.danielvaughan.com/2026/04/14/context-compaction-deep-dive-codex-cli-claude-code-opencode/ and https://www.sitepoint.com/claude-code-context-management/
- Anthropic's 2026 Agentic Coding Trends Report: task horizons are growing from minutes to days or weeks, with "strategic human checkpoints", and agent teams work across separate context windows. [P] https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf
- **Assessment:**
  - Demand is huge and easy to reach (HN, X, GitHub), but the space is **crowded and commoditising** (worktree plus kanban plus a parallel runner is table stakes).
  - Willingness to pay is low, since the free OSS tools get tens of thousands of stars.
  - The differentiators that survive are:
    - long-running *external* jobs (not just agent turns)
    - fresh-context stepping that stretches the quota
    - per-step cost attribution
    - hand-off to people
  - Use this segment as the **adoption and credibility channel**, not the revenue base.

**Why us:** It is the only board where a packet can wait hours on a real job without polling, then resume in a fresh, cheap context. It stretches your weekly quota (measured ~1.7x) and shows exactly what each task cost.

---

## 5. Engineering leads and platform teams: visibility and cost attribution

- **Gartner (June 2026)**: AI coding costs will surpass the average developer's salary by 2028. About a quarter of tech leaders already spend $200–500 per developer per month on tokens, and about 6% spend more than $2,000. [S, the press release returned 403] https://www.gartner.com/en/newsroom/press-releases/2026-06-24-gartner-predicts-ai-coding-costs-will-surpass-average-developer-salary-by-2028-as-token-consumption-surges
- KPMG 2026, quoted secondhand [S]:
  - Of $1B+ firms planning about $202M of AI spend, only 26% have real-time cost visibility.
  - 36% cite lack of financial attribution as a barrier.
  - https://reinvently.co.uk/blog/ai-agent-governance-gap/
- Retool, July 2026 (n=101 tech leaders) [P]:
  - 43% are over their AI budget.
  - Only 5% of CIOs, CISOs and CTOs are confident they can see production AI tool use.
  - Agentic workflows use 5–30x the tokens of chat.
  - https://retool.com/blog/how-tech-leaders-are-handling-ai-cost-management
- **Competition:**
  - Claude Code's built-in Team/Enterprise analytics, Analytics API and OpenTelemetry `cost.usage` already give per-user, per-repo and per-model spend. [S] https://bindplane.com/blog/claude-code-opentelemetry-per-session-cost-and-token-tracking and https://www.eesel.ai/blog/monitoring-claude-code
  - The gap is attribution to a **unit of work** (project, packet, task, step) across harnesses, plus what the work produced. Per-user and per-repo spend does not cover that.
- **Assessment:**
  - Treat this as a feature that wins the second buyer (the manager) inside segments 1 and 2, not as a standalone segment.
  - It competes with vendor analytics and FinOps tools (Vantage, CloudZero) if sold alone.

**Why us:** Spend is attributed to the work item (project, packet, task, step) across any harness, next to the results it produced. Leads see cost per bug fixed or per coverage hole closed, not only per seat.

---

## Gaps and caveats

- I found no primary 2025–2026 survey that directly measures regression-triage hours for DV. The 47% debug figure (WRG 2024) is the best proxy.
- I found no public evidence of quant firms or national labs formally banning cloud coding agents. The HPC evidence is about operational harm and data leakage, not bans.
- The air-gap argument for defense is weaker after GovCloud Claude Code (Oct 2026). Lead with "artifacts and workspace stay local" rather than "the model stays local".
- Several sources (staffing, SEO and vendor blogs) are marked [W]. Do not cite them externally without checking.
