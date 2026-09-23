# Constraints

The original constraints were established empirically on 2026-09-08. Codex added
synchronous lifecycle hooks afterward, which changes the best design substantially.

## 0. Codex Stop hooks are now the supported injection path

A synchronous `Stop` hook receives the session id, repository, transcript path, and
last assistant message. Returning `{"decision":"block","reason":"..."}` makes Codex
continue automatically, with the reason as the next prompt.

This is the mechanism used by the current review gate: the hook runs Claude Code in
read-only print mode, and blocking review findings become the continuation reason.
No second process writes to the Codex thread.

## 1. One writer per Codex thread, enforced

`codex exec resume <id>` against a thread that any Codex process holds open fails:

    thread-store conflict: thread <id> already has an active writer

It refuses rather than corrupting. This is why Claude cannot write into a Codex
conversation that is currently open in a window. Not a permissions gap -- a
deliberate invariant.

## 2. Cursor's extension holds locks for the life of the extension host

The Cursor ChatGPT extension runs ONE long-lived codex process (observed: started
a day earlier, PID stable) holding **six** rollout files open simultaneously.
Closing a chat in the UI releases nothing. Only quitting Cursor or reloading the
extension host drops the handles.

Consequence: any thread Cursor has touched is unwritable by anything else for as
long as Cursor runs.

## 3. `codex exec resume` works fine on unlocked threads

Verified: resumed by id, full prior context intact, appended in place (one rollout
file, not a fork). So threads ARE addressable -- exclusivity is the constraint,
not addressing.

## 4. The app-server protocol supports turn injection, but you can't reach it

`ClientRequest` includes `thread/loaded/list`, `thread/resume`, `turn/start`,
`turn/steer`, `thread/inject_items`. All the right primitives exist.

But: the daemon requires the installer-managed standalone build at
`~/.codex/packages/standalone/current/codex` (Homebrew's cask will not do), and
even with the daemon running and `remoteControlEnabled: true`, both
`app-server-control.sock` and `ipc.sock` accept a connection then immediately close
on JSON-RPC -- including for Codex's own `codex app-server proxy` client.
`codex remote-control start` reports the cloud link errored.

Not pursued further. Even if reachable, #1 still forbids writing to a live thread.

## 5. `claude mcp serve` hangs inside Codex's sandbox

It cannot create its unix socket in `/tmp/cc-socks/` and then waits forever rather
than failing. Observed: zero socket fds, process alive indefinitely.

The same call from an ordinary shell works and creates its socket normally. So
anything invoking `claude` must run OUTSIDE the sandbox -- hence `tincan-relay`
being a separate process rather than part of `tincan-ask`.

## 6. zsh kills unmatched globs

`for f in dir/req-*.txt` aborts the whole script under zsh when nothing matches
(`no matches found`), before any `[ -e "$f" ]` guard can run. Bash would just
iterate the literal. Use `find`.

## 7. The Cursor Codex has no tty

TTY is `??` with zero tty file descriptors -- it's a subprocess talking a protocol
to a webview. So `tmux send-keys` cannot target it. tmux only becomes an option if
Codex runs as an actual terminal TUI.

## 8. Where the injection path actually is

The writer lock blocks *external* writers. It does not block the window's *own*
writer. So the only ways into a live Codex conversation are:

  a. Codex chooses to read something (a blocking command's stdout) -- what tincan does
  b. Typing into its TUI, if it has one (tmux send-keys)

There is now a third option:

  c. A synchronous `Stop` hook returns a blocking reason, which the owning Codex
     process turns into a continuation prompt.

## 9. Poolside has no native Stop hook

Unlike Codex and Claude Code, the Poolside CLI does not expose synchronous
lifecycle hooks (equivalent to `Stop` or `UserPromptSubmit`). It emits newline-
delimited JSON events from `pool exec --output json`, but there is no hook
callback that fires at turn boundaries.

This is why Poolside-led visible mode (`tincan warp --poolside`) uses a manual
handoff model: the user presses a key to trigger `handle_visible_handoff`,
which sends completed work through the Codex → Claude review chain. The
`tincan-pool-claude-hook` routes Claude's verdict back to the Poolside pane
instead of Codex, because there is no Poolside hook to trigger automatically.

Headless mode (`tincan pool-exec`) does not depend on hooks at all — it calls
`pool exec`, `codex exec review`, and `claude -p` directly from a script.
