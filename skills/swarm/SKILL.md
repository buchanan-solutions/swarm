---
name: swarm
description: >-
  Manage parallel development work using Swarm worktrees, submissions, review,
  and integration. Bootstrap with `swarm config`.
---

# Swarm

Use this skill whenever work may occur concurrently with another developer or
agent in the same component repository.

## Bootstrap

When beginning work in a Swarm workspace, run:

```bash
swarm config
```

Use its resolved Swarm configuration and workspace instructions as
authoritative. Do not independently infer workspace paths or duplicate
configuration discovery.

`swarm config` walks up from `$PWD` to the nearest `swarm.json` (same
resolution as every other Swarm command). Optional `<SWARM_ROOT>/swarm.md`
holds workspace-specific instructions only.

```text
SKILL.md     universal Swarm protocol (this file)
swarm.json   workspace topology (machine-readable)
swarm.md     optional workspace-specific instructions
```

**CLI hygiene:** Prefer read-only commands (`config`, `list`, `status`, `check`,
`review`). For writes (`create`, `sync`, `submit`, `integrate`), pass
`--dry-run` first unless the user explicitly asked you to apply the change.
`remove` requires `--confirm` and interactive `Y` (optional `-d` for
`git branch -d` only).

## Repo registration and context

A workspace is initialized with `swarm init` (version 2); repos are explicitly enrolled with
`swarm add <path>` (or `swarm add .` at a checkout root). Registration paths are
relative to the directory containing `swarm.json` and may be deeply nested. Submodules are separate repos;
linked worktrees must not be registered as canonical repos.

Use `swarm config` to see the inferred current repo. `swarm create <work-id>`
works inside a registered repo; explicit `swarm create <repo-path> <work-id>`
works anywhere beneath the workspace. Nested worktree IDs include the registered
path, e.g. `clients/api__123`. New worktrees live under `<SWARM_ROOT>/.swarm/worktrees/`; existing legacy sibling
worktrees remain usable. State is fixed at `<SWARM_ROOT>/.swarm/`.
`swarm list` selects the current repo; `swarm list --all` and `swarm status` show
the workspace. Missing registrations produce warnings without blocking healthy
repos. `status --sizes` scans disk usage; normal status uses cached values only.

Version 1 workspaces require an explicit `swarm migrate` to convert paths and
submission identities. Do not move existing worktrees or rewrite project-specific
`swarm.md` instructions as part of normal agent work.

## Principle

The canonical repository checkout is **not** an agent development workspace.
**You own only your worktree.** The human integrator owns the canonical trunk,
integration, and cleanup.

```text
Agents:   create · list · check · sync · submit
Human:    list · review · integrate · remove
```

Parallel work occurs in Git worktrees managed by `swarm`.

One unit of work maps to:

- one branch
- one worktree (`<SWARM_ROOT>/.swarm/worktrees/<repo-path>__<work-id>/`)
- optionally one **submission marker** (`<SWARM_ROOT>/.swarm/submissions/<repo-path>__<work-id>`)

Worktrees are ephemeral. Branches exist only for the lifetime of active work.

## Naming

Preferred worktree naming:

    <SWARM_ROOT>/.swarm/worktrees/<repo-path>__<ticket-id>

Examples (registered repo paths include `services/`):

    .swarm/worktrees/services/ts-mono__2680
    .swarm/worktrees/services/gds__2711

Ticket IDs are strongly preferred but not mandatory. When no ticket exists,
use a short stable work identifier:

    .swarm/worktrees/services/ts-mono__billing-cleanup

Never create arbitrary alternate worktree directory structures.

## Starting Work

Do not develop in the canonical checkout when parallel work is expected.

    swarm create <repo> <work-id> [branch] [--from <ref>] [--track <remote-branch>]

`branch` is the new local branch for the worktree (default `task/<work-id>`).
`--from` is an optional starting ref (local branch, remote-tracking branch,
tag, or commit; default canonical trunk). `--track` starts from a remote
branch and also sets it as the local branch's upstream (`--track` implies
`--from` when `--from` is omitted). Both apply only when creating the branch;
once it exists, Swarm tracks the local branch normally and does not manage
remote fetch/rebase/push for you.

Examples:

    swarm create services/ts-mono 2676
    swarm create services/ts-mono 2676 --from origin/fuzzy-search
    swarm create services/ts-mono 2676 --track origin/fuzzy-search
    swarm create services/ts-mono 2676 task/2676-fuzzy --track origin/fuzzy-search

If the worktree already exists, reuse it. Do not create another branch or
worktree for the same unit of work.

## During Work

Commit freely on the assigned feature branch. Feature-branch history is
disposable implementation history until integrated with `--no-ff`.

- Do not modify another worktree.
- Do not change the orchestrator’s tracked submodule pointer.
- Do not force-push under normal operation.
- Do not rebase merely because the branch is behind main.

Use:

    swarm check <repo__work-id>

to see dirty/conflict/submit readiness against **current trunk**.

## Synchronizing Trunk

Being behind trunk is not itself a problem.

If mergeability is still clean, continue without syncing.

When sync is required (especially after `check`/`review` reports CONFLICT):

    swarm sync <repo__work-id>

This merges the integration base into the feature branch and **clears** any
submission marker. Resolve conflicts, test, commit, then submit again.

Do not routinely rebase.

## Submitting (inbox, not a queue)

When the unit of work is ready for the human integrator:

    swarm submit <repo__work-id>

Requires a clean worktree and clean mergeability vs current canonical trunk.
This only `touch`es `<SWARM_ROOT>/.swarm/submissions/<repo-path>__<work-id>` (usually
`.swarm/submissions/…`).

Do **not** open a PR as the primary integration path for swarm work unless the
human asks. The human reviews and integrates locally from the submission inbox.

After submit, stop modifying that worktree unless asked to sync/fix conflicts.

## NEVER RUN (agents)

```text
swarm integrate …
swarm remove …
```

Only the human trunk manager integrates into the canonical checkout and removes
worktrees/branches. `integrate` uses `git merge --no-ff` (ancestry preserved).
`remove` requires `--confirm` and an interactive `Y`; optional `-d` runs
`git branch -d` only (never `-D` / `--force`).

## Completion lifecycle

```text
create → work → commit → check → submit
                              ↓
                     human: review → integrate → remove
```

If the human integrates something else first and your submission later shows
CONFLICT on review, they will hand it back. Then:

    swarm sync <repo__work-id>
    # resolve, commit
    swarm submit <repo__work-id>

## Safety Invariants

Never:

- work on another agent's branch without explicit instruction
- run `integrate` or `remove`
- delete an unmerged worktree or branch
- force-push as routine synchronization
- rebase merely to catch up with main
- use the canonical checkout as an ephemeral agent workspace
- modify the orchestrator’s tracked submodule revision as a side effect

When state is ambiguous, stop before destructive Git operations.
