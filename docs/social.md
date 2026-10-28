# Social: discovery, questions and shared knowledge between packets

Status (2026-10-25): design for review. Nothing here is built. It turns
the notes in `docs/work-packet-social.md` into a design. It builds on
`docs/product.md`, which already moves packets between people (links,
the hub, assign, consult, reports). This document adds what those
sections lack: finding people and knowledge, asking questions, and
showing work in the channels people already read.

Contents: §1 summary · §2 what the notes ask for · §3 what product.md
already covers · §4 prior art · §5 design · §6 inside an organization
and in open source · §7 security · §8 open issues · §9 overlooked
opportunities · §10 recommendations and build order · §11 decisions ·
sources · status log.

## 1. Summary

**Findings.**

1. About half of the notes are already designed in product.md: the
   federated network, nodes that connect, packets that move between
   users, inside an organization and across organizations (§3). The new
   half is a **knowledge layer** (search, questions, findings) and a
   **channel layer** (posting to and reading from mail, issues, Teams
   and Confluence).
2. The prior art agrees on four points:
   - Moderation and abuse are what stall federation; transport does
     not (Forgejo federation, the fediverse).
   - Agent-to-agent "social networks" turn into noise and prompt
     injection when agents post by themselves (Moltbook, 2026).
   - Open-source maintainers are now defending themselves against
     AI-generated reports (curl ended its bug bounty in January 2026;
     GitHub added PR kill switches).
   - The tools people value suggest and let a human accept (Linear
     Triage Intelligence, Devin knowledge suggestions, Copilot's
     approver rule).
3. work-packet has a real advantage here that most of the prior art
   lacks: **a packet can prove things**. Its recipe and smoke check
   re-run, and its journal shows how a conclusion was reached. A
   question that carries a reproduction, or an answer that carries a
   verification, is worth more than a chat message. That property
   should run through every social feature.

**Conclusions.**

- **Don't build a social network. Build a few social *objects* that
  travel over links, hubs and existing channels.** The objects are a
  card (who I am and what I accept), a finding (something learned,
  with evidence), a question, an answer and a post. A feed is the
  least valuable of these; findings and questions are the most
  valuable.
- **The unit of knowledge is a finding, not a packet.** Packets are
  work in progress, private by default and large. Findings are small,
  publishable on their own and checkable. Today nothing in the format
  holds them.
- **The searching side pays the tokens, the listening side pays
  nothing by default.** Knowledge is published as **index snapshots**
  that others download and search locally at zero cost to the
  publisher. A question is sent only after the sender has searched.
  It then arrives in a batched, budgeted inbox, and a quarantined
  model with no tools sorts it before any agent or person reads it.
- **Existing channels are syndicated copies, not the source of
  truth** (POSSE, from IndieWeb). The packet stays canonical. A post
  to Teams or a GitHub issue carries a link back, and replies are
  pulled back into the journal. Each user's own daemon posts with
  their own token, with no hosted bridges (Matrix retired its Slack
  bridge in January 2026 over cost).

**Recommendations, in order** (§10):

| Step | What | When |
|---|---|---|
| **K0** | **first application: the weekly post.** A digest of the week's public packets, drafted by a scheduled packet, edited by you, published on your site and syndicated to LinkedIn, Mastodon and Bluesky (§5.9) | now; needs only today's journals |
| K1 | findings in the packet format; a local index; `wpk search`; an MCP tool so agents search before they ask | with R4 (needs nothing from anyone else) |
| K2 | index snapshots shared over links; questions and answers over links; the triage inbox and budgets | with R5 |
| K3 | channel adapters: forge issues (GitHub and Forgejo) and email first; Teams and Confluence as post-only | with R5–R6 |
| K4 | hub: the merged organization snapshot, "who has solved this" from findings, suggested posts, the intake packet for priorities | with R6 |
| K5 | open source: a published card, identity proofs, the reproduction gate at intake, respect for each project's AI policy | with R7 |

## 2. What the notes ask for

From `docs/work-packet-social.md`, grouped:

| # | Ask | Covered by |
|---|---|---|
| A1 | always a federated network | product.md §5.1 (already a principle) |
| A2 | nodes publish their existence | §5.1 cards (new) |
| A3 | nodes connect | product.md §7.4 links; §5.1 here for discovery before a link |
| A4 | connect to existing channels: mail, GitHub issues, Gist, Confluence, Teams; for less overhead and more security | §5.6 channels (new) |
| A5 | move packets across users easily | product.md §11.7 assign and consult |
| A6 | share information and raise questions easily and safely | §5.3 findings, §5.4 questions (new) |
| A7 | agents discover and search shared information; index snapshots for fast local search | §5.3 index snapshots (new) |
| A8 | "question pings" | §5.4 (new) |
| A9 | don't burden the listening agent with tokens: opt-in, or batch (review incoming, assess, update) | §5.5 triage inbox (new) |
| A10 | maximize "AI connected to the social network" | §5.3 MCP tools, §9 |
| A11 | works inside an organization and publicly | §6 |
| A12 | a built-in social aspect: suggest activity posts from what gets attention | §5.7 posts (new) |
| A13 | suggest priorities from incoming work (issues) | §5.8 the intake packet (new) |

## 3. What product.md already covers, and the gap

product.md is a design for **moving work**. It has:

- four scales, one protocol (§5.1);
- links between daemons with a `peer` scope that never runs anything
  (§7.4);
- a hub that indexes and relays but runs nothing (§11.4);
- export profiles that carry less the further they go (§11.1);
- reports across organizations, with public intake (§11.6);
- assign and consult (§11.7);
- untrusted import (§12).

None of that needs to change.

The gaps:

| Gap | Why it matters |
|---|---|
| No way to **find** a person, a node or a past answer before you have a link | A3 assumes you already know whom to link to. In an organization the hub directory helps. In open source nothing does |
| Questions go only to **named** people (consult) or to the packet's owner (`ask:`) | No way to ask "has anyone seen this UVM phase hang?" of a team or a topic |
| Nothing is **shareable smaller than a packet** | Sharing what you learned means sending the whole packet (a `team` bundle) or retyping it into chat |
| The hub's summaries are **state**, not **knowledge** | D5 shares title, state, owner and waiting since. That's enough for a team board, not for search |
| No **channel** other than wpk's own | The notes want mail, issues, Teams and Confluence. Only CI and forge issues (for reports) appear in product.md |
| No **cost model** for the listener | A consult's copy is opened by a person. An agent that answers questions automatically has no budget |

## 4. Prior art

Three research passes on 2026-10-25 covered:

- federation and identity;
- agent-to-agent systems;
- knowledge sharing, work routing and reproducible hand-off.

The table keeps what bears on the design; sources are at the end.
Items marked *(unverified)* rest on one secondary source.

### 4.1 Federation, discovery and identity

