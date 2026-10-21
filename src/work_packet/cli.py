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

    p = sub.add_parser("step", help="run one step of a packet",
                       description="Run exactly one step. Exit status: 0 committed, "
                       "1 attempt failed, 2 not runnable, 3 lease held, 4 usage error.")
    p.add_argument("target", help="packet directory, or project directory for its root")
    p.add_argument("--force", action="store_true",
                   help="run even if the packet is not due or not RUNNABLE")
    p.set_defaults(func=cmd_step)

    p = sub.add_parser("recover", help="finish or clean up a crashed step; run no model")
    p.add_argument("target", help="packet directory, or project directory for its root")
    p.set_defaults(func=cmd_recover)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)
