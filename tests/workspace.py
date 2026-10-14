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
        wt = self.root / 'a/deep/app__feature'
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
        wt = parent / 'nested/sub__subwork'
        self.runcli('add', '.', cwd=wt, ok=False)
        err = self.runcli('init', cwd=wt, ok=False).stderr
        self.assertIn(str(sub), err)
        self.runcli('check', 'parent/nested/sub__subwork')
        self.assertIn('CANONICAL', self.runcli('status', 'parent/nested/sub').stdout)
        self.assertIn('parent/nested/sub__subwork', self.runcli('list', cwd=wt).stdout)
    def test_stale_health_and_sizes(self):
        repo = self.register('deep/repo')
        self.runcli('create', 'deep/repo', 'dead')
        shutil.rmtree(self.root / 'deep/repo__dead')
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
        fake = self.repo('second__fake')
        self.runcli('check', 'second__fake', ok=False)
        self.runcli('remove', 'second__fake', '--confirm', ok=False)
        self.assertTrue(fake.is_dir())

    def test_config_boundaries_and_legacy(self):
        self.register('legacy')
        self.runcli('create', 'legacy', 'one')
        self.runcli('check', 'legacy/one')
        self.runcli('create', 'legacy', 'two', '--dry-run')
        self.assertFalse((self.root / 'legacy__two').exists())
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