| System | What it is | Lesson for work-packet |
|---|---|---|
| **ActivityPub / AS2, WebFinger, NodeInfo** | Signed POSTs to per-actor inboxes. Discovery: WebFinger resolves `acct:user@host`, and NodeInfo describes a server at `/.well-known/` | Copy the discovery layer and the vocabulary (`Create`, `Offer`, `Question`). Sign with RFC 9421 HTTP Signatures and ed25519 from the start; the fediverse has been stuck on the old draft for years |
| **ForgeFed / Forgejo federation** | AS2 extended for repositories, tickets and patches | Started in 2023; only federated stars shipped. The Forgejo FAQ calls it experimental because "moderation and access control have not yet been developed". **Build revocation, scopes and blocking before cross-organization transfer** |
| **Fediverse moderation** | Domain blocklists; IFTAS (trust and safety) ran out of money in 2025; Oliphant's blocklist retired for FIRES in 2026 | Volunteer moderation doesn't pay for itself. Public intake needs mechanical gates, not moderators (§5.4, §7) |
| **AT Protocol (Bluesky)** | DID per account, PDS holds signed records, relays and AppViews index them, Lexicon schemas, pluggable labelers. Private data ("Spaces") only reached alpha in 2026 | The closest structural match: wpkd ≈ PDS, hub ≈ relay plus AppView, packet schemas ≈ Lexicons, organization policy ≈ labeler. The index is derived data and the hub is replaceable |
| **Tangled** | git collaboration on atproto: self-hosted "knots" hold repos and "spindles" run CI; social records live in users' PDSes. Raised $4.5M (March 2026) | Shows self-hosted work with a shared index. Pitches "human or agent" participation |
| **Radicle** | Peer-to-peer git: node keys, issues and patches as signed op-logs in git ("COBs"), per-repo choice of what to seed. 1.10 in Sept 2026 | The journal is a natural COB. "Seeding policy" is a model for what each link may pull. Small adoption despite good engineering, so don't ask users to run a new network |
| **Nostr NIP-34, ngit** | Signed events on relays; git repos announced over Nostr. Block's "Buzz" (2026) is a workspace for "teams of humans and AI agents" on Nostr *(unverified)* | Many dumb mirrors is a good model for bundle stores. Buzz is the closest product to read |
| **Secure Scuttlebutt** | Append-only signed feeds, gossiped. Faded | Joining needed the full history (gigabytes). **Never require full sync: summaries first, journals on demand** |
| **Matrix** | Federated rooms, bridges | The matrix.org Slack bridge was retired on 2026-01-13 over cost. **Hosted bridges to closed platforms are a treadmill** |
| **public-inbox, lore, lei, b4** | Mailing lists archived as git; `lei` runs saved searches against mirrors and pulls results into a local maildir; b4 fails over between mirrors | **This is the index snapshot pattern, in production for the Linux kernel**: a shared index you clone or query, results pulled local, Message-ID as a global ID, email as the zero-onboarding transport |
| **IndieWeb: POSSE, Webmention, Bridgy** | Publish on your own site, syndicate copies to silos with links back, backfeed replies | **The model for A4**: the packet is canonical, posts elsewhere are copies |
| **Keyoxide, Sigstore/gitsign, did:web** | Two-way identity proofs (the key names the account, the account names the key); short-lived certificates from an OIDC login; a DID at a web URL | Solves "is this really Alice?" before a link is accepted. Gives D8/D11 in product.md concrete options |

### 4.2 Agent-to-agent systems

| System | What it is | Lesson |
|---|---|---|
| **A2A** (Linux Foundation; v1.0 in April 2026) | Agent Cards at a well-known path (signed in v1.0; an extended card after login); tasks with `INPUT_REQUIRED`; webhook push | A signed **card** and a public/authenticated split are what A2 needs. A question maps onto a task. Stay close enough to A2A that a bridge is cheap. Don't adopt its full binding matrix |
| **MCP** (now at the Agentic AI Foundation) | Tools; Tasks ("call now, fetch later", 2025-11-25); a registry | **Expose search and the question inbox to Claude Code as MCP tools.** Agents then reach the network through tools, not prompt plumbing |
| **ANP, AGNTCY dir, NANDA** | `did:wba` identities served over HTTPS; federated, signed agent directories; NANDA's lean index pointing at signed "AgentFacts" | The hub index should be lean pointers plus summaries; the owning daemon serves the detail. That is already product.md §11.4; NANDA confirms it |
| **IBM ACP** | Merged into A2A in Aug 2025 | Don't invent a wire protocol |
| **Microsoft NLWeb** | `/ask` per site, also an MCP server; a path-traversal bug exposed `.env` files (fixed June 2025) | "Every node answers `/ask` from its index" is a good idea. Any endpoint that reads packet directories needs strict path confinement |
| **Entra Agent ID / Agent 365** | Agents get their own directory identity, distinct from the human | Label what an agent wrote as the agent's, on behalf of a person, in every object (§5.2) |
| **Moltbook** (Jan 2026; bought by Meta, Mar 2026) | A Reddit for agents. Joining installs a skill that fetches and executes a server's `heartbeat.md` every few hours | The anti-model: **remote instructions executed by a local agent are remote code execution**. A Supabase key exposed 1.5M agent tokens. Agents prompt-injected each other. A study of 1.3M posts found 3.3% reciprocal interaction, 85.6% of threads never past one reply, and about 10% spam. **Agents posting by themselves produce noise** |
| **OpenClaw / ClawHub** | 386 malicious skills uploaded in three days (Feb 2026) | Shared templates and skills are a supply chain: pin by hash, review before use |
| **GitHub Copilot coding agent** | Only users with write access can trigger it; comments from others never reach it; the person who assigned it can't approve its PR | Two rules to copy: **only trusted text reaches the agent**, and **whoever delegates can't self-approve** |
| **Linear Agent Interaction Guidelines; Devin; Rovo** | The human stays the accountable assignee; agents disclose and show their state; the agent proposes knowledge and the human accepts | The suggest-then-accept pattern for posts, findings and priorities |
| **LangChain Agent Inbox** | Ambient agents interrupt humans only to *notify*, *ask* or *review*, in one inbox | Three kinds of inbound item; one inbox |
| **Notification batching** (Fitz, Kushlev et al., 2019, n=237) | Batching three times a day lowered stress; turning notifications off raised anxiety | **Default to triage windows, two or three a day**, not real time and not off |
| **Prompt injection**: GitHub MCP exploit (May 2025), the "lethal trifecta", *Design Patterns for Securing LLM Agents* (2025), CaMeL | An issue hijacked an agent that had private repo access and posted the data publicly. Private data + untrusted content + an outbound channel = exfiltration | A packet agent that reads questions and can reply has all three. **Break one leg**: triage runs in a quarantined context with no tools and no private data (Dual LLM / Map-Reduce patterns); outbound actions derived from remote content need a human |
| **AGENTS.md, Agent Skills, Letta shared memory** | Repo guidance files and skills, both at the Agentic AI Foundation; shared memory blocks any agent can write | Packets can follow the AGENTS.md convention. **Subscribe to others' knowledge; don't let it write into your context** |

### 4.3 Knowledge sharing, routing, reproducible hand-off

