# Run history: active records, harvest, and the history store (design, 2026-10-27)

Status: a design for review. Nothing here is built. Consolidated into
`docs/work-data-design.md`, which wins where the two differ. It follows
`docs/packet-card.md` §6.4–§6.5 (what travels) and `docs/packet-views.md`
(how history is browsed), and settles where execution detail lives over
time.

## 1. The decision

**Execution detail does not travel with a packet.** That means token
metrics, steps, plans as executed, diffs and transcripts. It belongs to
the server that ran the work, and it is kept there for the long view: what
work cost, how it went, and how agents and models compare over months.

It lives in two places over a packet's life:

| Phase | Where the detail is | Shape | Who reads it |
|---|---|---|---|
| **Active**: the packet is on the board | the run record, `~/.work-packet/runs/<id>/` | files, as today: `journal.jsonl`, `steps/NNNN/`, `tasks/`, `state/`, the private git repo | the executor, the dashboard, the TUI and CLI |
| **Harvested**: the packet is off the board (closed and archived, or discarded) | the **history store**, owned by the server (wpkd) | an archive per packet, plus a database built from the archives | the dashboard, the TUI and CLI, `wpk stats`, the token dashboard |

The card is unaffected throughout. It travels, and its `Record:`
trailers point at whichever of the two holds the run (§5).

## 2. Harvest

**When.** A packet is harvested when it leaves the board:
- after `close`, once it is archived (14 days by default, or at once
  with `wpk done --archive`; `packet-card.md` O1);
- when it is discarded. Its metrics are still harvested, because cost
  accounting must not depend on what you kept. Only `wpk purge`
  removes a packet without trace, and it asks first;
- for a sub-packet, together with its root.

**What it does**, in order. Each step is idempotent, so a harvest that
stops part-way is simply run again.

1. **Freeze** the card if it isn't already (`packet-card.md` §6.5). Its
   last `Record:` trailer then names the run record's final commit.
2. **Write the archive**: `history/<yyyy>/<mm>/<id>.wph`, one file per
   packet (§3).
3. **Load the archive into the database**, inside one transaction.
4. **Check**: the database's step and cost totals for the packet match
   the run record's.
5. **Remove the run record.** The card's `Record:` now resolves to the
   history store.

Nothing reaches the history store except through an archive. That keeps
"files are the source of truth" (`runner.md`): the database can always
be rebuilt from the archives, and backing up the history store means
copying a directory.

## 3. What is kept, and for how long

