You are working on the repository in work/$repo/ (branch $branch).
The task: <what to do, and the plan or issue it comes from, e.g. $plan>.

Plan documents (plans, outlines, questions, progress notes) live in state/
and are never committed to work/$repo. Commits in work/$repo hold code and
tests only. All build and test output goes to log files, never the
terminal.

Never: git push, network access, or changes outside this packet.

Every step:
- Do one bounded piece of the task: change the files, run the checks
  (<build and test commands>), commit in work/$repo.
- Keep a short running log in state/log.md.
- Write the memento body as the instruction for the next step: what is
  left, with the files and checks it needs. Not the whole plan.
- If you need a decision you cannot make, stop and ask (ask:).
- Continue with resume: now. Use resume: done when the task is done.
  With it, write the completion report: what was decided and where
  the results are.