| System | Lesson |
|---|---|
| **Stack Overflow → Stack Internal** | Public questions down about 78% year on year by December 2025; developers ask AI instead. The internal product now sells "verified human knowledge to feed AI". **Verified, attributable answers are the asset; a separate Q&A site is not** |
| **Expert finding research** | Most methods mine commit history; real choices weigh availability. **The journal is a better expertise signal than commits** (who resolved which kind of failure). Opt in, show availability, never auto-assign |
| **Glean** | Ingests each source's access lists and enforces them per document at query time. **The index carries the source's permissions**; it doesn't invent its own |
| **Backstage, CODEOWNERS** | Ownership already exists in catalogs. **Read them; don't keep a parallel owner table** |
| **Google Snippets** | Weekly "what I did / will do", written by the author and readable by all. **Draft it from the journal; the person edits and sends** |
| **GitHub dashboard redesign** (2025–26) | The home page moved from a social feed to "things waiting on me"; the algorithmic feed drew pushback. **"Needs you" first; posts are secondary** |
| **Workplace surveillance research** | Activity metrics about people produce productivity theater and distrust. **Never publish attention or time metrics about people** |
| **Pernosco, Replay.io** | The hand-off is a link to something replayable plus notes; Replay now feeds its recordings to an AI for root cause. Confirms the packet |
| **LLVM bug guide, cvise, llvm-reduce** | A reducer's "interestingness test" is a command that exits 0 if the bug is present. **That is the report's smoke check**; it allows automatic reduction. No HDL testcase reducer is in common use, which is a gap |
| **Cadence Verisium AutoTriage, Siemens Questa Regression Navigator** | Group regression failures by likely common cause and route them to engineers. These are the incumbents for "priority from incoming work" in DV |
| **Synopsys Verdi IDX** | Extracts an IP-level FSDB so an SoC team can send a vendor a failing scenario without the rest of the chip. **Cross-organization DV reports need extraction to an IP boundary**, not only file selection |
| **GitLab Service Desk, sourcehut lists** | Email in, confidential issue out, with no account needed. Email is the universal cross-organization channel |
| **Gists** | Git-backed, so a bundle or snapshot can be a gist. "Secret" gists are only unlisted: **not for proprietary data** |
| **Slack Connect** | Cross-organization channels; accidental exposure is the main risk, and DLP is Enterprise-only. **Scan before anything crosses a boundary** |
| **gh-aw triage, Linear Triage Intelligence, Dosu** | Label, find duplicates, ask follow-ups, never auto-close; show reasoning; accept or decline. Dosu cut Superset's median first response from about 2 days to under 5 minutes |
| **AI slop in open source**: curl, GitHub PR controls, project AI policies | curl's valid security reports fell from about 1 in 6 to 1 in 20–30, and it ended its bounty. GitHub added settings to disable or restrict PRs (Feb 2026). Gentoo, NetBSD and QEMU ban AI contributions; LLVM and Linux require human review and an `Assisted-by:` trailer. **A network that makes it easy for agents to file things at strangers will be read as a slop cannon unless it has friction that proves value** |

## 5. Design

### 5.1 Social objects

Six small objects, each a file with frontmatter or a JSON document,
signed by the daemon that made it. Each object names a human author and,
where an agent wrote it, the agent (`assisted_by`). The names follow
Activity Streams where one fits, so an ActivityPub or A2A bridge later
is mapping, not redesign.

| Object | AS2 type | What | Lives in |
|---|---|---|---|
| **card** | `Service` / A2A Agent Card | who a node or person is, the key, what they accept (intake templates, question topics), budgets, availability, AI policy | `$WPK_HOME/card.toml`, served at `/.well-known/wpk` and copyable to static places (§5.2) |
| **finding** | `Note` (with evidence) | one thing learned: claim, evidence, scope, verification | `state/findings/<slug>.md` in a packet |
| **snapshot** | `Collection` | a searchable index of the findings and summaries a node shares | a signed file (§5.3) |
| **question** | `Question` | text, context (packet address, what the sender already searched), audience, due, budget hint | sender's outbox, receiver's inbox |
| **answer** | `Note` in reply to a question | text, optional finding, optional changes (a git bundle, as in a consult reply) | as above |
| **post** | `Create` / `Note` | a short update about a packet's outcome, linking to its address | syndicated to a channel (§5.6) |

Assign, consult and report (product.md §11) stay as they are. Under this
vocabulary they are `Offer`s of a bundle.

### 5.2 Cards and discovery (A2, A3)

A **card** is how a node "publishes its existence". It is not a link:
reading someone's card gives you nothing of theirs. Linking stays
mutual and explicit (product.md §5.1 rule 5).

```toml
# $WPK_HOME/card.toml
id       = "wpk:node:3f9c…"            # hash of the public key
person   = "Matthew Ballance"
key      = "ed25519:…"
proofs   = ["https://github.com/mballance", "https://codeberg.org/mballance"]  # each names this key back
endpoint = "https://hub.example.com/u/mballance"   # where to send; a relay, not the daemon, in public
accepts  = ["question:topic/pyvsc", "question:topic/uvm", "report:pyvsc", "consult"]
budget   = { questions_per_day = 10, triage = "2x daily" }
ai_policy = "assisted ok; human sign-off required"
```

Where a card is found depends on the scale:

| Scale | Discovery |
|---|---|
| your hosts, a tailnet | Tailscale already lists the peers; `wpk link add` with a name |
| organization | the hub directory (product.md §11.4): cards, teams, and topics drawn from published findings ("who has solved this", §5.3) |
| open source | **static places that already exist**: `.wpk/intake.toml` in a repo (product.md §11.6) names the project's intake; a person's card goes in a profile repo, a gist or their domain (`/.well-known/wpk`, or WebFinger). Keyoxide-style two-way proofs tie the key to forge accounts |

A personal daemon is usually behind NAT or on a tailnet, and should not
be on the open internet. So a public card names a **relay**: the
person's organization hub, or a project's intake. It never names the
daemon itself.

### 5.3 Findings and index snapshots (A6, A7, A10)

**Findings.** The agent writes findings in `state/findings/` while it
works. The system prompt says when: a root cause, a workaround, a "this
tool version does X", a dead end worth recording. The owner may also
write them by hand. Each has:

```markdown
---
claim: "Questa 2025.3 hangs in run_phase when uvm_objection drain time is 0 and …"
scope: {repos: [pyhdl-if], tools: [questa@2025.3], tags: [uvm, objection]}
evidence: {packet: "wpk:01J…", steps: [12, 14], commit: "a1b2c3d"}
verify: "make -C tests sim TEST=drain0"     # exits 0 if the claim still holds (optional)
verified: 2026-10-24
author: mballance
assisted_by: claude-sonnet-5
share: team                                  # private | team | org | public
---
Body: what, why, and what to do about it.
```

A finding with `verify` is a **checkable** finding. Someone else's
daemon can re-run it, in a sandbox, at their revision. That is the
difference from a wiki page or a chat answer, and the reason anyone
would trust a finding from a stranger.

**Snapshots.** `wpk publish` builds a snapshot from everything a node
shares at a given level:

- findings;
- packet summaries (title, outcome, scope tags, address);
- open questions the owner chose to make public.

A snapshot is a signed SQLite file with an FTS5 index. Optionally it
also holds small embeddings. Snapshots are content-addressed and
segmented, so an update is a few new segments, as zoekt shards or lei's
incremental fetches are.

