# Tincan

Tincan opens Codex and Claude Code side by side in Warp, then carries completed
work and review feedback between their real interactive terminal UIs.

Codex remains the implementation lead. Claude reviews the shared checkout. A
blocking finding goes back to Codex, which may fix it or rebut it with evidence;
Claude then reviews again. Approval ends the current review cycle; after Codex
reports the approved result, the same panes wait for another task. Five unresolved
rounds escalate to the human by default.

## Access and installation

Tincan currently runs from its source repository; it is not yet distributed as a
Homebrew package or standalone application. Because the repository is private, a
new user first needs to be invited as a GitHub collaborator and accept the
invitation. Packaging would make installation easier, but a private package would
still require some form of access control.

### 1. Install the prerequisites

Tincan currently requires:

- macOS
- Warp
- Git
- the `codex` CLI, installed and authenticated with the user's own account
- the `claude` CLI, installed and authenticated with the user's own account

Both commands must be available on `PATH`. Tincan does not provide or share access
to either service.

### 2. Get access and clone Tincan

Send the repository owner your GitHub username. After the owner adds you as a
collaborator, accept GitHub's invitation, then run:

```sh
mkdir -p ~/dev
cd ~/dev
git clone https://github.com/jrphilo/tincan.git
cd tincan
```

### 3. Put the launcher on your path

Create a symlink once:

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/bin/tincan" ~/.local/bin/tincan
```

If `~/.local/bin` is not already on `PATH`, add this line to `~/.zshrc`, then open
a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Verify the installation:

```sh
tincan doctor
```

Resolve any reported failures before continuing.

### 4. Start a session

Run Tincan from any Git repository you want Codex and Claude to work on:

```sh
cd ~/dev/your-project
tincan
```

Tincan opens a new Warp window with Codex on the left and Claude on the right.
Give Codex a normal task; do not mention handoffs or reviewers. For example:

> Implement the requested change. When finished, summarize what changed and the
> verification you ran.

For implementation tasks, Tincan tells Codex to inspect the Git state and move
off the repository's default branch before editing. Codex chooses a meaningful
branch from the task rather than using a generic session name. Existing work is
preserved, and explicit user directions or repository-specific `AGENTS.md` rules
take precedence when they call for a different branching workflow.

No separate arming command or issue number is required. The first launch in a
repository installs a local Codex Stop hook. Codex may ask you to trust that hook
once.

To update Tincan later:

```sh
cd ~/dev/tincan
git pull
```

The symlink continues to use the updated checkout.

To launch without changing directory first:

```sh
tincan warp --repo ~/dev/your-project
```

Use `--tab` for a tab in the current Warp window and `--max-rounds N` to change the
review limit.

## Distribution options

The private collaborator flow above is the simplest way to share Tincan with a
small number of people. It provides normal `git pull` updates and does not require
maintaining a separate package.

Other options are:

- Send a source archive directly. This avoids a GitHub invitation, but updates are
  manual and recipients cannot pull fixes.
- Publish a private Homebrew tap or package. This improves installation, but users
  still need credentials for the private source or artifact host.
- Make the repository public and add an open-source license. This removes the
  invitation step and makes a public Homebrew formula straightforward.

In other words, repository access and packaging solve different problems: access
controls who may obtain Tincan; packaging controls how conveniently they install
it.

## Independent brainstorms

Launch the opt-in brainstorm mode when you want Codex and Claude to develop views
as peers rather than use the implementation-and-review workflow:

```sh
cd ~/dev/your-project
tincan brainstorm
```

Type each question once in the Codex pane. Tincan sends the same prompt to Claude
before Codex begins its response. Neither model sees the other's initial answer.
After both finish, Tincan exchanges those answers and asks each model to reconsider
its position. When both reconsiderations finish, Codex presents a synthesis that
retains any material disagreement. The panes then wait for the next question.

```text
                         one user prompt
                        /               \
          Codex independent view   Claude independent view
                        \               /
                     exchange after both finish
                        /               \
             Codex reconsideration   Claude reconsideration
                        \               /
                         Codex synthesis
