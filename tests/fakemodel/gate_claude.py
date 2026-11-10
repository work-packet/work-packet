"""A fake Claude for the launch hook's acceptance test (brief-request.md): checks
the ordinary setting (``env_file``) and the gateway credential (a launch hook's),
appends only ``pass`` or ``fail`` to ``$GATE_RESULT``, then runs the usual fake.
The credential is compared with the private file ``$GATE_EXPECT`` names; its
value is never printed."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.environ["GATE_EXPECT"], encoding="utf-8") as fp:
    want = fp.read()
ok = os.environ.get("ACME_SETTING") == "plain" and \
    os.environ.get("ACME_GATEWAY_HEADERS") == want
with open(os.environ["GATE_RESULT"], "a") as fp:
    fp.write("pass\n" if ok else "fail\n")
sys.argv[0] = os.path.join(HERE, "fake_claude.py")
runpy.run_path(sys.argv[0], run_name="__main__")