Not everything deserves the same retention. Transcripts are most of the
bytes and the least of the long-term value, and they are the most
likely to hold something sensitive (a token in tool output, a
customer's file).

| Tier | Contents | Stored as | Kept |
|---|---|---|---|
| **Metrics** | per step: start, end, duration, worker, harness, model, profile, attempts, outcome, tokens (input, cache write, cache read, output, reasoning), context peak, calls, `cost_usd`, tool-cost breakdown (`toolcost.py`). Per task and packet: totals, question count and wait time, sub-packet tree | rows in the archive's `metrics.jsonl`, then database tables | for good |
| **Narrative** | per step: summary, the plan and notes as of that step, questions asked; per task: instruction, report, deliverables list | blobs, by hash (`packet-card.md` §9.1), named in the archive's manifest. Plans change little between steps, so content addressing stores each version once | for good (small) |
| **Changes** | per step: the diff of the work and of the record's state | blobs | 1 year by default |
| **Transcripts** | per step: the full transcript and stderr | blobs, compressed | 90 days by default; per-host policy, and `--keep` per packet |
| **Not kept** | leases, `.pending/`, mailbox, scheduler state, session ids, the private git repo itself (its per-step content is already captured above) | | |

The archive file is a zip (`.wph`, for "packet history"):

```
01JBF3K8….wph
  manifest.json     packet id, name, card hash, record final commit, tier of every entry, blob hashes
  card.wp.md        the frozen card, as it was at harvest
  metrics.jsonl     one line per step, one per task, one for the packet
  narrative.jsonl   per step and task: the blob hash of each summary, plan, report …
```

Blobs are not inside the archive. They go to the server's blob store,
deduplicated across packets. Expiry under the retention policy removes
blobs, never archive files or rows. A view of an old step then says
"transcript expired 2027-01-25" instead of failing.

## 4. The database

SQLite by default, from the standard library, with WAL mode and a
schema version. A team hub may use Postgres; the archives are the same.

```
packet(id, name, title, origin, by, to, created, closed, outcome, cost_usd, steps, host, archive_path)
task(packet_id, n, instruction_blob, started, ended, outcome, cost_usd, report_blob)
step(packet_id, n, task_n, started, ended, worker, harness, model, profile, attempts, outcome,
     tok_in, tok_cache_write, tok_cache_read, tok_out, tok_reasoning, context_peak, calls, cost_usd,
     summary_blob, plan_blob, diff_blob, transcript_blob)
tool_cost(packet_id, step_n, tool, target, tokens)
question(packet_id, qid, asked, answered, wait_s)
edge(parent_id, child_id)                -- the sub-packet tree
tag(packet_id, tag)
```

It is **separate from `index.db`** (`packet-card.md` §4.7):

| | `index.db` | the history database |
|---|---|---|
| Holds | live cards and run-record summaries | harvested runs |
| Rebuilt from | a scan of cards and run records | the archive files |
| If lost | rebuilt in seconds | rebuilt from the archives; lost only if they are |

## 5. Reading history: one view, two backends

The view model (`packet-views.md` §1) gets a second reader:

```
 view/ ──► record backend ── active run records (files)
       └─► history backend ─ the history database + blobs
```

- **Every view works on a harvested packet**: `wpk log`,
  `wpk step uart-overrun@s4`, the TUI's history browser and the
  dashboard's task and step pages. A harvested packet is shown from the
  history backend at the fidelity its tiers still have.
- **`wpk stats` and the token dashboard query the database**, plus the
  active records for the rest. Today `stats.collect` walks project
  directories, so deleting a project loses its numbers. Harvest ends
  that.
- **Search across history**: "every packet that touched fw-uart16550",
  "steps over 1 USD last month", "how long questions waited". These are
  SQL over the database; the CLI gets `wpk history <filters>`.

## 6. Packets that move between servers

A packet's run can be split. You worked on it, then Alice did, then it
came back. Each server keeps the part of the run it executed:

- each segment's record and its harvest belong to the server that ran
  it;
- the card stitches them together: each `handoff` and `pinned` entry
  carries a `Record: run:<id>@<commit>` trailer, and with more than one
  server, the host as well (`Record: matt/run:…`);
- a view of a step another server ran says where it is held, and
  through the hub, when both servers are linked to one, it can fetch it
  if that server allows;
- the hub never collects other people's detail by default. A team that
  wants pooled statistics turns on metrics-only sharing to the hub (the
  metrics tier, without narrative or transcripts).

## 7. Reopening

A harvested packet can be reopened (`reopened`, `packet-card.md` §4.4):

- a new run record is made with the core of the old one: the last plan
  and notes, taken from the narrative blobs, and the memento rebuilt
  from the closing summary;
- step numbering continues from the history;
- the history before the reopen stays in the history store, so
  the views join the two backends.

## 8. Open questions

| # | Question | Default |
|---|---|---|
| H1 | Retention defaults for diffs and transcripts | Diffs 1 year, transcripts 90 days; set per host |
| H2 | Redact secrets from transcripts at harvest (patterns, known tokens)? | Yes for known credential patterns; transcripts are also the first thing expired |
| H3 | Who owns the history store when wpkd isn't running (CLI-only use)? | The same files under `~/.work-packet/history/`; `wpk` harvests on its own when the server is absent |
| H4 | Harvest active packets' metrics continuously too, so the database is always complete? | Yes, metrics only: the database gets rows as steps commit, marked provisional until harvest. The token dashboard then needs one source |
| H5 | Do sub-packets that were requests to another server appear in the requester's history? | As a row with the delegate's outcome and cost from its `result` entry, and a link; their detail stays on the other server |

## 9. A slice

1. The archive writer and reader (`.wph`), with blobs to the local blob
   store.
2. The database schema and its loader; `wpk history rebuild`.
3. Harvest on archive and on discard; removing the run record after the
   check.
4. The history backend in `view/`; `wpk stats` reading the database.
5. Retention expiry for diffs and transcripts.

Test with the existing projects under `~/work-packet-runs/`: harvest
them, delete the run directories, and check that `wpk stats` and the
dashboard show the same numbers as before.

## Status

- 2026-10-27: design written. Nothing built.