- Links pull your snapshot at your share level for them.
- The hub merges members' snapshots into an organization snapshot, with
  each entry carrying its share level. Glean's lesson: the index
  enforces the source's permissions.
- In open source, a project publishes its snapshot next to its releases
  or in a gist, and anyone can download it.

Searching is local: `wpk search "objection drain hang questa"` across
your own packets and every snapshot you hold. It is also an MCP tool,
`wpk.search`, that every step's agent has. **Searching costs the
publisher nothing**: no daemon is woken and no tokens are spent. That is
the "index snapshot" in the notes, and the same pattern the kernel
community uses with lore and lei.

### 5.4 Questions (A6, A8)

A question goes to an **audience**:

- one person (that is a lightweight consult, without a copy);
- a team;
- a topic (`topic/uvm`, routed to cards that accept it);
- a project's intake.

**The sender pays.** Before a question leaves, the sender's daemon:

1. runs `wpk search` on it and attaches the top hits as `searched`, so
   the receiver sees what the sender already ruled out;
2. if a hit is a verified finding that matches closely, offers it and
   asks the sender to confirm the question is still needed;
3. attaches context only by reference: a packet address and, for
   reproducible questions, a `report` bundle (product.md §11.1). The
   smoke check is "the thing I'm asking about happens".

A question from an agent (`ask:` addressed to a team or topic, not to
the owner) is a draft. The owner approves it before it leaves, as with
D13 in product.md, in reverse. Agents never ping strangers by
themselves.

**Answers.**

- An answer goes back to the sender's inbox and is attributed to its
  author.
- The sender (not the answerer) can mark it **accepted**.
- If it comes with a `verify` command that passes on the sender's side,
  it is **verified** and becomes a finding in the sender's packet, with
  the answerer credited.
- This is how knowledge accumulates without anyone curating a wiki.

### 5.5 The listener: inbox, triage and budgets (A9)

This is the part the notes worry about most. Everything inbound
(questions, consult requests, assignment offers, reports, channel
mentions) goes through one pipeline. No step of it uses the receiver's
main agent.

```
inbound ──► 1. gate (deterministic) ──► 2. queue ──► 3. triage window ──► 4. person ──► 5. optional agent
            link/card allowlist         inbox/       2-3x daily, or        sees one       only on items the
            quotas per sender           (files)      on demand             batch          person sends on,
            size limits, signatures                  quarantined model:    accept /       as a new packet
            dedupe against own index                 no tools, no private  answer /       or a note
            auto-reply from index                    data, structured out  decline
```

1. **Gate.** Nothing that fails a signature, quota, size or allowlist
   check is stored. A question that the receiver's own snapshot answers
   gets an automatic reply with the matching findings. This is NLWeb's
   `/ask` idea, with no model involved.
2. **Queue.** Files under `$WPK_HOME/inbox/`, as product.md §7.2
   already has.
3. **Triage.** At the receiver's chosen times (default twice a day),
   one call to a small model reads the batch. It has no tools and no
   access to the receiver's packets; it sees only the inbound text and
   the receiver's card. Its output is structured, one entry per item:
   - `kind`: notify, question or review;
   - `topic`;
   - `likely_answerable_from` (a list of the receiver's own finding IDs
     by title, already public to the sender);
   - `effort`: minutes or hours;
   - `suggested`: answer, forward, decline or ignore.

   This is the Dual LLM / Map-Reduce pattern. Untrusted text never
   meets private data or an outbound channel in the same context.
4. **Person.** The board's **Asked** column shows the batch, sorted.
   The person answers, declines, or forwards.
5. **Agent, only by choice.** "Draft an answer with my agent" creates a
   new packet with the person's instruction. The question is quoted as
   the asker's text, never as the instruction (product.md §12). The
   draft needs approval before it goes out.

**Budgets.** Configured per card and per link: questions per day,
triage spend per day, and the most an agent draft may cost. Each answer
records its cost, so both sides see what a question cost. Over budget,
items wait for the next window or are declined with a polite automatic
reply. Opt-in, which the notes ask for, is the default: a card that
doesn't list `accepts = ["question:…"]` gets no questions, only consults
from linked people.

### 5.6 Channels (A4)

The packet is canonical; channels carry copies (POSSE). An adapter has
three operations:

```
publish(object) -> url        post a question, finding, post or report summary; link back to the address
ingest(since)   -> objects    read new items (issues, mail, mentions) as inbound objects for §5.5
backfeed(url)   -> replies    read replies to something published, into the journal as notes
```

Adapters run in the user's daemon with the user's own token. There are
no hosted bridges. What we post is ours to keep; what we read is
untrusted input (§7).

