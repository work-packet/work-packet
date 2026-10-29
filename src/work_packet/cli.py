"""The ``wpk`` command line. Stage 1 subcommands land here (docs/stage1-plan.md)."""
import argparse
import os
import re
import sys

from .__about__ import __version__


def cmd_check(args) -> int:
    from .check import check
    rep = check(args.path)
    base = os.path.abspath(args.path) if args.path else None
    for i in rep.issues:
        if args.quiet and i.level != "error":
            continue
        p = i.path
        if base and (p == base or p.startswith(base + os.sep)):
            p = os.path.relpath(p, base)
        loc = p if i.field is None else "%s: %s" % (p, i.field)
        print("%s: %s: %s" % (i.level, loc, i.msg))
    ne, nw = len(rep.errors), len(rep.warnings)
    print("%d error%s, %d warning%s" % (ne, "" if ne == 1 else "s",
                                         nw, "" if nw == 1 else "s"),
          file=sys.stderr)
    if ne or (args.strict and nw):
        return 1
    return 0


def _outcome(out) -> int:
    print("wpk: %s" % out.msg, file=sys.stderr)
    return out.code


class Terminated(BaseException):
    """SIGTERM: the scheduler cancelled this step (Stop now, a farm limit)."""


def _on_term(signum, frame):
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # once: let the unwinding finish
    raise Terminated()


def cmd_step(args) -> int:
    import signal
    from . import executor
    signal.signal(signal.SIGTERM, _on_term)     # unwind: kill the model, free the lease
    try:
        return _outcome(executor.step(args.target, force=args.force, lost=args.lost))
    except Terminated:
        print("wpk: step stopped (SIGTERM)", file=sys.stderr)
        return 128 + signal.SIGTERM


def cmd_recover(args) -> int:
    from . import executor
    return _outcome(executor.recover(args.target))


def _err(msg, code=4) -> int:
    print("wpk: %s" % msg, file=sys.stderr)
    return code


def _packet(target):
    from . import registry
    from .packet import Packet
    return Packet(registry.resolve(target))


def cmd_new(args) -> int:
    from . import project
    if args.prompt_file:
        try:
            with open(args.prompt_file, encoding="utf-8") as fp:
                prompt = fp.read()
        except OSError as e:
            return _err(str(e))
    else:
        prompt = args.prompt
    copy = None
    if args.from_setup:
        from . import setup
        try:
            src = _project_dir(args.from_setup)
            copy = setup.copy_setup(project.load_project(src), args.name, src)
        except (ValueError, project.ProjectError) as e:
            return _err(str(e))
    packet = args.here or args.packet
    if args.here and args.dir:
        return _err("--here and --dir: give one")
    try:
        plan = project.new(args.name, prompt, path=os.getcwd() if args.here else args.dir,
                           model=args.model, tz=args.tz, paused=args.paused,
                           dry_run=args.dry_run, extra=copy, packet=packet)
    except (project.ProjectError, OSError) as e:
        return _err(str(e))
    verb = "Would create" if args.dry_run else "Created"
    print("%s project %s at %s" % (verb, plan.name, plan.path))
    for f in plan.files:
        print("  " + f)
    print("Root packet %s, model %s, zone %s" % (plan.root, plan.model, plan.tz or "local"))
    print("Steps run with --permission-mode %s --allowedTools %s" % (
        plan.permission_mode, ",".join(plan.allowed_tools)))
    if args.dry_run:
        return 0
    if packet:
        from . import layout
        folder = layout.packet_folder(plan.path)
        print("Steps work in %s (the packet folder); the card is %s." % (
            folder, os.path.basename(layout.card_path(plan.path, plan.name))))
    if prompt is None:
        print("The root is held for setup. Fill in %s:" % plan.path)
        print("  prompt.md   the first instruction (or `wpk instruct %s --template outline`)"
              % plan.name)
        if not packet:
            print("  work/       what the task works on: git clones (steps get a worktree "
                  "of each), or any directory")
        print("  state/      plans and notes the steps read (copied in at the first step)")
        print("  identity/   links to read-only material")
        print("Next: `wpk setup %s` (a guided setup), or `wpk doctor %s` (what is missing)."
              % (plan.name, plan.name))
    else:
        print("Run `wpk tick` to start it%s." % (" (it is PAUSED: `wpk resume %s` first)"
                                                 % plan.name if args.paused else ""))
    return 0


def cmd_start(args) -> int:
    """docs/starters-v1.md: make a packet with a starter, or from a recipe."""
    import json
    from . import starters
    if args.list or not (args.starter or args.recipe):
        for n in starters.names():
            s = starters.get(n)
            print("%-8s %s" % (n, s.help))
            for f in s.fields:
                print("         %-8s %s%s%s" % (f.key + "=", f.label, " (%s)" % f.placeholder
                                                    if f.placeholder else "",
                                                    ", required" if f.required else ""))
        print("every starter: name= dir= objective= from= model= harness= hold=no")
        for n, e in starters.broken().items():
            print("%s: did not load: %s" % (n, e))
        return 0
    try:
        if args.recipe:
            fp = sys.stdin if args.recipe == "-" else open(args.recipe, encoding="utf-8")
            with fp:
                recipe = starters.check(json.load(fp))
        else:
            vals = {}
            for kv in args.values:
                k, eq, v = kv.partition("=")
                if not eq:
                    return _err("%s: give key=value" % kv)
                vals[k] = v
            if args.search:
                for c in starters.get(args.starter).search(args.search, vals.get(
                        args.search, ""), vals):
                    print("%-40s %s" % (c["value"], c["label"]))
                return 0
            recipe = starters.from_values(args.starter, vals)
        if args.go:
            recipe["hold"] = False
        lines = starters.preview(recipe)
        if args.json:
            print(starters.dumps(recipe))
        for ln in lines:
            print(ln)
        if args.dry_run:
            return 0
        plan = starters.make(recipe)
    except (starters.StartError, ValueError, OSError) as e:
        return _err(str(e))
    print("Created %s: the card is %s" % (plan.name, layout_card(plan)))
    return 0


def layout_card(plan):
    from . import layout
    return layout.card_path(plan.path, plan.name)


def cmd_convert(args) -> int:
    from . import convert
    try:
        p = convert.convert(args.name, dry_run=args.dry_run)
    except (convert.ConvertError, OSError) as e:
        return _err(str(e))
    verb = "Would move" if args.dry_run else "Moved"
    if p["in_place"]:
        print("%s %s into %s" % (verb, ", ".join(p["items"]), p["dot"]))
    else:
        print("%s %s to %s" % (verb, p["from"], p["dot"]))
    print("  packets/ -> runs/ (%d runs)" % len(p["runs"]))
    if p["card"]:
        print("  card -> %s" % p["new_card"])
    print("Packet folder: %s" % p["folder"])
    if args.dry_run:
        return 0
    print("Backup: %s" % p["backup"])
    if p["checks"]:
        for x in p["checks"]:
            print("  problem: %s" % x)
        return 1
    print("Checked: history verifies, stats agree, wpk check clean.")
    return 0


def cmd_adopt(args) -> int:
    from . import project
    try:
        e = project.adopt(args.dir)
    except (project.ProjectError, OSError) as ex:
        return _err(str(ex))
    print("Registered %s (%s)" % (e["name"], e["path"]))
    return 0


def cmd_rm(args) -> int:
    from . import registry
    if registry.get(args.name) is None:
        return _err("no registered project named %r" % args.name)
    registry.unregister(args.name)
    print("Removed %s from the registry; its files are untouched" % args.name)
    return 0


def cmd_board(args) -> int:
    """Boards of the dash (docs/boards.md)."""
    from . import registry
    try:
        if args.op == "new":
            registry.new_board(args.name, args.title)
            print("Made board %s" % args.name)
        elif args.op == "rm":
            moved = registry.delete_board(args.name)
            print("Deleted board %s%s" % (args.name, "; moved %s to %s" % (
                ", ".join(moved), registry.DEFAULT_BOARD) if moved else ""))
        elif args.op == "move":
            was = registry.move(args.name, args.board)
            print("%s is on %s already" % (args.name, args.board) if was == args.board else
                  "Moved %s from %s to %s" % (args.name, was, args.board))
        else:
            bs = registry.boards()
            on = [b["name"] for b in bs]
            es = registry.entries()
            for b in bs:
                ps = [e["name"] for e in es if registry.board_of(e, on) == b["name"]]
                print("%-20s %s" % (b["name"], ", ".join(ps) or "-"))
    except registry.BoardError as e:
        return _err(str(e))
    return 0


def cmd_pr(args) -> int:
    """Hand a packet back to its forge: push its branch, open a pull request."""
    from . import pr
    try:
        r = pr.open_pr(args.project, draft=args.draft, dry_run=args.dry_run)
    except pr.PRError as e:
        return _err(str(e))
    if args.dry_run:
        print("would push %s (%d commit%s) to %s:%s and open a pull request into %s:" % (
            r["branch"], r["ahead"], "" if r["ahead"] == 1 else "s", r["forge"], r["repo"],
            r["base"]))
        print("\n# %s\n\n%s" % (r["title"], r["body"]))
        return 0
    pr.forget_failure(args.project)
    print("%s %s: %s" % ("opened" if r["new"] else "pushed; already open:",
                         "draft" if r.get("draft") else "pull request", r["url"]))
    return 0


