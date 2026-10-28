# Paper simulation: the task outline replayed over fw-proto-chi

Status: done (2026-10-23). Nothing was run: no models, no builds. This is a
replay on paper of the outline shape in `docs/stack-experiment.md` §1a over
the real fw-proto-chi history. Every estimate is marked as one, and §7 says
how the numbers were made.

Sources:

- the transcripts, cited as **main L*n*** (`e0d42399…jsonl`) and **docs L*n***
  (`c69d45c2…jsonl`), using JSONL line numbers;
- `users.txt`, `seg1.txt` and `seg2.txt` in this folder;
- `~/projects/featherweight-ip/fw-proto-chi/docs/fw-proto-chi-design.md`,
  cited as **D§n**.

The scripts behind the numbers in §7 (`nar.py`, `chunks.py`, `leaves.py`)
were run in the session scratchpad and are not kept. They group the
main-thread API calls by transcript line range. Each range is a piece of
work, read from the narration.

---

## 0. Setup

The packet starts with the user's seed prompt (main L5, verbatim in
`users.txt`) as its task, and the `project` template's five items:

1. Create a design (gather resources first)
2. Resolve open issues → sign-off gate
3. Create a detailed plan
4. Resolve open issues → sign-off gate
5. Implement the detailed plan

The executor shows the current item, its parents' goals in one line each, and
the titles of the remaining items. Each step is one `claude -p` session. It
ends by committing state and a memento. The C3 budget hook (context.md §2)
nudges the model at `step_context_tokens` and stops it at 1.5×. The default
for the `claude` profile is 80k (`project.py`). C4 carries a session over
only when the previous step ended under the budget.

## 1. Triage

