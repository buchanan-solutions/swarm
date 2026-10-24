# Swarm

A tiny Git worktree orchestrator for parallel coding agents, with human review and integration.

Each task gets its own checkout and branch. Swarm names repos, locates worktrees,
tracks local submissions, and opens your editor or CLI agent. Git owns the branches
and worktree registry. There is no daemon or separate active-worktree database.

## Quickstart

Add the **directory containing the executable** to your Bash PATH:

```bash
export PATH="/home/alex/git/bs/swarm:$PATH"
```

For future terminals, add that line to `~/.bashrc`, or use Swarm's managed installer:

```bash
/home/alex/git/bs/swarm/swarm install --path
source ~/.bashrc
command -v swarm
```

Initialize a parent workspace and register a repo anywhere beneath it:

```bash
cd ~/git
swarm init
swarm add core/deploy/services/ts-mono
# What do you want to name this repo? [ts-mono]
# Press Enter to use the repo folder name:
```

Scripts supply the name explicitly:

```bash
swarm add other/services/ts-mono --name ts-mono-secondary
```

Then work from the canonical repo, any subdirectory of it, or a managed worktree:

```bash
cd core/deploy/services/ts-mono
swarm create 1234 --from HEAD
swarm open 1234 --cursor
```

Or use explicit repo names anywhere beneath the workspace:

```bash
swarm create ts-mono 1234
swarm path ts-mono             # absolute canonical checkout path
swarm path ts-mono 1234        # absolute worktree path
swarm open ts-mono 1234 --cursor
cd "$(swarm path ts-mono 1234)"
```

There is no reinstall after updating the source checkout on PATH.

## Workspace configuration

```json
{
  "version": 2,
  "default_ide": "",
  "repos": {
    "ts-mono": "core/deploy/services/ts-mono",
    "ts-mono-secondary": "other/services/ts-mono",
    "engine": "core/deploy/services/engine"
  }
}
```

The nearest ancestor `swarm.json` selects the workspace. Repo names are unique,
stable identifiers; repo paths are relative to that config. Paths may be deeply
nested, include spaces, or be `"."` for a checkout at the workspace root. Names
cannot contain spaces. Submodules must be enrolled separately. An unregistered
nested Git repo does not inherit its parent's registration.

`swarm add` prompts for a name unless `--name` is supplied. Defaults use the target
folder name, even when adding from another directory. Invalid or duplicate names
prompt again; Swarm never silently adds a numeric suffix. Noninteractive registration
requires `--name`. Re-adding a checkout reports its existing name without prompting;
registering the same physical checkout under another name is rejected.

Names and work IDs start with a letter or digit, followed by letters, digits, dots,
dashes, or underscores. `___` is reserved; repo names cannot end in an underscore.
Paths outside the workspace and inside `.swarm` are rejected. Linked worktrees cannot
be registered or initialized as canonical repos; Swarm prints their main checkout path.

Initialization does not enroll repos automatically. Repeating `init` preserves config.
Changing a repo name with active work is unsupported; no rename command is included.

Local state has fixed locations:

```text
workspace/
├── swarm.json
├── swarm.md
├── core/deploy/services/ts-mono/    canonical checkout
└── .swarm/                        ignored local state
    ├── worktrees/ts-mono___1234/   isolated checkout
    ├── submissions/ts-mono___1234
    └── sizes/                     disposable disk-usage cache
```

The managed `.gitignore` block ignores only `.swarm/`. No broad underscore patterns
or legacy-path exceptions are installed. Fresh clones recreate runtime directories
as needed; worktrees and submissions are local, not shared through Git.

`swarm.md` holds project-specific instructions: ticket tooling, conventions, build
constraints, and review expectations. Config belongs in `swarm.json`; universal
agent behavior belongs in the bundled skill. Swarm preserves existing `swarm.md`.

## Open an editor or agent

Set `"default_ide": "cursor"`, `"claude"`, or `"codex"` in `swarm.json`, then:

```bash
swarm open ts-mono 1234
# Inside ts-mono or one of its worktrees:
swarm open 1234
```

