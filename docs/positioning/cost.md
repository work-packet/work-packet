# Prior-art survey: agent token-cost reduction and task-level metrics

Date of survey: 2026-10-26. Angle: (a) token-cost reduction strategies for agents, (b) task-based (not user/request) metrics for agentic work, (c) closed-loop use of metrics.

Marking: **[P]** = primary source read directly (vendor doc, paper abstract, original blog). **[S]** = secondary (aggregator, blog summary, search-snippet summary, or a number I could not trace to the original). Numbers marked [S] should be re-verified before quoting externally.

Work-packet reference result (for comparison throughout): 31-step HW-verification project, $42 vs $71 (1.7x) for one Claude Code session auto-compacting at 200k; 1.4x vs ideally timed compaction; 5.4x vs a 1M-context model at default; 14.5x vs never compacting. Reported in billed dollars, measured on a real multi-step project, with per-step attribution.

---

## 1. Research and vendor claims on agent cost

### 1.1 Context rot (why long context is bad for quality, not just cost)

- **Chroma, "Context Rot: How Increasing Input Tokens Impacts LLM Performance"** (Jul 2025). 18 models (GPT-4.1, Claude 4, Gemini 2.5, Qwen3). Performance falls as input length grows even on trivial retrieval/replication tasks with task difficulty held constant; distractors and needle-question similarity make it worse. [P] https://www.trychroma.com/research/context-rot
  - "Steepest degradation in 100k-500k range" is an aggregator's framing. [S] https://hivetrail.com/blog/context-rot-chroma-study
- **"Classifier Context Rot"** (arXiv 2605.12366): monitor/classifier performance also degrades with context length. [S, title only] https://arxiv.org/pdf/2605.12366
- Relevance: gives a quality argument for fresh-context steps in addition to the cost argument. Work-packet can cite this as the "why", and its own $ data as the "how much".

### 1.2 Anthropic guidance: compaction, context editing, memory, sub-agents, harnesses

- **"Effective context engineering for AI agents"** (Anthropic Engineering, 2025-09-29). Three levers for long-horizon tasks: compaction, structured note-taking (NOTES.md/TODO outside the window), sub-agent architectures (clean context per sub-agent, compact summary back). [P] https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **"Managing context on the Claude Developer Platform"** (Sep 2025): context editing (auto-clearing stale tool results) + memory tool. On a 100-turn web-search eval, context editing cut **token consumption 84%** and let runs finish that otherwise exhausted context; memory + context editing improved performance 39% over baseline, context editing alone 29%. [P] https://claude.com/blog/context-management
  - Note: 84% is tokens, not dollars, and on an internal agentic search eval, not a coding/verification project.
- **"Effective harnesses for long-running agents"** (Anthropic, 2025-11-26). Initializer agent creates init.sh, `claude-progress.txt`, a JSON feature list (200+ items, all "failing"), and a git commit; subsequent coding-agent sessions start with **fresh context**, read progress notes and git log, do one feature, commit. **No token/cost data published.** [P] https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - This is the closest published design to work-packet's "short fresh-context steps inside a packet". Differentiator for work-packet: it measures the cost effect and attributes it per step; Anthropic's post makes the argument on coherence/quality only.
- **"How we built our multi-agent research system"** (Anthropic, Jun 2025). Multi-agent beat single-agent Opus 4 by 90.2% on internal research eval; agents use ~4x tokens of chat, multi-agent ~**15x tokens of chat**; token usage explains ~80% of performance variance (BrowseComp). Economic viability requires high-value tasks. [P via Simon Willison summary; original at anthropic.com/engineering/built-multi-agent-research-system] https://simonwillison.net/2025/Jun/14/multi-agent-research-system/
- **Claude Code "Manage costs effectively" docs** (current). [P] https://code.claude.com/docs/en/costs
  - Average ~$13/dev/active day, $150-250/dev/month, 90% of users < $30/active day.
  - Agent teams use **~7x tokens** of a standard session (plan mode).
  - Guidance: `/clear` between tasks ("costs nothing"); `/compact` is itself a large request; delegate verbose ops to subagents; hooks to pre-filter tool output (e.g., grep logs); prefer CLI over MCP; code-intelligence plugins to avoid file reads.
  - "Why usage climbs in a long session": full history re-read at cache rate every request; cache misses after TTL; compaction cost.
  - **`/usage` plan breakdown now attributes recent usage to skills, subagents, plugins and individual MCP servers (share of total) and emits recommendations ("Trim CLAUDE.md · 49k tokens per request", "/effort high"), with an `f` key that applies some of them.** This is a *per-user, per-machine, last-24h/7d* closed loop on configuration, not per task. Closest thing on the market to "stats feed back into profiles", but scoped to the individual's harness config.
  - `/insights` produces an HTML report on friction and usage patterns across up to 200 sessions.
  - `Prompt cache (main)` line: share of input from cache, misses with likely cause, expected rebuilds (compaction / tool-result clearing).
