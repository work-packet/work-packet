"""The scribe (docs/session-checkpoint.md §4.2): a checkpoint drafted from the end
of a session's transcript, so a packet worked on by hand in VS Code has a
current status even when nobody recorded one.

Off until ``[ide] sessions_scribe = true``: until then wpk never reads a
session's content. When on, a session of a packet that changed something (an
edit or a shell command) after the packet's last step, and has since ended or
gone idle for ``scribe_idle_s``, gets one draft: the last part of its
transcript (what the person asked, what the agent said, the tools it used and
on what; never their output), the outline and the current status go to a small
model with no tools, and what comes back is recorded with
``checkpoint.record(worker="scribe")``. It never moves the memento (D1), and a
checkpoint by hand made since the work wins.

``pass_once`` runs in the board's session loop and in an IDE job's watcher on
its host, where the transcripts are; a claim file per session and work time
makes sure one of them drafts it, once.
"""

import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time

from . import checkpoint, ide_sessions, layout, registry

log = logging.getLogger("wpk.scribe")

TAIL_BYTES = 4 << 20        # read this much of the end of each transcript (tool output is bulky)
TAIL_CHARS = 12000          # and give the model at most this much of it
OUTLINE_CHARS = 4000
STATUS_CHARS = 1500
MAX_AGE_S = 2 * 86400       # never draft for work older than this (turning it on)
TIMEOUT_S = 90
BUDGET_USD = 0.05

PROMPT = """You keep a work packet's status current. A person just worked on it in a
Claude or Codex session; below is the end of that session, the packet's plan
(outline) and its status before the session.

Reply with JSON only, no fence:
{"status": "...", "body": "...", "next": "...", "asked": "..."}

- status: where the work stands now, one line, at most 80 characters.
- body: two to five short lines: what changed in this session, decisions made,
  open questions. Plain text.
- next: the next action if the session makes it clear, one line; else "".
- asked: if the session ends with the agent asking the person something they
  have not answered yet (a decision, an approval, a choice), that question,
  quoted closely with its options; else "".

Say only what the session shows. Do not invent progress.

## Plan (state/outline.md)

{outline}

## Status before the session

{status}

## The session (its end)

{tail}
"""


# --- the transcript's end -------------------------------------------------------------

def _clip(s, n=200):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _tail_lines(path, max_bytes=TAIL_BYTES):
    with open(path, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        size = fp.tell()
        fp.seek(max(0, size - max_bytes))
        data = fp.read()
    lines = data.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]               # the first is cut
    for raw in lines:
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def _target(inp):
    """What a tool call was about: a path, a command, a pattern, a URL."""
    if not isinstance(inp, dict):
        return ""
    for k in ("file_path", "path", "notebook_path", "command", "cmd", "pattern", "url",
              "query", "description"):
        v = inp.get(k)
        if isinstance(v, list):
            v = " ".join(map(str, v))
        if isinstance(v, str) and v.strip():
            return _clip(v, 160)
    return ""


def _claude(d):
    kind = d.get("type")
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    content = msg.get("content")
    if kind == "user" and not d.get("isMeta"):
        if isinstance(content, str):
            yield "Person: " + _clip(content, 1500)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    yield "Person: " + _clip(b.get("text", ""), 1500)
    elif kind == "assistant" and isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                yield "Agent: " + _clip(b["text"], 1500)
            elif b.get("type") == "tool_use":
                yield "(tool %s %s)" % (b.get("name"), _target(b.get("input")))


_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)


def _codex(d):
    p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
    if d.get("type") == "event_msg":
        if p.get("type") == "user_message" and p.get("message"):
            yield "Person: " + _clip(p["message"], 1500)
        elif p.get("type") == "agent_message" and p.get("message"):
            yield "Agent: " + _clip(p["message"], 1500)
    elif d.get("type") == "response_item" and p.get("type") in ("function_call",
                                                                 "custom_tool_call"):
        args = p.get("arguments") if p.get("type") == "function_call" else p.get("input")
        if isinstance(args, str) and p.get("type") == "function_call":
            try:
                args = json.loads(args)
            except ValueError:
                pass
        if p.get("name") == "apply_patch" and isinstance(args, str):
            what = ", ".join(_PATCH_FILE.findall(args)[:6])
        else:
            what = _target(args) if isinstance(args, dict) else _clip(args or "", 160)
        yield "(tool %s %s)" % (p.get("name"), what)


