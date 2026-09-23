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

## 9. Poolside lifecycle hooks use a different protocol

Poolside CLI 1.0.16 supports native `SessionStart`, `UserPromptSubmit`, and `Stop`
hooks. See the [Poolside hook reference](https://docs.poolside.ai/hooks).
Its protocol uses snake_case (`hook_specific_output`, `additional_context`), unlike
the Claude/Codex hook response format. The Stop payload contains a `reason` and
`trajectory_path`, not `last_assistant_message`; Tincan reads the final assistant
message from that trajectory for review context.

Visible Poolside sessions load private hook settings through `pool -- --settings`.
Hooks advance a session-scoped controller; Codex and Claude run in their own normal
terminal processes and return read-only verdicts through their Stop hooks. Poolside
never needs to spawn either reviewer inside its tool sandbox. Both enabled reviewers
must approve identical content before Poolside finalizes. Headless `pool-exec`
remains a separate execution path.