- **Pricing (current)** [P] https://platform.claude.com/docs/en/about-claude/pricing
  - Cache write 1.25x (5-min) / 2x (1-h) base input; cache read 0.1x base for most models, **0.05x on Opus 5.5 / Sonnet 5.5**, 0.025x on Fable/Mythos 5.1. Opus 5.5 $4 in / $20 out / $0.20 cache read per MTok.
  - Long-context (>200k) 2x surcharge on Opus/Sonnet 4.6 was removed 2026-03-13; 1M context billed flat. [P] https://claude.com/blog/1m-context-ga ; [S] https://tokencost.app/blog/anthropic-long-context-flat-pricing
  - Implication: the 1M-context penalty work-packet measures (5.4x) is not a pricing surcharge; it is accumulated cache-read volume (quadratic-ish in session length). Cheaper cache reads on 5.5-generation models shrink but do not remove it; the ratio vs fresh steps will shift and should be re-measured per model.

### 1.3 Other vendor/practitioner measurements

- **Sonar, "Stop the context tax"** (Antonio Aversa, 2026-09-01). Instrumented trace of one 800-line PR: 512 round-trips, peak context 458.7k, 106k fresh input, 3.1M cache write, **152.8M cache read**, 289k output; ~156M tokens, ~$41. 98% of volume is cache re-reads. Across 18 PRs: median ~$52/PR (mean ~$65), ~700 round-trips, peaks 450k-975k. One unnecessary whole-file read (618 lines vs 67 needed) = ~5.8k tokens immediately but **2.7M tokens re-billed over 470 later turns (~$0.54)**. [P] https://www.sonarsource.com/blog/stop-the-context-tax/ ; commentary [S] https://www.beri.net/article/coding-agent-cache-read-context-tax-tokens-per-pr-turn-budget (claims "cut turns 10% -> ~16% cost")
  - Very close to work-packet's "which tool results burn context" view. Sonar's remedy is better tools (symbol-level navigation), not step boundaries; it is per-PR analysis of one harness, not a product attributing every project.
- **LangWatch, "When should a coding agent compact? 287k API calls measured"** (Rogerio Chaves, 2026-08-02). 2,451 Claude Code sessions, 287,748 calls, 873 compactions. Cumulative cost grows ~context^2.55 (R^2 0.994): reaching 100k ~1.4M cumulative tokens, 200k ~9M, 800k ~338M; "every doubling of context costs ~6x". Useful context stays ~8k tokens regardless of window (47.5% of window <50k, 2.5% >600k). Cost-optimal compaction threshold ~220k (170k-316k within 10%); quality-adjusted 239k-453k. Post-compaction correction rate 41.9% vs 17.7% baseline; 25-30 steps of "rediscovery". Observed 600k default costs ~23M extra tokens per 1,000 productive steps; never compacting ~2.3x worse than 220k at 1M. Only 14% of audited steps needed verbatim old context. [P] https://langwatch.ai/blog/context-tax-when-to-compact ; related https://langwatch.ai/research/finding-the-optimal-context-window
  - Search snippet (not verified on page): in 36 runs x 6 clearing policies, clearing after **every** task was +33.5% vs clearing every 3 tasks. [S] — a useful counterpoint: too-small steps pay re-orientation cost. Work-packet's step sizing/profiles is the answer to exactly this trade-off.
