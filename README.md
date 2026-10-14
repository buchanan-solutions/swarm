# Swarm

**A tiny Git worktree orchestrator for running a swarm of coding agents without them stepping on each other's toes.**

Swarm gives each unit of work its own Git branch and worktree, gives coding agents a small, constrained development lifecycle, and leaves integration under human control.

No daemon. No database. No scheduler. No replacement for Git.

Just Git worktrees with some opinions.

## Quickstart

Add the **directory containing the executable** to your Bash PATH (adjust the checkout path):

```bash
export PATH="/home/alex/git/bs/swarm:$PATH"
```

For future terminals, add that export line to `~/.bashrc`, or use the managed installer:

```bash
/home/alex/git/bs/swarm/swarm install --path
source ~/.bashrc
command -v swarm
```

Initialize one workspace, then explicitly register repos anywhere beneath it:

```bash
cd ~/git
swarm init
swarm add clients/project/services/api  # normal shell Tab completion works

cd clients/project/services/api
swarm add .                            # safely reports Already registered
swarm create task-123                   # infers this registered repo
swarm list                             # this repo's Swarm worktrees
swarm list --all                        # all registered repos
swarm status                           # workspace health and all linked worktrees
swarm status --sizes                    # measure/cache disk usage, including node_modules
```

`swarm init` and `swarm add` are idempotent. Initialization enrolls no repos automatically.
A repo selector is its registered path relative to the folder containing `swarm.json`, not its remote name.
Submodules can be registered separately; linked worktrees cannot be initialized or registered.
There is no reinstall after editing or updating the source checkout on PATH.

## Why?

Coding agents are very good at working independently.

They are considerably less good at sharing the same working directory.

Swarm makes parallel development boring:

```text
main
 │
 ├── worktree / task-123 ── Agent A
 ├── worktree / task-124 ── Agent B
 ├── worktree / task-125 ── Agent C
 │
 └── human review + integration
```

Each work item gets an isolated filesystem, branch, dependencies, build state, and Git history.

Agents work independently. Git handles history. Swarm handles the workspace lifecycle.

## Install

Clone Swarm and put the executable on your `PATH`.

Then, from the workspace folder containing the repos you want to use with Swarm:

```bash
swarm install
```

Install agent skills into the **current directory**, independently of the Swarm root:

```bash
cd services/ts-mono
swarm install --cursor --claude --codex
```

Or select a target relative to your current directory:

```bash
swarm install services/ts-mono --cursor
swarm install ../other-repo --claude --codex
```

Destinations are `.cursor/skills/swarm/`, `.claude/skills/swarm/`, and
`.agents/skills/swarm/` (Codex). The target directory must already exist.
Skill flags do not initialize a workspace or update ancestor workspace files.
If a matching skill exists in a parent directory, Swarm shows its path and asks
whether to install another copy at the target. Use `--yes` to accept that prompt
in scripts; existing skills at the destination are always preserved.

Without skill flags, `swarm install` still configures the discovered workspace.

If Swarm cannot find an existing workspace, it will offer to initialize the current directory:

```text
No Swarm workspace found.

Configure /home/me/code/project as a new Swarm root? [Y/n]:
```

Installation is idempotent. Existing workspace configuration and installed skills are left alone.
To refresh a customized local skill, back up or rename its `SKILL.md` first, then
rerun the appropriate install command.

## Workspace

A Swarm workspace is intentionally small:

```text
project/
├── swarm.json
├── swarm.md
├── .swarm/
└── ...
```

### `swarm.json`

Machine-readable workspace topology:

```json
{
  "version": 2,
  "repos": []
}
```

Repositories can live at any depth beneath the workspace, including initialized submodules.
Register them with `swarm add <path>` from anywhere under the workspace. The argument
is relative to your current directory; config entries are normalized relative to the folder containing `swarm.json`.
For example, `"repos": ["clients/project/services/api", "other/api"]`.
Paths outside the workspace, paths containing `__`, and newline/tab characters are rejected.
New worktrees live under `.swarm/worktrees/`: `.swarm/worktrees/clients/project/services/api__task-123`.
State always lives in `.swarm/` beside `swarm.json`; the managed ignore block ignores
that directory without a broad double-underscore pattern.
Use the full registered path in workspace-level commands:

```bash
swarm create clients/project/services/api task-123
swarm check clients/project/services/api__task-123
```

Inside that repo, `swarm create task-123` infers the repo. An unregistered nested
Git repo does not inherit its parent's registration. From a Swarm worktree, the
basename ID (`api__task-123`) also resolves in the current repo's context.

### Migrating an existing version 1 workspace

Version 1 configs remain supported until explicitly migrated:

```bash
swarm migrate --dry-run
swarm migrate
swarm status
```

Migration prepends the old `repos_dir` to registrations, removes `repos_dir` and
`state_dir`, and sets `version` to 2. For example, `"repos_dir": "services"` with
`"repos": ["ts-mono"]` becomes `"repos": ["services/ts-mono"]`.
`swarm.md` is preserved unchanged; update its path examples when convenient.

Existing sibling worktrees stay in place and remain usable for check, sync,
submit, review, integrate, and removal. Creating the same work ID reuses its
existing checkout; new work IDs use `.swarm/worktrees/`. Duplicate registered
checkouts for the same identity, or missing checkouts with live metadata, produce
an error instead of silently creating another checkout.