```

Brainstorm sessions run Codex read-only and Claude in plan mode. They are intended
for exploration and decisions, not implementation. Start an ordinary Tincan session
when the discussion turns into work you want the agents to perform.

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
     -> APPROVED: return the result to Codex and complete this cycle
     -> CHANGES_REQUESTED: return findings to Codex
        -> Codex fixes or rebuts
           -> Claude re-reviews
```

After an approval, Codex visibly summarizes the result as usual. Tincan does not
send that approval summary back for redundant review. Instead, it resets the round
counter and waits. The next task you enter in the same Codex pane begins a fresh
review cycle automatically when it changes checked-out content; reopening Tincan
is unnecessary. Administrative follow-ups such as committing, switching branches,
pushing, or opening a pull request do not trigger another review when the approved
file contents remain unchanged.

After the first approval in a cycle, Codex automatically assesses Claude's optional
suggestions. It may implement a suggestion only when it is clearly useful, in scope,
small, low-risk, and directly verifiable; otherwise it briefly defers or declines it.
If that triage changes checked-out content, Claude reviews the result. Tincan offers
this optional-improvement pass only once so approval cannot become an endless polish
loop.

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
tincan warp --poolside [--repo PATH]  open the three-pane Poolside workspace
tincan brainstorm [--repo PATH]     independent views, reconsideration, synthesis
tincan warp --tab                   open in the current Warp window
tincan warp --max-rounds N          set the review limit (1-10)
tincan pool-exec [-p PROMPT]        run headless Poolside → Codex → Claude loop
tincan pool-exec --skip-codex        skip Codex peer review (Claude only)
tincan pool-exec --skip-claude       skip Claude secondary review (Codex only)
tincan pool-exec --continue         resume the previous pool exec run
tincan pool-exec --dry-run          show current state without running agents
tincan pool-review                  review current changes (Codex → Claude)
tincan pool-exec --max-rounds N     cap review cycles in pool-exec mode
tincan warp --poolside              open 3-pane Poolside workspace
tincan warp --poolside --no-codex    open 2-pane (Poolside + Claude)
tincan warp --poolside --no-claude   open 2-pane (Poolside + Codex)
tincan send-claude MESSAGE          inject a prompt into the active Claude pane
tincan send-codex MESSAGE           inject a prompt into the active Codex pane
tincan send-poolside MESSAGE        inject a prompt into the active Poolside pane
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

## Poolside mode

Poolside can serve as the implementation lead, with Codex and Claude performing
peer and secondary review respectively. Two workflows are supported:

### Headless: `tincan pool-exec`

Runs a fully automated loop without Warp:

```sh
tincan pool-exec --repo ~/dev/your-project \
  -p "Implement the requested feature in the user-service module"
```

The pipeline runs: **Poolside (implement) → Codex (peer review) → Claude (secondary review)**,
reporting each round's verdict. When both reviewers approve, the cycle ends. Blocking
findings are fed back to Poolside as a follow-up prompt and the loop repeats, up to
`--max-rounds` (default 5).

```sh
tincan pool-exec -p "..."                    # fresh pool exec run
tincan pool-exec -p "..." --max-rounds 3     # cap at 3 review cycles
tincan pool-exec -p "..." --continue         # resume the previous pool run
tincan pool-exec --dry-run                   # show current state without running
tincan pool-review                           # review only (Codex → Claude on current changes)
```

The `pool` binary must be on `PATH`. If it lives in `~/.local/bin`, ensure that
directory is on your shell's `PATH`. You can also override the binary with the
`TINCAN_POOL` environment variable (e.g. `TINCAN_POOL=~/.local/bin/pool`).

### Visible: `tincan warp --poolside`

Opens a three-pane Warp workspace so you can observe the review chain live:

```sh
tincan warp --repo ~/dev/your-project --poolside
```