def cmd_docs(args) -> int:
    """Sphinx docs in the project's work: list them, build them, open the newest
    (docs/sphinx-docs-v1.md)."""
    import datetime
    import webbrowser
    from . import docs, setup
    try:
        tg = setup.target(args.project or os.getcwd())
    except setup.SetupError as e:
        return _err(str(e))
    cfg = docs.settings(tg.proj)
    sets = docs.detect(tg.proj, cfg=cfg)
    if not sets:
        print("no Sphinx docs found in %s's work (set [docs] source in project.toml "
              "if they are somewhere unusual)" % tg.name)
        return 0
    code = 0
    for ds in sets:
        if args.build and (args.force or docs.is_stale(ds)):
            print("%s/%s: building %s ..." % (ds.entry, ds.name, ds.src), flush=True)
            rec = docs.build(ds, cfg, by="cli")
            if rec is None:
                print("  a build of it is under way already")
            elif rec["result"] == "failed":
                code = 1
        st = docs.state(ds)
        b = st["built"]
        when = datetime.datetime.fromtimestamp(b["end"]).strftime("%Y-%m-%d %H:%M") \
            if b else ""
        what = "building" if st["building"] else (
            "never built" if not b else "%s %s%s%s" % (
                b["result"], when, " (%d warnings)" % b["warnings"] if b["warnings"] else "",
                ": " + b["why"] if b.get("why") else ""))
        print("%s/%s  %s  %s%s" % (ds.entry, ds.name, st["rel"], what,
                                   ", stale" if st["stale"] and not st["building"] else ""))
        index = os.path.join(ds.html, "index.html")
        if st["has_html"]:
            print("  %s\n  board: /p/%s/docs/%s/%s/" % (index, tg.name, ds.entry, ds.name))
            if args.open:
                webbrowser.open("file://" + index)
        elif b:
            print("  log: %s" % os.path.join(ds.out, "build.log"))
    return code


def cmd_seen(args) -> int:
    """Finished projects no one has looked at (docs/overview-recent.md): list them,
    or mark them seen, as opening them on the board does."""
    from . import executor, layout, registry
    from .dash import data
    from .packet import Packet
    cols, _ = data.board()
    unread = sorted((c for v in cols.values() for c in v if c["unread"]),
                    key=lambda c: c["unread"]["at"], reverse=True)
    if not args.projects and not args.all:
        for c in unread:
            u = c["unread"]
            print("%-8s %-24s %s  %s" % (u["kind"].upper(), c["name"], u["local"],
                                         (u["outcome"] or "").splitlines()[0][:80]
                                         if u["outcome"] else ""))
        if not unread:
            print("nothing finished that you have not seen")
        return 0
    names = [c["name"] for c in unread] if args.all else args.projects
    worst = 0
    for name in names:
        e = registry.get(name)
        if e is None:
            worst = _err("no project %s" % name)
            continue
        out = executor.mark_seen(Packet(layout.run_dir(e["path"], e["root"])))
        print("%s: %s" % (name, out.msg))
        worst = worst or out.code
    return worst


def cmd_watch(args) -> int:
    """Watchers on boards (docs/starters-v1.md): list them, or poll them now."""
    import datetime
    from . import watch
    if args.op != "poll":
        ws = watch.watchers()
        for w in ws:
            if w.get("problems"):
                print("%s: bad [[watch]]: %s" % (w["board"], "; ".join(w["problems"])))
                continue
            s = watch.load_state(w)
            when = datetime.datetime.fromtimestamp(s["polled"]).strftime("%Y-%m-%d %H:%M") \
                if s.get("polled") else "never"
            print("%s/%s%s  every %s  polled %s  made %d%s" % (
                w["board"], w["name"], "" if w.get("enabled", True) else " (off)",
                w.get("every", "15m"), when, len(s["seen"]),
                ", %d failing" % len(s["failed"]) if s["failed"] else ""))
            print("    %s%s -> %s" % (", ".join(w["repos"]), "  labels: " + ", ".join(
                w["labels"]) if w.get("labels") else "", w["dir"]))
            for e in s.get("errors") or []:
                print("    error: %s" % e)
        if not ws:
            print("No watchers. Add [[watch]] to boards/<board>.toml (docs/starters-v1.md).",
                  file=sys.stderr)
        return 0
    try:
        ws = watch.find(args.which)
    except watch.WatchError as e:
        return _err(str(e))
    rc = 0
    for w in ws:
        r = watch.poll(w, dry_run=args.dry_run)
        for k in r["would"]:
            print("%s/%s: would make a packet for %s" % (w["board"], w["name"], k))
        for k, name in r["made"]:
            print("%s/%s: made %s for %s" % (w["board"], w["name"], name, k))
        for k, e in r["failed"].items():
            print("%s/%s: %s: %s" % (w["board"], w["name"], k, e))
            rc = 1
        for e in r["errors"]:
            print("%s/%s: %s" % (w["board"], w["name"], e))
            rc = 1
        if not (r["would"] or r["made"] or r["failed"] or r["errors"]):
            print("%s/%s: nothing new" % (w["board"], w["name"]))
    return rc


def cmd_ps(args) -> int:
    from . import registry, views
    es = registry.entries()
    if args.project:
        es = [e for e in es if e["name"] == args.project]
        if not es:
            return _err("no registered project named %r" % args.project)
    lines = views.ps(es, show_all=args.all)
    for line in lines:
        print(line)
    if not lines:
        print("No active projects%s." % ("" if args.all else " (--all shows finished ones)"),
              file=sys.stderr)
    return 0


def cmd_show(args) -> int:
    from . import registry, views
    try:
        for line in views.show(_packet(args.target)):
            print(line)
    except (registry.LookupFailed, OSError) as e:
        return _err(str(e))
    return 0


def cmd_report(args) -> int:
    from . import registry, views
    try:
        for line in views.report_lines(_packet(args.target)):
            print(line)
    except (registry.LookupFailed, OSError) as e:
        return _err(str(e))
    return 0


def cmd_log(args) -> int:
    from . import registry, views
    try:
        for line in views.log(_packet(args.target), step=args.step):
            print(line)
    except (registry.LookupFailed, OSError) as e:
        return _err(str(e))
    return 0


def cmd_admin(args) -> int:
    """pause / resume: one packet, or every packet of a project."""
    from . import executor, registry, views
    from .packet import Packet
    op = args.cmd
    e = registry.get(args.target)
    if e is None and os.path.isfile(os.path.join(args.target, "project.toml")):
        from .project import load_project
        try:
            d = load_project(args.target)
        except Exception as ex:
            return _err(str(ex))
        e = {"name": d["name"], "path": os.path.abspath(args.target), "root": d["root"]}
    if e is None:
        try:
            pkts = [_packet(args.target)]
        except registry.LookupFailed as ex:
            return _err(str(ex))
    else:
        want = {"pause": ("RUNNABLE", "SLEEPING"), "resume": ("NEEDS_INPUT", "PAUSED"),
                "handoff": ("NEEDS_INPUT", "PAUSED", "FAILED")}[op]
        pkts = [p for _, p, m, _ in views.packets(e["path"], e["root"])
                if m is not None and m["state"] in want]
        if not pkts:
            print("wpk: nothing to %s in %s" % (op, e["name"]), file=sys.stderr)
            return 0
    note = None
    if op == "handoff":
        if args.note_file == "-":
            note = sys.stdin.read()
        elif args.note_file:
            try:
                with open(args.note_file, encoding="utf-8") as fp:
                    note = fp.read()
            except OSError as ex:
                return _err(str(ex))
        else:
            note = args.message
    if op in ("resume", "handoff") and not args.force:
        refused = _setup_guard(pkts)
        if refused:
            return refused
    code = 0
    for p in pkts:
        out = executor.admin(Packet(p.path), op, note=note)
        print("wpk: %s" % out.msg, file=sys.stderr)
        code = max(code, out.code)
        if op == "pause" and out.code == 0:
            _cancel_pending(p.wpid)
    return code


def _cancel_pending(wpid):
    """A paused packet's job that is still waiting in the batch queue is withdrawn."""
    from .sched import authz, control
    for r in control.cancel_pending(wpid, authz.principal_cli()):
        print("wpk: cancelled its pending job %s" % r.id, file=sys.stderr)


def _setup_guard(pkts):
    """``resume``/``handoff`` of a root held for setup: refuse while doctor finds
    something missing (docs/setup.md §7)."""
    from . import setup
    from .project import held_for_setup
    for p in pkts:
        try:
            meta, _ = p.load_status()
            if not held_for_setup(meta):
                continue
            tg = setup.target(p.path)
        except Exception:
            continue
        checks = setup.readiness(tg, tools=False)
        miss = setup.missing(checks)
        if miss:
            print("wpk: %s is not set up yet:" % tg.name, file=sys.stderr)
            for c in miss:
                print("  %s %s" % (MARK["missing"], c.title), file=sys.stderr)
                for f in c.fix[:1]:
                    print("      " + f, file=sys.stderr)
            print("wpk: `wpk doctor %s` shows all checks; --force hands it off anyway"
                  % tg.name, file=sys.stderr)
            return 1
    return 0


# --- setup (docs/setup.md) -------------------------------------------------------

MARK = {"ok": "\u2713", "info": "\u00b7", "warn": "!", "missing": "\u2717"}


def _target(t):
    from . import setup
    return setup.target(t)