**Would the agent pick `project`? Yes, without doubt.** The seed asks for
"a design document here with your plans and initial opportunities for me to
review". It names five resources to study: the CHI spec, `design.md`,
fw-hdl, fw-proto-wb and pss-registers-up. It raises an unsolved design
problem ("bi-directional communication binds … in an efficient and
ergonomic way"). It names three deliverables: TLM APIs with SVUnit tests,
signal-level transactors, and a project template. It also opens a research
direction ("formal between TLM/SPL and RTL"). Every `project` criterion in
§1a holds: a new design, open questions, many sessions.

**Would it adapt the template? Yes, in two ways.**

- **Merge the plan into the design, but keep item 3 as an outline step.**
  The seed asks for "plans" in the design document, and the real document
  has a phase table with a "Done when" column (D§10). So item 1 writes the
  phases as prose, and item 3 only turns D§10 into the item tree under item 5
  (refs, checks, granularity). It writes no new reasoning. One step.
- **Gate 4 becomes `notify`, not `always`.** The design gate already carries
  the plan-level questions (D§12 items 6–8 are about tooling, fw-hdl changes
  and test defaults). At gate 2 the user said "Okay, proceed to implement"
  (main L539), which is a sign-off on the plan as well. A blocking second
  gate would have asked the same person the same questions twice.

It would **not** drop gate 2. The seed says "for me to review", so gate 2 is
`always`.

---

## 2. Item 1: design (gather resources first)

### 2.1 Sub-items

The agent's real first 52 calls (main L5–L366) break cleanly into resource
reviews. They match D§1.1–§1.6 one for one, which shows the agent already
thought of them as separate items.

| Sub-item | Goal | What the agent actually did | Calls (real) |
|---|---|---|---|
| 1.1.1 CHI spec review | Pull what matters for the kit from B1–B16 and Part C | Mapped the spec's headings (L37–L63), then started **four parallel spec readers** (L67–L73: B1–B3, B4–B9, B13–B16, B10–B12 + C). Their verdicts reached the doc as D§1.1, including "the `.md` copy garbles the C1 field tables" (L379) | 7 (plus 4 subagent contexts) |
| 1.1.2 fw-hdl kernel | Learn ports, exports, `fw_root` and the macros, and find whether any bidirectional construct exists | Skill `fw-hdl` (L82); read the whole kernel (L100–L118); `fw_root` (L323); searched for bidi (L283: none) | 7 + part of 1.1.5 |
| 1.1.3 fw-proto-wb + kit skills | The reference kit's layering, transactor cores, formal harness and `PROPERTIES.md` | L122–L183; the `fw-proto-kit`/`fw-proto-create` skills (L157–L175, L304) | 7 |
| 1.1.4 Template project | pss-registers-up layout, CI, dv-flow-libproject archetypes, dv-flow-libhdltest | L184–L206 | 4 |
| 1.1.5 Formal/abstraction notes and prior art | fw-hdl's `spl-formal.md`, `tl-formal-spec.md`, `formal-transactor-bridge.md`; the earlier CHI brief (`psstools/pssc/docs/design/chi-fw-hdl-brief.md`, found at L249–L252); zuspec `bundle`/`mirror` (L262–L272); fw-hdl's XLS "same test, every level" pattern (L289–L299); fw-proto-core (L348, L361) | L207–L366 | 18 |
| 1.1.6 Resource digest | Write `work/notes/resources.md`: per resource, what matters and where it is (file:line, spec section) | **Did not happen.** The digest lived only in the session context. Its loss shows at main L541–L680, where the first post-compact stretch re-reads fw-hdl, fw-proto-wb and B13.9 (18 calls, 94k of growth) | n/a |
| 1.2 Write the design doc | D§0–§12: layering, socket/mirror, types, APIs, transactors, testing, template, F1–F10, phases, notes map, decisions | One 49 KB `Write` (main L368) | 1 |

Two corrections reached the agent during item 1 as queued prompts: "as long
as the unit tests have the transactor APIs, it doesn't matter what implements
them" (L331) and "I'm not positive that fw-proto-core is still relevant"
(L371). In the outline shape they are hand-off notes on item 1. They change
its content (D§7.1 views, dropping fw-proto-core), not the tree.

**1.1.6 is the sub-item the shape should force.** Without it, every fresh
step that needs fw-hdl or the spec pays for exploration again. Item refs
should point into the digest, and from there into the sources.

### 2.2 Steps

**Estimate:** about 7 steps at a 150k budget, and 13 at the 80k default.

The 1.1.x reviews are independent. They could be four child packets
(`spawn`), as the spec readers already were subagents. That would cut item 1
to about 3 sequential steps: spawn the readers, review the repos, write the
doc.

### 2.3 Output and check

The output is D§0–§12 in its 2026-10-10 form (about 1000 lines).

The design is judged at the gate, so the check can only be structural. A
script, for example `work/checks/design.py`, that passes when:

- D§10 has a "Done when" cell for every phase;
- every bullet of `design.md` appears in the D§11 table;
- every D§12 question has a *Recommended* answer;
- D§3.7 lists each risk with a fallback.

The third test would have failed on the real document. D§12 item 4 ends in
"OK?", and item 6 offers two options with no recommendation. A gate needs a
recommendation for every question, or "take the recommendations" means
nothing for those items.

---

## 3. Gate 2: design sign-off (`always`)

### 3.1 Questions the gate would present

These come from D§12 and D§3.7, plus the naming question that the 2026-10-10
draft still had open (`fw_bidi`; the user's four lines `fw_port` /
`fw_export` / `fw_interface` / `fw_bidi` at D lines 29–32).

| # | Question | Recommended | What really happened |
|---|---|---|---|
| Q0 | Name for the bidirectional construct (`fw_bidi`)? | `fw_bidi` (draft) | The user asked for **industry research** (L382). The agent searched IP-XACT, PyMTL3, Amaranth, TLM-2.0 sockets and SpinalHDL/Chisel (L393–L431) and returned a table (L435). User: "I lean toward socket. `fw_socket<I,E>`, `fw_mirror<I,E>`" (L439). Applied (L442–L466). The user then overwrote the file by mistake, and the agent applied it again (L492) |
| Q1 | Do `fw_socket`/`fw_mirror` live in fw-hdl? | Yes | **Not answered at the gate.** The agent staged the classes in `src/fw_ext/` (L1506: "I didn't want to edit fw-hdl before you confirm decision 1") and asked again at the end of P1. User: "Sure. Just keep track of what has been added" (L1509) |
| Q2 | L1 flit-granular? | Yes | Unanswered; the recommendation was taken |
| Q3 | Issue H, with a profile parameter for E.b? | Yes | Unanswered; taken |
| Q4 | Package, dfm and API names | (none written: "OK?") | Unanswered; the draft names were used |
| Q5 | One RN link shape? | Yes | Unanswered; taken |
| Q6 | `project.dv.svunit` archetype, or local SVUnit wiring? | (none written) | Unanswered; wiring stayed local |
| Q7 | Small fw-hdl changes for R3 (restart, "elaborated") in P0? | (implied yes) | Unanswered. First avoided (D§3.7 R3), then done in fw-hdl after Q1 (L1620–L1700) |
| Q8 | Default test config N=7, RAW=48, DW=256; DW=128 for formal? | (implied yes) | Unanswered; taken |
| R1–R3 | Accept the spike-first plan for the risks? | Yes | Implicit in "proceed" |

### 3.2 Mode and outcome

**Mode `always`** is right for this gate. The real gate held for about 25
hours of wall clock, from the rename at L439 (10-10 14:54) to "proceed to
implement" at L539 (10-11 16:13). Most of that wait was the user's time, not
the agent's.

The **naming detour** shows that answering a gate can take work. The answer
to Q0 was "go research it", so the gate spawns two items under itself:

- `[+] 2.1` research names: one step, 7 calls, with a findings table as the
  deliverable;
- `[+] 2.2` apply the rename across the doc: one step, 11 calls. The
  overwrite at L492 adds a second pass. In work-packet that is a failed check
  ("no `fw_bidi` left in D"), retried.

The gate then reopens with Q0 answered.

**Outcome.** Q0 was answered. The user's "Okay, proceed to implement" would
be read as **"take the recommendations" for Q1–Q8**. That reading changes
one thing: Q1 is a "yes" from the start, so the socket goes straight into
fw-hdl. The staging departure (D§13.3 first bullet), the second question at
L1506 and the 16-call move at L1509–L1615 would not have happened. The
agent's caution there was about **editing another repository**, which is a
permission, not a design choice. The gate should list cross-repo writes as
explicit questions ("may this packet write to `~/projects/featherweight-hdl/
fw-hdl`?").

One more input arrived with the sign-off: "Does fw-hdl benefit from having a
native understanding of credits?" (L541), followed by "credit balancing is
always tricky … features for formally reasoning about credit availability"
(L577). That is not an answer to a gate question. It becomes a new research
item (`[+]` F10, see §6).

---

## 4. Item 3: the detailed plan (expanding item 5)

The plan step reads D§10, D§7.2, D§7.3, D§8 and D§3.7. It writes the tree
under item 5. Refs are design-doc sections. Checks are the commands the
project ended up with (D§13.2, README lines 16–30). At plan time some of
those commands did not exist yet; the plan names them as targets that the
template item creates.

Step estimates per leaf are at a 150k budget and come from the real call
counts of the matching work (§7).

### P0: template, socket spike, types, L1 in TLM (D§10 P0)

Done when: `l1_basic` passes in `tlm`; `tests/socket` passes on Verilator and
xezim; the encodings are spot-checked against B13.10.

| Leaf | Goal | Refs | Check | Est. steps |
|---|---|---|---|---|
| **P0.1 Template** | | D§8, `packages/pss-registers-up` | | |
| P0.1.1 dfm project | `flow.yaml` on `project.dv`, a suite × view matrix | D§8, D§7.1 | `dfm run tests` lists the `l1_basic.tlm` cell | ½ |
| P0.1.2 IVPM dep-sets | `dev`/`docs` dep-sets; svunit, dv-flow-libhdltest, -libformal, -libhdllint | D§8 | `ivpm update` succeeds; `python -c 'import fw.hdl'` in the venv | ½ |
| P0.1.3 Repo hygiene | `.gitignore` covers the spec, `packages/` and `rundir/`; README | D§8 | `git check-ignore IHI*.md packages rundir` | ½ |
| P0.1.4 Lint | lint top; held to zero findings | D§8 | `dfm run lint-rtl` reports 0 | ½ |
| P0.1.5 CI | `ci/run.sh`, cache key, both workflows from the template | D§8 | `CI_SKIP_BOOTSTRAP=1 ci/run.sh` | 1 |
| **P0.2 Socket/mirror spike** (R1) | | D§3.2–§3.4, §3.7 | | |
| P0.2.1 Classes and IMP macros | `fw_socket`/`fw_mirror`, `FW_SOCKET/MIRROR_IMP_*`, in fw-hdl (Q1) | D§3.2, §3.3 | the spike test compiles on Verilator | ½ |
| P0.2.2 Spike tests | peer bind from either side; hierarchical bind; unbound diagnostic; toy bridge | D§3.7 | `dfm run socket.socket` (in fw-hdl) | ½ |
| P0.2.3 Negative compiles | socket-to-socket and swapped `<I,E>` are compile errors | D§3.7 R1 | a script expects both compiles to fail | ¼ |
| P0.2.4 xezim | the same tests on xezim | D§3.7 | the spike passes on xezim | ¼ |
| P0.2.5 R3 in fw-hdl | `fw_root` restart, "elaborated" event (Q7) | D§3.7 R3 | fw-hdl's regression; a restart test | 1 |
| **P0.3 `chi_types_pkg`** | | D§4, B13.9, B13.10 | | |
| P0.3.1 Encodings | every Issue H opcode, RespErr, Resp, Order, MemAttr | D§4 | `l1_basic.encodings_roundtrip` | ½ |
| P0.3.2 Flit structs and widths | max-width structs, `chi_link_param_t`, width functions | D§4 | a test: REQ 137, SNP 94, DAT 240 at RAW=44, DW=128 | ½ |
| P0.3.3 `tables/` started | encodings as data | D§9 F3 | `dfm run tables-check` | ½ |
| **P0.4 L1 class layer** | four channel APIs, link typedefs, IMP macros, `chi_link_cfg`, scripted endpoints | D§5.1, §3.5 | `dfm run lint-rtl`; `l1_basic` compiles | 1 |
| **P0.5 `chi_env_tlm` + `l1_basic`** | the TLM view and the suite from D§7.2 | D§7.1, §7.2 | `dfm run tests` → `l1_basic.tlm` all pass | 1 |

### P1: link layer, transactors, formal (D§10 P1)

Done when: `l1_basic` and `l0_link` pass in both views; `fv` and `fv-cover`
pass; CI is green.

| Leaf | Goal | Refs | Check | Est. steps |
|---|---|---|---|---|
| P1.1 pack/unpack | B13.9 wire format, synthesizable, in L0 | D§4, B13.9 | a round-trip test per channel | ½ |
| **P1.2 Link cores** | | D§6.1, B14 | | |
| P1.2.1 TX/RX cores | generic credited TX and RX | D§6.1 | `dfm run lint-rtl` 0 | ½ |
| P1.2.2 Control core | LINKACTIVE four-phase, banned output races | D§6.1, B14.6 | lint 0; `chi_link_ctrl_checker` binds | ½ |
| P1.3 Wrappers + transactor interfaces | four wrappers (RN, ICN-RN, SN, ICN-SN) + monitor | D§6.2, §6.3 | lint 0 | ½ |
| P1.4 Bridges + root binds | four L1 bridges, `` `fw_root_bind_socket/mirror `` | D§3.4 | `xtor` env elaborates | ½ |
| P1.5 Checkers + `chi_env_xtor` | `chi_link_checker` per channel; the `xtor` view | D§6.4, §7.1 | `dfm run tests` → `l1_basic.xtor` passes | 1 |
| **P1.6 Formal back-to-back** | | D§7.3, F1, `fw-proto-wb/tests/formal` | | |
| P1.6.1 Harness + `PROPERTIES.md` | TX⇄RX with control cores, free streams | D§7.3 | `dfm run fv` (BMC depth 30) | ½ |
| P1.6.2 Induction | credit conservation, unbounded | D§7.3 | `dfm run fv-prove` | ½ |
| P1.6.3 Cover | up, traffic, LCrdReturn, deactivate, re-activate | D§7.3 | `dfm run fv-cover` | ¼ |
| P1.6.4 Teeth | corrupt a bit, early credit use, skip LCrdReturn | D§7.3 | `dfm run fv-teeth` (each mutant fails) | ½ |
| P1.7 `l0_link` suite | activation races, starvation, LCrdReturn, reset mid-traffic | D§7.2 | `dfm run tests` → `l0_link.xtor` passes | 1 |
| P1.8 Monitor | `chi_mon_if`, TLM taps, pin monitor | D§5.3, §6.2 | a monitor test in both views | 1 |
| P1.9 RP/shared credits, SYSCO, parity, LDE | the rest of the link layer | D§6.1, B14 | `l0_link` RP cases; `fv-prove` | 2 |
| P1.10 Phase close | CI green; D§13 status | D§10 | `ci/run.sh` | ½ |

### P2–P4, one level

| Phase | Leaves (one level) | Check (from D§10) | Est. steps |
|---|---|---|---|
| **P2** L2 non-coherent | P2.1 `chi_xact_if` + RN adapter · P2.2 SN adapter + memory model · P2.3 completer policy + `chi_test_home` · P2.4 `chi_to_mem` · P2.5 `chi_flow_check` · P2.6 F3 flow tables + generator · P2.7 `l2_rn_sn` · P2.8 `l2_checker_teeth` · P2.9 table-cell mutation (D§9 F3 last bullet) | the brief's §5.7 cases in both views; teeth bite; `tables/table_teeth.py` | 8–10 |
| **P3** RN-F | P3.1 snoop handler API + default · P3.2 hazards (B4.11.1) · P3.3 coherent opcode subset · P3.4 `l2_rnf` vs a scripted Home | snoop × state table covered; hazard tests pass | 5–8 (no real data) |
| **P4** formal opportunities | P4.1 F4 formal scoreboard · P4.2 F5 SPL formal on adapters · P4.3 F6 `rtl` view | one TL property proven and cross-checked in both readings | 6+ (no real data) |

### Granularity

The P0/P1 leaves are mostly ½-step items. The real calls behind them range
from 2 (L1 class package, main L764–L778) to 20 (env + dfm + `l1_basic`,
L779–L901). At a 150k budget a step fits 2–3 such leaves.

So **"one step may finish an item and start the next" has to be allowed**.
Otherwise P0 and P1 cost about 35 fresh orientations for about 200 calls of
work. The P2 leaves are the opposite. Real P2 work came in 33–64-call
chunks, each with 100–215k of growth (§7). Those are 2–3-step items even at
150k.

---

## 5. Gate 4: plan review (`notify`)

The questions the plan step would raise:

1. **xezim in P0's "Done when"?** The plan cannot know yet that xezim 0.11.1
   cannot parse fw-hdl (L1506). This question only appears during P0.2.4.
2. **CI in P0 or P1?** The template wants it early; it needs fw-hdl's socket
   upstream first (D§13.3 "CI caveat").
3. **P2 subset:** RN-I/HN-I/SN-I non-coherent only? The agent later chose
   this itself (D§13.3 "P2: scope"). It is a real plan decision, made with
   no one asked.
4. **Order of F-items:** do F3/F4 wait for P2/P3, as D§9 says?
5. **Commit policy:** commit per phase, or when the user asks? In reality
   nothing was committed until L3845, and then "Don't commit working docs".

**Would it block? No.** Nobody signed off the plan in reality. "Proceed to
implement" (L539) arrived at the design gate, and Claude took its own
recommendations from then on. `notify` matches that: the gate proceeds and
lists Q1–Q5 on the board.

Q3 and Q5 were real decisions that would have been worth a glance. A
`notify` gate makes them visible, which the real run did not. Q1 and Q2 show
that **most plan-gate questions come from implementation, not planning**
(see §9).

---

## 6. Item 5: execution, mapped onto the tree

### 6.1 Order of work (real), against the planned tree

| # | Real span | Leaf | Notes |
|---|---|---|---|
| 1 | main L541–L680 | (orientation) | A post-compact resume re-reads fw-hdl, fw-proto-wb and B13.9. With item 1.1.6 this would be ref reading inside P0.3 |
| 2 | L681–L737 | P0.2.1–P0.2.3 | R1 retired on Verilator (L698, L703). **Departure:** staged in `src/fw_ext/`, not fw-hdl (Q1 unanswered) |
| 3 | (L703 on) | P0.2.4 | xezim cannot parse fw-hdl → **blocked**. A new gate question: "drop xezim from Done-when?" Taken as yes, implicitly |
| 4 | L738–L763 | P0.3.1–P0.3.2 | P0.3.3 (`tables/`) not done → **moved** to P2.6 |
| 5 | L764–L778 | P0.4 | 2 calls |
| 6 | L779–L901 | P0.1.1, P0.5 | **Discovered:** fw-hdl's dfm plugin not installed (L845) → `[+]` P0.1.6. `l1_basic` 7/7 in `tlm` (L897). **P0 check passes except xezim** |
| 7 | L902–L965 | P1.2 | B14 rules read (L926) |
| 8 | L966–L1081 | P1.6.1–P1.6.4, out of order | Formal before the transactors. **Rework inside the item:** induction failed twice, on 4-bit wraparound (L1035) and an unreachable start state (L1047). A teeth mutant duplicated another (L1077). The check failed on the attempt and passed on the retry; not a reopen |
| 9 | L1082–L1137 | P1.1, P1.3, P1.4 | **Departure:** pack/unpack in the class layer (`chi_wire`), not L0. Synthesizable pack → **deferred** `[~]` |
| 10 | L1138–L1270 | P1.5, P0.1.4 | Lint 0 (L1228); `fv*` through dfm |
| 11 | L1271–L1370 | P1.7 | Hang → livelock (L1276–L1352). **Reopens P1.2.2** (the `IDLE_CYCLES` hold-off) and forces **P1.6 to re-run** after the core changed (L1352–L1371) |
| 12 | L1371–L1508 | P0.1.3, P1.10, `[+]` F10 | Sizing sweep → `DEPTH=5`, the answer to L541/L577. D§13 is written. P1 report (L1506) **defers** the link monitor, CI, RP/shared credits, SYSCO and the IVPM dep-set restructure. **Asks Q1 again** |
| 13 | L1509–L1615 | `[+]` P0.2.6 move into fw-hdl | Two checkouts kept in step; `docs/fw-hdl-changes.md` |
| 14 | L1616–L1700 | P0.2.5 (R3), `[+]` bind-map entry | fw-hdl kernel work, cross-repo |
| 15 | L1701–L1845 | P1.8 | Verilator cannot wait on a queue through a virtual interface (L1795–L1800) → a ring buffer (departure) |
| 16 | L1846–L1911 | P0.1.5 | CI, done last instead of first |
| 17 | L1912–L2173 | P2.1–P2.4, P2.7, P2.8 (first slice) | Peak context **620k** (L2171). **Discovered:** dfm test selection is broken (L2062–L2067) → a note, no item |
| 18 | L2200–L2621 | P2.3 rest, P2.5, P2.6 | Flow tables as data. **Rework:** R7 (CompAck timing) too strict → P2.5 reopened (L2479). **Found by the tables:** reserved Order in our own `ordered_reads` test (D§13.3) |
| 19 | L2648–L3070 | P2.9 table teeth | First run killed **66/156** → **reopens P2.5** (dead cells, CompAck bypass) and **P2.8** (matrix tests vs a second transcription). **Discovered:** `dfm run suites.X` exits 0 on failures (L2754). 153/156 at the end |
| 20 | L3100–L3844 | `[+]` P4.1′ F4 at the transaction level | **User scope** (L3100): "how much formal verification we can do above RTL … see what you can find". **F4 pulled ahead of P3.** Six checker gaps found → **reopens P2.5 again**. Mutation runs (2.5 h) collide with edits (L3821) |
| 21 | L3845–L3924 | `[+]` commit | User policy: no Claude attribution; working docs stay out |
| 22 | L3925–L4039 | `[+]` P4.1′.a dv-solve vs Bitwuzla | **User scope** (L3925). Research: an 8-parameter limit in dv-solve |
| 23 | L4066–L4093 | (outline revision) | "What's next?" The agent proposes an order (L4091): finish mutations, prove the Home, then one of three. That **is** revising the remaining items |
| 24 | L4119–L4791 | `[+]` P4.1′.b Home plan as pure functions | The proof finds Exclusive bugs (L4350–L4561) → **reopens P2.3** (`chi_test_home`), P2.5 and P2.6 (a new B13.10.27 cell). Done in a worktree to avoid the background jobs (L4250) |
| 25 | docs L7–L636 | `[+]` 6.1 Sphinx docs | **User scope**, a separate session → in the shape, a **child packet** |
| 26 | docs L637–L1002 | `[+]` 6.2 Publish; fw-hdl commit + push | Cross-repo commit and push (L717) |
| 27 | docs L1026 | `[+]` 6.3 sphinx-systemverilog features | Ends on an open question → a `[G]` if-open gate, still waiting |

### 6.2 Where the outline is revised (D§13.3 departures)

| Departure | Outline change |
|---|---|
| Socket staged here, then moved to fw-hdl | P0.2.1 note: "staged pending Q1". `[+]` P0.2.6 "move to fw-hdl" added when Q1 was answered. An explicit Q1 = yes would remove both |
| One unparameterized `chi_link_xtor_if` | P1.3 note only; no tree change |
| pack/unpack in the class layer | P1.1 done as `chi_wire`; `[+]` "synthesizable pack" **deferred** to the `rtl` view (P4.3) |
| `IDLE_CYCLES` hold-off | P1.2.2 reopened by P1.7's failure |
| Reset (R3) in fw-hdl | P0.2.5 moves after P0.2.6 (it needs fw-hdl write access) |
| Pin-monitor ring buffer | P1.8 note |
| CI caveat (needs fw-hdl `d5d17c1`) | P0.1.5 check depends on an upstream commit → stays `[~]` until docs L717 pushes fw-hdl |
| P2 serializes per line (`chi_line_lock`) | P2.3 note; found by P2.7 |
| P2 subset only | `[+]` P2.10 "subset remainder" (ReadNoSnpSep, NCBWrDataCompAck, OWO, Excl, DataCheck, TagMatch), `[ ]` |
| F3 first cut; B4 tables wait for RN-F | P2.6 note; B4 tables → P3 |
| F4 at the transaction level first | P4.1 split: `[+]` P4.1′ (TL) done; the RTL-monitor half stays `[ ]`. **Moved ahead of P3** |
| R7, R11, reserved Order, table teeth | reopenings of P2.5/P2.7/P2.8 (see 6.3) |
| Not built from P1: RP, SYSCO, parity, LDE, IVPM restructure | P1.9 and part of P0.1.2 → **deferred**. The cursor must skip them (see §9) |

### 6.3 Rework as reopened items or failed checks

| Event | Where | In the outline |
|---|---|---|
| Induction redone twice | L1035, L1047 | P1.6.2's check fails on the attempt and passes on the retry, inside one item |
| Equivalent teeth mutant | L1077 | P1.6.4 note |
| Livelock in the control core | L1283–L1352 | P1.7's check fails; **P1.2.2 reopened**; P1.6 checks re-run |
| R7 CompAck timing too strict | L2479 | P2.5 reopened by a spec re-read in P2.3 |
| Reserved Order in our own test | L2489 | P2.7 reopened |
| Table teeth 66/156 | L2648–L3069 | P2.9's check (`table_teeth.py`: no unexpected survivors) fails; **P2.5 and P2.8 reopened**; P2.9 passes at 153 |
| Six gaps found by TL proofs | L3100–L3844 | P2.5 reopened by P4.1′ |
| Home Exclusive bugs + a false positive | L4350–L4561 | **P2.3 reopened**, plus P2.5 and P2.6 (a new table cell) |

`chi_flow_check` (P2.5) is reopened four times. It is the item whose real
check, "the checker catches what the spec forbids", was only partly
expressible when it was first closed. Each later item put a stronger check
on it: table mutation, proofs, the Home proof. The outline should let a leaf
carry a **list of checks that grows**, so that a reopen is a new check
failing and not a judgment call.

---

## 7. Session boundaries: steps and context

### 7.1 Method (estimates)

1. Group the main-thread API calls of both transcripts (819 = 665 main + 154
   docs; subagent sidechains excluded) into 34 real work spans by line
   range, read from the narration (§6.1). Each span maps to one leaf or a
   few adjacent leaves.
2. For each span, take its **growth**: the sum of the positive increases in
   context between consecutive calls. That is roughly the new tokens the
   work brings in (tool output, writes). The total is about **2.13M**.
3. Assume a fresh step starts at **O = 50k**. Real cold starts were 41k
   (main L26, docs L7). Post-compact restarts were 51–56k, including a 7–20k
   summary. A wpk step carries the memento, the item and the outline instead
   of the summary.
4. A leaf needs `ceil(growth / (budget − O))` steps. Every extra step adds 4
   orientation calls. Average context per call ≈ O + (headroom used) / 2.
5. Input-equivalent cost = 0.1 × (context read per call) + 2 × (tokens
   written to the cache: all growth, plus O per fresh step; 1-hour TTL). C4
   carry-over is ignored, because a step the hook stops does not carry.

What this leaves out:

- Re-reading in fresh steps is counted only as O and 4 calls. Spec reading
  recurred in reality (B13.9 at L640, B14 at L902, B2 and B9 at L2252–L2285),
  so a fresh step on an item with spec refs may well start at 70–90k, not 50k.
- Work order is the real order.
- A step that finishes several small leaves is counted as one step per leaf
  span, which overstates the step count for P0/P1 a little.

### 7.2 Result

| | Real | Fresh step per leaf, 80k budget | Same, 150k budget |
|---|---|---|---|
| Steps / sessions | 2 sessions, 6 `/compact` | **≈ 87 steps** | **≈ 45 steps** |
| API calls | 819 | ≈ 1030 | ≈ 860 |
| Average context per call | **≈ 265k** (main ≈ 255k) | ≈ 64k | ≈ 88k |
| Peak | 620k | ≤ 120k (hard stop at 1.5×) | ≤ 225k |
| Cache reads (input-equiv.) | 21.4M | 6.6M | 7.6M |
| Cache writes (input-equiv.) | 7.0M | 13.0M | 8.8M |
| **Total input-equivalent** | **28.4M** | **≈ 19.6M (−31%)** | **≈ 16.4M (−42%)** |

Per top-level item (steps at 80k / 150k):

| Item | Real calls | Steps 80k | Steps 150k |
|---|---|---|---|
| 1 Design (1.1.1–1.2) | 44 | 13 | 7 |
| 2 Gate detour (2.1, 2.2) | 18 | 2 | 2 |
| 3 Plan | 0 (no real counterpart) | 1 | 1 |
| P0 (incl. the resume orientation, socket move, CI) | 80 | 10 | 7 |
| P1 (incl. monitor, R3/bind map, F10) | 118 | 10 | 8 |
| P2 (slice, remainder + tables, table teeth) | 159 | 17 | 7 |
| Inserted formal work (F4 TL, dv-solve, Home plan, commit, what's next) | 246 | 21 | 9 |
| 6 Docs (child packet) | 154 | 14 | 5 |

Reading the numbers:

- **Context per call drops by 3–4×.** Total cost drops much less, by about a
  third, because fresh steps pay to write O into the cache again. At 80k,
  writes cost more than the real run's.
- **The 80k default is too small for this kind of project.** Leaves like the
  TL formal work (289k of growth) or Sphinx (286k) would take about 10 steps
  each. 120–150k fits the shape better. Even then, the large leaves are 2–3
  steps.
- The real run's 250k average came mostly from **carrying P0/P1 into P2**:
  the L2 first slice ran at 515k–620k (main L1912–L2173). Item boundaries
  remove exactly that.

---

## 8. The final tree

Markers: `[x]` done, `[~]` partial or deferred, `[ ]` not started, `[+]`
inserted mid-run, `[G]` gate. `(n)` is the estimated steps at a 150k budget.
`(–)` means the leaf shares a step with its neighbours.

```
- [x] 0 Triage → project; adapted: plan merged into design, gate 4 = notify   (–)
- [x] 1 Create a design (gather resources first)                             (7)
  - [x] 1.1 Gather resources
    - [x] 1.1.1 CHI spec: four readers (B1–B3, B4–B9, B10–B12+C, B13–B16)    (1)
    - [x] 1.1.2 fw-hdl kernel: ports, exports, fw_root, no bidi exists       (1)
    - [x] 1.1.3 fw-proto-wb and the fw-proto-kit skills                      (1)
    - [x] 1.1.4 Template: pss-registers-up, dv-flow-libproject, -libhdltest  (1)
    - [x] 1.1.5 fw-hdl formal notes, CHI brief, zuspec bundle/mirror,
                XLS examples, fw-proto-core                                  (2)
    - [ ] 1.1.6 Resource digest (proposed; skipped in reality)               (–)
  - [x] 1.2 Write design doc D§0–§12                                         (1)
- [G] 2 Design sign-off (always): Q0 answered; Q1 answered late; Q2–Q8 recs  (2)
  - [+][x] 2.1 Naming research (IP-XACT, PyMTL3, Amaranth, TLM-2, Chisel)    (1)
  - [+][x] 2.2 Rename to fw_socket/fw_mirror; reapply after overwrite        (1)
  - [+][x] 2.3 F10: does fw-hdl benefit from native credits? (L541/L577)     (–, answered in P1.11)
- [x] 3 Detailed plan: expand item 5 from D§10                                (1)
- [G] 4 Plan review (notify): xezim, CI timing, P2 subset, F-order, commits  (0)
- [~] 5 Implement the detailed plan
  - [x] P0 Template, socket spike, types, L1 in TLM                          (7)
    - [~] P0.1 Template
      - [x] P0.1.1 dfm project on project.dv, suite × view                   (–)
      - [~] P0.1.2 IVPM dep-sets (svunit + 3 libs only; restructure deferred)(–)
      - [x] P0.1.3 .gitignore (spec, packages, rundir), README               (–)
      - [x] P0.1.4 lint-rtl at 0 findings (done in P1)                       (–)
      - [x] P0.1.5 CI scripts and workflows (done after P1; green after
                   fw-hdl d5d17c1)                                           (1)
      - [+][x] P0.1.6 install fw-hdl dfm plugin in packages/python           (–)
    - [x] P0.2 Socket/mirror spike (R1)
      - [x] P0.2.1 classes + IMP macros (staged in src/fw_ext first)         (–)
      - [x] P0.2.2 spike tests: binds, hierarchy, unbound, toy bridge        (1)
      - [x] P0.2.3 negative compiles (socket↔socket, swapped <I,E>)          (–)
      - [~] P0.2.4 xezim (blocked: xezim 0.11.1 cannot parse fw-hdl)         (–)
      - [x] P0.2.5 R3: fw_root restart + elaborated flag (in fw-hdl)         (1)
      - [+][x] P0.2.6 move socket into fw-hdl, both checkouts, change log    (1)
      - [+][x] P0.2.7 bind map: one entry per socket/mirror link             (–)
    - [x] P0.3 chi_types_pkg
      - [x] P0.3.1 Issue H encodings                                         (–)
      - [x] P0.3.2 flit structs, link params, width check (137/94/240)       (1)
      - [~] P0.3.3 tables/ with encodings (moved to P2.6)                    (–)
    - [x] P0.4 L1 class layer: APIs, typedefs, IMP macros, cfg, endpoints    (–)
    - [x] P0.5 chi_env_tlm + l1_basic (7/7 tlm)                              (1)
  - [~] P1 Link layer, transactors, formal                                   (8)
    - [~] P1.1 pack/unpack (class-layer chi_wire; synth pack deferred)       (–)
    - [x] P1.2 Link cores
      - [x] P1.2.1 TX/RX cores                                               (1)
      - [x] P1.2.2 control core (reopened: IDLE_CYCLES livelock fix)         (–)
    - [x] P1.3 four wrappers + one chi_link_xtor_if                          (1)
    - [x] P1.4 bridges + fw_root_bind_socket/mirror                          (–)
    - [x] P1.5 link + ctrl checkers, chi_env_xtor                            (1)
    - [x] P1.6 Formal back-to-back
      - [x] P1.6.1 harness, PROPERTIES.md, fv BMC 30                         (1)
      - [x] P1.6.2 fv-prove (two failed attempts: wraparound, bad start)     (–)
      - [x] P1.6.3 fv-cover (6 goals)                                        (–)
      - [x] P1.6.4 fv-teeth (8/8; equivalent mutants rejected)               (–)
    - [x] P1.7 l0_link suite (incl. reset mid-traffic)                       (1)
    - [x] P1.8 monitor: chi_mon_if, taps, pin monitor (ring buffer)          (1)
    - [~] P1.9 RP/shared credits, SYSCO, parity/DataCheck, LDE (deferred)    (0)
    - [x] P1.10 phase close: CI local 7/7, D§13 written                      (1)
    - [+][x] P1.11 F10 credit sizing: fv-sizing, DEPTH=5                     (–)
  - [~] P2 L2 non-coherent, RN-I/HN-I/SN-I subset                            (7)
    - [x] P2.1 chi_xact_if + RN-I adapter (TxnID pool, retry, CompAck)       (1)
    - [x] P2.2 SN adapter + chi_mem_model                                    (–)
    - [x] P2.3 chi_test_home + chi_line_lock (reopened: Excl bugs)           (1)
    - [x] P2.4 chi_to_mem (fw_mem_if over CHI)                               (–)
    - [x] P2.5 chi_flow_check R1–R13 (reopened ×4: R7, teeth, proofs, Excl)  (1)
    - [x] P2.6 F3 flow tables, generator, tables-check                       (1)
    - [x] P2.7 l2_rn_sn 15/15 both views (reopened: reserved Order)          (–)
    - [x] P2.8 l2_checker_teeth 30/30 incl. matrix tests                     (1)
    - [x] P2.9 table-cell mutation (66 → 153 of 156)                         (2)
    - [+][ ] P2.10 subset remainder: ReadNoSnpSep, NCBWrDataCompAck, OWO,
                   Excl, DataCheck, TagMatch                                 (0)
  - [ ] P3 RN-F at the kit level                                             (0)
    - [ ] P3.1 snoop handler API + default handler
    - [ ] P3.2 B4.11.1 hazards
    - [ ] P3.3 coherent opcode subset at the requester
    - [ ] P3.4 l2_rnf against a scripted Home
  - [~] P4 Formal opportunities (F4 pulled ahead of P3)                      (9)
    - [+][x] P4.1′ F4 at the transaction level: chi_flow_fsm_pkg, formal_tl,
                  fv-tl in CI (user scope L3100)                             (3)
    - [+][x] P4.1′a dv-solve vs Bitwuzla (user scope L3925)                  (1)
    - [+][x] P4.1′b Home plan as pure functions + proof (L4066/L4119)        (3)
    - [+][x] P4.1′c commit f893bca (user L3845; no attribution, no docs)     (1)
    - [ ] P4.1 F4 RTL monitor on the cores (SymbiYosys)
    - [ ] P4.1″ two-transaction proofs (R1, P-credits); RN adapter as pure fns
    - [ ] P4.2 F5 SPL formal on the L2 adapters
    - [~] P4.3 F6 rtl view (+ synthesizable pack from P1.1)
- [+][~] 6 Documentation (child packet; docs session)                        (5)
  - [+][x] 6.1 Sphinx site with sphinx-systemverilog (67 pages, -W clean)    (3)
  - [+][x] 6.2 Publish: .forgejo docs.yml; fw-hdl commit + push (d5d17c1)    (1)
  - [+][G] 6.3 sphinx-systemverilog feature list (if-open; awaiting user)    (1)
- [+][ ] 7 Upstream reports (outside the repo)
  - [ ] 7.1 fw-hdl formal-flow issues T1–T8 (tl-formal-findings §7)
  - [ ] 7.2 dv-solve: 8-parameter define-fun limit; 0.2.3 "unknown"
  - [ ] 7.3 dfm: suites.X exits 0 on failure; --tests selection broken
```

**Counts.** 72 leaves, gates excluded (item 0, item 3 and the unbuilt 1.1.6
included):

| Status | Leaves |
|---|---|
| `[x]` done | 54 |
| `[~]` partial or deferred | 6 |
| `[ ]` not started | 12 (P3, the P4 rest, item 7, P2.10, 1.1.6) |
| `[+]` inserted mid-run | 14, of which 13 are done; plus item 7's 3 upstream reports |

The planned tree at item 3 had about 55 leaves. Execution inserted 17 and
dropped none, but left 6 partial or deferred. In steps, the inserted work
(P4.1′ and its siblings, plus the docs) is about 13 of the 45, close to a
third of the project.

---

## 9. Observations

### Where the shape fit

- **P0/P1 match the outline closely.** The real order (spike → types → L1 →
  env → cores → formal → transactors → `l0_link`) is the D§10 order, with
  small swaps. Every leaf has a mechanical check from D§13.2. This is the
  slice where a cursor and checks would do their job.
- **The design gate is real and was used.** The user researched, decided,
  and signed off (L382, L439, L539). Making Q2–Q8 explicit costs one line
  ("take the recommendations") and would have avoided the Q1 staging
  detour.
- **Status leaves the doc.** D§13 is about 200 lines of status, departures
  and next steps, re-read at every resume. In the shape, the departures are
  notes on P1.1, P1.2.2, P1.3, P2.3 and P2.10. D§13.4 "Next" is the
  remaining `[ ]` items. The doc keeps only the reasoning.
- **The docs session is a child packet.** It was separate in reality too,
  with its own context, and touched only `docs/` and fw-hdl.

### Where it strained

1. **The cursor rule would stall on deferred work.** "The current item is
   the first leaf not done" would have sent the agent into P1.9 (RP, SYSCO)
   before P2, and into P3 before the F4 work the user steered toward. The
   outline needs a **`deferred` status the cursor skips** (with a reason and
   a "revisit after" pointer), and **cheap reordering** (F4 pulled ahead of
   P3).
2. **Gate questions arise during implementation, not only at template
   positions.** Examples: xezim cannot parse fw-hdl (P0.2.4), Q1 asked again
   at L1506, the R11 reading of B9.1.2 vs Table B9.7, and the docs session's
   closing question (docs L1026). Gates must be **insertable on any item**.
   Best as `if-open` gates that let work continue on a provisional answer
   (as the agent did by staging the socket), plus an automatic "revisit if
   answered differently" item.
3. **Research is not a task.** "Pay attention, see what you can find"
   (L3100), "try dv-solve and compare" (L3925), the credit question
   (L541/L577), the naming research (L382) and the sphinx-systemverilog
   features (docs L1026) have no pass/fail check. Their deliverable is a
   findings section and an answer. A third item kind, **`research`**, would
   fit: a `question`, a `deliverable` (a doc section), a step cap, and an
   end that is either an answer or a gate. It often spawns work items too:
   the TL formal research produced `chi_flow_fsm_pkg` and six checker fixes.
4. **Item size is unknowable at plan time.** P0/P1 leaves are ¼–½ step;
   P2.5, P4.1′ and 6.1 are 3 steps each at 150k. The plan step should
   estimate size from refs. The executor should allow several small items
   per step and split a big item when its first step ends with the hook.
5. **Checks that grow, and reopening.** `chi_flow_check` was "done" four
   times. A leaf should hold a list of checks, and a later item should be
   able to **add a check to an earlier item**: the table-mutation threshold,
   or the proof that the Home is legal. A failure then reopens that item
   mechanically. Today's single `check` string cannot express this.
6. **Cross-repo work needs its own field and permission.** fw-hdl was edited
   in two checkouts (`~/projects/featherweight-hdl/fw-hdl` and
   `packages/fw-hdl`), logged in `docs/fw-hdl-changes.md`, then committed
   and pushed a day later from the docs session. Items need a `repo`. The
   gate should carry write permission per repo. The step commit must know
   which repo it is committing in.
7. **Commit policy conflicts with commit-per-step.** The user kept
   everything uncommitted until L3845, then excluded working docs, and later
   committed them (74c7359). work-packet commits state each step. It needs
   either a packet-level "work branch, squash on hand-off" mode or state
   kept outside the target repo. Either has to be settled before a replay
   (E2).
8. **Long-running checks.** Table mutation took 25 minutes; the simulation
   mutation run took 2.5 hours (L3843). The runs collided with edits (L3821,
   L4255; fixed with a worktree, L4250). A step must be able to end as
   "waiting on job X". The next step must resume on the result, and the
   executor must stop other items from writing the files the job reads.
9. **Discovered tool bugs are neither items nor notes.** Examples: the
   `dfm` exit code (L2754), test selection (L2067), Verilator's virtual
   interface queues (L1795), the xezim parse failure, the dv-solve parameter
   limit. They belong in an "upstream" list (item 7 above), not in this
   packet's work. Beads' `discovered-from` link fits.
10. **Gate 4 added nothing here.** The plan was the design's §10. A `notify`
    gate is the right default for `project` when the design gate already
    covered the plan. The real plan decisions (the P2 subset, commit policy)
    surfaced later and would be better caught by point 2.

### Changes to the shape this suggests

| Change | Why (from this replay) |
|---|---|
| Add a `deferred` status (with reason) that the cursor skips; allow moving items | P1.9, P0.3.3, P2.10; F4 ahead of P3 |
| Add a `research` item kind: question, deliverable, step cap, ends in an answer or a gate | L382, L541, L3100, L3925, docs L1026 |
| Allow inline gates on any item (`if-open`, provisional answer + revisit) | Q1 at L1506, xezim, R11, docs L1026 |
| Make `check` a list, and let later items add checks to earlier ones | P2.5 reopened four times |
| Make the item design → resources produce a digest file that refs point into | the 18-call, 94k re-orientation at L541–L680 |
| Allow several small items per step; split big items when the hook fires | ¼-step P0 leaves vs 3-step P2.5/P4.1′ |
| Add a `repo` field on items; put cross-repo write permission in the design gate | fw-hdl staging and move, two checkouts, push from docs |
| Allow a step to end as "waiting on job"; lock files the job reads | 2.5 h mutation runs; collisions at L3821, L4255 |
| Keep an "upstream" list for discovered tool bugs | dfm, Verilator, xezim, dv-solve |
| Default `project` gate 4 to `notify` when the design holds the phase plan | L539 covered both gates |
| Raise `step_context_tokens` for `work/` projects to about 150k | 80k → about 87 steps and higher write cost; 150k → about 45 steps, −42% input-equivalent (§7) |