- **dev.to measurement**: Claude Code `/compact` at 136k cost $0.06 warm cache, ~9x cold; `/clear` sends zero requests. [S] https://dev.to/rulestack/claude-codes-compact-cost-006-at-136k-tokens-with-a-warm-cache-9x-that-cold-and-clear-sent-85f
- **Factory.ai, "Evaluating context compression for AI agents"**: probe-based eval on 36k production messages; Factory anchored iterative summary 3.70 vs Anthropic 3.44 vs OpenAI compact 3.35. Key line: "the right optimization target is not tokens per request. It is tokens per task." [P/S — title and framing from search; verify] https://factory.ai/news/evaluating-compression
- **Cognition, "Don't build multi-agents"** (Walden Yan, Jun 2025): share full traces; sub-agents without shared context make conflicting implicit decisions. Later (2026) softened: some multi-agent setups work. [S] https://agentic-ai.readthedocs.io/en/latest/ContextEngineering/devin/ ; https://x.com/walden_yan/status/2047054554433462360
  - Relevance: the counter-argument to fresh-context steps is lost decisions; work-packet's packet state/hand-off is the mitigation. Worth addressing explicitly.

### 1.4 Academic papers on agent token efficiency (2025-2026)

| Paper | Mechanism | Reported saving | Source |
|---|---|---|---|
| AgentDiet, "Reducing Cost of LLM Agents with Trajectory Reduction" (arXiv 2509.23586, FSE 2026) | Cheap reflection LLM removes useless/redundant/expired content from trajectory | Input tokens -39.9% to -59.7%; **final cost -21.1% to -35.9%** (1.27x-1.56x), same solve rate | [P] https://arxiv.org/abs/2509.23586 |
| "The Complexity Trap" (JetBrains, NeurIPS 2025 DL4Code, arXiv 2508.21433) | Observation masking vs LLM summarization, SWE-agent on SWE-bench Verified | Masking **~halves cost** vs raw agent, matches summarization solve rate; summarization lengthens trajectories ~15% and is 2.9-7.2% of instance cost, cache-hostile | [P] https://arxiv.org/pdf/2508.21433 ; code https://github.com/JetBrains-Research/the-complexity-trap |
| "Less Context, Better Agents" (Microsoft, arXiv 2606.10209) | Keep last N tool call/response pairs + summarize evicted | Full context 71.0% completion, 1.48M tokens, 14.6h; last-5 pruning 79.0%, 535k tokens (**2.8x fewer**), 5.4h; +summary 91.6% | [P] https://arxiv.org/abs/2606.10209 |
| CliffCompaction (Nguyen, Cho, Chen, Dettmers; arXiv 2609.26779) | Remove/truncate only, never re-summarize compacted output; API proxy for Claude Code/Codex | **Up to 50% cost** under bounded context, equal or better performance | [P] https://arxiv.org/abs/2609.26779 |
| BATS / Budget Tracker (Google, arXiv 2511.17006, COLM 2026) | Agent sees remaining tool-call budget, decides dig vs pivot | Similar accuracy with 10 vs 100 tool calls; **total cost -31.3%** | [P] https://arxiv.org/abs/2511.17006 |
| "Token Reduction Is Not Cost Reduction" (Weinberger, Hozez; arXiv 2607.12161) | Evaluates 3 tool-output compression tools on coding agents, billed $ | Most aggressive cut tool-output tokens 38.4% but **raised billed cost 6.8%**; token reduction vs cost reduction Pearson r = 0.15; cache operations dominate input cost; compression changes behavior (extra retrieval) | [P] https://arxiv.org/abs/2607.12161 |
| "Tokenomics: where tokens are used in agentic SE" (arXiv 2601.14470) | ChatDev + GPT-5, 30 tasks, tokens by phase | Code review phase **59.4%** of tokens; design 2.4%, coding 8.6% | [P] https://arxiv.org/abs/2601.14470 |
| "How Do AI Agents Spend Your Money?" (arXiv 2604.22750) | Token consumption analysis/prediction on agentic coding | Same task runs differ **up to 30x** in tokens; accuracy peaks at intermediate cost; models predict own usage poorly (r <= 0.39) and underestimate; agentic coding ~1000x tokens of code chat; input dominates | [P] https://arxiv.org/abs/2604.22750 |
| "Context as a Tool" (arXiv 2512.22087), "Active Context Compression" (2601.07190), StateComp (2609.27298), ContextSniper (2607.01916), CoACT (2607.02911), AutoCompact (PREreview) | Learned/agent-driven compaction timing and compression | various | [S, titles only] |

