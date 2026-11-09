# CI watchers: a packet per CI breakage

Status: Built and running on edapack, 2026-11-08 (see §7). Not committed.

## 1. The question

A CI failure in one of an org's repos (e.g. `github.com/edapack`) arrives
as an email. You then open a packet by hand to look into it. Instead, a
packet should open by itself, with an agent's investigation queued.

Board watchers (`[[watch]]`, docs/starters-v1.md "Watchers") already do
this for issues: they poll an org (`github:owner/*`), skip what they have
already made, make a packet through a starter, and either hold it,
hand it to the runner, or propose it in the Inbox. This doc adds a second
event source to the same watcher: **CI runs**.

Decided (2026-11-08): **a new packet per breakage** (not a task on a
long-running per-repo packet; that is the "watch fires a trigger" path of
triggers.md §9, which waits for triggers T1–T2).

## 2. Configuration

```toml
[[watch]]
name = "ci"
on = "ci"                       # issues (default) | ci
repos = ["github:edapack/*"]
branches = ["main"]             # branches whose runs count (default: the repo's default branch)
workflows = ["CI"]              # optional: workflow names or file names (ci.yml)
dir = "~/work/edapack-ci"
every = "10m"
hold = false                    # false: the runner starts the investigation at once
propose = false                 # true: each breakage goes to the Inbox first
pr = "draft"                    # a fix made on the packet's branch becomes a draft PR
prompt = "~/wpk/ci-notes.md"    # optional: extra instructions added to every objective
since = "7d"                    # a breakage whose newest red run is older is left (default 7d)
```

`labels` and `query` apply to issues only, and `branches` and `workflows`
to CI only. A watcher with `on = "ci"` that sets `labels` is refused.
`prompt` works for both sources.

## 3. A breakage, not a run

A packet per failed run would flood the board when a nightly job is flaky
or `main` stays red for a day. The unit is a **breakage**: an unbroken
streak of failed runs of one workflow on one branch.

- Runs are listed per repo and branch (`GET /repos/{r}/actions/runs?branch=
  &status=completed`, newest first, 50 per page) and grouped by workflow.
- Conclusions `failure`, `timed_out` and `startup_failure` are red,
  `success` is green, and anything else (`cancelled`, `skipped`, `neutral`,
  …) is ignored.
- If the newest counted run is red, the breakage is named by the **first red
  run of the streak**: `github:edapack/foo@main/ci.yml#<run id>`. That key
  stays the same while the streak lasts, so polling again makes nothing new.
  The next red run after a green one has a new key, and so a new packet.
- If all 50 listed runs are red, the streak's start is outside the page.
  Then a breakage already made for the same workflow and branch counts as
  the same one, unless a green run was seen after it. The watcher remembers
  the last green run per workflow and branch (`green` in its state).
- A breakage whose *newest* red run is older than `since` (default `7d`) is
  left alone, so a new watcher doesn't open packets for workflows that last
  failed months ago (disabled, or no longer scheduled).
  `wpk watch poll --dry-run` lists what it leaves. It is judged by the newest
  red run, not the first: a weekly job that has been red for a month still
  fails every week and gets a packet (changed 2026-11-08; judging by the
  first red run left such jobs out forever).
- The key is kept in the packet's `[origin]` (`kind = "ci"`, `key`). As
  with issues, losing `$WPK_HOME/watch/<board>.<name>.json` never makes a
  breakage twice.

**When it goes green.** When a poll sees a green run after a breakage
that has a packet, it leaves the packet a note ("CI is green again at run
N, commit X"), using the same path as `wpk note`. A running investigation
sees it after its next tool call, and the next step's prompt shows it.
This happens once per breakage (`cleared` in the state). The packet is
not marked done, because the investigation may still be worth reading.

## 4. The `ci` starter

It can also be used by hand: "From a CI run" on the New page, or
`wpk start ci repo=github:edapack/foo run=123456`.

- Fields: `repo` (`forge:owner/repo`) and `run` (a run id, or a run URL
  `…/owner/repo/actions/runs/<id>`).
- It fetches the run, its failed jobs (`/actions/runs/{id}/jobs`) and the
  end of each failed job's log (`/actions/jobs/{id}/logs`: the last 200
  lines, timestamps stripped). The log redirect to blob storage is followed
  **without** the Authorization header.
- It clones the repo, checks out the failing commit, and makes branch
  `wpk/ci-<workflow>-<sha7>`.
- The input is `state/ci-run-<id>.md`: the workflow, run, commit, trigger
  event, and for each failed job its failed steps and log tail.
- The objective asks the agent to work out why the run fails, reproduce it
  if it can, and classify the failure (a regression and which change caused
  it, a flaky test, or a CI or infrastructure problem). If the fix is small
  and clear, it should make it and commit it on the branch. Otherwise it
  should say what the fix needs. The objective ends with the watcher's
  `prompt` text, if there is one.
- `origin = {kind = "ci", forge, repo, workflow, run, url, sha, key,
  branch = <wpk branch>, base = <the watched branch>}`. `pr.py` already uses
  `branch` and `base`, so `pr = "draft"` works unchanged.

Only GitHub is supported for now. A Forgejo forge answers `on = "ci"`
with a poll error ("CI runs: not supported on forgejo yet").

## 5. Cost and rate

Each poll makes one runs call per repo per branch. With 27 repos (edapack
today) every 10 minutes, that is about 160 calls an hour, well under
GitHub's 5,000 an hour with a token. Jobs and logs are fetched only
when a packet is made. Webhooks would cut the delay, but they need an
endpoint GitHub can reach, and wpkd only listens on the tailnet.

## 6. The board page

The Watchers table shows "CI failures on main" in place of the labels.
The edit form gets an *On* select (issues / CI) and a *Branches* field. Keys
the form doesn't show (`workflows`, `prompt`) are kept, as `query` is now.

## 7. Plan

| step | content | status |
|---|---|---|
| C1 | `forges.GitHub.runs()`, `.run()`, `.run_jobs()`, `.job_log()`; `_get_text` with a redirect that drops auth | done |
| C2 | `ci` starter (fields, input markdown, objective, origin) | done |
| C3 | `on`, `branches`, `workflows`, `prompt` in `WATCH_KEYS` and `validate_watches` | done |
| C4 | `watch.poll` CI source: breakage keys, `green`, `known` from origins, note on green | done |
| C5 | board page: On/Branches in the form, "CI failures" in the table | done |
| C6 | tests against a fake GitHub (`tests/test_ci_watch.py`) | done |
| C7 | edapack: watcher `edapack/ci` in `boards/edapack.toml` (hold = false, pr = draft, every 10m, since 7d); openroad's breakage seeded as `openroad-bin-20261107`. wpkd restarted onto the new code 2026-11-08 03:3x UTC; first server poll 03:34, no errors, 21 workflows green, 4 old breakages left | done |
| C8 | `since` judged by the newest red run, not the first (weekly jobs red for weeks were never made; found 2026-11-08 when yosys/nextpnr/gdb-multiarch failed with no packet). Code and test done; wpkd not yet restarted onto it | done (code) |

## 8. Later

- A note to the packet when the same breakage fails again with a
  *different* failing job.
- Forgejo Actions runs (`/repos/{o}/{r}/actions/runs`, once Forgejo
  has it).
- With triggers: `mode = "task"` to hand a breakage to an existing
  per-repo packet instead of making a new one (triggers.md §9).
