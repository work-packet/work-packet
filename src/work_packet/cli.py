"""The ``wpk`` command line. Stage 1 subcommands land here (docs/stage1-plan.md)."""
import argparse
import os
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


def cmd_step(args) -> int:
    from . import executor
    return _outcome(executor.step(args.target, force=args.force))


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
    if prompt is None:
        return _err("give --prompt or --prompt-file")
    try:
        plan = project.new(args.name, prompt, path=args.dir, model=args.model, tz=args.tz,
                           paused=args.paused, dry_run=args.dry_run)
    except (project.ProjectError, OSError) as e:
        return _err(str(e))
    verb = "Would create" if args.dry_run else "Created"
    print("%s project %s at %s" % (verb, plan.name, plan.path))
    for f in plan.files:
        print("  " + f)
    print("Root packet %s, model %s, zone %s" % (plan.root, plan.model, plan.tz or "local"))
    print("Steps run with --permission-mode %s --allowedTools %s" % (
        plan.permission_mode, ",".join(plan.allowed_tools)))
    if not args.dry_run:
        print("Run `wpk tick` to start it%s." % (" (it is PAUSED: `wpk resume %s` first)"
                                                 % plan.name if args.paused else ""))
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
        want = ("RUNNABLE", "SLEEPING") if op == "pause" else ("PAUSED",)
        pkts = [p for _, p, m, _ in views.packets(e["path"], e["root"])
                if m is not None and m["state"] in want]
        if not pkts:
            print("wpk: nothing to %s in %s" % (op, e["name"]), file=sys.stderr)
            return 0
    code = 0
    for p in pkts:
        out = executor.admin(Packet(p.path), op)
        print("wpk: %s" % out.msg, file=sys.stderr)
        code = max(code, out.code)
    return code


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
                       "becomes the root packet's first instruction.")
    p.add_argument("name")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--prompt", help="the task, as text")
    g.add_argument("--prompt-file", help="the task, from a file")
    p.add_argument("--dir", help="project directory (default ./<name>)")
    p.add_argument("--model", help="model for the root packet")
    p.add_argument("--tz", help="IANA zone for resume times (default: local)")
    p.add_argument("--paused", action="store_true", help="create the root PAUSED")
    p.add_argument("--dry-run", action="store_true", help="print what would be created")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("adopt", help="register an existing project directory")
    p.add_argument("dir")
    p.set_defaults(func=cmd_adopt)

    p = sub.add_parser("rm", help="remove a project from the registry (files are kept)")
    p.add_argument("name")
    p.set_defaults(func=cmd_rm)

    p = sub.add_parser("ps", help="list packets of registered projects")
    p.add_argument("--all", action="store_true", help="include finished projects")
    p.add_argument("--project", help="only this project")
    p.set_defaults(func=cmd_ps)

    p = sub.add_parser("show", help="print a packet's status, memento and children")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("log", help="print a packet's journal, or one step")
    p.add_argument("target", help="WPID (or unique prefix), project name or directory")
    p.add_argument("--step", type=int, help="show this step's summary, diff and meta")
    p.set_defaults(func=cmd_log)

    for op, h in (("pause", "set PAUSED"), ("resume", "set PAUSED or FAILED back to RUNNABLE")):
        p = sub.add_parser(op, help=h + " (a WPID, or every packet of a project)")
        p.add_argument("target", help="WPID (or unique prefix), project name or directory")
        p.set_defaults(func=cmd_admin)

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

    p = sub.add_parser("step", help="run one step of a packet",
                       description="Run exactly one step. Exit status: 0 committed, "
                       "1 attempt failed, 2 not runnable, 3 lease held, 4 usage error.")
    p.add_argument("target", help="WPID (or unique prefix), project name, or a packet or project directory")
    p.add_argument("--force", action="store_true",
                   help="run even if the packet is not due or not RUNNABLE")
    p.set_defaults(func=cmd_step)

    p = sub.add_parser("recover", help="finish or clean up a crashed step; run no model")
    p.add_argument("target", help="WPID (or unique prefix), project name, or a packet or project directory")
    p.set_defaults(func=cmd_recover)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)
