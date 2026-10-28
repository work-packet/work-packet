You are working on the repository in work/$repo/ (branch $branch).
The task is the plan in $plan. Follow its ground rules.

Plan documents (the plan, state/outline.md, state/questions.md, notes)
live in state/ and are never committed to work/$repo. Commits in
work/$repo hold code and tests only. All build, timing and test output
goes to log files, never the terminal.

Never: git push, network access, or changes outside this packet.

Keep the work as an outline in state/outline.md:
- One line per item: [ ] pending, [>] active, [x] done, [-] deferred
  (with a reason), [+] added during the run. Each item has a goal, refs
  (plan sections and files) and checks (commands).
- Work only on the active item. When you split an item, add its sub-items
  under it. Each sub-item is one or two steps.
- Work you discover that is not this item: add it as a [+] item; do not do it.
- When an item closes, add its checks to a "Regression" list at the end of
  outline.md, and run the quick part of that list before you close each
  later item.
- Keep outline.md under 4 KB: it is shown in every step's prompt. Put
  detail in state/notes/<item>.md.

Keep questions for me in state/questions.md. Each has: the question, your
recommended answer, the items that depend on it, and whether you can go
on provisionally. If you can go on, do so, on your recommendation. Stop to
ask only when no item can continue without an answer.

The first step: read the plan, write state/outline.md, and stop with
resume: now.

Every step:
- Do a bounded piece of the active item, and commit it in work/$repo.
- Update the item's notes and its line in the outline.
- Write the memento body as the instruction for the next step: the active
  item only, with its refs and checks.
- Continue with resume: now. Use resume: done when every item is done or
  deferred.
  With it, write the completion report: what was decided and where
  the results are.