Active submissions are copied to their version 2 identities. Original config and
submission snapshots are retained in `.swarm/migration-v1/`. Custom old state
directories are retained. Swarm's managed ignore block contains only `.swarm/`;
no legacy checkout or custom-state ignore entries are retained. User-owned rules
outside the managed block are preserved. Repeating migration is safe. Legacy repo selectors
such as `ts-mono__1234` remain accepted after migration when unambiguous.

### `swarm.md`

Optional workspace-specific instructions for agents.

Use it for things like:

* work-management or MCP tooling
* repository-specific conventions
* specification/documentation workflows
* local build and test constraints

Machine configuration belongs in `swarm.json`. Universal Swarm behavior belongs in the Swarm skill. Project-specific instructions belong in `swarm.md`.

## Workflow

The lifecycle is deliberately small:

```text
CREATE → WORK → CHECK → SUBMIT → REVIEW → INTEGRATE → REMOVE
  agent                agent       │          human
                                   └────────── human
```

A work item normally maps to:

```text
one work ID
one branch
one worktree
one submission
one merge into trunk
```

For example:

```bash
swarm create ts-mono 2680
```

might create:

```text
ts-mono/                          canonical checkout
.swarm/worktrees/ts-mono__2680/    isolated agent worktree
```

on:

```text
task/2680
```

The agent works entirely inside its worktree.

When finished:

```bash
swarm check ts-mono__2680
swarm submit ts-mono__2680
```

The trunk manager can then:

```bash
swarm review ts-mono__2680
swarm integrate ts-mono__2680
swarm remove ts-mono__2680 --confirm -d
```

Integration uses normal Git ancestry and a `--no-ff` merge commit. Swarm does not require routine rebasing.

If trunk changes create a real conflict, the feature worktree can explicitly synchronize:

```bash
swarm sync ts-mono__2680
```

Resolve once, test, and resubmit.

Being behind trunk is not, by itself, a problem.

## Commands

```text
swarm init
swarm add <path>
swarm migrate [--dry-run]
swarm install [directory] [--path] [--cursor] [--claude] [--codex] [--yes]
swarm config

swarm create <repo> <work-id> [branch] [--from <ref>] [--track <remote-branch>]
swarm list [--all]
swarm status [repo-path] [--sizes | --refresh-sizes]
swarm check <worktree>
swarm sync <worktree>
swarm submit <worktree>

swarm review <worktree>
swarm integrate <worktree>
swarm remove <worktree> --confirm [-d]

swarm --version
swarm --help
```

Agents normally use:

```text
create
list
check
sync
submit
```

Humans own:

```text
review
integrate
remove
```

## Submissions

Swarm does not have a database or merge queue.

A submission simply means:

> This worktree is ready for trunk-manager attention.

Swarm records that declaration as ephemeral local state under `.swarm/`.

Everything else remains Git state.

```text
worktree + no submission    ACTIVE
worktree + submission       SUBMITTED
worktree removed            done
```

Review and integration are always evaluated against the **current** trunk.

## Agent context

Agents can get the complete workspace context with:

```bash
swarm config
```

Swarm discovers the nearest `swarm.json` by walking upward from the current directory and prints:

1. the resolved Swarm root
2. the workspace configuration
3. the workspace's `swarm.md` instructions

This means agents do not need to guess paths or independently discover project configuration.

## Philosophy

Swarm is intentionally not:

* a CI/CD system
* a GitHub replacement
* a task tracker
* an agent framework
* a workflow database
* a merge queue
* a deployment system

Git already knows about branches, commits, ancestry, merges, conflicts, and worktrees.

Swarm tries very hard not to know those things twice.

It adds the small amount of coordination needed to make many simultaneous local development streams manageable:

**isolate the work, constrain the lifecycle, declare when it's ready, and let Git do Git.**

## Development

Want to hack on Swarm itself?

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

The short version:

```bash
git clone <repo>
cd swarm

export PATH="$PWD:$PATH"

swarm --version

mkdir -p test
cd test
swarm init
swarm install --cursor
```

`test/` is a gitignored disposable Swarm workspace, so you can develop the CLI and immediately exercise the code you're editing without installing development copies or modifying your shell profile.

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the contributor workflow.

## License

See `LICENSE`.

## Workspace health and disk usage

Workspace-aware commands warn about every missing or invalid registered repo.
These warnings persist until the registration is corrected; healthy repos remain usable.
Commands requiring an unavailable repo fail with a specific error.

`swarm status` shows all registered repos, linked-worktree counts, canonical and
linked checkouts, branches, Git cleanliness, Swarm state, and health. External
worktrees, missing/prunable worktrees, and orphan submissions are included.
`swarm status <repo-path>` selects one repo; `swarm list` selects the current repo
when possible, and `swarm list --all` always lists the whole workspace.

Normal status does not scan disk usage. `swarm status --sizes` measures allocated
space including ignored dependency/build folders and caches results for 24 hours.
`--refresh-sizes` forces measurement. Cached values include UTC timestamps;
unknown/unreadable sizes do not block the report. Measurements are per directory,
not estimates of reclaimable space. Cache files live under `.swarm/sizes/`.

Runtime requirements: Bash, Git, jq, GNU coreutils, awk, and flock (util-linux).