def _doctor_lines(tg, checks, verbose=False):
    from . import layout, setup
    meta = tg.status() or {}
    st = meta.get("state", "?") + (": %s" % meta["reason"] if meta.get("reason") else "")
    out = ["%s  %s   root %s  (%s)" % (tg.name, setup.tilde(tg.proj), tg.packet.wpid[:8], st)]
    for g in setup.GROUPS:
        cs = [c for c in checks if c.group == g]
        if not cs:
            continue
        head = g
        if g == "work" and not layout.is_packet_layout(tg.proj):
            head += "      " + setup.tilde(tg.work)
        out.append("")
        out.append(head)
        for c in cs:
            out.append("  %s %s" % (MARK[c.level], c.title))
            if c.level in ("warn", "missing") or verbose:
                if c.detail and (verbose or c.level == "missing"):
                    out.append("      " + c.detail)
                for f in c.fix:
                    out.append("      $ " + f)
    nm = len(setup.missing(checks))
    nw = sum(1 for c in checks if c.level == "warn")
    out.append("")
    out.append("%d missing, %d warning%s.  Next: %s" % (
        nm, nw, "" if nw == 1 else "s", setup.next_step(tg, checks)))
    return out


def cmd_doctor(args) -> int:
    import json
    from . import registry, setup
    if args.target is None:
        checks = setup._tools()
        rows = []
        for e in registry.entries():
            try:
                tg = setup.target(e["name"])
            except setup.SetupError as ex:
                rows.append({"name": e["name"], "error": str(ex)})
                continue
            cs = setup.readiness(tg, tools=False)
            rows.append({"name": tg.name, "missing": len(setup.missing(cs)),
                         "warnings": sum(1 for c in cs if c.level == "warn"),
                         "state": (tg.status() or {}).get("state"),
                         "next": setup.next_step(tg, cs)})
        if args.json:
            print(json.dumps({"tools": [c.to_json() for c in checks], "projects": rows},
                             indent=1))
        else:
            for c in checks:
                print("%s %s" % (MARK[c.level], c.title))
                for f in c.fix:
                    print("    $ " + f)
            for r in rows:
                if "error" in r:
                    print("%s %s: %s" % (MARK["missing"], r["name"], r["error"]))
                else:
                    print("%s %-20s %-10s %d missing, %d warnings%s" % (
                        MARK["missing" if r["missing"] else "ok"], r["name"], r["state"],
                        r["missing"], r["warnings"],
                        ("   next: " + r["next"]) if r["missing"] else ""))
        return 1 if any(c.level == "missing" for c in checks) else 0
    try:
        tg = _target(args.target)
        if args.run:
            setup.run_smoke(tg, echo=lambda m: print(m, file=sys.stderr))
    except setup.SetupError as e:
        return _err(str(e))
    checks = setup.readiness(tg)
    if args.fix:
        did = False
        for c in checks:
            if c.safe and c.level in ("warn", "missing") and c.fix:
                for f in c.fix:
                    r = setup.run_fix(f)
                    print("wpk: %s %s" % ("ran" if r.returncode == 0 else "FAILED:", f),
                          file=sys.stderr)
                    if r.returncode:
                        print((r.stderr or r.stdout).rstrip(), file=sys.stderr)
                        break
                did = True
        if did:
            checks = setup.readiness(tg)
    if args.json:
        print(json.dumps({"project": tg.name, "path": tg.proj, "packet": tg.packet.path,
                          "checks": [c.to_json() for c in checks],
                          "next": setup.next_step(tg, checks)}, indent=1))
    else:
        for line in _doctor_lines(tg, checks, verbose=args.verbose):
            print(line)
    return 1 if setup.missing(checks) else 0


def cmd_path(args) -> int:
    from . import setup
    try:
        tg = _target(args.target)
    except setup.SetupError as e:
        return _err(str(e))
    if args.packet:
        print(tg.packet.path)
    elif args.state:
        print(tg.state)
    elif args.work is not None:
        if args.work == "":
            print(tg.work)
        else:
            if args.work not in tg.entries():
                return _err("no %r in %s's work/ (there is: %s)" % (
                    args.work, tg.name, ", ".join(tg.entries()) or "nothing"))
            print(os.path.join(tg.work, args.work))
    else:
        print(tg.proj)
    return 0


def cmd_shell(args) -> int:
    from . import setup
    try:
        tg = _target(args.target)
    except setup.SetupError as e:
        return _err(str(e))
    repo = args.repo
    if repo is None and len(tg.entries()) == 1:
        repo = tg.entries()[0]
    if repo and repo not in tg.entries():
        return _err("no %r in %s's work/" % (repo, tg.name))
    d = setup.shell_dir(tg, repo)
    print("wpk: a shell in %s (exit to leave)" % setup.tilde(d), file=sys.stderr)
    import subprocess
    return subprocess.call(setup.shell_argv(tg), cwd=d, env=setup.shell_env(tg))


def _helper(args, fn) -> int:
    from . import setup
    try:
        tg = _target(args.target)
        msgs = fn(tg)
    except setup.SetupError as e:
        return _err(str(e))
    for m in msgs:
        print("wpk: %s" % m, file=sys.stderr)
    return 0


def cmd_add_input(args) -> int:
    from . import setup
    return _helper(args, lambda tg: setup.add_input(tg, args.files, force=args.force))


def cmd_add_smoke(args) -> int:
    from . import setup
    return _helper(args, lambda tg: setup.add_smoke(tg, args.command, args.repo))


def cmd_instruct(args) -> int:
    from . import setup

    def run(tg):
        if args.file == "-":
            text = sys.stdin.read()
        elif args.file:
            with open(args.file, encoding="utf-8") as fp:
                text = fp.read()
        else:
            body, _ = setup.instruction(tg)
            start = setup.template_text(tg, args.template) if args.template else body
            text = _edit(start, tg)
            if text is None:
                return ["unchanged"]
        return setup.instruct(tg, text)
    try:
        return _helper(args, run)
    except OSError as e:
        return _err(str(e))


def _edit(text, tg):
    """``text`` edited in ``$VISUAL``/``$EDITOR``; None if unchanged."""
    import shlex
    import subprocess
    import tempfile
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w", suffix=".md", prefix="wpk-%s-" % tg.name,
                                     delete=False) as fp:
        fp.write(text)
    try:
        if subprocess.call(shlex.split(ed) + [fp.name]):
            return None
        with open(fp.name, encoding="utf-8") as f:
            new = f.read()
    finally:
        os.unlink(fp.name)
    return None if new == text else new


def cmd_setup(args) -> int:
    from . import setup
    if args.apply:
        if args.target is None:
            return _err("--apply needs a project")
        r = _helper(args, setup.apply)
        if r:
            return r
        args.run = args.fix = args.json = args.verbose = False
        return cmd_doctor(args)
    try:
        from .tui import setup_app
    except ImportError as e:
        return _err("wpk setup needs the tui extra: pip install 'work-packet[tui]' (%s)" % e)
    return setup_app.main(args.target)


def cmd_note(args) -> int:
    from . import actions, registry
    if args.note_file == "-":
        text = sys.stdin.read()
    elif args.note_file:
        try:
            with open(args.note_file, encoding="utf-8") as fp:
                text = fp.read()
        except OSError as ex:
            return _err(str(ex))
    else:
        text = args.message
    try:
        pkt = _packet(args.target)
    except registry.LookupFailed as ex:
        return _err(str(ex))
    out = actions.note(pkt, text, wake=args.wake)
    print("wpk: %s" % out.msg, file=sys.stderr)
    return out.code


def _text_arg(args):
    """-m TEXT, or --note-file F (- for stdin); None if neither."""
    if getattr(args, "note_file", None) == "-":
        return sys.stdin.read()
    if getattr(args, "note_file", None):
        with open(args.note_file, encoding="utf-8") as fp:
            return fp.read()
    return args.message


def cmd_request(args) -> int:
    from . import registry, requests
    if args.op == "sync":
        for e, msg in requests.sync():
            print("%s %s: %s" % (e["from"]["wpid"][:8], e["id"], msg))
        return 0
    if args.op == "list":
        wpid = None
        if args.target:
            try:
                wpid = _packet(args.target).wpid
            except registry.LookupFailed as e:
                return _err(str(e))
        es = requests.entries(wpid=wpid)
        if not es:
            print("no requests")
        for e in es:
            print("%s %-9s %s" % (e["from"]["wpid"][:8], e["state"], requests.describe(e)))
        return 0
    try:
        pkt = _packet(args.target)
    except registry.LookupFailed as e:
        return _err(str(e))
    try:
        if args.op == "send":
            e = requests.send(pkt, args.id, to=args.to, path=args.dir, external=args.external)
            t = e["to"]
            if "external" in t:
                print("Recorded request %s as taken outside wpk. When it is done: "
                      "`wpk request done %s %s -m RESULT`." % (e["id"], pkt.wpid[:8], e["id"]))
            elif t.get("created"):
                d = requests.delegate_state(e) or ("?", 0, None)
                print("Created project %s at %s for request %s; its root %s is %s." % (
                    t["project"], os.path.dirname(os.path.dirname(t["path"])), e["id"],
                    t["wpid"][:8], d[0]))
                if d[0] != "RUNNABLE":
                    print("Not started: %s" % d[2])
            else:
                print("Sent request %s to project %s: its root %s has it as batch %d." % (
                    e["id"], t["project"], t["wpid"][:8], t["batch"]))
            return 0
        if args.op == "cancel":
            e, what = requests.cancel(pkt, args.id, reason=args.reason)
            print("Cancelled request %s of %s; %s." % (e["id"], pkt.wpid[:8], what))
            return 0
        try:
            text = _text_arg(args)
        except OSError as ex:
            return _err(str(ex))
        ok = requests.done(pkt, args.id, text)
        print("Delivered request %s to %s%s." % (args.id, pkt.wpid[:8], "" if ok else
              "; its journal record waits for the running step to end (`wpk request sync`)"))
        return 0
    except requests.RequestError as e:
        return _err(str(e))


