"""Record start and end times to $WPK_FAKE_LOG around a short sleep, then finish."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def run(prompt, fault, model):
    log = os.environ["WPK_FAKE_LOG"]
    with open(log, "a") as fp:
        fp.write("start %f\n" % time.time())
    time.sleep(0.4)
    with open(log, "a") as fp:
        fp.write("end %f\n" % time.time())
    common.finish({"resume": "done"}, "", "Slept.\n", fault)
    return "slept"
