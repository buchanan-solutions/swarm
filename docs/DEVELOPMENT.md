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

Use the ignored `test/` child directory instead. That keeps development artifacts such as `swarm.json`, `swarm.md`, `.swarm/`, `.cursor/`, `.claude/`, `.agents/`, and temporary repositories out of the public source tree.

## Create the disposable test workspace

From the repository root:

```bash
mkdir -p test
cd test
swarm init
swarm install --cursor
```

Or without the temporary PATH:

```bash
mkdir -p test
cd test
../swarm init
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

swarm init
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

Exercise the shared skill installers:

```bash
swarm install --cursor
swarm install --claude
swarm install --cursor --claude --codex
```

Repeated invocation is useful for verifying installer idempotency. Skill flags
install into the current directory, independently of ancestor workspace discovery.
Use an explicit target path and `--yes` when testing intentional parent duplicates.

## Automated CLI verification

```bash
bash -n swarm wp lib/*.sh
python3 tests/workspace.py -v
python3 tests/access.py -v
git diff --check
```

Tests create disposable repositories under the system temp directory and use local
remotes only. PTYs exercise naming prompts, cancellation, parent-skill confirmation,
and interactive removal. Fake launcher executables capture argv and working directory;
tests do not open real editors or agents.

Coverage includes explicit/inferred targets, root checkouts, submodules, external and
missing worktrees, default IDE selection, cached sizes, target-local skills, both old
config shapes, naming collisions, active submissions, custom state, and interrupted
migration retries.

## Final v2 schema and identity

```json
{
  "version": 2,
  "default_ide": "",
  "repos": {"api": "services/api"}
}
```

Repo names are stable identifiers; paths are workspace-relative and may be `"."`.
Use `swarm add services/api --name api` in automated fixtures. New identities are
`api___1234`; new paths are `.swarm/worktrees/api___1234`. Git's registry owns the
active checkout list. `.swarm/migration/` holds static source config, chosen names,
submission snapshots, and a temporary recovery journal, not an activity database.

`lib/repos.sh` shares identity and path rules with the internal `wp` create/sync
helper. The public CLI resolves repo names, context, targets, and launchers. Both
version 1 and early-v2 array fixtures must pass through explicit `swarm migrate`;
normal commands reject those shapes. No version 3 is introduced.

The release checks are Bash syntax, all integration tests, and `git diff --check`.
Keep help, README, installation docs, and the shared agent skill consistent. Project
`swarm.md` and customized installed skills must not be overwritten by upgrades.

## Linux access allocation testing

`tests/access.py` uses disposable files under `/tmp/swarm` and exercises actual ACL
inheritance without creating accounts or applying elevated allocation. A sandbox
with only one mapped GID skips the real second-group check; it needs host testing.

For the privileged acceptance test, have the administrator create a disposable
account first (never use a real collaborator account):

```bash
sudo useradd --create-home --user-group --shell /bin/bash swarm-access-test
sudo python3 tests/access_privileged.py --owner swarm-access-test
```

The test refuses root/the administrator as target and requires a name beginning
with `swarm-access-test`. It creates a workspace and dedicated group under a random
`/tmp/swarm/host-access-*` directory, exercises actual ownership, ACLs, user/admin
commits, confirmation and retries, and checks system-ancestor ACLs were unchanged.
It never creates users or touches real project checkouts. Its installer check
emulates dependency directories, chmod and rename without downloading packages.
It retains its workspace for inspection and prints exact directory/group cleanup
commands and `sudo userdel --remove swarm-access-test` after testing. The disposable
user's Git configuration and group membership are intentionally changed.
