"""The studio's agent (docs/studio-plan.md P0.3): writes what the question asks.

``write <path>`` lines in the question become Write calls of
``# <path>\\n\\nwritten by the studio\\n``; the reply says what it wrote. With
none, it writes ``docs/findings.md``.
"""

import os


def run(prompt, fault, model):
    paths = [ln.split(None, 1)[1].strip() for ln in prompt.splitlines()
             if ln.startswith("write ") and len(ln.split(None, 1)) == 2]
    paths = paths or ["docs/findings.md"]
    return {"text": "Wrote %s [model %s, cwd %s]" % (", ".join(paths), model, os.getcwd()),
            "writes": [(p, "# %s\n\nwritten by the studio\n" % p) for p in paths]}
