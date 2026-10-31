"""Access preflight/ACL tests: only disposable files under /tmp/swarm are changed.
No test creates users/groups or invokes the elevated allocation command.
"""
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'swarm'
spec = importlib.util.spec_from_file_location('swarm_access', ROOT / 'lib/access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)
ENV = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null',
           GIT_AUTHOR_NAME='Swarm access test', GIT_AUTHOR_EMAIL='test@example.com',
           GIT_COMMITTER_NAME='Swarm access test', GIT_COMMITTER_EMAIL='test@example.com')


class Access(unittest.TestCase):
    def setUp(self):
        Path('/tmp/swarm').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp/swarm', prefix='access-')
        self.root = Path(self.tmp.name)
        access.ACL_API = access.ACL()

    def tearDown(self):
        self.tmp.cleanup()

    def runcli(self, *args, ok=True, cwd=None):
        result = subprocess.run([str(CLI), *args], cwd=cwd or self.root, env=ENV,
                                text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def git(self, path, *args):
        return subprocess.run(['git', '-C', str(path), *args], env=ENV, check=True,
                              text=True, capture_output=True).stdout.strip()

    def fixture(self):
        self.runcli('init')
        repo = self.root / 'repo'
        repo.mkdir()
        self.git(repo, 'init', '-b', 'main')
        (repo / 'hello').write_text('hello\n')
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-m', 'initial')
        self.runcli('add', 'repo', '--name', 'api')
        self.runcli('create', 'api', 'test', '--from', 'HEAD')
        return repo, self.root / '.swarm/worktrees/api___test'

    def test_help_and_unknown_user_without_workspace(self):
        self.assertIn('--owner', self.runcli('access', '--help').stdout)
        result = self.runcli('access', 'api', 'test', '-u', 'swarm-no-such-user-8319', ok=False)
        self.assertIn('user does not exist', result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_dry_run_and_reuse_preview_are_read_only(self):
        repo, wt = self.fixture()
        old = [(p, p.stat().st_mode, p.stat().st_uid, p.stat().st_gid, p.stat().st_mtime_ns)
               for p in (repo, wt, wt / 'hello', repo / '.git/config')]
        group = __import__('grp').getgrgid(os.getgid()).gr_name
        result = self.runcli('access', 'api', 'test', '-u', pwd.getpwuid(os.getuid()).pw_name,
                             '--group', group, '--dry-run')
        self.assertIn('DRY-RUN: no changes made', result.stdout)
        self.assertIn('Existing group:', result.stdout)
        self.assertIn('Parent r-x:', result.stdout)
        self.assertIn(str(repo / '.git/worktrees'), result.stdout)
        for p, mode, uid, gid, mtime in old:
            st = p.stat()
            self.assertEqual((st.st_mode, st.st_uid, st.st_gid, st.st_mtime_ns), (mode, uid, gid, mtime))

    def test_group_and_target_validation(self):
        self.fixture()
        for args in [('api', 'test', '--group', 'bad/group'), ('api', '../escape'), ('api', 'missing')]:
            self.runcli('access', *args, '--dry-run', ok=False)
        if os.getuid() != 0:
            self.assertIn('requires sudo', self.runcli('access', 'api', 'test', ok=False).stderr)

    def test_symlinked_worktree_and_metadata_are_rejected(self):
        repo, wt = self.fixture()
        moved = wt.with_name('moved')
        wt.rename(moved)
        wt.symlink_to(moved, target_is_directory=True)
        self.runcli('access', 'api', 'test', '--dry-run', ok=False)
        wt.unlink()
        moved.rename(wt)
        (repo / '.git/config-link').symlink_to(self.root / 'outside')
        result = self.runcli('access', 'api', 'test', '--dry-run', ok=False)
        self.assertIn('symlink in Git metadata', result.stderr)

    def test_hardlinks_nested_repos_and_alternates_fail_preflight(self):
        repo, wt = self.fixture()
        os.link(wt / 'hello', wt / 'hardlink')
        result = self.runcli('access', 'api', 'test', '--dry-run', ok=False)
        self.assertIn('hard-linked file', result.stderr)
        (wt / 'hardlink').unlink()
        (wt / 'nested/.git').mkdir(parents=True)
        result = self.runcli('access', 'api', 'test', '--dry-run', ok=False)
        self.assertIn('nested Git', result.stderr)
        (wt / 'nested/.git').rmdir()
        (repo / '.git/objects/info/alternates').write_text('/somewhere\n')
        result = self.runcli('access', 'api', 'test', '--dry-run', ok=False)
        self.assertIn('alternates', result.stderr)

    def test_checkout_symlinks_do_not_touch_external_target(self):
        external = self.root / 'external'
        external.write_text('private')
        tree = self.root / 'tree'
        tree.mkdir()
        (tree / 'link').symlink_to(external)
        entries = access.inventory(tree)
        self.assertEqual([e[0] for e in entries], [tree])
        self.assertEqual(external.read_text(), 'private')

    def test_inode_replacement_is_rejected(self):
        file = self.root / 'file'
        file.write_text('before')
        entry = access.inventory(file)[0]
        file.rename(self.root / 'old')
        file.write_text('after')
        with self.assertRaisesRegex(access.AccessError, 'changed after preflight'):
            with access.pinned(entry):
                pass

    def test_acl_mask_preservation_and_named_user_override(self):
        text = 'user::rwx\nuser:60002:r--\ngroup::rwx\ngroup:60003:rwx\nmask::r--\nother::---\n'
        updated = access.parse_acl(access.acl_update(text, 60004, 60002, True, True).replace(',', '\n'))
        self.assertEqual(updated['group:60003'], 'r--')
        self.assertEqual(updated['group:'], 'r--')
        self.assertEqual(updated['user:60002'], 'rwx')
        self.assertEqual(updated['group:60004'], 'rwx')
        self.assertEqual(updated['default:group:60004'], 'rwx')

    def test_real_acl_inheritance_and_parent_no_defaults(self):
        tree = self.root / 'tree'
        tree.mkdir(mode=0o700)
        entry = access.inventory(tree)[0]
        access.apply_entry(entry, os.getgid(), os.getuid(), checkout=True)
        with access.opened(tree) as fd:
            acl = access.parse_acl(access.acl_text(fd))
        self.assertEqual(acl[f'default:group:{os.getgid()}'], 'rwx')
        self.assertTrue(tree.stat().st_mode & 0o2000)
        previous_umask = os.umask(0o077)
        try:
            (tree / 'child').write_text('hello')
        finally:
            os.umask(previous_umask)
        with access.opened(tree / 'child') as fd:
            inherited = access.parse_acl(access.acl_text(fd))
        self.assertEqual(access.bits(inherited[f'group:{os.getgid()}']) & access.bits(inherited['mask:']), 6)
        parent_entry = access.inventory(self.root)[0]
        access.apply_entry(parent_entry, os.getgid(), parent='r-x')
        with access.opened(self.root) as fd:
            self.assertFalse(any(k.startswith('default:') for k in access.parse_acl(access.acl_text(fd))))

    def test_reapplication_preserves_two_groups(self):
        tree = self.root / 'tree'
        tree.mkdir()
        entry = access.inventory(tree)[0]
        access.apply_entry(entry, os.getgid())
        try:
            access.apply_entry(entry, 65534)
        except OSError as exc:
            if exc.errno == 22:
                self.skipTest('sandbox maps only the current GID; a real second group requires host testing')
            raise
        access.apply_entry(entry, os.getgid())
        with access.opened(tree) as fd:
            acl = access.parse_acl(access.acl_text(fd))
        for prefix in ('', 'default:'):
            self.assertEqual(acl[prefix + f'group:{os.getgid()}'], 'rwx')
            self.assertEqual(acl[prefix + 'group:65534'], 'rwx')

    def test_administrator_acl_and_execute_bits_survive(self):
        tree = self.root / 'tree'
        tree.mkdir(mode=0o700)
        script = tree / 'script'
        script.write_text('script')
        script.chmod(0o700)
        for entry in access.inventory(tree):
            access.apply_entry(entry, os.getgid(), os.getuid(), checkout=True,
                               administrator=os.getuid())
        self.assertEqual(script.stat().st_mode & 0o111, 0o110)
        with access.opened(tree) as fd:
            acl = access.parse_acl(access.acl_text(fd))
        self.assertEqual(acl[f'default:user:{os.getuid()}'], 'rwx')

    def test_existing_group_confirmation_precedes_mutations(self):
        self.fixture()
        with mock.patch.object(access.Path, 'cwd', return_value=self.root):
            discovered = access.discover(['api', 'test'], pwd.getpwuid(os.getuid()))
        group = __import__('grp').getgrgid(os.getgid()).gr_name
        with mock.patch.object(access, 'discover', return_value=discovered), \
             mock.patch.object(access, 'actor', return_value=pwd.getpwuid(os.getuid())), \
             mock.patch.object(access.os, 'geteuid', return_value=0), \
             mock.patch.object(access, 'apply_entry') as mutation, \
             mock.patch.object(access.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(access.AccessError, 'confirmation or --yes'):
                access.main(['api', 'test', '--group', group])
            mutation.assert_not_called()
            access.main(['api', 'test', '--group', group, '--yes'])
            self.assertTrue(mutation.called)

    def test_partial_failure_is_reported_and_stops(self):
        self.fixture()
        with mock.patch.object(access.Path, 'cwd', return_value=self.root):
            discovered = access.discover(['api', 'test'], pwd.getpwuid(os.getuid()))
        group = __import__('grp').getgrgid(os.getgid()).gr_name
        with mock.patch.object(access, 'discover', return_value=discovered), \
             mock.patch.object(access, 'actor', return_value=pwd.getpwuid(os.getuid())), \
             mock.patch.object(access.os, 'geteuid', return_value=0), \
             mock.patch.object(access, 'apply_entry', side_effect=OSError('simulated failure')) as mutation:
            with self.assertRaisesRegex(access.AccessError, 'partial allocation stopped'):
                access.main(['api', 'test', '--group', group, '--yes'])
            self.assertEqual(mutation.call_count, 1)

    def test_submodule_backed_git_discovery(self):
        parent, _ = self.fixture()
        source = self.root / 'module-source'
        source.mkdir()
        self.git(source, 'init', '-b', 'main')
        (source / 'hello').write_text('hello')
        self.git(source, 'add', '.')
        self.git(source, 'commit', '-m', 'initial')
        self.git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', source.as_uri(), 'module')
        self.git(parent, 'commit', '-am', 'module')
        self.runcli('add', 'repo/module', '--name', 'module')
        self.runcli('create', 'module', 'test', '--from', 'HEAD')
        result = self.runcli('access', 'module', 'test', '--dry-run')
        self.assertIn(str(parent / '.git/modules/module'), result.stdout)


if __name__ == '__main__':
    unittest.main()
