"""Offline black-box coverage for Swarm's public CLI and migration."""
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
    def cmd(self, args, cwd=None, ok=True, env=None):
        result = subprocess.run(args, cwd=cwd or self.root, env=env or ENV, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result
    def runcli(self, *args, cwd=None, ok=True, env=None):
        return self.cmd([CLI, *args], cwd, ok, env)
    def interactive(self, args, answers, cwd=None, ok=True):
        master, slave = pty.openpty()
        proc = subprocess.Popen([CLI, *args], cwd=cwd or self.root, env=ENV,
                                stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(slave)
        os.write(master, answers)
        out, err = proc.communicate(timeout=25)
        os.close(master)
        self.assertEqual(proc.returncode == 0, ok, out + err)
        return out.decode(), err.decode()
    def git(self, path, *args):
        return self.cmd(['git', '-C', str(path), *args])
    def repo(self, relative):
        path = self.root / relative
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, 'init', '-b', 'main')
        (path / 'hello').write_text('hello\n')
        self.git(path, 'add', '.')
        self.git(path, 'commit', '-m', 'initial')
        self.git(path, 'remote', 'add', 'origin', str(path))
        return path
    def register(self, relative, name='api'):
        path = self.repo(relative)
        self.runcli('add', '.', '--name', name, cwd=path)
        return path
    def config(self):
        return json.loads((self.root / 'swarm.json').read_text())
    def write_config(self, config):
        (self.root / 'swarm.json').write_text(json.dumps(config))
    def wt(self, name='api', work='1234'):
        return self.root / '.swarm/worktrees' / (name + '___' + work)
    def feature(self, wt):
        (wt / 'feature').write_text('ready\n')
        self.git(wt, 'add', '.')
        self.git(wt, 'commit', '-m', 'feature')

    def test_init_and_registration(self):
        self.assertEqual(self.config(), {'version': 2, 'default_ide': '', 'repos': {}})
        self.assertNotIn('*__*/', (self.root / '.gitignore').read_text())
        repo = self.repo('a/deep/ts-mono')
        self.runcli('add', str(repo), ok=False)
        out, err = self.interactive(['add', str(repo)], b'\n')
        self.assertIn('ts-mono', err)
        self.assertEqual(self.config()['repos'], {'ts-mono': 'a/deep/ts-mono'})
        before = (self.root / 'swarm.json').read_bytes()
        self.runcli('add', '.', cwd=repo)
        self.runcli('init')
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        other = self.repo('b/ts-mono')
        out, err = self.interactive(['add', str(other)], b'\ninvalid___name\nsecondary\n')
        self.assertIn('already', err)
        self.assertEqual(self.config()['repos']['secondary'], 'b/ts-mono')
        self.runcli('add', '.', '--name', 'another', cwd=repo, ok=False)
        self.runcli('add', str(other), '--name', 'secondary')
        repo2 = self.repo('repo__with spaces')
        self.runcli('add', str(repo2), '--name', 'spaces')
        self.assertEqual(self.config()['repos']['spaces'], 'repo__with spaces')
        for index, bad in enumerate(['bad___name', 'trailing_', '../bad', 'has space']):
            fresh = self.repo('fresh-' + str(index))
            self.runcli('add', str(fresh), '--name', bad, ok=False)

    def test_registration_cancellation_boundaries_and_concurrency(self):
        repo = self.repo('one')
        before = (self.root / 'swarm.json').read_bytes()
        self.interactive(['add', str(repo)], b'\x04', ok=False)
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        other = self.repo('two')
        jobs = [subprocess.Popen([CLI, 'add', str(path), '--name', path.name], cwd=self.root,
                                 env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for path in [repo, other]]
        for job in jobs:
            out, err = job.communicate(timeout=25)
            self.assertEqual(job.returncode, 0, out + err)
        self.assertEqual(self.config()['repos'], {'one': 'one', 'two': 'two'})
        self.runcli('add', str(repo / 'hello'), '--name', 'file', ok=False)
        with tempfile.TemporaryDirectory() as outside:
            self.git(outside, 'init')
            self.runcli('add', outside, '--name', 'outside', ok=False)
        hidden = self.repo('.swarm/hidden')
        self.runcli('add', str(hidden), '--name', 'hidden', ok=False)

    def test_full_lifecycle_and_target_forms(self):
        repo = self.register('deep/services/api')
        self.register('second/api', 'secondary')
        self.runcli('create', '1234', '--from', 'HEAD', cwd=repo)
        wt = self.wt()
        self.assertTrue(wt.is_dir())
        self.runcli('create', 'api', '1234')
        self.runcli('check', 'api', '1234')
        self.runcli('check', 'api___1234')
        self.runcli('check', str(wt))
        self.runcli('check', '1234', cwd=wt)
        self.runcli('check', 'api/1234', ok=False)
        self.runcli('check', 'api', '1234', 'extra', ok=False)
        self.runcli('create', 'api', 'bad___id', ok=False)
        self.runcli('create', 'api', 'future', '--dry-run')
        self.assertFalse(self.wt('api', 'future').exists())
        self.runcli('sync', 'api', '1234')
        self.feature(wt)
        self.runcli('submit', '1234', cwd=wt)
        self.assertTrue((self.root / '.swarm/submissions/api___1234').is_file())
        self.runcli('review', 'api', '1234')
        self.runcli('integrate', 'api', '1234', '--dry-run')
        self.runcli('integrate', 'api', '1234', '-m', 'Integrate feature')
        self.assertTrue((repo / 'feature').is_file())
        self.runcli('remove', 'api', '1234', ok=False)
        self.interactive(['remove', 'api', '1234', '--confirm', '-d'], b'Y\n')
        self.assertFalse(wt.exists())

    def test_integrate_allows_unrelated_untracked_files(self):
        repo = self.register('api')
        self.runcli('create', 'api', '1234', '--from', 'HEAD')
        self.feature(self.wt())
        self.runcli('submit', 'api', '1234')
        (repo / 'notes').write_text('leave me alone\n')
        result = self.runcli('integrate', 'api', '1234', '--dry-run')
        self.assertIn('actual merge', result.stdout + result.stderr)
        self.runcli('integrate', 'api', '1234')
        self.assertEqual((repo / 'notes').read_text(), 'leave me alone\n')
        self.assertEqual(self.git(repo, 'status', '--porcelain').stdout.strip(), '?? notes')
        self.assertFalse((self.root / '.swarm/submissions/api___1234').exists())

    def test_integrate_preserves_untracked_collisions_and_submission(self):
        repo = self.register('api')
        self.runcli('create', 'api', '1234', '--from', 'HEAD')
        self.feature(self.wt())
        self.runcli('submit', 'api', '1234')
        before = self.git(repo, 'rev-parse', 'HEAD').stdout
        (repo / 'feature').write_text('local notes\n')
        result = self.runcli('integrate', 'api', '1234', ok=False)
        self.assertIn('untracked working tree files', result.stderr)
        self.assertEqual((repo / 'feature').read_text(), 'local notes\n')
        self.assertEqual(self.git(repo, 'rev-parse', 'HEAD').stdout, before)
        self.assertTrue((self.root / '.swarm/submissions/api___1234').exists())

    def test_integrate_blocks_tracked_changes(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                name = 'api' + str(staged)
                repo = self.register(name, name)
                self.runcli('create', name, '1234', '--from', 'HEAD')
                self.feature(self.wt(name))
                self.runcli('submit', name, '1234')
                (repo / 'hello').write_text('local edit\n')
                if staged:
                    self.git(repo, 'add', 'hello')
                result = self.runcli('integrate', name, '1234', ok=False)
                self.assertIn('canonical trunk has tracked changes', result.stderr)
                self.assertFalse((repo / 'feature').exists())
                self.assertTrue((self.root / ('.swarm/submissions/' + name + '___1234')).exists())

    def test_create_defaults_to_source_head_and_respects_overrides(self):
        repo = self.register('services/api')
        initial = self.git(repo, 'rev-parse', 'HEAD').stdout.strip()
        self.git(repo, 'fetch', 'origin')
        self.git(repo, 'switch', '-c', 'collector')
        self.feature(repo)
        source_head = self.git(repo, 'rev-parse', 'HEAD').stdout.strip()
        (repo / 'uncommitted').write_text('not part of HEAD')
        env = dict(ENV, WP_BASE_REF='origin/main')
        dry = self.runcli('create', 'api', 'monitor', '--dry-run', env=env)
        self.assertIn(source_head, dry.stdout)
        self.assertFalse(self.wt('api', 'monitor').exists())
        self.runcli('create', 'api', 'monitor', env=env)
        wt = self.wt('api', 'monitor')
        self.assertEqual(self.git(wt, 'rev-parse', 'HEAD').stdout.strip(), source_head)
        self.assertFalse((wt / 'uncommitted').exists())
        self.assertEqual(self.git(wt, 'branch', '--show-current').stdout.strip(), 'task/monitor')
        self.runcli('create', 'api', 'explicit', 'custom-name', '--from', 'main')
        self.assertEqual(self.git(self.wt('api', 'explicit'), 'rev-parse', 'HEAD').stdout.strip(), initial)
        self.runcli('create', 'api', 'tracked', '--track', 'origin/main')
        tracked = self.wt('api', 'tracked')
        self.assertEqual(self.git(tracked, 'rev-parse', 'HEAD').stdout.strip(), initial)
        self.assertEqual(self.git(tracked, 'rev-parse', '--abbrev-ref', '@{upstream}').stdout.strip(), 'origin/main')
        # Calling from another worktree still selects the canonical source HEAD.
        self.runcli('create', 'from-worker', cwd=tracked)
        self.assertEqual(self.git(self.wt('api', 'from-worker'), 'rev-parse', 'HEAD').stdout.strip(), source_head)
        self.git(repo, 'branch', 'already-exists', 'main')
        self.runcli('create', 'api', 'reuse-branch', 'already-exists')
        self.assertEqual(self.git(self.wt('api', 'reuse-branch'), 'rev-parse', 'HEAD').stdout.strip(), initial)
        self.runcli('create', 'api', 'monitor', '--from', 'main')
        self.assertEqual(self.git(wt, 'rev-parse', 'HEAD').stdout.strip(), source_head)
        self.git(repo, 'switch', '--detach', source_head)
        self.runcli('create', 'api', 'detached-source')
        self.assertEqual(self.git(self.wt('api', 'detached-source'), 'rev-parse', 'HEAD').stdout.strip(), source_head)

    def test_paths_inference_listing_and_external_health(self):
        repo = self.register('deep folder/api')
        self.register('other/api', 'secondary')
        self.runcli('create', 'api', 'one')
        self.runcli('create', 'secondary', 'two')
        wt = self.wt('api', 'one')
        for args, cwd, expected in [(['path', 'api'], self.root, repo),
                                    (['path'], wt, repo),
                                    (['path', 'api', 'one'], self.root, wt),
                                    (['path', 'one'], wt, wt),
                                    (['path', 'api___one'], self.root, wt),
                                    (['path', str(wt)], self.root, wt)]:
            self.assertEqual(self.runcli(*args, cwd=cwd).stdout, str(expected) + '\n')
        self.runcli('path', ok=False)
        self.runcli('path', 'api', 'missing', ok=False)
        self.assertNotIn('secondary', self.runcli('list', cwd=wt).stdout)
        self.assertIn('secondary', self.runcli('list', '--all', cwd=wt).stdout)
        self.assertNotIn('secondary', self.runcli('list', 'api').stdout)
        self.runcli('list', 'api', '--all', ok=False)
        self.assertIn('Canonical path:', self.runcli('config', cwd=wt).stdout)
        external = self.root / 'external'
        self.git(repo, 'worktree', 'add', '-b', 'external', str(external))
        self.assertIn('EXTERNAL', self.runcli('list', 'api').stdout)
        self.runcli('check', str(external), ok=False)
        shutil.rmtree(wt)
        self.assertIn('MISSING/INVALID', self.runcli('status').stdout)
        self.runcli('create', 'api', 'one', ok=False)
        shutil.rmtree(repo)
        self.assertEqual(self.runcli('path', 'secondary').stderr, '')
        self.assertIn('warning:', self.runcli('status').stderr)
        self.assertEqual(self.runcli('status', 'secondary').stderr, '')
        self.assertEqual(self.runcli('list', '--all').stderr, '')
        self.assertEqual(self.runcli('config').stderr, '')
        self.runcli('list', 'api', ok=False)
        self.runcli('create', 'secondary', 'three')
        self.assertNotIn('error:', self.runcli('sync', 'secondary', 'two').stderr)
        self.runcli('path', 'api', ok=False)

    def test_quiet_worktree_paths_with_unavailable_registrations(self):
        repo = self.register('services/ts-mono', 'ts-mono')
        self.runcli('create', 'ts-mono', 'monitor')
        cfg = self.config()
        cfg['repos'].update({'engine': 'services/engine', 'web': 'services/web'})
        self.write_config(cfg)
        (self.root / 'services/engine').mkdir()  # directory exists but is not a repo
        path = self.runcli('path', 'ts-mono', 'monitor')
        self.assertEqual(path.stderr, '')
        self.assertEqual(path.stdout, str(self.wt('ts-mono', 'monitor')) + '\n')
        self.assertEqual(self.git(path.stdout.strip(), 'status').stderr, '')
        self.assertEqual(self.runcli('check', 'ts-mono', 'monitor').stderr, '')
        self.assertEqual(self.runcli('list').stderr, '')
        health = self.runcli('status')
        self.assertIn('engine (services/engine)', health.stderr)
        self.assertIn('web (services/web)', health.stderr)
        self.assertIn('MISSING/INVALID', health.stdout)
        for args in [('path', 'engine'), ('path', 'web', 'one'),
                     ('check', 'engine', 'one'), ('create', 'web', 'one')]:
            error = self.runcli(*args, ok=False).stderr
            self.assertTrue('unavailable' in error or 'not found' in error, error)

    def test_schema_validation_and_size_cache(self):
        repo = self.register('api')
        cfg = self.config()
        for bad in [None, False, 7, 'vscode', 'Cursor']:
            cfg['default_ide'] = bad; self.write_config(cfg)
            self.runcli('config', ok=False)
        cfg.pop('default_ide'); self.write_config(cfg)
        self.runcli('config')
        for bad in ['../escape', '/absolute', '.swarm/hidden']:
            cfg['repos'] = {'bad': bad}; self.write_config(cfg)
            self.runcli('status', ok=False)
        cfg['repos'] = {'api': 'api', 'duplicate': 'api'}; self.write_config(cfg)
        self.runcli('status', ok=False)
        cfg['repos'] = {'api': 'api'}; self.write_config(cfg)
        self.runcli('create', 'api', 'one')
        self.assertIn('cached', self.runcli('status', '--sizes').stdout)
        caches = list((self.root / '.swarm/sizes').glob('*.json'))
        before = {p: p.read_bytes() for p in caches}
        self.runcli('status', '--sizes')
        self.assertEqual(before, {p: p.read_bytes() for p in caches})
        for p in caches:
            data = json.loads(p.read_text()); data['timestamp'] = 1; p.write_text(json.dumps(data))
        self.runcli('status', '--sizes')
        self.assertTrue(all(json.loads(p.read_text())['timestamp'] > 1 for p in caches))
        for p in caches: p.write_text('broken')
        self.runcli('status')
        self.runcli('status', '--refresh-sizes')
        (self.root / '.swarm/submissions/api___gone').touch()
        self.assertIn('ORPHAN', self.runcli('status').stdout)

    def test_submodules_and_wrong_ownership(self):
        parent = self.register('parent', 'parent')
        source = self.repo('source')
        self.git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'nested/sub')
        self.git(parent, 'commit', '-am', 'submodule')
        sub = parent / 'nested/sub'
        self.assertIn('Current repo: none', self.runcli('config', cwd=sub).stdout)
        self.git(sub, 'remote', 'set-url', 'origin', str(source))
        self.runcli('add', '.', '--name', 'sub', cwd=sub)
        self.runcli('create', 'one', cwd=sub)
        wt = self.wt('sub', 'one')
        self.runcli('check', 'sub', 'one')
        self.assertIn(str(sub), self.runcli('init', cwd=wt, ok=False).stderr)
        self.runcli('add', str(wt), '--name', 'bad', ok=False)
        fake = self.repo('.swarm/worktrees/parent___fake')
        self.runcli('check', 'parent', 'fake', ok=False)
        self.runcli('remove', 'parent', 'fake', '--confirm', ok=False)
        self.assertTrue(fake.is_dir())

    def test_launcher_selection_and_failures(self):
        repo = self.register('deep/api')
        self.runcli('create', 'api', 'one')
        wt = self.wt('api', 'one')
        self.assertIn('No default IDE', self.runcli('open', 'api', 'one', ok=False).stderr)
        initial = self.config(); initial.pop('default_ide'); self.write_config(initial)
        self.assertIn('No default IDE', self.runcli('open', 'api', 'one', ok=False).stderr)
        bindir = self.root / 'bin'; bindir.mkdir()
        log = self.root / 'launch.json'
        for name in ['cursor', 'claude', 'codex']:
            exe = bindir / name
            exe.write_text('#!/usr/bin/env python3\nimport os,sys,json\nopen(os.environ["LAUNCH_LOG"],"w").write(json.dumps({"exe":os.path.basename(sys.argv[0]),"args":sys.argv[1:],"cwd":os.getcwd()}))\nsys.exit(int(os.environ.get("LAUNCH_EXIT","0")))\n')
            exe.chmod(0o755)
        env = dict(ENV, PATH=str(bindir) + ':' + ENV['PATH'], LAUNCH_LOG=str(log))
        cfg = self.config()
        for name in ['cursor', 'claude', 'codex']:
            cfg['default_ide'] = name; self.write_config(cfg)
            self.runcli('open', 'one', cwd=repo, env=env)
            record = json.loads(log.read_text())
            self.assertEqual(record['exe'], name)
            if name == 'cursor': self.assertEqual(record['args'], ['--new-window', str(wt)])
            if name == 'claude': self.assertEqual(record['cwd'], str(wt))
            if name == 'codex': self.assertEqual(record['args'], ['--cd', str(wt)])
        self.runcli('open', 'api', '--cursor', env=env)
        self.assertEqual(json.loads(log.read_text())['args'], ['--new-window', str(repo)])
        self.runcli('open', 'api', '--cursor', '--claude', env=env, ok=False)
        self.runcli('open', 'api', '--vscode', env=env, ok=False)
        result = subprocess.run([CLI, 'open', 'api', '--cursor'], cwd=self.root,
                                env=dict(env, LAUNCH_EXIT='17'), capture_output=True)
        self.assertEqual(result.returncode, 17)
        (bindir / 'claude').unlink()
        only_tools = self.root / 'tools-only'; only_tools.mkdir()
        for tool in ['bash', 'git', 'jq', 'dirname', 'realpath', 'mkdir', 'sed', 'grep']:
            (only_tools / tool).symlink_to(shutil.which(tool))
        missing_env = dict(env, PATH=str(only_tools))
        self.assertIn('not found', self.runcli('open', 'api', '--claude', env=missing_env, ok=False).stderr)

    def test_root_repo(self):
        self.repo('.')
        self.runcli('add', '.', '--name', 'root')
        self.assertEqual(self.config()['repos'], {'root': '.'})
        self.git(self.root, 'add', 'swarm.json')
        self.git(self.root, 'commit', '-m', 'register root')
        self.runcli('create', 'root', 'one')
        self.assertEqual(self.runcli('path', 'one', cwd=self.wt('root', 'one')).stdout,
                         str(self.wt('root', 'one')) + '\n')

    def legacy(self, version=1, state='.swarm', paths=None):
        paths = paths or ['services/api']
        repos = [self.repo(p) for p in paths]
        cfg = {'version': version, 'repos': [p.removeprefix('services/') for p in paths] if version == 1 else paths,
               'custom': {'keep': True}}
        if version == 1: cfg.update(repos_dir='services', state_dir=state)
        self.write_config(cfg)
        (self.root / 'swarm.md').write_text('Keep project instructions.\n')
        (self.root / '.gitignore').write_text('user-rule\n# <-- swarm:start -->\n*__*/\n.swarm/\n# <-- swarm:end -->\nafter-rule\n')
        return repos, cfg
    def old_work(self, repo, version, state='.swarm', work='active', central=False):
        rel = str(repo.relative_to(self.root))
        wt = self.root / '.swarm/worktrees' / (rel + '__' + work) if central else pathlib.Path(str(repo) + '__' + work)
        self.git(repo, 'worktree', 'add', '-b', 'task/' + work, str(wt))
        self.feature(wt)
        key = rel.removeprefix('services/') if version == 1 else rel
        marker = self.root / state / 'submissions' / (key + '__' + work)
        marker.parent.mkdir(parents=True, exist_ok=True); marker.touch()
        return wt, marker

    def test_v1_migration_active_lifecycle(self):
        repos, cfg = self.legacy()
        wt, marker = self.old_work(repos[0], 1)
        self.runcli('config', ok=False)
        before = (self.root / 'swarm.json').read_bytes()
        self.runcli('migrate', '--dry-run')
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        self.interactive(['migrate'], b'custom-name\n')
        self.assertEqual(self.config(), {'version': 2, 'default_ide': '', 'repos': {'custom-name': 'services/api'}, 'custom': {'keep': True}})
        self.assertTrue(wt.is_dir())
        self.assertFalse(marker.exists())
        self.assertTrue((self.root / '.swarm/submissions/custom-name___active').exists())
        self.assertEqual(json.loads((self.root / '.swarm/migration/config.json').read_text()), cfg)
        self.assertEqual((self.root / 'swarm.md').read_text(), 'Keep project instructions.\n')
        self.assertNotIn('*__*/', (self.root / '.gitignore').read_text())
        self.assertIn('user-rule', (self.root / '.gitignore').read_text())
        self.runcli('migrate')
        self.runcli('check', 'custom-name', 'active')
        self.runcli('create', 'custom-name', 'active')
        self.assertFalse(self.wt('custom-name', 'active').exists())
        self.runcli('create', 'custom-name', 'new')
        self.assertTrue(self.wt('custom-name', 'new').exists())
        self.runcli('review', str(wt))
        self.runcli('integrate', 'custom-name', 'active')
        self.interactive(['remove', 'custom-name', 'active', '--confirm', '-d'], b'Y\n')
        self.assertFalse(wt.exists())

    def test_early_v2_custom_state_and_orphans(self):
        repos, _ = self.legacy(2)
        wt, marker = self.old_work(repos[0], 2, central=True)
        cfg = self.config(); cfg['default_ide'] = 'claude'; self.write_config(cfg)
        orphan = marker.parent / 'api__gone'; orphan.touch()
        self.runcli('migrate', '--yes')
        self.assertEqual(self.config()['default_ide'], 'claude')
        self.assertTrue((self.root / '.swarm/submissions/api___active').exists())
        self.runcli('check', str(wt))
        self.assertEqual(self.runcli('path', 'active', cwd=wt).stdout, str(wt) + '\n')
        self.assertIn('ORPHAN', self.runcli('status').stdout)

    def test_migration_custom_state_timestamp_cancellation_and_preflight(self):
        repos, cfg = self.legacy(1, 'runtime/state')
        wt, marker = self.old_work(repos[0], 1, 'runtime/state')
        timestamp = marker.parent / ('2026-10-14-001__' + marker.name)
        marker.rename(timestamp)
        self.runcli('migrate', ok=False)
        self.interactive(['migrate'], b'\x04', ok=False)
        self.assertEqual(self.config(), cfg)
        self.assertTrue(timestamp.exists())
        gi = self.root / '.gitignore'; original = gi.read_text()
        gi.write_text('# <-- swarm:start -->\n')
        self.runcli('migrate', '--yes', ok=False)
        self.assertEqual(self.config(), cfg)
        gi.write_text(original)
        self.runcli('migrate', '--yes')
        self.assertTrue(timestamp.exists())
        self.assertTrue((self.root / '.swarm/submissions/api___active').exists())
        self.runcli('check', str(wt))

    def test_migration_collision_reprompt_and_retry(self):
        repos, cfg = self.legacy(2, paths=['a/api', 'b/api'])
        wt, marker = self.old_work(repos[0], 2, central=True)
        self.runcli('migrate', '--yes', ok=False)
        self.runcli('migrate', '--dry-run', ok=False)
        self.assertEqual(self.config(), cfg)
        self.interactive(['migrate'], b'\n\nsecondary\n')
        self.assertEqual(self.config()['repos'], {'api': 'a/api', 'secondary': 'b/api'})
        duplicate = self.wt('api', 'active')
        self.git(repos[0], 'worktree', 'add', '-b', 'duplicate', str(duplicate))
        self.runcli('create', 'api', 'active', ok=False)
        self.runcli('check', 'api', 'active', ok=False)
        self.git(repos[0], 'worktree', 'remove', str(duplicate))
        shutil.rmtree(wt)
        self.runcli('create', 'api', 'active', ok=False)

    def test_migrated_submodule_and_legacy_recognition_scope(self):
        repos, cfg = self.legacy()
        parent = repos[0]
        source = self.repo('source')
        self.git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'nested/sub')
        self.git(parent, 'commit', '-am', 'submodule')
        sub = parent / 'nested/sub'
        self.git(sub, 'remote', 'set-url', 'origin', str(source))
        cfg['repos'].append('api/nested/sub'); self.write_config(cfg)
        wt, marker = self.old_work(sub, 1)
        self.runcli('migrate', '--yes')
        self.runcli('check', 'sub', 'active')
        self.runcli('sync', 'active', cwd=wt)
        self.assertFalse((self.root / '.swarm/submissions/sub___active').exists())
        self.assertIn('Current repo: sub', self.runcli('config', cwd=wt).stdout)
        self.runcli('create', 'sub', 'new')
        self.assertTrue(self.wt('sub', 'new').exists())
        # A repo added after migration must not inherit old naming rules.
        fresh = self.register('fresh', 'fresh')
        manual = pathlib.Path(str(fresh) + '__manual')
        self.git(fresh, 'worktree', 'add', '-b', 'manual', str(manual))
        self.assertIn('EXTERNAL', self.runcli('list', 'fresh').stdout)
        self.runcli('check', str(manual), ok=False)

    def test_migration_interruption_resume(self):
        repos, cfg = self.legacy()
        wt, marker = self.old_work(repos[0], 1)
        wrappers = self.root / 'wrappers'; wrappers.mkdir()
        wrapper = wrappers / 'mv'
        wrapper.write_text('#!/bin/bash\nif [[ "${@: -1}" == "' + str(self.root / 'swarm.json') + '" ]]; then exit 42; fi\nexec /usr/bin/mv "$@"\n')
        wrapper.chmod(0o755)
        env = dict(ENV, PATH=str(wrappers) + ':' + ENV['PATH'])
        self.runcli('migrate', '--yes', env=env, ok=False)
        self.assertEqual(self.config(), cfg)
        self.assertTrue(marker.exists())
        self.runcli('migrate', '--yes')
        self.assertEqual(self.config()['repos'], {'api': 'services/api'})
        self.assertFalse(marker.exists())
        self.assertIn('SUBMITTED', self.runcli('status').stdout)
        self.runcli('check', str(wt))

    def test_local_skills_and_parent_confirmation(self):
        repo = self.register('services/api')
        self.runcli('install', '--cursor', '--claude', '--codex')
        before = (self.root / 'swarm.json').read_bytes()
        self.runcli('install', '--cursor', cwd=repo, ok=False)
        self.interactive(['install', '--cursor'], b'n\n', cwd=repo)
        local = repo / '.cursor/skills/swarm/SKILL.md'
        self.assertFalse(local.exists())
        self.interactive(['install', '--cursor'], b'y\n', cwd=repo)
        self.assertTrue(local.exists())
        local.write_text('custom')
        self.runcli('install', str(repo), '--cursor', '--claude', '--codex', '--yes')
        self.assertEqual(local.read_text(), 'custom')
        self.assertEqual(before, (self.root / 'swarm.json').read_bytes())
        for folder in ['.claude', '.agents']: self.assertTrue((repo / folder / 'skills/swarm/SKILL.md').exists())
        with tempfile.TemporaryDirectory(prefix='swarm-skills-') as folder:
            self.runcli('install', '--cursor', '--claude', '--codex', cwd=folder)
            self.assertFalse((pathlib.Path(folder) / 'swarm.json').exists())
        self.runcli('create', 'api', 'one')
        self.runcli('install', str(self.wt('api', 'one')), '--codex', '--yes')
        self.assertTrue((self.wt('api', 'one') / '.agents/skills/swarm/SKILL.md').exists())

if __name__ == '__main__':
    unittest.main()
