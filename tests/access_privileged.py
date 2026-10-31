#!/usr/bin/env python3
"""Manual host acceptance test; requires a pre-created disposable user.

Run as the normal administrator:
  sudo python3 tests/access_privileged.py --owner swarm-access-test
Creates a private workspace under /tmp/swarm and a dedicated temporary group.
Never creates/deletes users. Leaves test resources for inspection and prints cleanup.
"""
import argparse
import grp
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import sys
import tempfile

CLI = Path(__file__).resolve().parents[1] / 'swarm'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not os.environ.get('SUDO_UID'):
        parser.error('run with sudo from the normal administrator account')
    admin = pwd.getpwuid(int(os.environ['SUDO_UID']))
    owner = pwd.getpwnam(args.owner)
    if not owner.pw_name.startswith('swarm-access-test') or owner.pw_uid in (0, admin.pw_uid):
        parser.error('owner must be a separate disposable user named swarm-access-test...')
    base = Path('/tmp/swarm')
    base.mkdir(exist_ok=True)
    if base.is_symlink() or base.stat().st_uid not in (0, admin.pw_uid):
        parser.error('/tmp/swarm must be a real directory owned by root or the invoking administrator')
    root = Path(tempfile.mkdtemp(prefix='host-access-', dir=base))
    os.chown(root, admin.pw_uid, admin.pw_gid)
    group = f'swarm-test-{root.name.removeprefix("host-access-")}'
    try:
        grp.getgrnam(group)
    except KeyError:
        pass
    else:
        parser.error('generated test group already exists; refusing to reuse it')
    def run(command, user=admin, ok=True, elevated=False, cwd=root):
        role = 'root' if elevated else user.pw_name
        print(f'[{role}] {shlex.join(list(map(str, command)))}', flush=True)
        env = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', HOME=user.pw_dir,
                   GIT_AUTHOR_NAME='Swarm permission test', GIT_AUTHOR_EMAIL='test@example.com',
                   GIT_COMMITTER_NAME='Swarm permission test', GIT_COMMITTER_EMAIL='test@example.com',
                   LC_ALL='C', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(Path(user.pw_dir) / '.gitconfig') if user.pw_uid == owner.pw_uid else '/dev/null')
        identity = {}
        if elevated:
            env['SUDO_UID'] = str(admin.pw_uid)
        else:
            identity = dict(user=user.pw_uid, group=user.pw_gid,
                            extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, **identity,
                                stdin=subprocess.DEVNULL,
                                text=True, capture_output=True, timeout=90)
        if (result.returncode == 0) != ok:
            raise RuntimeError(f'{command}\n{result.stdout}\n{result.stderr}')
        print('  OK' if ok else '  OK (expected rejection)', flush=True)
        return result
    def git(path, *args, user=admin):
        return run(['/usr/bin/git', '-c', f'safe.directory={path}', '-C', path, *args], user=user)
    try:
        print(f'Test workspace: {root}\nTest group: {group}\nTest user: {owner.pw_name}', flush=True)
        run([CLI, 'init'])
        repo = root / 'repo'
        run(['/usr/bin/mkdir', repo])
        git(repo, 'init', '-b', 'main')
        run(['/usr/bin/python3', '-c', 'from pathlib import Path; Path("repo/hello").write_text("hello\\n")'])
        git(repo, 'add', '.')
        git(repo, 'commit', '-m', 'initial')
        run([CLI, 'add', 'repo', '--name', 'api'])
        run([CLI, 'create', 'api', 'test', '--from', 'HEAD'])
        run([CLI, 'create', 'api', 'sibling', '--from', 'HEAD'])
        wt = root / '.swarm/worktrees/api___test'
        sibling = root / '.swarm/worktrees/api___sibling'
        gitdir = repo / '.git'
        git_owner_before = gitdir.stat().st_uid
        outside_before = {p: run(['/usr/bin/getfacl', '-cpn', p], elevated=True).stdout
                          for p in (Path('/tmp'), base)}
        # Reproduce a restrictive named-user ACL overriding group access.
        run(['/usr/bin/setfacl', '-m', f'u:{owner.pw_uid}:r-x', root], elevated=True)
        run(['/usr/bin/setfacl', '-m', f'u:{owner.pw_uid}:r--', gitdir / 'config'], elevated=True)
        command = [CLI, 'access', 'api', 'test', '-u', owner.pw_name, '--group', group]
        preview = run([*command, '--dry-run'], elevated=True)
        assert 'DRY-RUN' in preview.stdout
        unknown = run([CLI, 'access', 'api', 'test', '-u', 'swarm-user-does-not-exist-8319',
                       '--group', group], elevated=True, ok=False)
        assert 'user does not exist' in unknown.stderr
        run(command, elevated=True)
        assert wt.stat().st_uid == owner.pw_uid
        assert (wt / 'hello').stat().st_uid == owner.pw_uid
        assert gitdir.stat().st_uid == git_owner_before
        assert sibling.stat().st_uid == admin.pw_uid
        denied = run(command, elevated=True, ok=False)
        assert 'confirmation or --yes' in denied.stderr
        run([*command, '--yes'], elevated=True)
        # Emulate an installer under a restrictive umask, including chmod and rename.
        run(['/usr/bin/python3', '-I', '-c', '''import os,pathlib
os.umask(0o077)
p=pathlib.Path('node_modules/.bin');p.mkdir(parents=True)
f=p/'tool';f.write_text('test');f.chmod(0o755);f.rename(p/'renamed')
p=pathlib.Path('.venv/bin');p.mkdir(parents=True)
(p/'placeholder').write_text('test')
'''], user=owner, cwd=wt)
        assert (wt / 'node_modules').stat().st_gid == grp.getgrnam(group).gr_gid
        run(['/usr/bin/python3', '-I', '-c', "from pathlib import Path; Path('hello').write_text('alia commit\\n')"], user=owner, cwd=wt)
        # Do not override safe.directory here: test the actual user's trust config.
        run(['/usr/bin/git', '-C', wt, 'add', 'hello'], user=owner)
        run(['/usr/bin/git', '-C', wt, 'commit', '-m', 'test user commit'], user=owner)
        run(['/usr/bin/python3', '-I', '-c', "from pathlib import Path; Path('hello').write_text('admin sibling commit\\n')"], cwd=sibling)
        git(sibling, 'add', 'hello')
        git(sibling, 'commit', '-m', 'admin sibling commit')
        # Admin can still inspect and edit dependencies in the transferred checkout.
        run(['/usr/bin/python3', '-I', '-c', "from pathlib import Path; Path('.venv/bin/placeholder').write_text('admin write')"], cwd=wt)
        for p, before in outside_before.items():
            assert run(['/usr/bin/getfacl', '-cpn', p], elevated=True).stdout == before, f'changed system ancestor ACL: {p}'
        print('PASS: ownership, parent navigation, inheritance, user/admin commits, confirmation, retry and shared Git owner preservation.')
    finally:
        print('\nResources retained for inspection. After testing, cleanup:')
        print(f'sudo rm -rf -- {shlex.quote(str(root))}')
        print(f'sudo groupdel {shlex.quote(group)}')
        print(f'sudo userdel --remove {shlex.quote(owner.pw_name)}')


if __name__ == '__main__':
    main()