### 1.5 Benchmarks reporting cost per task

- **HAL, Holistic Agent Leaderboard** (Princeton, ICLR 2026): 21,730 rollouts, 9 benchmarks, 9 models, ~$40k; publishes accuracy-vs-cost Pareto frontiers ($ and tokens); fewer than one-third of models on the frontier; expensive models usually not. [P] https://arxiv.org/html/2510.11977v1 ; https://hal.cs.princeton.edu/
- Follows Kapoor et al. "AI Agents That Matter" (2024) which argued for cost-controlled agent evaluation. [S]
- **Live-SWE-agent leaderboard**: $ per resolved instance, e.g., Claude Opus 4.5 ~$0.86 at 79.2%, GPT-5.2 ~$0.55 at 73.6%, GPT-5-mini ~$0.05 at 63.0%. [S, from search summary] https://live-swe-agent.github.io/
- Sonar Foundation Agent $1.26/issue on SWE-bench; Agentless ~$0.34/issue; AIDE ~$20/issue. [S] https://www.sonarsource.com/company/press-releases/sonar-claims-top-spot-on-swe-bench-leaderboard/
- Gap: benchmark tasks are single-issue, 1-2 hours of human work. Nobody publishes cost for a 31-step, multi-day project; work-packet's measurement is at a scale (and domain: HW verification) that benchmarks do not cover.

### 1.6 User complaints and pricing changes (2025-2026)

- **Claude Code weekly limits** effective 2025-08-28 on top of 5-hour windows; Anthropic said <5% of subscribers affected; Pro 40-80 h Sonnet/week, Max $200 240-480 h Sonnet + 24-40 h Opus. [S, multiple] https://developers.slashdot.org/story/25/07/29/0156200/claude-code-users-hit-with-weekly-rate-limits ; HN https://news.ycombinator.com/item?id=44713757 ; https://tessl.io/blog/why-claude-code-is-capping-power-users-and-what-it-means
- 2026: off-peak doubling promo Mar 13-28; **5-hour limits permanently doubled 2026-05-06**, weekly caps unchanged. [S] https://explainx.ai/blog/claude-usage-limits-2026-timeline-explained
- **Cursor** June 2025: request-based -> usage-based credit pools ($20 of frontier usage in Pro); backlash; apology and refunds for 2025-06-16 to 07-04. [P] https://cursor.com/blog/june-2025-pricing ; [S] https://www.finout.io/blog/what-happened-to-cursor-pricing-2026-guide-5-cost-cutting-tips
- **GitHub Copilot**: premium requests billing from 2025-06-18 (multipliers 0.25x-50x, $0.04 overage) [P] https://docs.github.com/en/copilot/concepts/billing/copilot-requests ; [S] https://www.theregister.com/2025/06/20/github_begins_enforcing_premium_request/ . **Moved to token-based usage billing (GitHub AI Credits, $0.01 each) on 2026-06-01**; ~$2-5 per 30-min agent session [S]. [P] https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/ ; dev reaction https://visualstudiomagazine.com/articles/2026/04/27/devs-sound-off-on-usage-based-copilot-pricing-change-you-will-get-less-but-pay-the-same-price.aspx
- Trend: every major coding tool moved from flat/request pricing to token-metered pricing in 2025-2026. That moves agent token efficiency from a vendor-margin problem onto the customer's bill, which is the market opening for work-packet.

---

## 2. Cost and usage tooling: what is the unit of attribution?