An explicit flag overrides the default:

```bash
swarm open ts-mono 1234 --cursor   # new Cursor window
swarm open ts-mono 1234 --claude   # foreground Claude session in the checkout
swarm open ts-mono 1234 --codex    # Codex with that working directory
swarm open ts-mono --cursor       # canonical checkout
```

The initial default is blank; an omitted property also means blank. Without a
selected launcher, `open` asks you to pass `--cursor`, `--claude`, or `--codex`,
or configure `default_ide`. Unsupported defaults, multiple launcher flags, and
missing executables are errors. There is no fallback launcher or VS Code support.
Opening does not install skills, alter permissions, or start background agents.

On success, `path` emits only an absolute path to stdout, so it composes with shell commands.
On failure, it prints `.` and exits nonzero, keeping `cd $(swarm path …)` in the
current directory. Errors go to stderr. Quote the substitution to support spaces:
`cd "$(swarm path ts-mono 1234)"`.
Warnings go to stderr. `path` alone returns the inferred canonical repo; supplying
a work ID selects its existing worktree. It never creates checkouts.

## Agent skills and installation

Install the shared skill into the directory your agent opens, independently of the
Swarm workspace location:

```bash
swarm install --cursor --claude --codex
swarm install services/ts-mono --cursor
swarm install "$(swarm path ts-mono 1234)" --cursor --codex
```

Destinations are `.cursor/skills/swarm/`, `.claude/skills/swarm/`, and
`.agents/skills/swarm/` (Codex). Parent duplicates prompt; `--yes` accepts duplication
for scripts. Existing local `SKILL.md` files are never overwritten, even with `--yes`.
To refresh one, back it up outside the skill directory, then rerun installation:

```bash
mv .cursor/skills/swarm/SKILL.md .cursor/swarm-SKILL.md.backup
swarm install --cursor
```

Compare the saved copy and reapply custom instructions as needed. Copies in other
repos/worktrees are not updated automatically.

Skill flags do not initialize or modify the ancestor workspace. A bare `swarm install`
retains workspace discovery and interactive initialization; `install --path` is Bash
PATH setup only. See [installation details](docs/INSTALLATION.MD).

## Work lifecycle

```text
create → work → commit → check → submit → review → integrate → remove
  agent                              human integration and cleanup
```

```bash
swarm create ts-mono 1234 --from HEAD
# Edit and commit in the generated checkout.
swarm check ts-mono 1234
swarm submit ts-mono 1234

# Human integrator:
swarm review ts-mono 1234
swarm integrate ts-mono 1234 -m "1234: integrate feature"
swarm remove ts-mono 1234 --confirm -d
```

Integration requires a clean feature worktree and no staged or unstaged tracked
changes in the canonical checkout. Unrelated untracked files may remain; Git
rejects the merge if they would be overwritten. `integrate --dry-run` does not
check untracked-file collisions. A failed merge keeps the submission for retry.

New branches start at the canonical source checkout's current committed `HEAD`,
even when you invoke Swarm from another worktree. Uncommitted edits are not copied.
The default branch name is `task/<work-ID>`; an optional positional branch overrides it.
`--from` overrides the starting ref. `--track` additionally sets the branch upstream.
Repeat creation to reuse an existing worktree for the same repo and work ID.
Branch names may differ from work IDs; worktree identity never depends on the branch.

`sync` merges the configured integration base into the worktree and clears its
submission marker. Commit conflicts, test, and submit again. Integration uses
`--no-ff`, preserving feature ancestry. `swarm remove ts-mono 1234 -d` previews
without changing anything; `--dry-run` explicitly requests the same preview, even
with `--confirm`. The breakdown includes the exact folder, submission marker,
tracked changes, untracked and ignored files, and the branch to delete or keep.
Dirty worktrees are blocked; ignored files are reported because removal deletes them.
Commit safety checks report other local branches and last-fetched remote refs that
preserve the commits, plus commits unique to the target. No fetch is performed.
Deletion eligibility follows Git's upstream (or canonical HEAD) merge check;
commits preserved elsewhere may still require keeping or merging the branch.
Pass `--confirm` to see the breakdown again and answer `y` or `Y` to
`Are you sure you want to do this? [y/N]`. Empty input cancels.
Optional `-d` uses safe `git branch -d`. Force deletion is not supported;
remote branches are never deleted.

