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
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)