| Channel | publish | ingest | backfeed | Notes | Order |
|---|---|---|---|---|---|
| **GitHub / Forgejo issues** | report as an issue with the bundle attached; question as a Discussion | issues and labels on watched repos; CI artifacts (product.md §11.2) | comments | API drift is the cost (git-bug's bridges break on token format changes). Forgejo first: it is the user's forge, and ForgeFed later | 1 |
| **Email** | question, report, weekly digest | a per-node address (`wpk+<topic>@…`), like GitLab Service Desk; IMAP or a forward | replies by `Message-ID` / `In-Reply-To` | works across every organization with no account; bundles as attachments; DKIM gives weak identity | 1 |
| **Files and gists** | snapshot, report, card | import by URL | none | gists are git, so a snapshot or a card can be one. Unlisted is not private: refuse anything above `public` | 2 |
| **Teams / Slack** | post and question summaries via an incoming webhook or bot | mentions only, if at all | thread replies (bot) | a Teams bot needs tenant admin consent, so start with webhook posting only. Matrix's bridge shutdown is the warning against more | 3 |
| **Confluence** | a page per project: published findings and a digest | none | page comments, optionally | publishing findings to the organization's wiki is where Confluence pays off: the wiki is kept current by work, not by people | 3 |
| **Generic webhook / SSE** | every event | `POST` to the inbox with the `ci` or `peer` scope | — | covers n8n, Zapier and anything else | 2 |

### 5.7 Posts (A12)

Posts are **drafted, never sent** by the system. Drafts come from
signals, and the signals are about **packets and outcomes, never
people**:

| Signal | Draft |
|---|---|
| a batch completed with a verified finding | "Root cause for the pyhdl-if objection hang: … (finding, packet)" |
| a packet was imported, consulted or searched-and-opened by N others this week | "The UART RX FIFO packet is getting attention; here's where it stands" |
| an answer was accepted and verified | "Thanks @x: … is now a finding" |
| a report reproduced, or a fix landed upstream | "Fixed in pyvsc a1b2c3d: …" |
| weekly | a Snippets-style "done / next / blocked", from journals |

The owner edits and sends, to whichever channel the project names. No
counts of a person's activity appear anywhere. Attention counts are per
packet and are visible only to the owner.

### 5.8 Priorities: the intake packet (A13)

Priority suggestion is itself work, so it is **a packet**. An intake
packet is a long-running, scheduled packet (`resume: every weekday
08:00`) with:

- channel `ingest` as its inputs (watched repos' issues, CI failures,
  the inbox);
- its instruction: "propose a ranked list with reasons; look for
  duplicates; don't act".

Its output is a structured `state/suggestions.md`, which the board shows
as a **Suggested** column: accept (becomes a new packet, from
`from-issue` or `from-ci-failure`), dismiss, or snooze. Signals,
following gh-aw and Linear:

- age;
- who's waiting (CODEOWNERS, Backstage);
- duplicates against the person's own index;
- does it come with a reproduction;
- does it touch something they have findings about.

Since the input is untrusted (issue text), the intake packet runs with
read-only permissions, no push and no outbound channel. Its suggestions
are data that the board renders, not instructions to anything.

This makes the feature cheap to build, because it reuses the executor.
It also shows the product's own idea: a recurring piece of work with a
journal.

### 5.9 First application: the weekly post (working in public)

The first use is promotion. Each week you publish what you worked on,
to get people interested in the work and in work-packet. That changes
the order of the build (§10, K0), not the model: the weekly post is a
**post** (§5.7) with a public audience, syndicated through channels
(§5.6), and drafted by a packet (as in §5.8).

**Why this comes first.**

- It needs nothing from anyone else: no links, no hub, no readers
  running wpk. One person, their own journals, public channels.
- The data already exists. Every `commit-end` has the step's summary,
  cost and duration. Every `handoff` lists the commits made since the
  last one. `state/outline.md` holds the plan.
- It is the cheapest test of the "social" idea. If nobody reads what
  packets produce, the rest of this document has a demand problem. If
  people do, the weekly post builds the audience the later steps need.
- **The post promotes the tool by showing it working.** Each item is
  real work (pyvsc, featherweight-ip, dv-solve, work-packet itself)
  done through packets. "Three runs, $0.48" is a better advertisement
  than a feature list.

**Prior art** (general knowledge; no extra research pass):

- *weeknotes*, from UK government digital teams;
- *This Week in Rust*;
- Simon Willison's blog and TILs;
- Julia Evans' zines and posts;
- "build in public" threads;
- game devlogs.

What the ones that last have in common:

- a steady cadence, where missing a week is fine but disappearing is
  not;
- the author's own voice;
- concrete detail: a bug, a number, a picture;
- a link to something people can try or read;
- small surprises worth sharing ("today I learned").

The ones that fade read as marketing, or depend on the author finding
an hour every week.

**How it works.**

```
journals, outlines, commits, findings ──► 1. wpk digest --since 7d --public   (deterministic, no model)
   (public projects only)                   digest.json: packets, batches, commits with URLs, findings, cost
                                         ──► 2. the weekly packet drafts posts/2026-W43.md from digest.json only
                                         ──► 3. you edit (voice, what to leave out), then approve
                                         ──► 4. wpk post: the canonical page on your site, then short
                                                 copies to each channel, each linking back
```

1. **The digest is deterministic and filtered first.** `wpk digest`
   reads only packets in projects marked public (`[share] public = true`
   in `project.toml`, or per packet) and writes `digest.json`:
   - packets touched;
   - batches completed;
   - commits with their public URLs;
   - findings;
   - questions answered;
   - steps, agent hours and cost.

   Private work is either left out or appears as a count ("plus two
   private projects"), as you choose. The model never sees what isn't
   public. That is the leak defence: filter before the model, not after.
2. **The weekly packet** is a scheduled packet (`resume: every friday
   15:00`) in a `weekly` project. Its instruction: "draft this week's
   post from digest.json; 3–5 items, each with what, why, outcome, link;
   one *learned this week*; the numbers box; no claims beyond the
   digest". It has no tools beyond reading the digest and writing the
   draft, and no outbound channel.
3. **You edit and approve.** The draft is a starting point; the voice
   is yours. "Approve" is a board action (or `wpk post approve`).
   Nothing goes out without it (S6).
4. **Publish, POSSE-style.** The canonical post is a Markdown file in a
   site repo, built to a static site with an RSS/Atom feed. Short
   copies go to the channels you name, each with a link back.

**What a post has.**

| Part | From | Why it helps |
|---|---|---|
| title and one-line lede | you | the hook |
| 3–5 items: what, why, outcome, link | `digest.json` (batches, commits, outlines) | concrete and checkable |
| **learned this week** | a finding (§5.3) | the most shareable part; it becomes a public finding too |
| **how it was done** box: packets, steps, agent hours, cost, hand-offs, "ran overnight while I…" | `commit-end` and `handoff` records; `wpk stats` | the advertisement for work-packet, made of facts |
| one picture | a board screenshot, a dv-flow-mgr graph, a waveform | posts with an image get read |
| next week | open outlines | gives readers a reason to come back |
| a call to action | config | try it (`pip install work-packet`), follow, star, or ask a question |

**Channels for promotion.** These differ from §5.6, which is about
working channels:

| Channel | Who is there | How | Order |
|---|---|---|---|
| **your site + RSS/Atom** | everyone; the canonical copy | static site from Markdown (GitHub/Forgejo Pages, or a project site such as dvkit.org) | 1 |
| **LinkedIn** | DV and hardware engineers, managers, EDA vendors | a short post with an image and the link. The API needs an app with member posting permission, so copy and paste at first | 1 |
| **Mastodon / Bluesky** | open-source and tooling developers | both have simple posting APIs (an app token); thread of 2–3 posts | 2 |
| **GitHub/Forgejo Discussions** on the projects mentioned | that project's users | an "updates" category; one post per week per project, only when something happened there | 2 |
| **email newsletter** | people who want it delivered | RSS-to-email (Buttondown or similar), or a mailing list | 3 |
| **Hacker News, Reddit, lobste.rs** | wide reach | by hand, only for a post with a strong single story; never automated | by hand |

**Packet pages.** An item can link to a public **packet page**: a
static export of a public packet's core tier. It shows:

- the instruction and outline;
- a timeline of steps with their summaries;
- commits;
- findings;
- costs.

Transcripts are never included (product.md D1). This is the "show your
work" page that makes the post credible, and the seed of "fork this
investigation" (§9.3). It is the `report` export profile's sibling: a
`public` profile.

**Feedback.** A post's links can carry a per-item tag, and the site can
use privacy-friendly analytics (GoatCounter or Plausible). Together
they show which **items** got clicks and replies. That feeds next
week's draft ("the UART item got the most replies; follow up?"). Counts
are about posts and packets, never about readers.

Replies on Mastodon, Bluesky or Discussions can be pulled back (K3
backfeed) as notes on the packet they were about. A good question from
a reader becomes a question in your inbox (§5.4). That is how
promotion turns into the "ask" side of the network.

**Risks.**

- **AI voice.** Readers notice and discount it. The draft is
  scaffolding; keep its claims to what the digest proves, and say
  plainly that work-packet drafted it. That disclosure is itself
  promotion.
- **Leaks.** A public project can still mention a private customer or
  path. Run a secret scanner, check against a list of names that must
  never appear, and show the full post before it goes.
- **Cadence fatigue.** If a week is empty, the packet drafts a short
  "quiet week" post or nothing; the board reminds you only once.
- **Overclaiming.** A number in the post must come from the digest
  ("verified by the journal").

## 6. Inside an organization and in open source

| | Inside an organization | Open source |
|---|---|---|
| Discovery | hub directory; cards; "who has solved this" from findings | static cards (profile repo, gist, domain); `.wpk/intake.toml` in repos; identity proofs |
| Identity | OIDC through the hub; Tailscale on a tailnet | node key with Keyoxide-style proofs to forge accounts; the hub vouches for its members (product.md D11) |
| Trust default | linked colleagues are trusted to send; agents still don't act on their text | **nobody is trusted**: reports and questions are data; reproduction is the gate |
| Index | merged organization snapshot with per-entry share levels | per-project snapshot published with releases; per-person snapshots at `public` |
| Channels | Teams, Confluence, email, internal forge | GitHub/Forgejo issues and Discussions, mailing lists |
| The valuable object | findings ("we've seen this before"), and questions routed to the right expert | **the report that reproduces**, and verified findings attached to issues |
| Main risk | leaking across project or customer boundaries; surveillance | slop; prompt injection by bug report; maintainer burnout |
| What must exist first | hub policy on share levels (product.md D5) | the reproduction gate and per-sender limits |

**The reproduction gate (open source).** A public intake runs the
report's smoke check in the project's sandbox (product.md D10) before
any person sees it:

- *Reproduced* reports reach the triage column.
- *Did not reproduce* goes back to the reporter automatically, with the
  log.
- Reports with no runnable recipe are accepted only from linked or
  vouched senders.

This turns the AI-slop problem into a feature: an agent can help write
a report, but only a report that actually reproduces costs the
maintainer attention. A project's `.wpk/intake.toml` also states its AI
policy. `wpk report` refuses to file into a project that bans
AI-assisted contributions when an agent wrote any part of the report,
and adds `Assisted-by:` otherwise.

## 7. Security

Additions to product.md §12:

- **Nothing remote is an instruction.** No card, snapshot, question,
  post, channel item or template is ever executed or put to an agent as
  its instruction. This is Moltbook's heartbeat lesson and the GitHub
  MCP issue exploit. Remote text reaches an agent only quoted, under the
  receiver's own instruction, after a person sent it on.
- **Break the lethal trifecta in triage.** The triage model has no
  tools, no private data and no outbound channel. The agent that drafts
  an answer runs in a new packet. Sending the draft needs a person. That
  keeps "private data + untrusted content + outbound" from ever sharing
  one context unsupervised.
- **Provenance on everything.** Every object records where it came from
  (link, channel, card key). The daemon refuses an outbound action
  (send, post, push) whose content was derived from remote input unless
  a person confirmed it. This is a lightweight form of CaMeL.
- **Snapshots are publications.** `wpk publish` shows every entry
  before a snapshot leaves, as export does. A secret scanner runs on
  findings and posts before anything crosses a share level. Slack
  Connect shows how often that leaks.
- **Templates and skills are a supply chain.** Pin them by hash; show
  the diff on update. This is the ClawHub lesson.
- **Revocation and blocking exist before cross-organization
  features**: revoke a link, block a key or a domain, honour a hub's
  blocklist. This is Forgejo's lesson.
- **Path confinement** on every endpoint that reads packet files (the
  NLWeb bug).
- **No metrics about people.**

## 8. Open issues

1. **Who owns a finding after its packet is assigned?** It names its
   author, but the packet (and its `state/findings/`) moves. Proposed:
   findings are signed by their author at publication. The published
   copy is the author's, and the packet's copy goes with the packet.
2. **Retraction.** A finding turns out wrong, or a snapshot leaked
   something. Snapshots are copied by design. We can publish a
   retraction (a signed tombstone that indexes honour) but can't recall
   copies. Users must be told that "publish" means "copied".
3. **Verifying a stranger's finding costs compute and licences.** In DV
   the `verify` command may need a simulator licence the reader lacks.
   Should a finding record what verification needs (tools, licences,
   minutes)? Proposed: yes, in `scope.tools`, and the board shows
   "can verify here: yes or no".
4. **Who pays for an agent-drafted answer?** The receiver spends tokens
   on the sender's question. The budget limits it, but in an
   organization should cost be charged to the sender's project? It
   needs a decision before the hub's audit log is designed.
5. **Topic names.** `topic/uvm` needs a vocabulary. Free tags drift;
   a fixed list doesn't fit open source. Proposed: tags drawn from
   findings' `scope` (repo names, tool names), which are concrete, plus
   free tags, and the hub suggests merges.
6. **Embeddings in snapshots.** They make search better and snapshots
   larger and model-specific. Proposed: FTS5 only in K1; add embeddings
   as an optional segment later if search quality demands it.
7. **Expertise from findings is a ranking of people.** "Who has solved
   this" is useful and is also a person metric. Proposed: opt-in on the
   card (`expert_on = [...]` confirmed by the person), shown only as a
   suggestion when asking, never as a leaderboard.
8. **Export control, NDAs and customer data.** In semiconductor work a
   finding about a customer's design or a vendor's encrypted IP may be
   restricted. Share levels (`private/team/org/public`) are too coarse.
   It may need labels (customer, NDA, export class) that block
   publication across boundaries. These are the organization's
   labelers, in atproto's terms.
9. **IP-boundary extraction for DV reports.** Choosing files is not
   enough. Sending a vendor a reproduction needs the failing scenario
   cut down to their IP, as Verdi IDX does for waves. A real version is
   tool-specific and not designed here.
10. **Air-gapped organizations.** Many semiconductor sites have no
    outbound internet. Everything must work by file: cards, snapshots,
    reports and answers as signed files moved by hand. The design allows
    it (every object is a file). It should be a stated requirement and
    tested.
11. **Is "social" the right word?** "Worker social network" invites the
    Moltbook comparison and the surveillance worry. The valuable parts
    are search, questions and findings. Proposed: name the feature
    **Ask and share** in the product, and keep "network" for the
    architecture.
12. **The hub as a single point.** In atproto, relays recentralised in
    practice. Snapshots that any member can mirror (as lore is mirrored)
    keep search working with the hub down. Should that be required?
    Proposed: yes, for the organization snapshot.
13. **Teams and Confluence access.** Both need app registration by a
    tenant administrator to do more than post through a webhook. In a
    large organization that is a slow approval. Plan for post-only
    first.

## 9. Overlooked opportunities

1. **Answers that come with a test.** No Q&A system can say "this
   answer is still true at today's revision". A finding with `verify`
   can, and the network can re-check findings as tools and repos move
   (a scheduled packet that re-verifies, and marks stale ones). That is
   Stack Internal's "verified knowledge" pitch, built from work instead
   of curation.
2. **Reproduction as the spam filter.** Requiring a working smoke check
   for public reports converts the biggest current pain in open source
   into the product's selling point (§6).
3. **"Fork this investigation".** A finished packet with its recipe is
   a worked example. Publishing it (core tier, `public`) as a template
   lets others start from it: "the same bisect, on my repo". Templates
   (product.md §7.5) then grow from real work.
4. **An HDL testcase reducer.** LLVM has llvm-reduce and C has cvise;
   SystemVerilog has nothing in common use. A report's smoke check is
   already an interestingness test. An agent-driven reducer packet
   ("reduce this report until it is minimal and still fails") would be
   valuable on its own, and for vendor support cases especially.
5. **Upstream feedback from fixes.** When a report's fix lands
   (`fixed in <commit>`), every packet whose findings cite that bug can
   be told, through the snapshot's cross-references. That closes a loop
   that issue trackers leave open.
6. **The hub as the organization's agent memory.** Organizations are
   buying "knowledge layers" to feed their AI (Glean, Stack Internal).
   The organization snapshot is one, kept current as a side effect of
   work, and exposed to any MCP client, not only to wpk's agents.
7. **Your agent asks theirs a factual question, with no person
   involved.** For questions a published snapshot answers, the gate
   (§5.5 step 1) replies with no model and no person at all. Most
   "has anyone seen X" traffic could end there.
8. **CI as a social source.** A failing nightly in a shared repo is a
   question nobody asked: "who has seen this failure?". The CI bundle
   (product.md §11.2) plus a search of the organization snapshot can
   attach likely findings before the owner even opens it, as
   Verisium-style triage does, but across projects.
9. **Credit.** Accepted and verified answers name their authors. Over
   time, that is a record of help given across teams and across
   companies. Open-source maintainers in particular lack such a record
   (CHAOSS measures responsiveness, not help). It must stay the
   person's to show, not a ranking (§8.7).
10. **Cross-organization status without a call.** The report round trip
    (product.md §11.6) already shows "reproduced / fixed" back to the
    reporter. For IP vendors and customers that replaces a large part of
    the support-case portal: the customer sees the vendor's progress on
    their own board.

## 10. Recommendations and build order

0. **Start with the weekly post (K0, §5.9).** It is the first
   application: promotion of the work and of work-packet, built only
   from your own journals. It tests whether anyone wants to read what
   packets produce before the rest is built. It also builds the
   audience, the public findings and the packet pages that K1–K5 use.
1. **Keep the scope narrow: objects and pipes, no feed.** Build cards,
   findings, snapshots, questions, answers and posts as files that move
   over the links and hub of product.md. Don't build timelines,
   followers, likes or a web of everyone.
2. **Start with what works alone (K1).** Findings in the format, a local
   index, `wpk search` and the `wpk.search` MCP tool help one user on
   day one, because the agent finds what earlier packets learned. Every
   later step only widens what is searched.
3. **Make the listener safe before making asking easy (K2).** The gate,
   the triage window, budgets and the quarantined triage model come in
   the same release as questions, not after.
4. **Two channels first (K3): forge issues and email.** Both are
   universal across organizations, both have stable identifiers for
   backfeed, and the user already has both. Teams and Confluence as
   post-only after.
5. **Make the hub a knowledge index, not only a state index (K4).** Add
   the merged snapshot, "who has solved this", suggested posts and the
   intake packet. Require the snapshot to be mirrorable.
6. **Open source last, with the reproduction gate built in (K5).**
   Public cards, identity proofs, intake that reproduces before a
   person looks, and each project's AI policy respected.
7. **Align the vocabulary now, implement the protocols later.** Name
   fields after AS2 and A2A; sign with RFC 9421 and ed25519; serve
   `/.well-known/wpk`. Don't implement ActivityPub, atproto or A2A
   until a user needs one; each becomes a bridge, not a rewrite.

| Step | Release (product.md §14) | Contents | Exit |
|---|---|---|---|
| **K0** | now, beside R1 (needs only today's journals) | `[share] public` in `project.toml`; `wpk digest --since --public`; the `weekly` project template with its scheduled packet; `wpk post` writing the canonical Markdown to a site repo; per-channel short copies to paste (LinkedIn) or post (Mastodon/Bluesky by token); a secret and banned-name check; static packet pages (`public` profile) | four weekly posts in a row, published from real work (work-packet itself, pyvsc, featherweight-ip), each taking under 15 minutes of editing; at least one reader question that leads to a reply |
| **K1** | R4 | `state/findings/` in spec v0.3, with the system-prompt rule for when to write one; `wpk findings`; local FTS index; `wpk search`; `wpk.search` MCP tool in every step | on dvs-enh or fw-uart16550, a new packet's agent finds and cites a finding from an earlier packet without being told |
| **K2** | R5 | card; `wpk publish` (snapshot, with preview); snapshots over links; `wpk ask` to a person or a team of links; inbox gate, triage window, budgets, the **Asked** column; answers, accept, verify → finding | two people linked; one asks, the other's gate answers from a snapshot with no model; a second question goes through triage and is answered by a person; the answer verifies and becomes a finding |
| **K3** | R5–R6 | adapters: Forgejo/GitHub issues and email (publish, ingest, backfeed); webhook out; post drafts from journal signals | a question posted as a Forgejo Discussion, answered there, appears in the packet's journal; a weekly digest drafted and sent by email |
| **K4** | R6 | organization snapshot on the hub, mirrorable; topics and "who has solved this"; the intake packet and the **Suggested** column; Teams and Confluence posting | a CI failure in featherweight-ip arrives with a likely finding attached; the intake packet ranks a week of issues and the owner accepts two |
| **K5** | R7 | public cards and proofs; topic routing to cards; intake reproduction gate; AI-policy check in `wpk report`; retraction tombstones; blocklists | a report from outside reproduces at a pyvsc intake and reaches triage; a non-reproducing one goes back automatically; a project with a no-AI policy refuses an agent-written report |

## 11. Decisions

Each has the default this design assumes. The numbering continues
product.md §13 under a separate letter.

| # | Decision | Default assumed | Options |
|---|---|---|---|
| S1 | The unit of shared knowledge | **finding**, separate from the packet | packet summaries only; free-form notes |
| S2 | Snapshot format | **signed SQLite FTS5, segmented**; embeddings later and optional | JSONL plus a local index built on import; a search service on the hub instead of snapshots |
| S3 | Who may send you questions | **linked people, and cards listed in `accepts`**; nothing else | anyone in the organization; anyone with a card |
| S4 | Default triage cadence | **twice daily**, plus on demand | real time; once daily |
| S5 | Do agents send questions? | **drafts only; the owner sends** | agents send within a budget; never |
| S6 | Posts | **drafted, never sent automatically** | auto-post within a project; none |
| S7 | First channels | **Forgejo/GitHub issues and email** | Teams first (organization users); Slack |
| S8 | Wire vocabulary | **AS2 names, RFC 9421 signatures, `/.well-known/wpk`; no ActivityPub server** | full ActivityPub; A2A; our own |
| S9 | Public reports without a recipe | **only from linked or vouched senders** | never; always, into a lower queue |
| S10 | Feature name | **Ask and share** | Social; Network; Exchange |
| S11 | Where the canonical weekly post lives | **a static site from a Markdown repo, with RSS** (Forgejo/GitHub Pages; or dvkit.org) | LinkedIn articles; a newsletter service; a blog host |
| S12 | Which work is public | **opt-in per project** (`[share] public = true`); private work left out entirely | private work shown as counts; opt-out |
| S13 | First promotion channels | **site + LinkedIn (pasted), then Mastodon/Bluesky (by token)** | LinkedIn only; Discussions only |
| S14 | Cadence | **weekly, Friday draft**; a quiet week posts nothing | fortnightly; per batch completed |

## Sources

Federation and identity:
[Forgejo FAQ](https://forgejo.org/faq/),
[Forgejo federation roadmap](https://codeberg.org/forgejo-contrib/federation/src/branch/main/FederationRoadmap.md),
[ForgeFed](https://forgefed.org/),
[Mastodon 4.7 (RFC 9421)](https://blog.joinmastodon.org/2026/08/mastodon-4.7/),
[IFTAS shutdowns](https://about.iftas.org/2025/03/03/iftas-service-shutdowns/),
[atproto 2026 roadmap](https://atproto.com/blog/2026-spring-roadmap),
[IETF ATP charter](https://datatracker.ietf.org/doc/charter-ietf-atp/),
[Tangled funding](https://siliconangle.com/2026/03/02/tangled-announces-4-5m-round-build-github-alternative-built-blueskys-protocol/),
[Radicle 1.10](https://radicle.dev/2026/08/05/radicle-1.10.0),
[ngit / NIP-34](https://soapbox.pub/blog/what-is-ngit),
[SSB critique](https://derctuo.github.io/notes/secure-scuttlebutt.html),
[Matrix: removing the Slack bridge](https://matrix.org/blog/2025/11/removing-slack-bridge/),
[lore and lei](https://people.kernel.org/monsieuricon/lore-lei-part-1-getting-started),
[b4 0.16](https://lwn.net/Articles/1087388/),
[Bridgy Fed](https://fed.brid.gy/docs),
[Keyoxide ASP](https://blog.keyoxide.org/ariadne-signature-profiles/),
[gitsign](https://pkg.go.dev/github.com/sigstore/gitsign).

Agents:
[A2A specification](https://a2a-protocol.org/latest/specification/),
[MCP Tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks),
[ACP joins A2A](https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/),
[ANP](https://github.com/agent-network-protocol/AgentNetworkProtocol),
[AGNTCY dir](https://github.com/agntcy/dir),
[NANDA](https://arxiv.org/pdf/2507.14263),
[NLWeb vulnerability](https://www.itpro.com/security/microsoft-patched-a-critical-vulnerability-in-its-nlweb-ai-search-tool-but-theres-no-cve-yet),
[Moltbook security analysis](https://www.securityweek.com/security-analysis-of-moltbook-agent-network-bot-to-bot-prompt-injection-and-data-leaks/),
[Moltbook study: Form Without Function](https://arxiv.org/html/2604.13052v1),
[ClawHub malicious skills](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html),
[Copilot coding agent](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/coding-agent/about-copilot-coding-agent),
[Linear AIG](https://linear.app/developers/aig),
[Agent Inbox](https://github.com/langchain-ai/agent-inbox),
[Notification batching](https://www.semanticscholar.org/paper/Batching-smartphone-notifications-can-improve-Fitz-Kushlev/ce19cf66bdc6ced56a2f16d2483d97f9dc59b21d),
[GitHub MCP injection](https://www.docker.com/blog/mcp-horror-stories-github-prompt-injection/),
[The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/),
[Design Patterns for Securing LLM Agents](https://arxiv.org/pdf/2506.08837),
[CaMeL](https://arxiv.org/html/2503.18813v2),
[Agent Skills to AAIF](https://simonwillison.net/2026/Oct/22/donating-agent-skills/).

Knowledge and routing:
[Stack Overflow decline](https://www.devclass.com/ai-ml/2026/01/05/dramatic-drop-in-stack-overflow-questions-as-devs-look-elsewhere-for-help/4079575),
[Stack Internal](https://stackoverflow.blog/2025/11/18/introducing-stack-internal-powering-the-human-intelligence-layer-of-enterprise-ai/),
[Expert identification mapping study](https://www.researchgate.net/publication/374180938_Help_I_need_somebody_A_Mapping_Study_about_Expert_Identification_in_Software_Development),
[Glean connectors](https://docs.glean.com/connectors/connectors-power-glean),
[Google Snippets](https://blog.idonethis.com/google-snippets-internal-tool/),
[GitHub dashboard](https://github.blog/changelog/2025-08-28-improvements-to-the-home-dashboard-available-in-public-preview/),
[Workplace surveillance](https://knowablemagazine.org/content/article/society/2026/surveillance-at-work-is-increasing),
[Pernosco workflow](https://pernos.co/about/workflow/),
[LLVM bug guide](https://llvm.org/docs/HowToSubmitABug.html),
[Verisium AutoTriage](https://community.cadence.com/cadence_blogs_8/b/fv/posts/automate-regression-failure-triage-with-the-cadence-verisium),
[Questa Regression Navigator](https://eda.sw.siemens.com/en-US/ic/questa-one/verification-iq/regression-navigator/),
[Verdi IDX](https://semiengineering.com/intelligent-waveform-replay-for-efficient-debug/),
[GitLab Service Desk](https://docs.gitlab.com/user/project/service_desk/),
[gh-aw issue triage](https://github.github.com/gh-aw/gallery/ai-issue-triage/),
[Linear Triage Intelligence](https://linear.app/now/how-we-built-triage-intelligence),
[Dosu and Superset](https://dosu.dev/customers/how-preset-keeps-apache-superset-healthy),
[CHAOSS responsiveness](https://www.chaoss.community/practitioner-guide-responsiveness/),
[curl ends bug bounty](https://www.bleepingcomputer.com/news/security/curl-ending-bug-bounty-program-after-flood-of-ai-slop-reports/),
[GitHub PR controls](https://www.theregister.com/software/2026/02/03/github-ponders-kill-switch-for-pull-requests-to-stop-ai-slop/4334869),
[Assisted-by trailer](https://allthingsopen.org/articles/open-source-ai-contribution-policies-assisted-by-git-trailer-standard).

Not verified beyond one secondary source: Block's Buzz, Tangled's user
counts, A2A's move to the Agentic AI Foundation, the date GitHub's
concurrent-PR cap shipped, how VIP vendor support cases are handled.

## Status log

### 2026-10-25: design written

Written from `docs/work-packet-social.md`, against product.md, with
three research passes on prior art (federation and identity; agents;
knowledge and routing). Proposes findings, snapshots, questions with a
gated and budgeted inbox, POSSE channels, drafted posts and an intake
packet, in steps K1–K5 alongside R4–R7. Open issues in §8, decisions
S1–S10 in §11. Nothing built.

### 2026-10-25: the first application is promotion

You set the first application: publish what you're working on each
week, to get people interested. New §5.9: the weekly post, built from a
deterministic digest of public projects (filtered before any model sees
it), drafted by a scheduled packet, edited and approved by you, and
published on your site with copies to LinkedIn, Mastodon and Bluesky.
It includes a "how it was done" box that promotes work-packet with
journal facts, public packet pages, and feedback per item. New step K0
comes before K1; decisions S11–S14 cover where it lives, what is
public, channels and cadence.
