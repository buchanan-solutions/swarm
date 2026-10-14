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
`review`, `path`). For writes (`create`, `sync`, `submit`, `integrate`), pass
`--dry-run` first unless the user explicitly asked you to apply the change.
`remove` requires `--confirm` and interactive `Y` (optional `-d` for
`git branch -d` only).

## Repo registration and context

A workspace uses schema version 2, with `repos` mapping unique names to paths
relative to `swarm.json`, and `default_ide` optionally selecting a launcher.
`swarm init` creates an empty mapping and a blank default. Repos are explicitly
enrolled with `swarm add <path>`, which prompts for a unique name; use
`swarm add <path> --name <name>` noninteractively. Enter accepts the target repo
folder name, and duplicate names prompt again. Re-adding a checkout is idempotent.

Paths can be deeply nested or `"."` for the workspace-root checkout. Submodules
are separate repos; linked worktrees must not be registered as canonical repos.
An unregistered nested repo does not inherit its parent's registration.

Use `swarm config` to see the inferred repo name, canonical path, default IDE, and
project-specific instructions. `swarm create <work-ID>` works inside a registered
canonical checkout or managed worktree. Elsewhere use
`swarm create <repo-name> <work-ID>`. Repo names take precedence over shorthand.
Do not infer repo identity from its branch or reconstruct paths yourself.

New worktrees live at `.swarm/worktrees/<repo-name>___<work-ID>`; new submission
markers use the same basename under `.swarm/submissions/`. Both identifiers begin
with a letter or digit and otherwise use letters, digits, dots, dashes, and
underscores. Reserve `___` in identifiers; repo names cannot end in an underscore.

`swarm list [repo-name]` selects the current repo by default; `list --all` and
`swarm status` show the workspace. Git is the worktree source of truth. External
worktrees have no invented work IDs. Missing registrations warn without blocking
healthy repos. Missing/prunable or duplicate managed worktrees need human attention.
Normal status uses cached sizes; `status --sizes` performs disk scans.

Version 1 and early-v2 array configs require explicit `swarm migrate`. It prompts
for names before changing config or submissions. `--dry-run` previews defaults;
`--yes` accepts unique valid defaults. Existing worktrees remain in place and are
resolved through Git and the migration snapshot. Do not move them yourself or
rewrite project-owned `swarm.md` as part of ordinary agent work.

## Navigation and launching

Ask Swarm for locations; never calculate the relative path to its root:

```bash
swarm path ts-mono              # canonical checkout
swarm path ts-mono 1234         # existing worktree
cd "$(swarm path ts-mono 1234)"
```

Inside the repo or a managed worktree, `swarm path <work-ID>` selects that worktree;
`swarm path` alone selects the canonical repo. The command prints only an absolute
path to stdout and does not create worktrees.

With user authorization, open the target via:

```bash
swarm open ts-mono 1234 --cursor
swarm open ts-mono 1234 --claude
swarm open ts-mono 1234 --codex
```

Cursor opens a new window. CLI agents run in the foreground scoped to the checkout.
Omitting the launcher uses `default_ide` (`cursor`, `claude`, or `codex`). Blank or
omitted defaults require an explicit flag; explicit flags override the default.
There is no fallback launcher, automatic permission change, or background spawning.

The shared skill can be installed locally with `swarm install [directory] --cursor`,
`--claude`, or `--codex`. Opening does not install it. Parent duplicates prompt;
`--yes` accepts duplication. Existing local skill files are preserved. Do not replace
customized skills without preserving and reviewing the user's modifications.

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
- one worktree (`<SWARM_ROOT>/.swarm/worktrees/<repo-name>___<work-ID>/`)
- optionally one **submission marker** (`<SWARM_ROOT>/.swarm/submissions/<repo-name>___<work-ID>`)

Worktrees are ephemeral. Branches exist only for the lifetime of active work.

## Naming

Use the registered repo name and a stable work ID, preferably the actual ticket ID:

```text
.swarm/worktrees/ts-mono___2680
.swarm/worktrees/gds___2711
.swarm/worktrees/ts-mono___billing-cleanup
```

Do not invent ticket IDs or alternate checkout layouts. Names are not repo paths.
Reuse existing work for the same repo/work pair. Renaming active repo identities
is unsupported.

## Starting Work

Do not develop in the canonical checkout when parallel work is expected.

    swarm create [repo-name] <work-ID> [branch] [--from <ref>] [--track <remote-branch>]

`branch` is the new local branch for the worktree (default `task/<work-id>`).
`--from` is an optional starting ref (local branch, remote-tracking branch,
tag, or commit; default canonical trunk). `--track` starts from a remote
branch and also sets it as the local branch's upstream (`--track` implies
`--from` when `--from` is omitted). Both apply only when creating the branch;
once it exists, Swarm tracks the local branch normally and does not manage
remote fetch/rebase/push for you.

Examples:

    swarm create ts-mono 2676
    swarm create ts-mono 2676 --from origin/fuzzy-search
    swarm create ts-mono 2676 --track origin/fuzzy-search
    swarm create ts-mono 2676 task/2676-fuzzy --track origin/fuzzy-search

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

    swarm check [repo-name] <work-ID>

to see dirty/conflict/submit readiness against **current trunk**.

## Synchronizing Trunk

Being behind trunk is not itself a problem.

If mergeability is still clean, continue without syncing.

When sync is required (especially after `check`/`review` reports CONFLICT):

    swarm sync [repo-name] <work-ID>

This merges the integration base into the feature branch and **clears** any
submission marker. Resolve conflicts, test, commit, then submit again.

Do not routinely rebase.

## Submitting (inbox, not a queue)

When the unit of work is ready for the human integrator:

    swarm submit [repo-name] <work-ID>

Requires a clean worktree and clean mergeability vs current canonical trunk.
This only `touch`es `<SWARM_ROOT>/.swarm/submissions/<repo-name>___<work-ID>` (usually
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

    swarm sync [repo-name] <work-ID>
    # resolve, commit
    swarm submit [repo-name] <work-ID>

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
