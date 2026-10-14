# Installation

Swarm is currently distributed directly from its Git repository.

Installation is intentionally simple:

1. Clone the repository.
2. Add the Swarm executable to your `PATH`.
3. Run `swarm init` in a parent workspace, then `swarm add <path>` for each repo, choosing a unique name when prompted.

## Clone Swarm

Clone the repository somewhere you intend to keep it:

```bash
mkdir -p ~/git
cd ~/git

git clone <SWARM_REPOSITORY_URL> swarm
```

Swarm runs directly from this checkout. There is currently no separate package or binary installation.

Verify it:

```bash
~/git/swarm/swarm --version
```

## Add Swarm to your PATH

Swarm can configure your Bash `PATH` for you:

```bash
cd ~/git/swarm
./swarm install --path
```

Swarm determines the absolute location of its executable and offers to add it to `~/.bashrc`:

```text
Swarm is not currently on your PATH.

Add Swarm to ~/.bashrc? [Y/n]:
```

If accepted, Swarm creates a managed block:

```bash
# <-- swarm:start -->
export PATH="/home/me/git/swarm:$PATH"
# <-- swarm:end -->
```

Swarm owns only the contents between these markers.

After installation:

```bash
source ~/.bashrc
```

Then verify:

```bash
swarm --version
```

## Idempotent PATH configuration

PATH installation is safe to run repeatedly:

```bash
./swarm install --path
```

If the managed Swarm block already points to the current checkout, nothing changes.

If Swarm has moved—for example:

```text
/home/me/git/swarm
```

became:

```text
/home/me/tools/swarm
```

running:

```bash
/home/me/tools/swarm/swarm install --path
```

updates the existing managed block rather than adding another PATH entry.

There should be at most one Swarm-managed block in `.bashrc`.

Swarm must not modify anything outside:

```bash
# <-- swarm:start -->
...
# <-- swarm:end -->
```

If only one marker exists, the block is malformed, or Swarm cannot safely identify its managed section, installation should fail with a clear message rather than rewriting `.bashrc`.

Swarm should never overwrite `.bashrc`.

## Initialize a workspace and register repos

```bash
cd ~/git
swarm init
swarm add clients/project/services/api
# Or from the checkout itself:
cd clients/project/services/api
swarm add .
swarm create task-123
```

`swarm init` creates an empty `swarm.json`, optional instructions in `swarm.md`,
and ignored runtime state in `.swarm`. New worktrees live under `.swarm/worktrees/`.
The initial config is `{"version": 2, "default_ide": "", "repos": {}}`. Repeating initialization preserves config.
Registration resolves the argument relative to your current directory and records
its normalized path relative to the folder containing `swarm.json`. Standard Bash directory completion works.
Registration prompts `What do you want to name this repo? [api]`; Enter accepts
the target folder name. Duplicate or invalid names prompt again. Scripts use
`swarm add <path> --name api`. Re-adding a registered checkout reports its existing
name without prompting; the same checkout cannot have multiple names.
Only explicitly registered repos are managed. Submodules are supported; linked
worktrees are rejected with their main checkout path.

`swarm install` still discovers the nearest ancestor workspace and offers to
initialize the current directory if none exists. `swarm init` explicitly initializes
the current directory, without that interactive offer.

## Install skills in the directory your agent opens

Skill installation targets the current directory, or an explicit directory
relative to it. It does not initialize a workspace, change the ancestor config,
or update that workspace's `swarm.md` or managed ignore block.

```bash
cd ~/git/my-project
swarm install --cursor
swarm install --claude
swarm install --codex
# All three:
swarm install --cursor --claude --codex
# From a parent directory:
swarm install services/ts-mono --cursor
```

Destinations beneath the target:

- Cursor: `.cursor/skills/swarm/SKILL.md`
- Claude: `.claude/skills/swarm/SKILL.md`
- Codex: `.agents/skills/swarm/SKILL.md`

Codex's repository skill directory follows the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

If the same skill is found in a parent directory, installation prints that path
and asks `Install the <agent> skill here too? [y/N]:`. A no answer skips that copy.
Noninteractive installation fails when confirmation is needed unless `--yes`
is supplied:

```bash
swarm install services/ts-mono --cursor --codex --yes
```

