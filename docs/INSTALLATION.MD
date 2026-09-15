# Installation

Swarm is currently distributed directly from its Git repository.

Installation is intentionally simple:

1. Clone the repository.
2. Add the Swarm executable to your `PATH`.
3. Run `swarm install` inside a project to initialize or configure that workspace.

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

## Initialize a project

Once Swarm is available on your PATH, enter the project you want Swarm to manage:

```bash
cd ~/git/my-project
swarm install
```

Swarm searches the current directory and its ancestors for an existing `swarm.json`.

If none exists:

```text
No Swarm workspace found.

Configure /home/me/git/my-project as a new Swarm root? [Y/n]:
```

Accepting creates the initial workspace configuration:

```text
my-project/
├── swarm.json
└── swarm.md
```

A new workspace starts with:

```json
{
  "version": 1,
  "repos_dir": ".",
  "state_dir": ".swarm",
  "repos": []
}
```

`swarm.md` contains optional workspace-specific instructions for coding agents.

Running `swarm install` again discovers and validates the existing workspace. It does not overwrite `swarm.json` or `swarm.md`.

## Cursor

To initialize/configure the workspace and install the Swarm skill for Cursor:

```bash
swarm install --cursor
```

This installs a workspace-owned copy of the Swarm skill under:

```text
.cursor/skills/swarm/
```

Existing installed skill contents are not overwritten.

## Claude

For Claude:

```bash
swarm install --claude
```

The skill is installed under:

```text
.claude/skills/swarm/
```

For both:

```bash
swarm install --cursor --claude
```

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

# Initialize a project
cd ~/git/my-project
swarm install --cursor
```

After that, Swarm is available normally:

```bash
swarm config
swarm list
swarm create <repo> <work-id>
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
