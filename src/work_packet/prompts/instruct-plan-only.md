This step only plans; it changes nothing in work/.

work/$repo/ is a git clone on branch $branch. The task is $plan. Read the
plan, then the code and tests it points at, enough to plan.

Plan documents (the plan, state/outline.md, state/questions.md) live in
state/ and are never committed to work/$repo.

Write state/outline.md, the plan for carrying it out:
- One line per item: [ ] pending, [>] active, [x] done, [-] deferred
  (with a reason), [+] added during the run. Order the items as you would
  do them.
- Under each item: a goal, refs (plan sections and files) and checks
  (exact commands, with output to log files).
- Split items into sub-items of one or two steps each.
- Keep it under 4 KB: it is shown in every step's prompt. Put detail in
  state/notes/<item>.md.

Write state/questions.md: anything you need from me before you implement.
Each question has your recommended answer, the items that depend on it,
and whether you could go on provisionally. Include the permissions you
need (Bash commands) and how long the build and tests take, if you can
tell.

Then stop for my review: resume: fail, with reason "question: plan ready
for review".