Existing local `SKILL.md` files are never overwritten, including with `--yes`.
To refresh one, rename or back it up, then rerun installation. Install directly
inside a generated worktree if that is the folder your agent opens; copies in
the parent workspace do not replace local copies.

`swarm install --path` remains Bash PATH setup only. A bare `swarm install`
retains the existing workspace discovery and interactive initialization behavior.

## First-time setup

A typical first installation is therefore:

```bash
# Clone Swarm
cd ~/git
git clone <SWARM_REPOSITORY_URL> swarm

# Register the CLI on PATH
cd swarm
./swarm install --path

# Reload Bash
source ~/.bashrc

# Verify
swarm --version

# Initialize a workspace and enroll a repo
cd ~/git
swarm init
swarm add my-project
cd my-project
swarm install --cursor
```

After that, Swarm is available normally:

```bash
swarm config
swarm list
swarm create <repo-name> <work-ID>
```

## Updating Swarm

Because Swarm runs directly from the cloned repository, updating it is simply:

```bash
cd ~/git/swarm
git pull
```

No reinstall is necessary when the checkout remains in the same location.

If the repository is moved, rerun:

```bash
./swarm install --path
```

to update the managed Bash configuration.

## Development

Contributing to Swarm itself is slightly different: contributors can temporarily add their checkout to `PATH` without modifying their shell configuration.

See `docs/DEVELOPMENT.md`.

## Upgrade version 1 or early version 2 configs

Run from anywhere beneath the workspace:

```bash
swarm migrate --dry-run
swarm migrate
swarm status
```

Both old versions have a `repos` array. Migration keeps schema version 2 but replaces
that array with a unique-name-to-path object. Each registered repo is displayed with
its resolved path and a naming prompt; Enter accepts the folder name. Collisions and
invalid names prompt again. Cancellation leaves config and submissions unchanged.
`swarm migrate --yes` accepts valid unique defaults in scripts; duplicate defaults
require an interactive run. Dry-run previews defaults and conflicts without changes.

V1's `repos_dir` is folded into workspace-relative paths and both old directory
properties are removed. `default_ide` is initialized to an empty string if absent.
Original config, chosen naming plan, and submission snapshots are backed up in
`.swarm/migration/`. Active markers adopt `<repo-name>___<work-ID>` identities;
old custom state directories and project-owned `swarm.md` are preserved.

Existing worktrees remain where they are; Swarm finds them through Git and the
migration snapshot. Creating the same repo/work pair reuses its existing checkout.
New checkouts use `.swarm/worktrees/<repo-name>___<work-ID>`. Migration can safely
resume after interruption. Old path-based command aliases are not retained.

The managed ignore block contains only `.swarm/`. No broad `*__*/` rule or legacy
checkout exceptions are retained. User-owned rules outside that block are preserved.
Review your project-specific naming examples in `swarm.md` after migration.

## Navigation and launch defaults

```bash
swarm path ts-mono
swarm path ts-mono 1234
cd "$(swarm path ts-mono 1234)"
swarm open ts-mono 1234 --cursor
```

Inside the registered repo or one of its managed worktrees, omit the repo name:

```bash
swarm open 1234 --cursor
```

Set `"default_ide": "cursor"` in `swarm.json` to omit the flag as well. Supported
values are `""`, `"cursor"`, `"claude"`, and `"codex"`; an omitted property also
means no default. If no default or flag is selected, `open` fails with instructions
to choose one. Explicit flags override the default. Multiple flags and unavailable
executables are errors; no launcher fallback or VS Code support is included.

Cursor opens a new window; Claude runs in the selected directory in the foreground;
Codex uses its working-directory option. Install those tools separately on PATH.
Opening does not install skills, change permissions, or create background agents.

## Refresh existing skill copies

CLI updates take effect immediately, but installed skill copies are preserved.
Back up the relevant local file, then reinstall it:

```bash
mv .cursor/skills/swarm/SKILL.md .cursor/swarm-SKILL.md.backup
swarm install --cursor
```

For Claude use `.claude` and `--claude`; for Codex use `.agents` and `--codex`.
Compare the backup and reapply any custom guidance. Parent duplicates still prompt;
`--yes` accepts duplication but never overwrites an existing local skill.