| Tool | Attribution unit | Task/work-unit attribution? | Feeds back into next run? | Source |
|---|---|---|---|---|
| ccusage (OSS CLI) | day/week/month/session/5-h block, model; cache tokens; parses Claude Code, Codex, OpenCode, Amp, Gemini CLI, Copilot CLI, etc. | No (session at best) | No | [P] https://github.com/ccusage/ccusage |
| Claude Code OTel | per request event (`cost_usd`), session, user; arbitrary `OTEL_RESOURCE_ATTRIBUTES` (team, cost_center) | Only if the user injects a task id as a resource attribute per launch (possible, not built-in) | No | [P] https://code.claude.com/docs/en/monitoring-usage |
| Claude Code `/usage` breakdown | per user, last 24h/7d; share by skill/subagent/plugin/MCP server; loops | No | **Partly**: recommendations + `f` to apply (effort level, trim CLAUDE.md) | [P] https://code.claude.com/docs/en/costs |
| Claude Code analytics / Analytics API / Enterprise Analytics API | per user per day: spend, accepted lines, PRs with CC assistance | PR-level contribution (via GitHub), not cost per PR | No | [P] https://code.claude.com/docs/en/analytics ; [S] https://www.finout.io/blog/anthropics-enterprise-analytics |
| Cursor / Copilot dashboards | per user/seat, model, credits | No | No | [S] https://www.cloudzero.com/blog/github-copilot-cost/ |
| Linear agent | per session/loop run (tokens at cost + $0.25/20-min sandbox); workspace pool | Session is launched from an issue, so implicitly per issue, but reporting is workspace-level | No | [P] https://linear.app/docs/ai-credits |
| Devin | ACU per session; "Session Insights" | Session ~= task | No (insights are advisory) | [S] https://fast.io/resources/devin-acu-guide/ |
| Langfuse | trace, session_id, user_id, tags/metadata; Metrics API | Yes if you tag (generic tags) | No | [P] https://langfuse.com/docs/metrics/overview ; https://langfuse.com/docs/observability/features/tags |
| Helicone | request; sessions via header | Only via headers you set | No | [S] https://laminar.sh/article/best-ai-agent-cost-tracking-tools |
| AgentOps / Braintrust / Laminar | event/span/trace; agent run | Run ~= task in custom agents | No (evals are offline) | [S] https://latitude.so/blog/best-ai-agent-observability-tools-2026-comparison |
| LiteLLM / Portkey gateways | key, user, team, org, customer, tag, agent/session; hard budgets | Tag budgets can encode a ticket | **Budgets enforce caps** (stop), not reconfigure | [P] https://docs.litellm.ai/docs/proxy/tag_budgets ; https://portkey.ai/blog/claude-code-limits/ |
| Vantage / CloudZero / Finout | cloud bill line items; cost per model/customer/feature; CloudZero "Agentic FinOps" + MCP server (Dec 2025) | Unit economics by business dimension (customer, feature) | No | [S] https://www.finout.io/blog/ai-cost-visibility-in-2026-strategies-tools-and-best-practices ; https://www.vantage.sh/blog/cursor-pricing-explained |
| FOCUS 1.5 (FinOps Foundation spec, Dec 2026) | standardized token counts by model and token type (input/output/cache read/cache write/reasoning) in cost datasets | No | No | [P] https://focus.finops.org/focus-1-5-release-scope/ ; https://focus.finops.org/technology-categories/focus-for-ai/ |
| **Jellyfish** | tokens and $ per PR, per dev, per team; joins Copilot/Cursor/Claude Code token data to Git and Jira | **Yes, per PR** (tokens/PR as a trend) | No (manual: "review default model choices quarterly") | [P] https://jellyfish.co/library/ai-token-usage-monitoring/ |
| **LinearB** | "Daily AI Cost", "AI Cost per Pull Request" | **Yes, per PR** | No | [P] https://linearb.helpdocs.io/article/w1yl8ejm8p-ai-cost-and-token-consumption ; [S] https://www.minware.com/blog/best-cursor-analytics-tools |
| **Faros AI** (repositioned Sep 2026 as "token engineering platform") | links agent sessions and token spend to PRs, tickets and releases; cost per outcome by team/model/tool | **Yes, the strongest claim** | **Partly**: "Time Machine" replays completed work against other models/configs to see what lowers cost per outcome; separate "Optimal Model Routing" and governance products. Not described as automatic per-task re-sizing. | [P] https://www.faros.ai/blog/cost-per-outcome ; https://www.faros.ai/blog/your-ai-bill-doesnt-tell-you-what-you-think-it-does |