def cmd_answer(args) -> int:
    from . import actions, registry
    answers = {}
    for kv in args.answers:
        if "=" not in kv:
            return _err("expected id=answer, got %r" % kv)
        k, v = kv.split("=", 1)
        answers[k.strip()] = v.strip()
    try:
        pkt = _packet(args.target)
    except registry.LookupFailed as e:
        return _err(str(e))
    return _outcome(actions.answer(pkt, answers, note=args.message,
                                   take_recommendations=args.take_recommendations))


def cmd_next(args) -> int:
    """The next batch of work (docs/dash-tasks.md §6)."""
    from . import actions, layout, registry
    from .packet import Packet
    e = registry.get(args.target)
    try:
        pkt = Packet(layout.run_dir(e["path"], e["root"])) if e else _packet(args.target)
    except registry.LookupFailed as ex:
        return _err(str(ex))
    draft = actions.load_draft(pkt) if args.draft else None
    if args.draft and draft is None:
        return _err("no saved draft for %s (the board's Next batch saves one)" % pkt.wpid[:8])
    if args.file == "-":
        text = sys.stdin.read()
    elif args.file:
        try:
            with open(args.file, encoding="utf-8") as fp:
                text = fp.read()
        except OSError as ex:
            return _err(str(ex))
    elif draft:
        text = draft["instruction"]
    else:
        return _err("give the instruction with --file F (- for stdin), or --draft")
    note = args.message if args.message is not None else (draft or {}).get("note")
    archive = args.archive if args.archive is not None else (draft or {}).get("archive_outline")
    carry = args.carry_session or bool((draft or {}).get("carry_session"))
    return _outcome(actions.continue_(pkt, text, note=note, archive_outline=archive,
                                      carry_session=carry, force=args.force))


def _project_dir(target):
    """A registered project name, a project directory, or a packet in one."""
    from . import registry
    from .project import project_of
    e = registry.get(target)
    if e is not None:
        return e["path"]
    if os.path.isfile(os.path.join(target, "project.toml")):
        return os.path.abspath(target)
    try:
        proj = project_of(registry.resolve(target))
    except registry.LookupFailed as ex:
        raise ValueError(str(ex)) from None
    if proj is None:
        raise ValueError("%s is not in a project" % target)
    return proj


def cmd_config(args) -> int:
    """allow / deny / set: change project.toml (long-running.md §6)."""
    from . import executor, project
    try:
        proj = _project_dir(args.target)
        if args.cmd == "allow":
            changes = project.allow(proj, args.tools, executor._who())
        elif args.cmd == "deny":
            changes = project.deny(proj, args.tools, executor._who())
        else:
            pairs = []
            for kv in args.pairs:
                if "=" not in kv:
                    return _err("expected key=value, got %r" % kv)
                k, v = kv.split("=", 1)
                pairs.append((k.strip(), v.strip()))
            changes = project.set_values(proj, pairs, executor._who())
    except (ValueError, project.ProjectError) as e:
        return _err(str(e))
    for c in changes:
        print("wpk: %s" % c, file=sys.stderr)
    if not changes:
        print("wpk: nothing to change", file=sys.stderr)
    return 0


def cmd_migrate(args) -> int:
    import json
    from . import card, migrate
    try:
        res = migrate.migrate(args.targets or None, dry_run=args.dry_run)
    except KeyError as e:
        return _err("not registered: %s" % e.args[0])
    if args.print_card:
        for r in res:
            for path, c in r.get("preview") or []:
                if c.name == args.print_card or r["name"] == args.print_card and \
                        path.endswith(r["name"] + card.SUFFIX):
                    print("# " + path)
                    print(card.render(c))
        return 0
    if args.json:
        for r in res:
            r.pop("preview", None)
        print(json.dumps(res, indent=2))
    else:
        for r in res:
            if r["skipped"]:
                print("%-28s skipped: %s" % (r["name"], r["skipped"]))
                continue
            what = "would write" if args.dry_run else "wrote"
            cs = ", ".join("%s (%d entries, %s)" % (c["name"], c["entries"], c["state"])
                           for c in r["cards"])
            print("%-28s %-10s %s %s" % (r["name"], r["state"], what, cs))
            if not args.dry_run:
                print("%-28s %-10s harvested %d, provisional %d, %s" % (
                    "", "", len(r["harvested"]), len(r["provisional"]),
                    "statistics identical" if not r["problems"] else
                    "%d DIFFERENCES" % len(r["problems"])))
                for p in r["problems"][:10]:
                    print("    " + p)
    return 1 if any(r["problems"] for r in res) else 0


def cmd_card(args) -> int:
    import json
    from . import card, index
    if args.card_cmd == "list":
        rows = index.rows()
        if args.json:
            print(json.dumps(rows, indent=2))
        for r in [] if args.json else rows:
            print("%-36s %-12s %-20s %s" % (r["name"][:36], r["state"], (r["updated"] or "")[:16],
                                           (r["title"] or "")[:70]))
        return 0
    if args.card_cmd == "show":
        try:
            path = index.find(args.target)
        except LookupError as e:
            return _err(str(e))
        c = card.load(path)
        if args.json:
            d = c.to_json()
            d["path"] = path
            print(json.dumps(d, indent=2, ensure_ascii=False))
        else:
            sys.stdout.write(card.render(c))
        return 0
    bad = 0
    for p in args.paths:
        try:
            text = open(p, encoding="utf-8").read()
        except OSError as e:
            bad += 1
            print("%s: %s" % (p, e))
            continue
        c = card.parse(text)
        if args.card_cmd == "fmt":
            card.save(p, c)
            continue
        probs = card.check(c, text)
        for level, msg in probs:
            print("%s: %s: %s" % (p, level, msg))
        bad += any(level == "error" for level, _ in probs)
    return 1 if bad else 0


def cmd_history(args) -> int:
    import json
    from . import history, migrate, registry
    if args.history_cmd == "rebuild":
        n = history.rebuild()
        print("rebuilt %s from %d archives" % (history.db_path(), n))
        return 0
    con = history.connect()
    try:
        if args.history_cmd == "list":
            rows = []
            for pid, name, proj, rs, cs, prov in con.execute(
                    "SELECT id, name, project, run_state, card_state, provisional FROM packet "
                    "ORDER BY project, id"):
                f = history.figures(history.steps(con, packet=pid))
                rows.append(dict(f, id=pid, name=name, project=proj, run_state=rs,
                                 card_state=cs, provisional=bool(prov)))
            if args.json:
                print(json.dumps(rows, indent=2))
            for r in [] if args.json else rows:
                print("%-28s %-10s %-11s %4d steps %9.2f USD%s" % (
                    (r["name"] or r["id"])[:28], r["card_state"], r["run_state"], r["steps"],
                    r["cost_usd"], "  provisional" if r["provisional"] else ""))
            return 0
        es = [e for e in registry.entries() if not args.targets or e["name"] in args.targets]
        bad = 0
        for e in es:
            p = migrate.plan(e)
            if not p["exists"]:
                continue
            if args.history_cmd == "sync":
                for x in p["packets"]:
                    history.sync(e["name"], x["dir"], con=con)
            probs = history.verify_project(con, e["name"], e["path"])
            print("%-28s %s" % (e["name"], "identical" if not probs else
                                "%d differences" % len(probs)))
            for x in probs[:10]:
                print("    " + x)
            bad += bool(probs)
        return 1 if bad else 0
    finally:
        con.close()


def cmd_stats(args) -> int:
    import json
    from datetime import timedelta
    from . import clock, registry, schema, stats
    es = registry.entries()
    projects = []
    for t in args.targets or [e["name"] for e in es]:
        hit = [e for e in es if e["name"] == t]
        if hit:
            projects.append((t, hit[0]["path"]))
        elif args.history:
            projects.append((t, None))
        elif os.path.isfile(os.path.join(t, "project.toml")):
            projects.append((os.path.basename(os.path.abspath(t)), os.path.abspath(t)))
        else:
            return _err("no registered project or project directory %r" % t)
    since = None
    if args.since:
        m = re.match(r"^(\d+)([smhd])$", args.since)
        if not m:
            return _err("--since: expected a duration like 12h or 7d, got %r" % args.since)
        secs = int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        since = schema.format_timestamp(clock.now() - timedelta(seconds=secs))
    if args.history:
        from . import history
        con = history.connect()
        try:
            names = [n for n, _ in projects] if args.targets else history.projects(con)
            steps, finished = history.collect(names, since, con=con)
        finally:
            con.close()
    else:
        steps, finished = stats.collect(projects, since)
    if args.tools:
        from . import toolcost
        attrs = []
        for s in steps:
            a = stats.tool_attrs(s)
            if a:
                a["label"] = stats.ROLLUPS["step"](s)
                attrs.append(a)
        if args.json:
            print(json.dumps({"rows": toolcost.rollup(attrs, args.tools),
                              "repeats": toolcost.repeats(attrs),
                              "top": toolcost.top(attrs)}, indent=2))
        elif not attrs:
            print("No transcripts found.", file=sys.stderr)
        else:
            for line in toolcost.report(attrs, args.tools):
                print(line)
            print("\nBiggest single results:")
            for x in toolcost.top(attrs):
                print("  %9s carried  %-6s %s  (%s)" % (
                    stats._k(x["carried"]), x["tool"], x["target"][:70], x["step"]))
        return 0
    if args.by:
        rows = stats.rollup(steps, args.by)
        if args.json:
            print(json.dumps([dict(f, label=k, steps=n) for k, n, f in rows], indent=2))
        elif not rows:
            print("No steps found.", file=sys.stderr)
        else:
            for line in stats.rollup_report(rows):
                print(line)
        return 0
    gs = stats.groups(steps, finished)
    if args.json:
        print(json.dumps(stats.as_json(gs, args.min), indent=2))
    elif not gs:
        print("No steps found.", file=sys.stderr)
    else:
        for line in stats.report(gs, args.min):
            print(line)
    return 0


