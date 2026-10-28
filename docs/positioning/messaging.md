# Messaging: tracking is the hook, the packet is the product (2026-10-27)

Revised the same day: §3a, tracking long-running work started by hand, not only agents.

Status: a direction for review. It refines `docs/positioning-survey.md`
§6.1 and §7; it does not replace them.

## 1. The question

Until now the project has been described through the work packet: what
it is, how it passes between owners, the open format. Building the
dashboard (`docs/packet-page.md`, `docs/history.md`), the pull has come
from somewhere else: **keeping track of many agents' work.** Is
work-packet now an agent tracker? And what happens to that story once
people, not only agents, do and receive the work?

## 2. The answer: the two have converged

Tracking and exchange need the same record. To manage many pieces of
work, the owner needs to see, for any of them:

- what it was asked to do;
- what it did, step by step, and what that cost;
- what it produced, as it was when it finished;
- where it stands now, and what it is waiting on.

A colleague taking a packet over needs exactly that. So do a vendor
receiving a repro bundle, and the owner coming back after a week. Each
dashboard feature built so far (the task page, a task's own report, its
results kept as they were) is a view onto that one record.

So the choice is not between "agent tracker" and "unit of exchange".
**Tracking is how users first meet the packet. The packet is why
tracking works, and why it keeps working when people join in.**

## 3. Why tracking should not be the headline

- **Agent tracking is the crowded lane.** The survey (§7) already notes
  that harness vendors will absorb features that only concern agents.
  Fleet views, session lists and run dashboards are the obvious ones to
  absorb, and some exist already. Tracking long-running work *of any
  kind* is not in their lane (§3a).
- **The record is what they will not own.** An open, vendor-neutral
  record of the work, written by agents, people and batch tools alike,
  is not something a single harness vendor has reason to build.
- **People were always in the story.** The turnover metaphor (survey
  §1: "agents are shift workers with no memory; work-packet is the
  turnover discipline") comes from human crews in aviation and nuclear
  maintenance. Adding people later is not a pivot. It brings back the
  case the metaphor came from.

## 3a. Tracking is not only about agents

The dashboard was first tried as a way to stop waiting on agents. The
same pain is older than agents, and silicon engineers live with it
every day:

- **Long jobs, many terminals.** Sims, regressions, synthesis, place
  and route, formal runs and builds take minutes to hours. An engineer
  keeps several going at once, each in its own terminal tab or window,
  often across several machines or farm jobs.
- **Context switching on completion.** As each job finishes, the
  engineer has to notice, find the right window, work out what it was
  for, read the result and decide what to do next. Pages of terminals
  are the to-do list, and they hold no record once closed.
- **The record is lost.** What command ran, in which tree, at which
  commit, with what result, ends up in shell history and scrollback,
  if anywhere.

An agent step is one more long-running job. The unified view that
helps with agents (what is running, what has finished, what needs me,
and what each piece of work did) helps just as much with jobs a person
started by hand. That widens the hook from "people who run many
agents" to **every engineer who runs long jobs**. For silicon DV, the
first market (`audience.md`), that is everyone.

Who covers this today, and what they leave open:

- **Regression managers** (vManager, Questa VRM and similar) track
  planned regressions well. They do not track the ad-hoc runs an
  engineer starts while debugging, and they do not hold the *work*
  (why the run was started, what was learned, what comes next).
- **Batch systems** (SLURM, LSF, Grid Engine) know a job's state, not
  its purpose, and their views are per job, not per piece of work.
- **Harness vendors** track their own agents only.

The open space is one view of all of a person's long-running work,
agents and tools, grouped by the piece of work it serves, with a
record that stays.

## 4. The message, in order

1. **The benefit users feel now:** run many long jobs at once (agents,
   sims, regressions, builds) and still know, for any of them, what it
   was for, what it did and where the results are, without a wall of
   terminals.
2. **The reason:** each piece of work is a packet, a self-contained
   record that any worker can pick up, whether that is an agent, you, a
   colleague or a vendor.
3. **Why it lasts:** the packet is an open format (`docs/packet-format.md`),
   so the record outlives any one tool, harness or team.

One line, for any audience: **Start it, walk away, come back to the
record. Hand any of it on.** For an agent audience: **Run many agents.
Keep the record. Hand any of it on.** For silicon engineers: **Close
the terminals. Every run, agent or sim, in one view, with its record.**

Step 3 is the survey's §7 strategy, unchanged. It just should not be
the first sentence for someone who has not yet felt the hand-off
problem. An engineer with a dozen jobs running has felt the tracking
problem already, and that is the way in.

## 5. What it means for the build

1. **Every dashboard feature is a view onto the packet.** The dashboard
   holds no state of its own about the work. If a client needs a fact
   (where a task starts, what it produced), the fact goes in the packet
   format and every client reads it from there. This is the test
   `docs/history.md` applies, and it is now principle 9 of
   `docs/packet-format.md` §1.
2. **Do not assume an agent did the work.** A task done by a person (a
   Level 0 shift-end commit, `docs/packet-format.md` §2.4) appears in
   the same history, with a report and results. In `docs/history.md`,
   a task's steps and `task.json` must not require a model run.
3. **Build `wpk job` for people first** (`docs/product.md` §9: jobs,
   the progress protocol, the dfm, pytest, make and SLURM adapters).
   §9 assumes an agent starts the job from a step; the case in §3a is a
   person starting it from a terminal. What that needs beyond §9:
   - one prefix in any terminal, `wpk job -- make sim`, that finds its
     packet from the current directory (in-place discovery,
     `docs/packet-format.md` §2.2) or puts it in a default "loose jobs"
     packet;
   - a notice when it ends (browser, desktop, phone), with the exit
     code and the last progress line;
   - the board's "Needs you" column showing finished jobs not yet
     looked at, next to agents waiting on answers;
   - the run in the packet's history as an entry by a person (command,
     tree, commit, result, log), per `docs/history.md` §2.5.

   The fuller version needs no prefix at all: a terminal session on the
   board records each long command as a run, and its tab can be hidden
   while the run goes on (`docs/work-sessions.md`). An agent **scribe**
   then writes what people skip: a summary of each run, a log entry per
   stretch of work, a draft report at hand-off (`work-sessions.md`
   §3.5). The method's discipline stops being a cost the person pays:
   **people do the work; the record writes itself.** This is a strong
   message for the human side, since it is the one place an agent helps
   without being trusted to act.
4. **Agent-only features are the lowest priority.** A feature that
   matters only while an agent is running (live views, context
   charts) is worth building for our own use. It is not what the
   message rests on, and it is what a harness vendor is likeliest to
   ship first.

## 6. How we will know

The survey's checkpoint (2026-12-21) already has the right test:
**at least one hand-off has gone between people.** Read the result
both ways:

- **Engineers start their own jobs through it** (not only agents'):
  the tracking hook reaches beyond agent users, the larger audience.
  Count manual `wpk job` runs per user per week alongside finished
  packets.
- **Users track work but never hand a packet on:** tracking is the
  product, and the format is plumbing. Put the effort into the
  dashboard and the runner, and keep the format as the internal
  contract.
- **Hand-offs happen, even a few:** the exchange story holds. Push the
  spec, the checker and the cheap ways in (plugin, CI action), as §7
  plans.

Until then, build in the order that serves both: record first, then
the view onto it.