Notes:
- FinOps vocabulary converging on **"cost per successful task" / "Cost-per-Accepted-Outcome (CAPO)"** (failed/retried runs in numerator, accepted outcomes in denominator). [S] https://www.pointfive.co/blog/what-is-finops-for-ai ; https://www.infoworld.com/article/4138748/finops-for-agents-loop-limits-tool-call-caps-and-the-new-unit-economics-of-agentic-saas
- The "task" these tools attribute to is the **PR or ticket**, joined after the fact from Git/Jira by time window and author. None attribute *inside* the task (step, which tool result inflated context, failed attempts, per-call context curve). Work-packet's project -> packet -> step hierarchy is finer-grained and is captured at run time, not reconstructed.

---

## 3. Engineering-productivity measurement of AI

- **METR RCT** (2025-07-10): 16 experienced OSS devs, 246 tasks (~2 h each) on mature repos; with AI they were **19% slower** while believing they were 20% faster. [P] https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
  - Follow-up (Aug 2025 start, reported 2026-02-24): data unreliable due to selection (devs refusing to work without AI); raw estimates -18% (returning devs, CI -38% to +9%) and -4% (new, CI -15% to +9%); METR believes devs are now likely sped up. [P] https://metr.org/blog/2026-02-24-uplift-update/ ; self-report survey 2026-05-11 https://metr.org/blog/2026-05-11-ai-usage-survey/
  - Measures time per task, not cost per task.
- **DORA 2025 "State of AI-assisted Software Development"** (~5,000 respondents): AI is an amplifier; now associated with higher throughput but **still with higher delivery instability**. Survey-based; no token or cost-per-task measures. [P] https://services.google.com/fh/files/misc/2025_state_of_ai_assisted_software_development.pdf ; [S] https://redmonk.com/rstephens/2025/12/18/dora2025/
- **DX AI Measurement Framework**: utilization (DAU/WAU, % AI-assisted PRs, tasks assigned to agents), impact (time saved, human-equivalent hours, Core 4), cost (**AI spend total and per developer; net time gain = time saved minus AI spend**). Cost is per developer, not per task. [P] https://getdx.com/blog/ai-measurement-framework-guide/ ; https://getdx.com/blog/ai-roi-engineering/
- **Faros AI Productivity Paradox** (Jul 2025, 10k devs, 1,255 teams): high-AI teams +21% tasks, +98% PRs merged, but PR review time +91%, PR size +154%, bugs/dev +9%; org delivery flat. 2026 update (22k devs): review time +441%, 31% more PRs merged without review. [P] https://www.faros.ai/blog/ai-software-engineering ; [S for 2026 numbers] https://agentmarketcap.ai/blog/2026/04/07/faros-ai-coding-agent-metrics-enterprise-teams
- **Jellyfish**: 12,000 devs / 200 companies: cost per merged PR **$0.28 (lightest users) to $89.32 (heaviest)**; median dev ~7.5M tokens/PR, top decile 69M. Internal analysis, methodology not published. [P for claim, unverified data] https://jellyfish.co/library/ai-token-usage-monitoring/
- **LinearB**: 90th-percentile token cost $481/dev/month, <4% of fully loaded dev cost; AI ROI = engineering cost / "effective PRs". [S] https://linearb.io/resources/ai-engineering-productivity-gap
- **GitHub Copilot metrics API**: acceptance, active users, lines, PR summaries; billing per user. [S]