Layout:

```
┍━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃   Poolside    ┃     Codex     ┃
├───────────────────────────────┤
┃           Claude             ┃
└───────────────────────────────┘
```

Give Poolside a normal task. Native Poolside lifecycle hooks automatically run
**Poolside → Codex → Claude → Poolside**. Both reviewers inspect the same checkout
read-only, and both must approve. Tincan returns both reviews to Poolside; it fixes
valid blockers or rebuts them with evidence, then both reviewers audit again.
Five unresolved rounds stop for human adjudication by default (`--max-rounds N`).

After approval, Poolside summarizes and the panes wait for the next task. Optional
suggestions receive one triage pass; any resulting edits are reviewed again.
Commits and other administrative actions do not retrigger review when approved
file contents are unchanged. Missing or conflicting verdicts, failed handoffs,
and content changes during review stop the loop without approval.

This requires Poolside CLI **1.0.16 or newer**, using its built-in Poolside ACP
server. Tincan passes private per-session hook settings through `pool -- --settings`;
it preserves your project and personal settings. No manual send command is needed.
Restart sessions opened before this update to load the new hooks.
Claude API errors also stop the loop and return the failure to Poolside, without
marking the code approved. A saved login alone does not prove service access: if
Claude reports an organization restriction, try `/login` in Claude with the intended
subscription account and organization. If it persists, contact your organization
administrator or Anthropic support. Tincan cannot override account access policies.


Claude runs as the normal interactive `claude` CLI in its own Warp pane, using its
existing login. A Claude Pro/Max subscription works with Claude Code; no API key is
required. Check `claude auth status` from a normal terminal and use `claude auth login`
if needed. Running Claude from inside another agent's sandbox can hide the macOS
Keychain login; Tincan's visible mode avoids that by sending to the already running
Claude pane. An `ANTHROPIC_API_KEY` can override subscription authentication; see
[Claude's authentication guidance](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code).

`start --poolside` is a headless state command; it does not connect interactive panes.
Use `warp --poolside` for the visible automatic loop or `pool-exec` for headless work.

### Optional reviewer exclusion

Both workflows let you drop one reviewer:

```sh
# Headless — skip a reviewer
tincan pool-exec -p "..." --skip-codex      # Poolside → Claude only
tincan pool-exec -p "..." --skip-claude     # Poolside → Codex only

# Visible — 2-pane layout
tincan warp --repo ~/dev/project --poolside --no-claude   # Poolside + Codex
tincan warp --repo ~/dev/project --poolside --no-codex    # Poolside + Claude
```

| Flag | Headless | Visible layout | Review chain |
|---|---|---|---|
| *(default)* | `pool-exec` | 3 panes | Poolside → Codex → Claude → Poolside |
| `--skip-codex` / `--no-codex` | `pool-exec --skip-codex` | 2 panes | Poolside → Claude → Poolside |
| `--skip-claude` / `--no-claude` | `pool-exec --skip-claude` | 2 panes | Poolside → Codex → Poolside |

The excluded reviewer is neither launched nor called headlessly. The remaining
reviewer must approve; all other loop behavior is the same.

### Key differences from Codex-led mode

| Aspect | Codex-led (`tincan warp`) | Poolside-led (`tincan warp --poolside`) |
|---|---|---|
| Layout | 2 panes (Codex, Claude) | 3 panes (Poolside, Codex, Claude) |
| Implementation agent | Codex | Poolside |
| Review chain | Codex → Claude → Codex | Poolside → Codex → Claude → Poolside |
| Post-approval | Codex summarizes | Poolside summarizes; panes rearm |
| Hook routing | Claude verdict → Codex pane | Claude verdict → Poolside pane |

## Current scope

Tincan currently targets Warp on macOS and uses Warp Tab Configs for two- or
three-pane layouts. A future council mode may generalize the same session transport to several
read-only perspectives feeding one lead agent, but that is intentionally outside
the current implementation.