def cmd_tick(args) -> int:
    from . import registry, scheduler
    es = registry.entries()
    if args.project:
        es = [e for e in es if e["name"] == args.project]
        if not es:
            return _err("no registered project named %r" % args.project)
    if args.dry_run:
        for d in scheduler.due(es):
            print("%s  %s  %-9s due %s" % (d.project, d.wpid[:8], d.state, d.due))
        return 0
    try:
        jobs = args.jobs or registry.load_config()["max_concurrent"]
    except registry.ConfigError as e:
        return _err(str(e))

    def report(r):
        print("%s %s: %s" % (r.due.project, r.due.wpid[:8], r.msg))
        sys.stdout.flush()
    res = scheduler.tick(es, jobs=jobs, until_idle=args.until_idle, max_steps=args.max_steps,
                         report=report)
    print("%d step%s: %d committed, %d failed, %d skipped" % (
        len(res.ran), "" if len(res.ran) == 1 else "s", res.count(0), res.count(1),
        len(res.ran) - res.count(0) - res.count(1)), file=sys.stderr)
    return 0


def cmd_sched(args) -> int:
    """``wpk sched``: the pool, its queue and its controls (docs/scheduler.md §6.4)."""
    import json
    from . import registry
    from .sched import authz, control, explain
    by = authz.principal_cli()
    op = args.op or "show"
    if op in ("halt", "stop", "resume"):
        mode = {"halt": "drain", "stop": "stop", "resume": "run"}[op]
        return _outcome(control.set_mode(mode, by, args.message))
    if op == "doctor":
        from .sched import doctor
        try:
            checks = doctor.run(probe=not args.no_probe)
        except registry.ConfigError as e:
            return _err(str(e))
        for c in checks:
            print("  %s %s" % (MARK.get(c.level, "?"), c.title))
            if c.detail and c.level != "ok":
                print("      " + c.detail)
            for f in c.fix:
                print("      $ " + f)
        return 1 if any(c.level == "missing" for c in checks) else 0
    if op in ("hold", "release"):
        if not args.project:
            return _err("wpk sched %s needs a project" % op)
        if op == "hold":
            return _outcome(control.hold(args.project, by, args.message))
        return _outcome(control.release(args.project, by))
    try:
        snap = explain.snapshot()
    except registry.ConfigError as e:
        return _err(str(e))
    if op == "jobs":
        if args.json:
            print(json.dumps(snap["jobs"], indent=2))
            return 0
        if not snap["jobs"]:
            print("no jobs")
        for j in snap["jobs"]:
            print("%-12s %-5s %-8s %-10s %s  step %-4s %-5s %s  submitted %s%s" % (
                j["id"], j["kind"], j["state"], j["project"], j["wpid"][:8], j["step"],
                j["size"], j["ref"] or "-", j["submitted"],
                "  cancelling since %s" % j["cancel"] if j["cancel"] else ""))
        return 0
    if args.json:
        print(json.dumps(snap, indent=2))
        return 0
    for line in explain.lines(snap):
        print(line)
    return 0


def cmd_prio(args) -> int:
    from .sched import authz, control
    by = authz.principal_cli()
    if args.next:
        return _outcome(control.run_next(args.target, by))
    if args.clear:
        return _outcome(control.set_prio(args.target, None, by))
    if not args.cls:
        return _err("give a class (urgent, high, normal, low, background), --clear or --next")
    return _outcome(control.set_prio(args.target, args.cls, by))


def cmd_size(args) -> int:
    from .sched import authz, control
    by = authz.principal_cli()
    if args.clear:
        return _outcome(control.set_size(args.target, None, by))
    if not args.size:
        return _err("give a size from [sched.sizes], or --clear")
    return _outcome(control.set_size(args.target, args.size, by))


def cmd_dash(args) -> int:
    try:
        from .dash.server import Board, ServeError
    except ImportError as e:
        return _err("wpk dash needs the dash extra: pip install 'work-packet[dash]' (%s)" % e)
    import asyncio
    import logging
    from . import registry
    logging.basicConfig(format="wpk dash: %(message)s", level=logging.WARNING)
    try:
        cfg = registry.load_server_config()
    except registry.ConfigError as e:
        return _err(str(e))
    if args.port is not None:
        cfg["port"] = args.port
    if args.tailnet is not None:
        cfg["tailnet"] = args.tailnet
    if args.run is not None:
        cfg["run"] = args.run
    runner = None
    if cfg["run"]:
        from .dash.runner import Runner, RunnerBusy
        runner = Runner(jobs=args.jobs)
        try:
            runner.acquire()
        except RunnerBusy as e:
            return _err("%s; is another `wpk dash --run` or `wpk serve` up?" % e)

    def ready(board):
        for url in board.urls["network"] + board.urls["loopback"]:
            print("wpk dash: %s (Ctrl-C to stop)" % url, file=sys.stderr)
        if board.gate is not None:
            print("wpk dash: sign in as %s%s; see `wpk url`" % (board.gate.owner, (
                " (read-only: %s)" % ", ".join(cfg["allow"])) if cfg["allow"] else ""),
                file=sys.stderr)
        if runner is not None:
            print("wpk dash: running due packets (one runner for %s)" % runner.home,
                  file=sys.stderr)
        if board.tailnet is not None:
            print("wpk dash: tailnet: only %s; see `wpk url`" % (
                ", ".join(cfg["allow"]) or board.tailnet.owner() or "this node's owner"),
                file=sys.stderr)
    try:
        asyncio.run(Board(cfg, host=args.host, runner=runner).run(ready))
    except ServeError as e:
        return _err(str(e))
    return 0


def cmd_ide(args) -> int:
    import json
    from . import ide, registry, setup
    try:
        op = ide.resolve(args.target, args.repo, packet=args.packet)
        cfg = ide.load_config()
    except (ide.IdeError, registry.ConfigError) as e:
        return _err(str(e))
    web = None
    if cfg["web"]:
        try:
            from .dash.server import read_state
            st = read_state(registry.home())
        except ImportError:
            st = None
        if st and st.get("urls"):
            web = st["urls"][0].rstrip("/") + ide.web_path(op)
    ts = None
    try:
        from .dash.tailscale import Tailnet
        ts = Tailnet()
    except ImportError:
        pass
    links = {"remote": ide.desktop_url(op, ide.ssh_host(cfg, ts)),
             "local": ide.desktop_url(op), "web": web}
    if args.json:
        print(json.dumps(dict(op.to_json(), links=links), indent=1))
    else:
        print("%s: %s" % (op.label, setup.tilde(op.path)))
        if op.note:
            print("  note: " + op.note)
        if op.owner == "runner":
            print("  the runner owns this packet: edits may race a step")
        print("  desktop  %s" % links["remote"])
        print("  here     %s" % links["local"])
        if web:
            print("  web      %s" % web)
    if args.open:
        try:
            argv = ide.launch(op)
        except ide.IdeError as e:
            return _err(str(e))
        print("wpk: opened with %s" % " ".join(argv), file=sys.stderr)
    return 0


def cmd_serve(args) -> int:
    """``wpk serve``: wpkd, the board and the scheduler in one process
    (docs/scheduler.md §7.1). ``--detach`` starts it in the background with its
    log in ``$WPK_HOME/log/wpkd.log``; ``--ensure`` does that only if no wpkd
    holds this home's lease, so cron can run it every few minutes."""
    import subprocess
    import time
    from . import registry
    from .sched import home_lease
    h = registry.home()
    held = home_lease.live(h)
    if args.ensure and held:
        print("wpk: wpkd is running (host %s, pid %s)" % (held.get("host"), held.get("pid")),
              file=sys.stderr)
        return 0
    if args.detach or args.ensure:
        if held:
            return _err("wpkd is already running for %s: host %s, pid %s" % (
                h, held.get("host"), held.get("pid")))
        logdir = os.path.join(h, "log")
        os.makedirs(logdir, exist_ok=True)
        argv = [sys.executable, "-m", "work_packet", "serve"]
        if args.port is not None:
            argv += ["--port", str(args.port)]
        if args.jobs:
            argv += ["-j", str(args.jobs)]
        with open(os.path.join(logdir, "wpkd.log"), "ab") as log:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
        deadline = time.time() + 15
        while time.time() < deadline:
            got = home_lease.live(h)
            if got and got.get("pid") == p.pid:
                print("wpk: wpkd started (pid %d); log in %s" % (
                    p.pid, os.path.join(logdir, "wpkd.log")), file=sys.stderr)
                return 0
            if p.poll() is not None:
                return _err("wpkd exited with %s; see %s" % (
                    p.returncode, os.path.join(logdir, "wpkd.log")))
            time.sleep(0.1)
        return _err("wpkd (pid %d) did not take the home's lease; see %s" % (
            p.pid, os.path.join(logdir, "wpkd.log")))
    args.run, args.host, args.tailnet = True, None, None
    return cmd_dash(args)


