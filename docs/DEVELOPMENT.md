# Developing Swarm

Workflow for contributors working on the Swarm CLI itself.

## Clone and run directly

Clone the repository and invoke the source CLI:

```bash
git clone <repo-url>
cd swarm

./swarm --version
./swarm --help
```

`version` and `help` work from any directory. They do not require or discover a `swarm.json`.

## Temporary PATH for development

You do **not** need to install Swarm or modify `.bashrc` / `.zshrc` while developing it.

From the repository root:

```bash
export PATH="$PWD:$PATH"
```

The source checkout itself is then the `swarm` executable:

```bash
swarm --version
swarm --help
```

This PATH change applies only to the current shell session. A new shell restores your normal PATH.

Editing `./swarm` immediately changes what the `swarm` command executes. There is no copy or install step during development.

## Keep the source repo separate from the test workspace

Do **not** initialize the Swarm source repository itself as a Swarm workspace merely to develop or test the CLI.

Use the ignored `test/` child directory instead. That keeps development artifacts such as `swarm.json`, `swarm.md`, `.swarm/`, `.cursor/`, `.claude/`, and temporary repositories out of the public source tree.

## Create the disposable test workspace

From the repository root:

```bash
mkdir -p test
cd test
swarm install --cursor
```

Or without the temporary PATH:

```bash
mkdir -p test
cd test
../swarm install --cursor
```

`test/` is gitignored. A typical layout after install:

```text
test/
├── swarm.json
├── swarm.md
├── .swarm/
└── .cursor/
```

Contributors may freely destroy and recreate this directory. It can also hold temporary repositories and worktrees as needed.

The Swarm source repository itself must **not** need a `swarm.json`.

## Typical development loop

```bash
# terminal starts in cloned Swarm repository

export PATH="$PWD:$PATH"

swarm --version

mkdir -p test
cd test

swarm install --cursor
swarm config
swarm list
```

Then edit the CLI in the source repository and rerun commands from `test/`:

```text
swarm/
├── swarm          ← code being edited
└── test/          ← workspace exercising that exact code
```

No reinstall is required after editing `swarm`.

## Testing workspace discovery

The sandbox is also useful for testing Swarm's upward config discovery:

```bash
cd test
mkdir -p some/deep/directory
cd some/deep/directory

swarm config
```

This should still resolve `test/swarm.json` as the active Swarm configuration.

## Testing skill integrations

Exercise either or both installer integrations:

```bash
swarm install --cursor
swarm install --claude
swarm install --cursor --claude
```

Repeated invocation is useful for verifying installer idempotency.

## Automated CLI verification

```bash
bash -n swarm wp lib/*.sh
python3 tests/workspace.py -v
```

Tests create disposable repositories under the system temp directory, use local
remotes only, and exercise nested registration, submodules, warnings, cached
sizes, and the worktree lifecycle including interactive removal through a PTY.
They also cover v1 migration, custom state directories, active submissions,
legacy sibling checkouts, and centralized v2 worktrees.
