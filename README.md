# Swarm

**A tiny Git worktree orchestrator for running a swarm of coding agents without them stepping on each other's toes.**

Swarm gives each unit of work its own Git branch and worktree, gives coding agents a small, constrained development lifecycle, and leaves integration under human control.

No daemon. No database. No scheduler. No replacement for Git.

Just Git worktrees with some opinions.

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

Then, from the project you want to use with Swarm:

```bash
swarm install
```

For Cursor:

```bash
swarm install --cursor
```

For Claude:

```bash
swarm install --claude
```

Or both:

```bash
swarm install --cursor --claude
```

If Swarm cannot find an existing workspace, it will offer to initialize the current directory:

```text
No Swarm workspace found.

Configure /home/me/code/project as a new Swarm root? [Y/n]:
```

Installation is idempotent. Existing workspace configuration and installed skills are left alone.

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
  "version": 1,
  "repos_dir": ".",
  "state_dir": ".swarm",
  "repos": []
}
```

Repositories can live directly beneath the workspace or under a configured directory such as `services/`.

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
ts-mono/          canonical checkout
ts-mono__2680/    isolated agent worktree
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
swarm remove ts-mono__2680 -d
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
swarm install [--cursor] [--claude]
swarm config

swarm create <repo> <work-id> [branch] [--from <ref>] [--track <remote-branch>]
swarm list
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
swarm install --cursor
```

`test/` is a gitignored disposable Swarm workspace, so you can develop the CLI and immediately exercise the code you're editing without installing development copies or modifying your shell profile.

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the contributor workflow.

## License

See `LICENSE`.