**Gap**: The productivity camp measures time (METR), survey outcomes (DORA, DX), or PR throughput (Faros, Jellyfish, LinearB). Cost appears as spend per developer or per PR. Nobody reports outcome-per-token at a sub-PR granularity, and nobody separates "the agent did more useful work" from "the agent re-read its own history 500 times" (Sonar's 98% cache-read share). The PR is also the wrong unit for long-running agentic projects: one 31-step packet may produce many commits or one, and the review-bottleneck findings (Faros) mean PR counts are a noisy denominator.

---

## 4. Synthesis

### 4.1 How work-packet's numbers compare

| Comparison | Published | Work-packet |
|---|---|---|
| Trajectory pruning/masking vs raw agent | AgentDiet 1.27-1.56x cost; Complexity Trap ~2x; CliffCompaction up to 2x; Microsoft pruning 2.8x tokens; Anthropic context editing 6.25x tokens (84%) on a search eval | 1.7x vs auto-compact at 200k |
| Tuned vs default compaction | LangWatch: 220k vs observed 600k default ~+23M tokens per 1k steps; never-compact ~2.3x worse than 220k at 1M | 1.4x vs ideally timed compaction |
| Long-window / never-compact penalty | LangWatch power law (doubling context ~6x cumulative cost); Sonar 98% cache reads, $52 median per PR | 5.4x vs 1M default; 14.5x vs never compacting |
| Budget awareness | BATS -31% cost | (step sizing/profiles) |

- Work-packet's 1.4-1.7x is **in the same band as the best peer-reviewed results (1.3-2x in billed cost)**, which is credible rather than outlandish. The bigger headline numbers in the literature (84%, 2.8x) are token counts on single-domain evals, and "Token Reduction Is Not Cost Reduction" shows tokens can mislead (r = 0.15, one method cut tokens 38% and raised cost 7%). Work-packet reports **billed dollars including cache write/read**, which is the methodologically stronger claim; say so.
- The 1.4x vs **ideally timed** compaction is the most defensible differentiator: it beats an oracle version of the standard technique, which no published paper compares against. LangWatch's own finding (post-compaction 25-30 rediscovery steps, correction rate 41.9%) supplies the mechanism.
- Caveats to pre-empt: n=1 project; the LangWatch "clearing after every task is +33.5% vs every 3 tasks" result [S] says step size matters, too small costs more, so the claim should be "right-sized fresh steps", backed by work-packet's sizing feedback. Cheaper cache reads on 5.5-generation models (0.05x) will compress the 5.4x/14.5x ratios; re-run per model.

### 4.2 Who does task-level attribution

- At PR/ticket granularity, after the fact: **Faros** (strongest: sessions -> PRs, tickets, releases; cost per outcome), **Jellyfish** (tokens/cost per PR), **LinearB** (AI cost per PR). Linear and Devin bill per agent session, which is implicitly per issue.
- At generic tag granularity: Langfuse, LiteLLM, Helicone, Portkey, if the user plumbs a task id through.
- **Nobody found attributes inside the task** (step, failed attempts, per-call context curve, which tool results burned context) as a standing product feature. Sonar and LangWatch did it as one-off research on their own traces.

### 4.3 The closed-loop gap

- Existing feedback is either **caps** (LiteLLM/Portkey budgets, Claude Code spend limits), **advice** (Jellyfish "review models quarterly", Devin Session Insights, `/insights`), **per-user harness tweaks** (Claude Code `/usage` recommendations + `f` to fix: effort level, CLAUDE.md size), **offline what-if** (Faros Time Machine replay against other models/configs), or **within-run** (BATS budget tracker, CliffCompaction, AgentDiet).
- Missing: using measured per-step/per-task history to set **how the next task is decomposed and run** (step size, context budget, profile, model) for that class of work. "How Do AI Agents Spend Your Money?" shows models can't predict their own token use (r <= 0.39) and runs vary 30x, which argues for empirical, history-based sizing rather than model self-estimates. That is work-packet's open lane.

### 4.4 Who cares (budget holders)

- **VP/Director of Engineering, platform/DevEx leads** buying Faros/Jellyfish/LinearB/DX; they now face token-metered bills from Copilot (Jun 2026), Cursor (Jun 2025), Claude Code (usage credits/weekly caps).
- **FinOps teams** (FinOps Foundation, FOCUS 1.5 adding token labeling Dec 2026; CAPO/"cost per successful task" vocabulary) who need a unit-of-work denominator.
- **Engineering managers running agent fleets / platform teams** for long-running autonomous work (Anthropic's long-running harness pattern), where per-session cost reaches $40-65/PR (Sonar) and per-dev P90 $481/month (LinearB [S]).
- In semiconductor/EDA: verification managers whose budget is per-block/per-milestone; a project -> packet -> step cost ledger maps onto how they already plan and charge work.
- Individual Max/Pro power users hitting weekly caps (a cost-per-task view tells them which tasks burn the cap).
