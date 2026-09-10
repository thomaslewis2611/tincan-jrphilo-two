# Tincan

Tincan opens Codex and Claude Code side by side in Warp, then carries completed
work and review feedback between their real interactive terminal UIs.

Codex remains the implementation lead. Claude reviews the shared checkout. A
blocking finding goes back to Codex, which may fix it or rebut it with evidence;
Claude then reviews again. Approval ends the loop. Five unresolved rounds escalate
to the human by default.

## Quick start

Prerequisites: macOS, Warp, Git, and authenticated `codex` and `claude` CLIs.

Put the launcher on your path once:

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/bin/tincan" ~/.local/bin/tincan
```

Then run it from any Git repository:

```sh
cd ~/dev/your-project
tincan
```

Tincan opens a new Warp window with Codex on the left and Claude on the right.
Give Codex a normal task; do not mention handoffs or reviewers. For example:

> Implement the requested change. When finished, summarize what changed and the
> verification you ran.

No separate arming command or issue number is required. The first launch in a
repository installs a local Codex Stop hook. Codex may ask you to trust that hook
once.

To launch without changing directory first:

```sh
tincan warp --repo ~/dev/your-project
```

Use `--tab` for a tab in the current Warp window and `--max-rounds N` to change the
review limit.

## Review contract

Claude distinguishes concrete blocking problems from optional suggestions. Codex
considers each blocker rather than implementing it blindly: it may fix the problem
or push back with code, requirement, or verification evidence. Claude must address
that evidence before repeating a disputed finding. Style preferences and optional
improvements do not block approval.

The visible loop is:

```text
Codex completes a turn
  -> Claude reviews the current checkout
     -> APPROVED: return the result to Codex and stop
     -> CHANGES_REQUESTED: return findings to Codex
        -> Codex fixes or rebuts
           -> Claude re-reviews
```

If Claude omits its machine-readable verdict, a handoff fails, or the round limit
is reached, Tincan stops the loop instead of treating the work as approved.

## Permissions and isolation

Tincan starts Codex with `--approve-for-me`, which automatically reviews routine
approval requests while retaining Codex's workspace-write sandbox. Claude starts
in `auto` permission mode. Tincan does not enable either CLI's dangerous sandbox
bypass mode, so genuinely sensitive or out-of-workspace operations may still stop
or fail safely.

Each Warp launch creates a private session identity. Both terminal relays and both
hooks require that identity, so other Codex and Claude sessions in the same
repository are ignored. Agents share the checkout, but only Codex is instructed to
edit it; Claude's review prompt is read-only.

Project hook configuration is stored in `.codex/config.toml` and excluded locally
through `.git/info/exclude`. Session state lives under `.git/tincan/`. Neither
location dirties the project worktree.

## Commands

```text
tincan                              open the paired Warp workspace for this repo
tincan warp [--repo PATH]           explicitly open the paired workspace
tincan warp --tab                   open in the current Warp window
tincan warp --max-rounds N          set the review limit (1-10)
tincan send-claude MESSAGE          inject a prompt into the active Claude pane
tincan send-codex MESSAGE           inject a prompt into the active Codex pane
tincan doctor                       check local prerequisites
```

## Headless fallback

The earlier review gate remains available for environments where a paired Warp UI
is not appropriate:

```text
tincan install [--repo PATH]        install the project Stop hook
tincan start [--repo PATH]          arm the headless review gate
tincan start --issue N              include GitHub issue context
tincan status [--repo PATH]         inspect the headless gate
tincan watch [--repo PATH]          stream the headless Claude transcript
tincan stop [--repo PATH]           disarm the headless gate
tincan issues [--repo PATH]         list GitHub issues
```

The legacy file bridge commands `ask`, `listen`, `demo`, `transcript`, and `clear`
are retained for experiments documented in [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md).

## Current scope

Tincan currently targets Warp on macOS and uses Warp Tab Configs for the two-pane
layout. A future council mode may generalize the same session transport to several
read-only perspectives feeding one lead agent, but that is intentionally outside
the current implementation.
