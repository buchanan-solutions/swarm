"""Black-box CLI tests using disposable Git repositories; no network required."""
import json
import os
import pathlib
import pty
import shutil
import subprocess
import tempfile
import unittest

CLI = str(pathlib.Path(__file__).resolve().parents[1] / 'swarm')
ENV = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null',
           GIT_AUTHOR_NAME='Swarm test', GIT_AUTHOR_EMAIL='test@example.com',
           GIT_COMMITTER_NAME='Swarm test', GIT_COMMITTER_EMAIL='test@example.com')

class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='swarm-test-')
        self.root = pathlib.Path(self.tmp.name)
        self.runcli('init')
    def tearDown(self):
        self.tmp.cleanup()
    def cmd(self, args, cwd=None, ok=True):
        result = subprocess.run(args, cwd=cwd or self.root, env=ENV, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result
    def runcli(self, *args, cwd=None, ok=True):
        return self.cmd([CLI, *args], cwd, ok)
    def git(self, path, *args):
        return self.cmd(['git', '-C', str(path), *args])
    def repo(self, relative):
        path = self.root / relative
        path.mkdir(parents=True)
        self.git(path, 'init', '-b', 'main')
        (path / 'hello').write_text('hello\n')
        self.git(path, 'add', '.')
        self.git(path, 'commit', '-m', 'initial')
        self.git(path, 'remote', 'add', 'origin', str(path))
        return path
    def register(self, relative):
        path = self.repo(relative)
        self.runcli('add', '.', cwd=path)
        return path
    def config(self):
        return json.loads((self.root / 'swarm.json').read_text())
    def test_registration(self):
        repo = self.register('a/deep/repo with spaces')
        before = (self.root / 'swarm.json').read_bytes()
        self.assertIn('Already registered', self.runcli('add', 'a/deep/../deep/repo with spaces').stdout)
        self.assertIn('Already initialized', self.runcli('init').stdout)
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        self.assertEqual(self.config()['repos'], ['a/deep/repo with spaces'])
        (repo / 'src').mkdir()
        self.runcli('add', 'src', cwd=repo, ok=False)
        outside = pathlib.Path(tempfile.mkdtemp(prefix='swarm-outside-'))
        try:
            self.git(outside, 'init')
            self.runcli('add', str(outside), ok=False)
        finally:
            shutil.rmtree(outside)
    def test_full_lifecycle(self):
        repo = self.register('a/deep/app')
        self.register('b/app')
        self.runcli('create', 'feature', cwd=repo)
        wt = self.root / '.swarm/worktrees/a/deep/app__feature'
        self.runcli('create', 'b/app', 'feature')
        self.assertTrue(wt.is_dir())
        self.assertIn('a/deep/app', self.runcli('config', cwd=wt).stdout)
        self.assertNotIn('b/app', self.runcli('list', cwd=wt).stdout)
        self.assertIn('b/app', self.runcli('list', '--all', cwd=wt).stdout)
        self.runcli('check', 'a/deep/app__feature')
        self.runcli('sync', str(wt))
        (wt / 'feature').write_text('feature\n')
        self.git(wt, 'add', '.')
        self.git(wt, 'commit', '-m', 'feature')
        self.runcli('submit', 'a/deep/app__feature')
        self.assertTrue((self.root / '.swarm/submissions/a/deep/app__feature').is_file())
        self.runcli('review', 'a/deep/app__feature')
        self.runcli('integrate', 'a/deep/app__feature', '--dry-run')
        self.runcli('integrate', 'a/deep/app__feature')
        self.assertTrue((repo / 'feature').is_file())
        # remove deliberately requires a TTY and a separate typed Y confirmation.
        master, slave = pty.openpty()
        proc = subprocess.Popen([CLI, 'remove', 'a/deep/app__feature', '--confirm', '-d'],
                                cwd=self.root, env=ENV, stdin=slave, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        os.close(slave)
        os.write(master, b'Y\n')
        out, err = proc.communicate(timeout=15)
        os.close(master)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertFalse(wt.exists())
    def test_worktrees_submodules_and_inference(self):
        parent = self.register('parent')
        source = self.repo('source')
        self.git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'nested/sub')
        self.git(parent, 'commit', '-am', 'submodule')
        sub = parent / 'nested/sub'
        self.assertIn('Current repo: none', self.runcli('config', cwd=sub).stdout)
        self.git(sub, 'remote', 'set-url', 'origin', str(source))
        self.runcli('add', '.', cwd=sub)
        self.runcli('create', 'subwork', cwd=sub)
        wt = self.root / '.swarm/worktrees/parent/nested/sub__subwork'
        self.runcli('add', '.', cwd=wt, ok=False)
        err = self.runcli('init', cwd=wt, ok=False).stderr
        self.assertIn(str(sub), err)
        self.runcli('check', 'parent/nested/sub__subwork')
        self.assertIn('CANONICAL', self.runcli('status', 'parent/nested/sub').stdout)
        self.assertIn('parent/nested/sub__subwork', self.runcli('list', cwd=wt).stdout)
    def test_stale_health_and_sizes(self):
        repo = self.register('deep/repo')
        self.runcli('create', 'deep/repo', 'dead')
        shutil.rmtree(self.root / '.swarm/worktrees/deep/repo__dead')
        self.register('healthy')
        result = self.runcli('status', '--sizes')
        self.assertIn('MISSING/INVALID', result.stdout)
        self.assertIn('cached', result.stdout)
        caches = list((self.root / '.swarm/sizes').glob('*.json'))
        before = {p: p.read_bytes() for p in caches}
        self.runcli('status', '--sizes')
        self.assertEqual(before, {p: p.read_bytes() for p in caches})
        for p in caches:
            data = json.loads(p.read_text()); data['timestamp'] = 1; p.write_text(json.dumps(data))
        self.runcli('status', '--sizes')
        self.assertTrue(all(json.loads(p.read_text())['timestamp'] > 1 for p in caches))
        self.runcli('status', '--refresh-sizes')
        for p in caches: p.write_text('broken json')
        self.runcli('status')
        self.runcli('status', '--sizes')
        shutil.rmtree(repo)
        self.assertIn('warning:', self.runcli('list').stderr)
        self.runcli('create', 'healthy', 'ok')
        self.runcli('create', 'deep/repo', 'bad', ok=False)
        (self.root / '.swarm/submissions/healthy__orphan').touch()
        self.assertIn('ORPHAN', self.runcli('status').stdout)
    def test_spaces_external_worktrees_and_atomic_add(self):
        repo = self.repo('space folder/repo')
        other = self.repo('second')
        config = self.config(); config['custom'] = {'keep': True}
        (self.root / 'swarm.json').write_text(json.dumps(config))
        jobs = [subprocess.Popen([CLI, 'add', str(path)], cwd=self.root, env=ENV,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for path in [repo, other]]
        for job in jobs:
            out, err = job.communicate(timeout=20)
            self.assertEqual(job.returncode, 0, out + err)
        self.assertEqual(set(self.config()['repos']), {'space folder/repo', 'second'})
        self.assertEqual(self.config()['custom'], {'keep': True})
        self.runcli('create', 'space folder/repo', 'one')
        self.runcli('check', 'space folder/repo__one')
        self.runcli('create', 'one', cwd=repo)  # idempotent reuse
        external = self.root / 'external'
        self.git(repo, 'worktree', 'add', '-b', 'external', str(external))
        self.assertIn('EXTERNAL', self.runcli('status').stdout)
        self.assertIn(str(repo), self.runcli('add', str(external), ok=False).stderr)
        # A worktree-shaped independent repo must never be integrated or removed.
        fake = self.repo('.swarm/worktrees/second__fake')
        self.runcli('check', 'second__fake', ok=False)
        self.runcli('remove', 'second__fake', '--confirm', ok=False)
        self.assertTrue(fake.is_dir())

    def legacy_workspace(self, state='.swarm'):
        config = {'version': 1, 'repos_dir': 'services', 'state_dir': state,
                  'repos': ['api'], 'custom': {'preserve': True}}
        repo = self.repo('services/api')
        (self.root / 'swarm.json').write_text(json.dumps(config))
        (self.root / 'swarm.md').write_text('Keep these project instructions.\n')
        (self.root / '.gitignore').write_text('user-rule\n# <-- swarm:start -->\n*__*/\n.swarm/\n# <-- swarm:end -->\nafter-rule\n')
        self.runcli('create', 'api', 'active')
        wt = self.root / 'services/api__active'
        (wt / 'feature').write_text('ready\n')
        self.git(wt, 'add', '.')
        self.git(wt, 'commit', '-m', 'feature')
        self.runcli('submit', 'api__active')
        return repo, wt, config

    def test_v1_migration_and_active_lifecycle(self):
        repo, wt, config = self.legacy_workspace()
        before = (self.root / 'swarm.json').read_bytes()
        self.assertIn('"version": 2', self.runcli('migrate', '--dry-run').stdout)
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        self.runcli('migrate')
        self.assertEqual(self.config(), {'version': 2, 'repos': ['services/api'], 'custom': {'preserve': True}})
        self.assertEqual((self.root / 'swarm.md').read_text(), 'Keep these project instructions.\n')
        self.assertTrue(wt.is_dir())
        self.assertFalse((self.root / '.swarm/worktrees/services/api__active').exists())
        self.assertTrue((self.root / '.swarm/submissions/services/api__active').is_file())
        self.assertFalse((self.root / '.swarm/submissions/api__active').exists())
        self.assertEqual(json.loads((self.root / '.swarm/migration-v1/config.json').read_text()), config)
        ignore = (self.root / '.gitignore').read_text()
        self.assertNotIn('*__*/', ignore)
        self.assertNotIn('/services/api__active/', ignore)
        self.assertIn('user-rule', ignore); self.assertIn('after-rule', ignore)
        self.assertIn('Already version 2', self.runcli('migrate').stdout)
        self.runcli('check', 'api__active')  # retained legacy selector
        self.runcli('check', 'api/active')
        self.assertIn('SUBMITTED', self.runcli('list').stdout)
        self.runcli('create', 'api', 'active')  # reuses existing sibling
        self.runcli('create', 'services/api', 'new')
        self.assertTrue((self.root / '.swarm/worktrees/services/api__new').is_dir())
        self.runcli('review', str(wt))
        self.runcli('integrate', 'api__active')
        self.assertTrue((repo / 'feature').is_file())
        self.assertFalse((self.root / '.swarm/submissions/services/api__active').exists())
        self.runcli('sync', str(wt))
        master, slave = pty.openpty()
        proc = subprocess.Popen([CLI, 'remove', 'api__active', '--confirm', '-d'],
                                cwd=self.root, env=ENV, stdin=slave,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(slave); os.write(master, b'Y\n')
        out, err = proc.communicate(timeout=15); os.close(master)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertFalse(wt.exists())

    def test_custom_state_timestamp_orphans_and_migration_preflight(self):
        repo, wt, config = self.legacy_workspace('runtime/state')
        inbox = self.root / 'runtime/state/submissions'
        (inbox / 'api__active').rename(inbox / '2026-10-14-001__api__active')
        (inbox / 'gone__orphan').touch()
        gi = self.root / '.gitignore'
        valid_ignore = gi.read_text()
        gi.write_text('user-rule\n# <-- swarm:start -->\n')
        self.runcli('migrate', ok=False)
        self.assertEqual(self.config(), config)
        gi.write_text(valid_ignore)
        self.runcli('migrate')
        self.assertTrue((self.root / '.swarm/submissions/services/api__active').is_file())
        self.assertTrue((self.root / '.swarm/submissions/services/gone__orphan').is_file())
        self.assertTrue((inbox / '2026-10-14-001__api__active').is_file())
        self.assertNotIn('/runtime/state/', gi.read_text())
        self.assertIn('ORPHAN', self.runcli('status').stdout)
        self.runcli('check', str(wt))
        self.runcli('add', '.', cwd=repo)
        self.assertEqual(self.config()['repos'], ['services/api'])

    def test_migration_submodule_duplicate_and_missing_worktree_guards(self):
        repo, wt, _ = self.legacy_workspace()
        source = self.repo('source')
        self.git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'nested/sub')
        self.git(repo, 'commit', '-am', 'submodule')
        sub = repo / 'nested/sub'
        self.git(sub, 'remote', 'set-url', 'origin', str(source))
        self.runcli('add', '.', cwd=sub)
        self.runcli('create', 'subtask', cwd=sub)
        old_sub_wt = repo / 'nested/sub__subtask'
        self.runcli('migrate')
        self.runcli('check', str(old_sub_wt))
        self.runcli('create', 'newtask', cwd=sub)
        new_sub_wt = self.root / '.swarm/worktrees/services/api/nested/sub__newtask'
        self.assertTrue(new_sub_wt.is_dir())
        self.assertIn('services/api/nested/sub', self.runcli('config', cwd=new_sub_wt).stdout)
        self.assertIn(str(sub), self.runcli('init', cwd=new_sub_wt, ok=False).stderr)
        self.runcli('add', str(new_sub_wt), ok=False)
        duplicate = self.root / '.swarm/worktrees/services/api__active'
        self.git(repo, 'worktree', 'add', '-b', 'duplicate', str(duplicate))
        self.runcli('create', 'services/api', 'active', ok=False)
        self.runcli('check', 'services/api__active', ok=False)
        self.git(repo, 'worktree', 'remove', str(duplicate))
        shutil.rmtree(wt)
        self.runcli('create', 'services/api', 'active', ok=False)
        self.assertIn('MISSING/INVALID', self.runcli('status').stdout)

    def test_interrupted_migration_retry_and_minimal_v2_config(self):
        self.assertEqual(self.config(), {'version': 2, 'repos': []})
        self.assertNotIn('*__*/', (self.root / '.gitignore').read_text())
        repo, wt, config = self.legacy_workspace()
        wrappers = self.root / 'wrappers'; wrappers.mkdir()
        wrapper = wrappers / 'mv'
        wrapper.write_text('#!/bin/bash\nif [[ "${@: -1}" == "' + str(self.root / 'swarm.json') + '" ]]; then exit 42; fi\nexec /usr/bin/mv "$@"\n')
        wrapper.chmod(0o755)
        env = dict(ENV, PATH=str(wrappers) + ':' + ENV['PATH'])
        result = subprocess.run([CLI, 'migrate'], cwd=self.root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config(), config)
        self.assertTrue((self.root / '.swarm/submissions/api__active').exists())
        self.assertTrue((self.root / '.swarm/submissions/services/api__active').exists())
        self.runcli('migrate')
        self.assertEqual(self.config()['repos'], ['services/api'])
        self.assertFalse((self.root / '.swarm/submissions/api__active').exists())
        self.assertFalse((self.root / '.swarm/submissions/services/services/api__active').exists())
        self.assertIn('SUBMITTED', self.runcli('status').stdout)
        self.runcli('check', str(wt))

    def test_config_boundaries_and_legacy(self):
        self.register('legacy')
        self.runcli('create', 'legacy', 'one')
        self.runcli('check', 'legacy/one')
        self.runcli('create', 'legacy', 'two', '--dry-run')
        self.assertFalse((self.root / '.swarm/worktrees/legacy__two').exists())
        config = self.config()
        for bad in ['../escape', '/absolute', 'a/../legacy', 'bad__name']:
            config['repos'] = [bad]
            (self.root / 'swarm.json').write_text(json.dumps(config))
            self.runcli('status', ok=False)
        config['repos'] = ['legacy', 'legacy']
        (self.root / 'swarm.json').write_text(json.dumps(config))
        self.runcli('status', ok=False)

if __name__ == '__main__':
    unittest.main()