All lifecycle commands accept separate repo/work arguments, `ts-mono___1234`,
or an absolute managed-checkout path. Inside a registered checkout, omit the repo
name. A registered repo name takes precedence over shorthand; supply both arguments
if a work ID is also a repo name. Old path-based selectors are no longer accepted.

Agents must not integrate, remove worktrees, force-push routinely, modify another
agent's checkout, or change parent submodule pointers as a side effect.

## Listing and health

```bash
swarm config
swarm list                    # current repo, otherwise all repos
swarm list ts-mono
swarm list --all
swarm status                  # workspace-wide health
swarm status ts-mono --sizes
swarm status --refresh-sizes
```

Tables show repo names, work IDs, branches, checkout paths, Git cleanliness, Swarm
state, and health. Git-registered worktrees outside the naming convention appear
as external, without invented work IDs. Missing/prunable checkouts and orphan
submission markers remain visible. Duplicate managed identities prevent ambiguous
creation, navigation, or modification; stale metadata prevents replacement creation.

`swarm status` reports unavailable canonical repos, scoped to its selected repo or
the whole workspace. Operational commands such as `path`, `list`, and `check` stay
quiet about unrelated unhealthy registrations. Targeting an unavailable repo fails
with a focused error. Malformed configuration remains an error.

Normal status does not scan disk usage. `--sizes` measures allocated space, including
ignored dependencies/builds, and caches it for 24 hours. `--refresh-sizes` forces a scan.
Cached values include UTC timestamps; unknown/unreadable sizes do not block reporting.
Per-directory measurements are not reclaimable-space estimates.

## Migrate existing workspaces

Both version 1 and the earlier version 2 **array** format require explicit migration.
The schema number remains 2; there is no version 3:

```bash
swarm migrate --dry-run        # preview defaults and name conflicts, no changes
swarm migrate                 # prompt for each explicitly registered repo
swarm migrate --yes           # accept unique, valid folder-name defaults
```

Migration gathers all names before changing config or submissions. Enter accepts
each folder-name default; invalid or duplicate names prompt again. Cancellation
preserves config and submissions. Noninteractive migration requires `--yes`;
colliding defaults require an interactive run. Unregistered repos are not enrolled.

Version 1's `repos_dir` is folded into each workspace-relative path, and both old
directory properties are removed. Other config fields and `swarm.md` are preserved.
An absent `default_ide` becomes blank; a valid existing value is preserved.

Config, chosen names, and original submission snapshots live in `.swarm/migration/`.
Active submissions gain the chosen name and `___` identity. Unknown old orphan
markers are retained under `.swarm/submissions/legacy-orphans/`. Custom old state
directories are retained. Safe retry resumes the saved naming plan after interruption.

Existing checkouts are **not moved**. Git plus the static migration mapping lets
Swarm expose historical checkouts through the new interface. Creating the same
repo/work pair reuses its old checkout; new work goes into the flat named layout.
Old double-underscore identities remain an internal migration detail.

Migration updates only Swarm's managed ignore block to `.swarm/`; user-owned rules
outside it remain untouched. Existing legacy worktrees receive no ignore exceptions.
Update path and naming examples in your project-owned `swarm.md` manually if needed.

## Development and requirements

Runtime: Bash, Git, jq, GNU coreutils, awk, and flock (util-linux). Editor/agent launchers
must already be installed on PATH. Automated tests use Python's standard library and
local Git remotes; they do not open real editors or agents.

```bash
bash -n swarm wp lib/*.sh
python3 tests/workspace.py -v
git diff --check
```

Use disposable workspaces, not the source repo itself. The internal `wp` helper is
not a public CLI. See [development instructions](docs/DEVELOPMENT.md).

## License

See [LICENSE](LICENSE).