READERS = {"claude": _claude, "codex": _codex}


def tail(harness, paths, max_chars=TAIL_CHARS):
    """The end of a session as plain lines: the person, the agent and the tools
    it used (names and targets, never output). ``paths``: its files, oldest first."""
    out = []
    for path in paths:
        try:
            for d in _tail_lines(path):
                out.extend(READERS[harness](d))
        except OSError:
            continue
    text = "\n".join(out)
    return text[-max_chars:] if len(text) > max_chars else text


# --- the draft ----------------------------------------------------------------------------

def ask_model(prompt, home=None, budget=BUDGET_USD, timeout=TIMEOUT_S, model=None):
    """One model call with no tools (``model``, else the console's): ``(text, cost)``;
    ``("", 0.0)`` when it fails."""
    text, cost, _ = call_model(prompt, home, budget, timeout, model)
    return text, cost


def call_model(prompt, home=None, budget=BUDGET_USD, timeout=TIMEOUT_S, model=None, **facts):
    """``ask_model`` that also says why it failed: ``(text, cost, error or None)``.
    The child gets ``[harnesses.claude] env`` and ``env_file``, as a step does, then
    the launch hooks (``facts``: ``wpid``, ``project_dir``)."""
    from .dash import agent as agentmod
    exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
    argv = exe + ["-p", "--output-format", "json", "--model",
                  model or agentmod.config(home)["model"],
                  "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                  "--disable-slash-commands", "--max-budget-usd", str(budget)]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    for k in ("WPK_WPID", "WPK_PROJECT", "WPK_IDE_LAUNCH"):     # not one of the packet's sessions
        env.pop(k, None)
    from . import harness, hooks
    env.update(harness.home_env("claude", home=home))
    hooks.prepare_env("claude", "model-call", env, **facts)
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "", 0.0, "claude did not answer in %d s" % timeout
    except (OSError, subprocess.SubprocessError) as e:
        return "", 0.0, "claude could not start (%s)" % e
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    except (ValueError, IndexError):
        out = None
    if not isinstance(out, dict):
        out = {}
    text = (out.get("result") or "").strip()
    cost = float(out.get("total_cost_usd") or 0.0)
    if p.returncode or out.get("is_error") or not text:
        why = text if out.get("is_error") and text else (
            p.stderr.strip().splitlines() or p.stdout.strip().splitlines() or [""])[-1]
        return "", cost, "claude exited %d%s" % (p.returncode, ": " + why[:300] if why else "")
    return text, cost, None


def parse(text):
    """The model's reply as ``{"status", "body", "next"}``, or None."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        d = json.loads(text[a:b + 1])
    except ValueError:
        return None
    if not isinstance(d, dict) or not str(d.get("status") or "").strip():
        return None
    return {k: str(d.get(k) or "").strip() for k in ("status", "body", "next", "asked")}


def _read(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read(n)
    except OSError:
        return ""


def draft(pkt, harness, paths, home=None, ask=None):
    """``({"status", "body", "next"} or None, cost)`` for a session of ``pkt``."""
    t = tail(harness, paths)
    if not t.strip():
        return None, 0.0
    try:
        _, body = pkt.load_status()
    except Exception:           # noqa: BLE001 - a draft without it is still a draft
        body = ""
    prompt = PROMPT.replace("{outline}", _read(os.path.join(pkt.state_dir, "outline.md"),
                                              OUTLINE_CHARS).strip() or "(none)") \
        .replace("{status}", (body or "").strip()[:STATUS_CHARS] or "(none)") \
        .replace("{tail}", t)
    text, cost = (ask or ask_model)(prompt, home)
    return parse(text), cost


def scribe(home, rec, ask=None):
    """Draft and record a checkpoint for one session record. Returns the step, or None."""
    pkt = packet_of(rec, home)
    if pkt is None:
        return None
    paths = transcripts(home, rec)
    got, cost = draft(pkt, rec["harness"], paths, home, ask)
    if got is None:
        log.warning("%s %s: no draft for session %s", rec["project"], rec["wpid"][:8],
                    rec["session_id"][:8])
        return None
    meta = {"cost_usd": round(cost, 6), "harness": rec["harness"],
            "session_id": rec["session_id"],
            "scribe": {"session": rec["session_id"], "harness": rec["harness"],
                       "work_t": rec.get("last_work_t")}}
    out, n = checkpoint.record(pkt, got["status"], body=got["body"] or None,
                               next_action=got["next"] or None, worker="scribe",
                               by="scribe", meta=meta, after=rec.get("last_work_t"))
    if out.code != 0:
        log.warning("%s %s: scribe: %s", rec["project"], rec["wpid"][:8], out.msg)
    record_ask(pkt, rec["session_id"], got.get("asked"), rec.get("last_work_t"))
    return n


# --- questions left open in a session ---------------------------------------------------
#
# A question a session's agent put to the person and that is still unanswered when
# the session goes quiet is not one of the packet's questions (the scribe never
# moves the memento, D1), but it is waiting on the person all the same. The scribe
# keeps the latest one per session in ``session-asks.json`` in the packet's run
# folder, and the focus brief shows them under Decide.

ASKS = "session-asks.json"
ASK_TTL_S = 7 * 86400


def _asks_path(pkt):
    return os.path.join(pkt.path, ASKS)


def _load_asks(pkt):
    try:
        with open(_asks_path(pkt)) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record_ask(pkt, session_id, asked, t=None):
    """Keep (or, with no ``asked``, clear) the open question of one session."""
    from . import fsutil
    d = _load_asks(pkt)
    if asked and asked.strip():
        d[session_id] = {"q": asked.strip()[:1500], "t": t or time.time()}
    elif session_id in d:
        del d[session_id]
    else:
        return
    now = time.time()
    d = {k: v for k, v in d.items() if isinstance(v, dict) and now - (v.get("t") or 0)
         < ASK_TTL_S}
    try:
        fsutil.atomic_write(_asks_path(pkt), json.dumps(d, indent=1) + "\n")
    except OSError:
        log.warning("%s: could not keep the session's question", pkt.path)


def open_asks(pkt, now=None):
    """``[{"session", "q", "t"}]``, newest first: questions sessions left open in
    the last week, asked after the packet's last checkpoint by hand."""
    now = time.time() if now is None else now
    by_hand = checkpoint.last_by_hand(pkt) or 0
    out = [{"session": k, "q": v.get("q"), "t": v.get("t")} for k, v in _load_asks(pkt).items()
           if isinstance(v, dict) and v.get("q") and now - (v.get("t") or 0) < ASK_TTL_S
           and (v.get("t") or 0) > by_hand]
    return sorted(out, key=lambda x: -(x["t"] or 0))


# --- which sessions, and when ---------------------------------------------------------

def packet_of(rec, home=None):
    """The session's packet, or None."""
    from .packet import Packet
    try:
        e = registry.get(rec["project"], home)
    except Exception:           # noqa: BLE001 - an unregistered project: nothing to do
        return None
    if not e:
        return None
    d = layout.run_dir(e["path"], rec["wpid"])
    return Packet(d) if os.path.isfile(os.path.join(d, "status.md")) else None


def transcripts(home, rec):
    """The session's files that this host can read, oldest first."""
    files = (ide_sessions._load_cur(home, rec["harness"], rec["session_id"]).get("files")
             or {}).keys()
    got = [p for p in files if os.path.isfile(p)]
    return sorted(got, key=lambda p: os.path.getmtime(p))


def scribe_dir(home):
    return os.path.join(home, "ide", "scribe")


def _claim(home, rec):
    """Claim (session, its work time) for this host; False if it was claimed."""
    d = scribe_dir(home)
    os.makedirs(d, mode=0o700, exist_ok=True)
    name = "%s-%s-%d" % (rec["harness"], rec["session_id"], int(rec["last_work_t"]))
    try:
        os.close(os.open(os.path.join(d, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return False
    return True


def due(home, now, cfg, records=None):
    """The session records to draft for now, at most one per packet (its latest work)."""
    from . import checkpoint as cp
    idle = float(cfg.get("scribe_idle_s") or 1800)
    best = {}
    for r in ide_sessions.cached_records(home) if records is None else records:
        w = r.get("last_work_t")
        if not (r.get("project") and r.get("wpid") and w) or now - w > MAX_AGE_S:
            continue
        ended = r.get("attribution") in (ide_sessions.CONFIRMED, ide_sessions.HOOK) \
            and not r.get("live")
        if not (ended or now - (r.get("last_activity_t") or 0) >= idle):
            continue
        k = (r["project"], r["wpid"])
        if k not in best or w > best[k]["last_work_t"]:
            best[k] = r
    out = []
    for r in best.values():
        name = "%s-%s-%d" % (r["harness"], r["session_id"], int(r["last_work_t"]))
        if os.path.exists(os.path.join(scribe_dir(home), name)):
            continue
        pkt = packet_of(r, home)
        if pkt is None:
            continue
        last = cp.last(pkt)
        if last and last["t"] and last["t"] >= r["last_work_t"]:
            _claim(home, r)                 # a step since the work: nothing to draft
            continue
        if not transcripts(home, r):
            continue                        # on another host: its watcher drafts it
        out.append(r)
    return out


def switch_path(home):
    return os.path.join(home, "ide", "scribe.json")


def enabled(home, cfg=None):
    """Whether the scribe is on: the board's switch (``ide/scribe.json``, set from
    the dash) when it has been used, else ``[ide] sessions_scribe``."""
    try:
        with open(switch_path(home)) as fp:
            d = json.load(fp)
        if isinstance(d, dict) and isinstance(d.get("on"), bool):
            return d["on"]
    except (OSError, ValueError):
        pass
    if cfg is None:
        from . import ide
        try:
            cfg = ide.load_config(home)
        except Exception:           # noqa: BLE001 - a bad config.toml: off
            return False
    return bool(cfg.get("sessions_scribe"))


def set_enabled(home, on, by=None):
    """The dash's switch. ``config.toml`` is the person's file and is not rewritten."""
    from . import fsutil
    os.makedirs(os.path.dirname(switch_path(home)), mode=0o700, exist_ok=True)
    fsutil.atomic_write(switch_path(home), json.dumps(
        {"on": bool(on), "by": by, "t": time.time()}) + "\n")


_busy = threading.Lock()


def pass_once(home, cfg, now=None, ask=None, wait=False):
    """Draft what is due, one session at a time, in a thread (the session loop
    must stay fast). Off unless ``enabled``. Returns the records started."""
    if not enabled(home, cfg):
        return []
    if not _busy.acquire(blocking=False):
        return []                           # still drafting the last lot
    try:
        got = [r for r in due(home, time.time() if now is None else now, cfg)
               if _claim(home, r)]
    except Exception:
        _busy.release()
        raise
    if not got:
        _busy.release()
        return []

    def run():
        try:
            for r in got:
                try:
                    scribe(home, r, ask)
                except Exception:           # noqa: BLE001 - say why; the next goes on
                    log.exception("scribe: %s %s", r.get("project"), r.get("session_id"))
        finally:
            _busy.release()
    t = threading.Thread(target=run, name="wpk-scribe", daemon=True)
    t.start()
    if wait:
        t.join()
    return got
