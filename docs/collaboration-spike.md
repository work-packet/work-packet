# C0 spike: Claude Code hooks in a packet folder

The spike for `collaboration-plan.md` step C0, run on 2026-11-06 with Claude Code
2.1.280 (CLI) and the VS Code extension 2.1.318 (its bundled native binary).
Sanitized payloads are in `tests/data/hooks/*.json`. Prompt, reply and tool text
are replaced with `SENTINEL-*`, and paths with `@PKT@` and `@HOME@`.

## Method

- A scratch folder had `.claude/settings.local.json` hooks for every event, each
  running a script that saved stdin and the `CLAUDE*`/`WPK*` environment.
- **CLI, print mode:** `claude -p --model haiku "…"`.
- **CLI, interactive:** `claude` in tmux. I triggered a Bash permission prompt,
  approved it, waited for the idle notification, then ran `/exit`.
- **VS Code extension mode:** the extension's own binary, run the way
  `extension.js` runs it: `-p --input-format stream-json --output-format
  stream-json --permission-prompt-tool stdio --setting-sources user,project,local`
  with `CLAUDE_CODE_ENTRYPOINT=claude-vscode`. I triggered a Bash permission
  request (a `can_use_tool` control request) and left it unanswered.

## Results

| Question | Answer |
|---|---|
| Do project-local `settings.local.json` hooks fire in the CLI? | **Yes**: SessionStart (`source: startup`), UserPromptSubmit, PreToolUse, PermissionRequest, Notification, Stop, SessionEnd (`reason`: `other` in `-p`, `prompt_input_exit` on `/exit`). |
| …in the VS Code extension? | **Yes.** `extension.js` passes `settingSources: ["user","project","local"]`, and the bundled binary fired SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest and Notification under `--permission-prompt-tool stdio`. A click-through in a real VS Code window is still on the manual checklist (plan §4.6). |
| How do we see "blocked on a permission prompt"? | **`PermissionRequest` fires at once** (it has `tool_name` and `tool_input`), before the extension's `can_use_tool` request. `Notification` with `notification_type: "permission_prompt"` ("Claude needs your permission") follows about **6 s** later. Use PermissionRequest; Notification is a backstop. |
| Is the matcher the notification type? | The payload carries `notification_type` (`permission_prompt`, `idle_prompt`). Match `*` and branch on that field; don't parse the message. |
| Idle | `Notification` `idle_prompt` ("Claude is waiting for your input") arrives **60 s after Stop**. |
| What clears "blocked"? | **No event says a permission was granted.** The next PostToolUse, Stop or UserPromptSubmit does. To clear it while an approved tool is still running, hook **PostToolUse** as well (cost: one hook process per tool call; see latency). |
| `additionalContext` | **Works** from SessionStart and from UserPromptSubmit (JSON `hookSpecificOutput`). The model repeated both injected facts. A size limit wasn't probed; the plan keeps the briefing ≤ 1.5 KB. |
| Hook latency | Python start-up plus `import work_packet.journal` takes about **20 ms** on local disk. A stdlib-only `hookcmd` is well inside budget. Not measured on a shared NFS home; re-check on the farm. |
| Content in payloads | **Payloads carry content**: `prompt` (UserPromptSubmit), `last_assistant_message` (Stop), `tool_input` and `permission_suggestions[].rules[].ruleContent` (PreToolUse, PermissionRequest). `hookcmd` must allowlist fields and never write those. |
| Env seen by the hook | `CLAUDE_CODE_ENTRYPOINT` (`cli`, `sdk-cli`, `claude-vscode`), `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PROJECT_DIR`, `CLAUDE_PID`, `CLAUDE_CODE_SESSION_ATTENDED` (`1` interactive, `0` print mode). Plus whatever the terminal had (`WPK_WPID` etc. when the board set it). |
| Folder trust | The **interactive CLI asks "do you trust this folder?"** the first time, and project hooks run only after that. The extension relies on VS Code's workspace trust; the board already sets `workspace_trust`. A packet opened only from a terminal needs one trust click. |
| Will runner steps fire our hooks? | **No.** The runner and the studio agent run with `--setting-sources ""` (`harness/claude.py:141`, `dash/agent.py:279`), so project settings aren't loaded. As a second guard, `hookcmd` ignores any process with `WPK_STEP` set (`executor.py:808`). |
| `~/.claude/sessions/<pid>.json` | Has `status` (`idle` / `busy`), `statusUpdatedAt`, `kind: interactive` and `entrypoint`. It is a hook-free fallback for working vs idle. It doesn't show a permission wait. |
| Codex | Codex 0.147 has **hooks** (feature `hooks`, stable), configured in `~/.codex/hooks.json` with the same shape as Claude's. Whether a **project-local** `.codex/hooks.json` is honoured is **not verified**: Codex isn't signed in on this host (401). Open; see the plan's §2a row. |
| Counting web tabs | Not spiked against a live workbench. **Decision:** count tabs from the injected shim script. Each tab makes a random tab id and beats `/ide/<key>/__wpk/vis` with its `visibilityState`. That gives exact tabs and focus regardless of how many WebSockets a tab opens. The WebSocket count stays as the "something is attached" fallback. The workbench page is top-level (the shim is injected into it), so `visibilityState` is the tab's own. |

## Consequences for the plan

- C2 hooks: SessionStart, UserPromptSubmit, **PermissionRequest**,
  **PostToolUse**, Notification, Stop, PreCompact and SessionEnd. PreToolUse
  isn't needed.
  - PermissionRequest → `blocked` (with the tool name).
  - PostToolUse → `working`, but only if `blocked`. It returns at once otherwise.
  - Notification `idle_prompt` → confirmed `waiting`.
- The payload allowlist is part of C2.3, with a test that feeds every fixture and
  checks no `SENTINEL` reaches disk.
- The blocked threshold (2 min, design §4.3) is measured from PermissionRequest.
- Codex: deferred to when a signed-in host is available. Until then Codex
  sessions keep the transcript-only turn state, labelled "probably".
