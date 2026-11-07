"""Finish, proposing two follow-ups for the owner's Inbox (docs/collaboration.md W8)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def run(prompt, fault, model):
    common.finish({"resume": "done", "follow_ups": [
        "The DMA wrap test also fails on 32-bit bursts", "Remove the unused seed table"]},
        "", "Done; found two more things.\n", fault)
    return "proposed"