def cmd_url(args) -> int:
    try:
        from .dash.server import read_state
        from . import registry
    except ImportError as e:
        return _err("wpk url needs the dash extra: pip install 'work-packet[dash]' (%s)" % e)
    st = read_state(registry.home())
    if st is None:
        return _err("the board is not running (start it with `wpk dash` or `wpk serve`)")
    if st.get("sock"):
        from .dash.server import ssh_line
        print("# on your laptop, then open http://localhost:%d/" % st.get("port", 7878))
        print(ssh_line(registry.home(), st.get("port", 7878)))
    for url in st.get("urls", []):
        if not st.get("sock") or not url.startswith("http://localhost"):
            print(url)
    if st.get("auth") == "unix":
        from .dash import login
        cfg = registry.load_server_config()
        print("# sign in: open the URL, then run the `wpk login CODE` it shows "
              "(in any shell here)")
        if cfg["allow"]:
            print("# read-only for: %s" % ", ".join(cfg["allow"]))
            stop = login.reachable_by_others(registry.home())
            if stop:
                print("# but they cannot reach %s: chmod o+x %s (and each directory above)"
                      % (login.drop_dir(registry.home()), stop))
    return 0


def cmd_login(args) -> int:
    """``wpk login CODE``: prove to a board (yours, or ``--home``'s) that you
    are the Unix user running this (docs/unix-login.md)."""
    import getpass
    from . import registry
    from .dash import login
    home = os.path.abspath(os.path.expanduser(args.home)) if args.home else registry.home()
    try:
        path = login.drop(home, args.code)
    except ValueError as e:
        return _err(str(e))
    except FileExistsError:
        return _err("that code was already used")
    except FileNotFoundError:
        return _err("no board takes sign-ins at %s (no login/ there); is it the right "
                    "--home?" % home)
    except PermissionError:
        return _err("cannot write to %s: is %s's board shared with you "
                    "([server] allow)?" % (login.drop_dir(home), home))
    print("wpk: signed in as %s; the browser carries on by itself (%s)"
          % (getpass.getuser(), path), file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wpk", description="work-packet")
    parser.add_argument("--version", action="version", version=f"wpk {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    p = sub.add_parser("check", help="validate packets against the format spec",
                       description="Check a packet, a project or a runner home against "
                       "docs/spec.md. With no path, check the runner home and every "
                       "registered project.")
    p.add_argument("path", nargs="?", help="packet, project or runner home directory")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("-q", "--quiet", action="store_true", help="print errors only")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("new", help="create and register a project",
                       description="Create a project with the blank template: the prompt "
                       "becomes the root packet's first instruction. Without a prompt the "
                       "root is PAUSED for setup, with no instruction yet.")
    p.add_argument("name")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--prompt", help="the task, as text (without one, the root is held "
                   "for setup: see `wpk setup` and `wpk doctor`)")
    g.add_argument("--prompt-file", help="the task, from a file")
    p.add_argument("--from-setup", metavar="PROJECT",
                   help="copy [setup] (with the clones in its work/ and the links in its "
                   "identity/), [permissions] and "
                   "limits from another project; `wpk setup NAME --apply` then clones")
    p.add_argument("--dir", help="project directory (default ./<name>); with --packet, "
                   "the packet folder")
    p.add_argument("--here", action="store_true",
                   help="make the current directory (a clone, or any folder) the packet: "
                   "the card and .work-packet/ go in it, and steps work in it")
    p.add_argument("--packet", action="store_true",
                   help="the packet layout in --dir or ./<name>, as --here does")
    p.add_argument("--model", help="model for the root packet")
    p.add_argument("--tz", help="IANA zone for resume times (default: local)")
    p.add_argument("--paused", action="store_true", help="create the root PAUSED")
    p.add_argument("--dry-run", action="store_true", help="print what would be created")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("start", help="make a packet with a starter: a folder, a repo, an issue",
                       description="docs/starters-v1.md. `wpk start` lists the starters and "
                       "their fields. `wpk start issue issue=home:owner/repo#12` makes a "
                       "packet from an issue; held for setup unless --go.")
    p.add_argument("starter", nargs="?")
    p.add_argument("values", nargs="*", metavar="KEY=VALUE")
    p.add_argument("--recipe", metavar="FILE", help="a recipe as JSON (- for stdin)")
    p.add_argument("--search", metavar="FIELD", help="list the choices for a field "
                   "(its value is the search text)")
    p.add_argument("--go", action="store_true", help="runnable at once (needs an objective)")
    p.add_argument("--dry-run", action="store_true", help="say what it would do")
    p.add_argument("--json", action="store_true", help="print the recipe")
    p.add_argument("--list", action="store_true", help="the starters and their fields")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("convert", help="move a v0.2 project into the packet layout",
                       description="Renames only: the project becomes <packet>/.work-packet/, "
                       "packets/ becomes runs/, the card goes to the packet folder. A tarball "
                       "is written first. Projects with repos are not converted yet.")
    p.add_argument("name")
    p.add_argument("--dry-run", action="store_true", help="print what would move")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("adopt", help="register an existing project directory")
    p.add_argument("dir")
    p.set_defaults(func=cmd_adopt)

    p = sub.add_parser("rm", help="remove a project from the registry (files are kept)")
    p.add_argument("name")
    p.set_defaults(func=cmd_rm)

    p = sub.add_parser("board", help="list, make or delete the dash's boards, or move a "
                       "project to one", description="With no operation, list the boards "
                       "and their projects. Deleting a board moves its projects to main.")
    bsub = p.add_subparsers(dest="op", metavar="<op>")
    bp = bsub.add_parser("list", help="each board and its projects")
    bp = bsub.add_parser("new", help="make a board")
    bp.add_argument("name")
    bp.add_argument("--title", help="a longer name, shown on the board")
    bp = bsub.add_parser("rm", help="delete a board; its projects move to main")
    bp.add_argument("name")
    bp = bsub.add_parser("move", help="put a project on a board")
    bp.add_argument("name", help="the project")
    bp.add_argument("board")
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("watch", help="the boards' watchers: list them, or poll them now",
                       description="Watchers are [[watch]] tables in boards/<board>.toml; "
                       "the board's runner polls them (docs/starters-v1.md).")
    wsub = p.add_subparsers(dest="op", metavar="<op>")
    wsub.add_parser("list", help="each watcher, when it last polled, what it made")
    wp = wsub.add_parser("poll", help="poll now (all, a board's, or board/name)")
    wp.add_argument("which", nargs="?", help="board or board/name")
    wp.add_argument("--dry-run", action="store_true", help="say what it would make")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("seen", help="finished projects not looked at yet; mark them seen",
                       description="With no project: list the projects whose run stopped "
                       "(DONE, or STOPPED by a limit) since anyone looked. With projects, or "
                       "--all: mark them seen, as opening them on the board does "
                       "(docs/overview-recent.md).")
    p.add_argument("projects", nargs="*")
    p.add_argument("--all", action="store_true", help="mark every one listed seen")
    p.set_defaults(func=cmd_seen)

    p = sub.add_parser("docs", help="the project's Sphinx docs: list, build, open",
                       description="Find Sphinx docs in the project's work, say whether "
                       "their newest build is stale, and build them (into the runner home, "
                       "not the work) or open them (docs/sphinx-docs-v1.md).")
    p.add_argument("project", nargs="?", help="a project name or directory (default: here)")
    p.add_argument("--build", action="store_true", help="build the stale ones now")
    p.add_argument("--force", action="store_true", help="with --build: build even if fresh")
    p.add_argument("--open", action="store_true", help="open the built docs in a browser")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("pr", help="hand a packet back to its forge: push, open a pull request",
                       description="Push the packet's branch and open a pull request into "
                       "its repo's default branch, from the packet's report; for an issue, "
                       "one that closes it. Again: pushes, and finds the same one "
                       "(docs/starters-v1.md, Hand-off).")
    p.add_argument("project")
    p.add_argument("--draft", action="store_true", help="open it as a draft")
    p.add_argument("--dry-run", action="store_true", help="say what it would do")
    p.set_defaults(func=cmd_pr)

    p = sub.add_parser("ps", help="list packets of registered projects")
    p.add_argument("--all", action="store_true", help="include finished projects")
    p.add_argument("--project", help="only this project")
    p.set_defaults(func=cmd_ps)

    p = sub.add_parser("stats", help="step statistics per harness, model and profile, "
                                     "with advice")
    p.add_argument("targets", nargs="*", help="project names or directories (default: all)")
    p.add_argument("--since", help="only steps that ended in this long, e.g. 7d or 12h")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--min", type=int, default=30, help="steps a group needs for advice")
    p.add_argument("--by", choices=("project", "packet", "item", "model", "route", "day",
                                    "step"),
                   help="instead, a table of token use and cost per project, packet, "
                        "plan item (the memento's item), model, route (account@host), "
                        "day or step")
    p.add_argument("--tools", nargs="?", const="tool", choices=("tool", "kind", "target"),
                   help="instead, what used up context inside steps: by tool (default), "
                        "by kind (a shell command's program) or by target (file or command)")
    p.add_argument("--history", action="store_true",
                   help="read the history store instead of the runs")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("migrate", help="write cards for registered v0.2 projects, link their "
                       "runs and copy their records and metrics into the history store "
                       "(docs/migration-v1.md); nothing is moved or deleted")
    p.add_argument("targets", nargs="*", help="project names (default: all)")
    p.add_argument("--dry-run", action="store_true", help="print what it would do")
    p.add_argument("--print", dest="print_card", metavar="NAME",
                   help="with --dry-run: print the card it would write for NAME")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("card", help="packet cards (<name>.wp.md): list, show, check, fmt")
    csub = p.add_subparsers(dest="card_cmd", required=True)
    q = csub.add_parser("list", help="the cards in the index, newest first")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_card)
    q = csub.add_parser("show", help="print a card, or its JSON form")
    q.add_argument("target", nargs="?", default=".", help="name, id, path or directory")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_card)
    q = csub.add_parser("check", help="check cards strictly")
    q.add_argument("paths", nargs="+")
    q.set_defaults(func=cmd_card)
    q = csub.add_parser("fmt", help="rewrite cards in canonical form")
    q.add_argument("paths", nargs="+")
    q.set_defaults(func=cmd_card)

    p = sub.add_parser("history", help="the history store: list, verify, sync, rebuild")
    hsub = p.add_subparsers(dest="history_cmd", required=True)
    q = hsub.add_parser("list", help="packets in the history store, with totals")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_history)
    q = hsub.add_parser("verify", help="compare every statistic of registered projects "
                        "between their runs and the history store")
    q.add_argument("targets", nargs="*")
    q.set_defaults(func=cmd_history)
    q = hsub.add_parser("sync", help="load active runs' metrics (provisional)")
    q.add_argument("targets", nargs="*")
    q.set_defaults(func=cmd_history)
    q = hsub.add_parser("rebuild", help="make the database again from the archives")
    q.set_defaults(func=cmd_history)

    p = sub.add_parser("show", help="print a packet's status, memento and children")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("report", help="print a finished packet's completion report: outcome, "
                       "decisions, deliverables and open items, with its children's")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("log", help="print a packet's journal, or one step")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    p.add_argument("--step", type=int, help="show this step's summary, diff and meta")
    p.set_defaults(func=cmd_log)

    for op, h in (("pause", "set PAUSED"),
                  ("resume", "set NEEDS_INPUT, PAUSED or FAILED back to RUNNABLE")):
        p = sub.add_parser(op, help=h + " (a WPID, or every packet of a project)")
        p.add_argument("target", help="WPID (or unique prefix), project name or directory")
        if op == "resume":
            p.add_argument("--force", action="store_true",
                           help="resume a root held for setup even if doctor finds "
                                "something missing")
        p.set_defaults(func=cmd_admin, force=False)

    p = sub.add_parser("note", help="send a note to a packet, running or not",
                       description="Queue a note from the owner (docs/interaction.md §6a). "
                       "A running step gets it after its next tool call; otherwise the next "
                       "step's prompt shows it. The packet's state does not change.")
    p.add_argument("target", help="WPID (or unique prefix)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("-m", "--message", help="the note")
    g.add_argument("--note-file", help="the note, from a file (- for stdin)")
    p.add_argument("--wake", action="store_true", help="a SLEEPING packet runs now")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("handoff", help="hand a packet back to the runner, with a note",
                       description="Answer a packet's question (NEEDS_INPUT), or hand back a "
                       "PAUSED or FAILED one: it becomes RUNNABLE, and the next step's prompt "
                       "shows the question and your note. A project name hands off each of "
                       "its NEEDS_INPUT, PAUSED and FAILED packets.")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-m", "--message", help="the note for the next step, e.g. the answer")
    g.add_argument("--note-file", help="the note, from a file (- for stdin)")
    p.add_argument("--force", action="store_true",
                   help="hand off a root held for setup even if doctor finds something missing")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("next", help="give a stopped packet its next batch of work",
                       description="Replace a stopped packet's instruction (COMPLETED, "
                       "NEEDS_INPUT, PAUSED or FAILED) and hand it to the runner. From "
                       "COMPLETED the finished state/outline.md moves to state/history/. "
                       "Work repos with uncommitted changes refuse it (docs/dash-tasks.md §6).")
    p.add_argument("target", help="project name (its root), or WPID (or unique prefix)")
    p.add_argument("-f", "--file", help="the new instruction, from a file (- for stdin)")
    p.add_argument("--draft", action="store_true",
                   help="use the draft saved on the board (its note and options too)")
    p.add_argument("-m", "--message", help="a note for the next step")
    p.add_argument("--archive-outline", dest="archive", action=argparse.BooleanOptionalAction,
                   default=None, help="move state/outline.md to state/history/ "
                   "(default: only from COMPLETED)")
    p.add_argument("--carry-session", action="store_true",
                   help="the first step resumes the last step's session (its cache has "
                   "usually expired, so the first call costs the whole context again)")
    p.add_argument("--force", action="store_true", help="hand off with uncommitted changes")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("request", help="hand work to another project's agent, and bring "
                       "the result back", description="A packet's brief in "
                       "state/requests/<id>.md goes to the root of another project, new or "
                       "stopped; when that finishes, its outcome comes back as a note "
                       "(docs/delegation.md).")
    rsub = p.add_subparsers(dest="op", required=True)
    rp = rsub.add_parser("send", help="send a request")
    rp.add_argument("target", help="the requester: WPID (or unique prefix) or project name")
    rp.add_argument("id", help="the brief, state/requests/<id>.md")
    rp.add_argument("--to", help="the project that does it (default: the brief's to:)")
    rp.add_argument("--dir", help="where a new project goes (default: next to the "
                    "requester's project)")
    rp.add_argument("--external", metavar="NOTE",
                    help="no packet: you take it elsewhere; finish with `wpk request done`")
    rp.set_defaults(func=cmd_request)
    rp = rsub.add_parser("list", help="the requests, from the index")
    rp.add_argument("target", nargs="?", help="only this packet's (sent or received)")
    rp.set_defaults(func=cmd_request)
    rp = rsub.add_parser("done", help="deliver a result by hand")
    rp.add_argument("target", help="the requester: WPID (or unique prefix) or project name")
    rp.add_argument("id")
    g = rp.add_mutually_exclusive_group(required=True)
    g.add_argument("-m", "--message", help="the result")
    g.add_argument("--note-file", help="the result, from a file (- for stdin)")
    rp.set_defaults(func=cmd_request)
    rp = rsub.add_parser("cancel", help="withdraw a request; a delegate that never ran "
                         "stays paused")
    rp.add_argument("target", help="the requester: WPID (or unique prefix) or project name")
    rp.add_argument("id")
    rp.add_argument("-r", "--reason", help="why (the requester's prompt shows it)")
    rp.set_defaults(func=cmd_request)
    rp = rsub.add_parser("sync", help="deliver finished requests now")
    rp.set_defaults(func=cmd_request, target=None)

    p = sub.add_parser("answer", help="answer a packet's open questions and hand it off",
                       description="Answer the questions of a NEEDS_INPUT packet (`wpk show` "
                       "lists them) as id=answer pairs. A yes to a question that grants tools "
                       "allows them first, and an answer a question's `sets` names applies those "
                       "settings (step_budget_usd up to max_step_budget_usd). Then the packet is handed off, and the next step "
                       "sees each question with its answer.")
    p.add_argument("target", help="WPID (or unique prefix), project name, or a packet directory")
    p.add_argument("answers", nargs="*", metavar="id=answer")
    p.add_argument("-r", "--take-recommendations", action="store_true",
                   help="answer every question not given with its recommendation")
    p.add_argument("-m", "--message", help="a note for the next step as well")
    p.set_defaults(func=cmd_answer)

    for op, h in (("allow", "add tools to a project's allowed_tools"),
                  ("deny", "remove tools from a project's allowed_tools")):
        p = sub.add_parser(op, help=h, description=h.capitalize() + ", e.g. Bash or "
                           "'Bash(git commit *)'. Fails while a step is running.")
        p.add_argument("target", help="project name or directory, or a packet in it")
        p.add_argument("tools", nargs="+", metavar="tool")
        p.set_defaults(func=cmd_config)

    p = sub.add_parser("set", help="change a project setting",
                       description="Set project.toml keys: model, harness, profile, tz, "
                       "step_timeout, max_attempts, step_budget_usd, step_context_tokens, "
                       "carry_session, carry_ttl, carry_factor, permission_mode. Values are "
                       "TOML (3, 2.5, true, \"30m\") or plain strings; key= removes a key. "
                       "A new model also goes to the root packet and to packets on the old one.")
    p.add_argument("target", help="project name or directory, or a packet in it")
    p.add_argument("pairs", nargs="+", metavar="key=value")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("doctor", help="what a project's setup has, what it lacks, and "
                       "what to do", description="Check a project's setup (docs/setup.md "
                       "§3): tools, work repos, inputs, the instruction, limits. Each missing "
                       "item comes with a command to fix it. Exit status 0 when nothing is "
                       "missing. With no project: the tools, and a line per project.")
    p.add_argument("target", nargs="?", help="project name or directory, or a packet in it")
    p.add_argument("--json", action="store_true", help="print the checks as JSON")
    p.add_argument("--run", action="store_true", help="run the [setup] smoke commands first")
    p.add_argument("--fix", action="store_true", help="run the fixes marked safe")
    p.add_argument("-v", "--verbose", action="store_true", help="details for every check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("setup", help="set a project up, in a guided TUI with a shell",
                       description="The setup wizard (docs/setup.md §6). With --apply, do "
                       "what [setup] in project.toml asks that is not done yet (clones, "
                       "inputs, links), then print the doctor's report.")
    p.add_argument("target", nargs="?", help="project name or directory (none: a new one)")
    p.add_argument("--apply", action="store_true", help="no TUI: apply [setup], then doctor")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("path", help="print a project's directory, or a part of it",
                       description="Print the project's directory (where you set it up), "
                       "its work/ or an entry in it, where inputs go now (--state: the "
                       "root's state/ until the first step, then the root packet's), or "
                       "the root packet. For example: cd $(wpk path dvs-enh --work dv-solve)")
    p.add_argument("target", help="project name or directory, or a packet")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--work", nargs="?", const="", metavar="NAME", help="work/, or work/NAME")
    g.add_argument("--state", action="store_true", help="the state/ that inputs go to now")
    g.add_argument("--packet", action="store_true", help="the root packet")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("shell", help="a shell at a project's root",
                       description="Start $SHELL in the project's directory (in work/<name> "
                       "when there is exactly one entry), with WPK_PROJECT, WPK_PROJECT_DIR, "
                       "WPK_WPID, WPK_PACKET and WPK_WORK set.")
    p.add_argument("target", help="project name or directory, or a packet")
    p.add_argument("--repo", help="start in work/REPO")
    p.set_defaults(func=cmd_shell)

    p = sub.add_parser("add-input", help="copy files into a project's state/",
                       description="Copy plan documents and other inputs into state/ (the "
                       "project's until the first step, then the root packet's; never into a "
                       "repo), and record them in [setup].")
    p.add_argument("target", help="project name or directory")
    p.add_argument("files", nargs="+")
    p.add_argument("--force", action="store_true", help="replace a file that differs")
    p.set_defaults(func=cmd_add_input)

    p = sub.add_parser("add-smoke", help="add a build or test command for doctor --run",
                       description="Add a [[setup.smoke]] command: `wpk doctor --run` runs "
                       "it in the work repo and times it before the hand-off.")
    p.add_argument("target", help="project name or directory")
    p.add_argument("command")
    p.add_argument("--repo", help="run in work/REPO (default: the only work repo)")
    p.set_defaults(func=cmd_add_smoke)

    p = sub.add_parser("instruct", help="write a project's first instruction",
                       description="Edit the first instruction in $EDITOR, or set it from a "
                       "file: the project's prompt.md until the first step (it becomes the "
                       "memento then), the root packet's memento.md after. --template starts "
                       "from one of: list, outline, plan-only.")
    p.add_argument("target", help="project name or directory, or a packet")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--file", help="the instruction, from a file (- for stdin)")
    g.add_argument("--template", choices=("list", "outline", "plan-only"))
    p.set_defaults(func=cmd_instruct)

    p = sub.add_parser("tick", help="run every due packet once (one scheduler pass)",
                       description="Find due packets in every registered project and run "
                       "`wpk step` on them, oldest-due first.")
    p.add_argument("-j", "--jobs", type=int, help="steps at once (default: max_concurrent)")
    p.add_argument("--until-idle", action="store_true",
                   help="repeat passes until nothing is due")
    p.add_argument("--max-steps", type=int, help="stop after this many steps in all")
    p.add_argument("--dry-run", action="store_true", help="list what is due; run nothing")
    p.add_argument("--project", help="only this project")
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser("sched", help="the pool: its queue with reasons, and halt, stop, "
                       "resume, hold", description="Without an operation: the pool's mode, "
                       "what its jobs hold, and every due packet in the order it would start, "
                       "with what holds it back (docs/scheduler.md §6). halt: running steps "
                       "finish, nothing new starts. stop: running steps are killed and their "
                       "attempts not counted (needs -m). resume: run again. hold/release: "
                       "start nothing in one project. jobs: each job record. doctor: can this pool run "
                       "steps (batch commands, a probe job: shared file system, wpk and claude "
                       "on a node, clock skew)?")
    p.add_argument("op", nargs="?", choices=("show", "halt", "stop", "resume", "hold",
                                             "release", "jobs", "doctor"))
    p.add_argument("--no-probe", action="store_true",
                   help="doctor: do not submit the probe job")
    p.add_argument("project", nargs="?", help="hold, release: the project")
    p.add_argument("-m", "--message", help="why (shown on the board)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_sched)

    p = sub.add_parser("prio", help="set the priority class of a project or packet",
                       description="Classes, highest first: urgent, high, normal (the "
                       "default), low, background. A packet without its own class has its "
                       "project's (docs/scheduler.md §3).")
    p.add_argument("target", help="project name, or a packet (WPID prefix)")
    p.add_argument("cls", nargs="?", metavar="CLASS")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--clear", action="store_true", help="back to the project's (or normal)")
    g.add_argument("--next", action="store_true", help="run this packet next, once")
    p.set_defaults(func=cmd_prio)

    p = sub.add_parser("size", help="set the job size of a project or packet",
                       description="The job a step runs in: a size from [sched.sizes] in "
                       "config.toml (docs/scheduler.md §5.2). A memento's size: wins for "
                       "one step.")
    p.add_argument("target", help="project name, or a packet (WPID prefix)")
    p.add_argument("size", nargs="?")
    p.add_argument("--clear", action="store_true", help="back to the project's (or the default)")
    p.set_defaults(func=cmd_size)

    p = sub.add_parser("dash", help="serve the web board",
                       description="Serve the board: every registered project by state, "
                       "with packet trees, timelines and step transcripts, and forms to create, "
                       "set up, answer and hand off tasks (docs/dash-tasks.md). "
                       "Listens on 127.0.0.1 and, with --tailnet or [server] tailnet = true "
                       "in config.toml, on this node's tailnet addresses, where only your "
                       "tailnet login gets in (docs/server.md).")
    p.add_argument("--host", help="listen only on this address instead; not loopback "
                   "means tailnet identity is checked")
    p.add_argument("--port", type=int, help="port (default [server] port, 7878)")
    p.add_argument("--tailnet", action=argparse.BooleanOptionalAction, default=None,
                   help="also listen on the tailnet (default [server] tailnet)")
    p.add_argument("--run", action=argparse.BooleanOptionalAction, default=None,
                   help="run due packets in this process, as `wpk tick` would, and start "
                   "a step as soon as the board hands a packet off (default [server] run)")
    p.add_argument("-j", "--jobs", type=int, help="with --run: steps at once "
                   "(default: max_concurrent)")
    p.set_defaults(func=cmd_dash)

    p = sub.add_parser("serve", help="run wpkd: the board and the scheduler, in one process",
                       description="The same as `wpk dash --run`, for a login node or a "
                       "server: with [server] listen = \"unix\" the board is on "
                       "$WPK_HOME/run/wpkd.sock, reached with `ssh -L` (`wpk url` prints "
                       "the line). One wpkd per home, by $WPK_HOME/wpkd.lease, across hosts "
                       "that share the home (docs/scheduler.md §7.1).")
    p.add_argument("--detach", action="store_true",
                   help="start in the background; log in $WPK_HOME/log/wpkd.log")
    p.add_argument("--ensure", action="store_true",
                   help="start in the background unless a wpkd already runs (for cron)")
    p.add_argument("--port", type=int, help="port (default [server] port, 7878)")
    p.add_argument("-j", "--jobs", type=int, help="steps at once (default: the pool's jobs)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ide", help="open a packet or a work folder in VS Code",
                       description="Write or refresh the packet's VS Code workspace and print "
                       "links that open it: desktop VS Code over Remote-SSH, VS Code on this "
                       "machine, and web VS Code under the board's /ide/ ([ide] web = true). "
                       "With REPO, open that folder of work/ instead: your clone, or with "
                       "--packet the packet's worktree of it. See docs/vscode-plan.md.")
    p.add_argument("target", help="project name or directory, or a packet")
    p.add_argument("repo", nargs="?", help="an entry of the project's work/")
    p.add_argument("--packet", action="store_true",
                   help="with REPO: the packet's worktree, not your clone")
    p.add_argument("--open", action="store_true",
                   help="open it with `code` (in a VS Code terminal, or with a display)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_ide)

    p = sub.add_parser("url", help="print the running board's URLs",
                       description="Print the URLs the running `wpk dash` listens on.")
    p.set_defaults(func=cmd_url)

    p = sub.add_parser("login", help="sign a browser in to a board",
                       description="Sign in the browser showing CODE on a board's login "
                       "page, as the Unix user running this command (docs/unix-login.md).")
    p.add_argument("code", help="the code the login page shows, like K7QF-29XA")
    p.add_argument("--home", help="the board's runner home, if it is not yours "
                   "(the login page shows it)")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("step", help="run one step of a packet",
                       description="Run exactly one step. Exit status: 0 committed, "
                       "1 attempt failed, 2 not runnable, 3 lease held, 4 usage error.")
    p.add_argument("target", help="WPID (or unique prefix), project name, or a packet or project directory")
    p.add_argument("--force", action="store_true",
                   help="run even if the packet is not due or not RUNNABLE")
    p.add_argument("--lost", metavar="REASON",
                   help="the scheduler ended the last attempt (Stop now, the farm took "
                   "the slot): if it is unfinished, record it without counting it")
    p.set_defaults(func=cmd_step)

    p = sub.add_parser("recover", help="finish or clean up a crashed step; run no model")
    p.add_argument("target", help="WPID (or unique prefix), project name, or a packet or project directory")
    p.set_defaults(func=cmd_recover)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args, rest = parser.parse_known_args(argv)
    if rest and getattr(args, "func", None) is cmd_start and all("=" in r for r in rest):
        args.values += rest           # key=value after an option
    elif rest:
        parser.error("unrecognized arguments: %s" % " ".join(rest))
    if args.cmd is None:
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)
