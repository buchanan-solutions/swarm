#!/usr/bin/env python3
"""Linux access allocation. Git/project inspection always runs as a non-root user.

Only this helper implements elevated mutations. All filesystem changes use pinned,
no-follow file descriptors; recursive scope is inventoried before accounts change.
"""
import argparse
import contextlib
import ctypes
import ctypes.util
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys


class AccessError(Exception):
    pass


def fail(message):
    raise AccessError(message)


def account(name):
    try:
        return pwd.getpwnam(name)
    except KeyError:
        fail(f'user does not exist: {name}; no changes made')


def actor():
    uid = os.getuid()
    if uid == 0:
        try:
            uid = int(os.environ['SUDO_UID'])
        except (KeyError, ValueError):
            fail('run through sudo from a non-root administrator account')
        if uid <= 0:
            fail('the invoking administrator must be a non-root user')
    return pwd.getpwuid(uid)


def run(args, user=None, check=True, global_config=None, **kwargs):
    env = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL='C',
               HOME=user.pw_dir if user else '/root',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0',
               GIT_NO_LAZY_FETCH='1')
    if global_config is not None:
        env['GIT_CONFIG_GLOBAL'] = global_config
    identity = {}
    if user and os.geteuid() == 0:
        identity = dict(user=user.pw_uid, group=user.pw_gid,
                        extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **identity, **kwargs)
    if check and result.returncode:
        fail(f'{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result


def git(path, user, *args):
    return run(['/usr/bin/git', '-c', f'safe.directory={path}',
                '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                '-C', str(path), *args], user=user).stdout.rstrip('\n')


@contextlib.contextmanager
def opened(path):
    """Resolve every component without following symlinks; pin final inode."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        fail(f'unsafe path: {path}')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 2:
                flags |= os.O_DIRECTORY
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def checked_path(path, boundary=None):
    path = Path(os.path.abspath(path))
    if boundary is not None and not path.is_relative_to(boundary):
        fail(f'path escapes workspace: {path}')
    with opened(path) as fd:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            fail(f'not a directory: {path}')
    return path


def identifier(value):
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value)) and '___' not in value


def discover(targets, caller):
    root = Path.cwd()
    while not (root / 'swarm.json').is_file():
        if root == root.parent:
            fail('no swarm.json found; run from the owning workspace')
        root = root.parent
    root = checked_path(root)
    # Root-level workspace configuration copied into a worktree is ambiguous.
    # Require the real workspace rather than interpreting its copy as authority.
    try:
        with opened(root / 'swarm.json') as fd:
            config = json.load(os.fdopen(os.dup(fd)))
    except (ValueError, TypeError) as exc:
        fail(f'invalid swarm.json: {exc}')
    repos = config.get('repos')
    if config.get('version') != 2 or not isinstance(repos, dict):
        fail('access requires a version 2 workspace; migrate first')
    if len(targets) == 1 and '___' in targets[0]:
        name, work = targets[0].split('___', 1)
    elif len(targets) == 2:
        name, work = targets
    else:
        fail('usage: swarm access <repo-name> <work-ID> [--owner USER] [--group GROUP]')
    if not identifier(name) or not identifier(work) or name not in repos:
        fail('invalid or unregistered repo/work ID')
    relative = repos[name]
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        fail('invalid registered repository path')
    canonical = checked_path(root / relative, root)
    if canonical.is_relative_to(root / '.swarm'):
        fail('canonical repository cannot be inside .swarm')
    # Do not let workspace JSON authorize modifications to a foreign repository.
    if canonical.stat().st_uid != caller.pw_uid or root.stat().st_uid != caller.pw_uid:
        fail('workspace and canonical checkout must belong to the invoking administrator')
    if git(canonical, caller, 'rev-parse', '--show-toplevel') != str(canonical):
        fail('registered repository is not a checkout root')
    common = checked_path(git(canonical, caller, 'rev-parse', '--path-format=absolute', '--git-common-dir'), root)
    if common == root or common == canonical or common.stat().st_uid != caller.pw_uid:
        fail('unexpected or foreign shared Git directory')
    main_private = git(canonical, caller, 'rev-parse', '--absolute-git-dir')
    if main_private != str(common):
        fail('registered canonical checkout is itself a linked worktree')
    records = git(canonical, caller, 'worktree', 'list', '--porcelain', '-z').split('\0')
    registered = [Path(s[9:]) for s in records if s.startswith('worktree ')]
    expected = root / '.swarm/worktrees' / f'{name}___{work}'
    candidates = [expected]
    # Support only the legacy locations explicitly enabled by Swarm migration.
    plan_file = root / '.swarm/migration/plan.json'
    if plan_file.is_file():
        with opened(plan_file) as fd:
            migration = json.load(os.fdopen(os.dup(fd)))
        if migration.get('repos', {}).get(name) == relative:
            candidates += [Path(f'{canonical}__{work}'), root / '.swarm/worktrees' / f'{relative}__{work}']
    matches = [p for p in registered if p in candidates]
    if len(matches) != 1:
        fail('expected exactly one registered managed worktree; run from its owning workspace')
    worktree = checked_path(matches[0], root)
    if worktree == canonical or worktree == root:
        fail('access requires a linked feature worktree')
    if git(worktree, caller, 'rev-parse', '--show-toplevel') != str(worktree):
        fail('managed worktree is not a checkout root')
    if git(worktree, caller, 'rev-parse', '--path-format=absolute', '--git-common-dir') != str(common):
        fail('worktree belongs to a different repository')
    private = checked_path(git(worktree, caller, 'rev-parse', '--absolute-git-dir'), common)
    if private.parent != common / 'worktrees':
        fail('unexpected private worktree metadata location')
    if common.is_relative_to(worktree) or worktree.is_relative_to(common):
        fail('checkout and shared Git scope overlap')
    return root, name, work, worktree, common, private


def inventory(root, metadata=False):
    """Snapshot scope; no symlink traversal, mounts, hardlinks or nested repos."""
    entries = []
    device = root.stat().st_dev
    def walk(path):
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            if metadata:
                fail(f'symlink in Git metadata requires manual review: {path}')
            return  # e.g. node_modules shims; never modify their targets
        if st.st_dev != device or (path != root and os.path.ismount(path)):
            fail(f'mounted path requires manual review: {path}')
        if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
            fail(f'special file requires manual review: {path}')
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            fail(f'hard-linked file requires manual review: {path}; recreate dependencies as their intended owner')
        if not metadata and path != root and path.name == '.git' and stat.S_ISDIR(st.st_mode):
            fail(f'nested Git repository requires separate allocation: {path.parent}')
        if not metadata and path.name == '.git' and path.parent != root:
            fail(f'nested Git worktree/submodule requires separate allocation: {path.parent}')
        entries.append((path, st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode)))
        if stat.S_ISDIR(st.st_mode):
            with os.scandir(path) as children:
                for child in sorted(children, key=lambda c: c.name):
                    walk(Path(child.path))
    walk(root)
    if metadata and (root / 'objects/info/alternates').exists():
        fail('external Git object alternates require manual allocation')
    return entries


def pinned(entry):
    path, device, inode, kind = entry
    @contextlib.contextmanager
    def context():
        with opened(path) as fd:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode)) != (device, inode, kind):
                fail(f'path changed after preflight: {path}; stop writers and retry')
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                fail(f'file acquired hard links after preflight: {path}')
            yield fd
    return context()


class ACL:
    ACCESS = 0x8000
    DEFAULT = 0x4000

    def __init__(self):
        library = ctypes.util.find_library('acl')
        if not library:
            fail('libacl is required (install the Linux acl package)')
        self.lib = ctypes.CDLL(library, use_errno=True)
        for name, args, result in [
            ('acl_get_fd', [ctypes.c_int], ctypes.c_void_p),
            ('acl_get_file', [ctypes.c_char_p, ctypes.c_int], ctypes.c_void_p),
            ('acl_to_text', [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)], ctypes.c_void_p),
            ('acl_from_text', [ctypes.c_char_p], ctypes.c_void_p),
            ('acl_valid', [ctypes.c_void_p], ctypes.c_int),
            ('acl_set_fd', [ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
            ('acl_set_file', [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
            ('acl_free', [ctypes.c_void_p], ctypes.c_int),
        ]:
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result

    def text(self, value):
        if not value:
            raise OSError(ctypes.get_errno(), 'cannot read ACL')
        try:
            size = ctypes.c_ssize_t()
            raw = self.lib.acl_to_text(value, ctypes.byref(size))
            if not raw:
                raise OSError(ctypes.get_errno(), 'cannot format ACL')
            try:
                return ctypes.string_at(raw, size.value).decode()
            finally:
                self.lib.acl_free(raw)
        finally:
            self.lib.acl_free(value)

    def get(self, fd):
        access = self.text(self.lib.acl_get_fd(fd))
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            default = self.text(self.lib.acl_get_file(f'/proc/self/fd/{fd}'.encode(), self.DEFAULT))
            access += ''.join('default:' + line + '\n' for line in default.splitlines() if line)
        return access

    def set(self, fd, text):
        parsed = parse_acl(text.replace(',', '\n'))
        for prefix in ('', 'default:'):
            lines = [f'{key[len(prefix):]}:{value}' for key, value in parsed.items()
                     if key.startswith('default:') == bool(prefix)]
            if not lines:
                continue
            value = self.lib.acl_from_text(','.join(lines).encode())
            if not value:
                raise OSError(ctypes.get_errno(), 'invalid ACL')
            try:
                if self.lib.acl_valid(value):
                    raise OSError(ctypes.get_errno(), 'invalid ACL')
                rc = (self.lib.acl_set_file(f'/proc/self/fd/{fd}'.encode(), self.DEFAULT, value)
                      if prefix else self.lib.acl_set_fd(fd, value))
                if rc:
                    raise OSError(ctypes.get_errno(), 'cannot apply ACL (filesystem must support POSIX ACLs)')
            finally:
                self.lib.acl_free(value)


ACL_API = None


def acl_text(fd):
    return ACL_API.get(fd)


def parse_acl(text):
    result = {}
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        fields = line.split(':')
        # libacl renders account names; normalize qualifiers to stable numeric IDs.
        offset = 1 if fields[0] == 'default' else 0
        if fields[offset + 1] and not fields[offset + 1].isdigit():
            kind, name = fields[offset:offset + 2]
            fields[offset + 1] = str(pwd.getpwnam(name).pw_uid if kind == 'user' else grp.getgrnam(name).gr_gid)
        result[':'.join(fields[:-1])] = fields[-1]
    return result


def perms(bits):
    return ''.join(c if bits & flag else '-' for c, flag in [('r', 4), ('w', 2), ('x', 1)])


def bits(value):
    return sum(flag for c, flag in [('r', 4), ('w', 2), ('x', 1)] if c in value)


def acl_update(text, group_id, owner_id, directory, executable, parent=None):
    """Expand masks without silently unmasking unrelated, ineffective grants."""
    acl = parse_acl(text)
    prefixes = [''] if parent or not directory else ['', 'default:']
    for prefix in prefixes:
        if prefix and prefix + 'user:' not in acl:
            # Seed defaults from current access ACL, preserving its effective rights.
            for key, value in list(acl.items()):
                if not key.startswith('default:'):
                    acl[prefix + key] = value
        mask = bits(acl.get(prefix + 'mask:', 'rwx'))
        for key in list(acl):
            if key.startswith('default:') != bool(prefix):
                continue
            short = key[len(prefix):]
            if short.startswith('group:') or (short.startswith('user:') and short != 'user:'):
                acl[key] = perms(bits(acl[key]) & mask)
        needed = parent if parent else ('rwx' if directory or executable else 'rw-')
        key = prefix + f'group:{group_id}'
        acl[key] = perms(bits(acl.get(key, '---')) | bits(needed))
        if owner_id is not None:
            # A named user entry overrides their supplementary group membership.
            key = prefix + f'user:{owner_id}'
            if key in acl:
                acl[key] = perms(bits(acl[key]) | bits(needed))
            if not parent:
                acl[prefix + 'user:'] = perms(bits(acl.get(prefix + 'user:', '---')) | bits(needed))
        effective_mask = mask
        for key, value in acl.items():
            if key.startswith('default:') != bool(prefix):
                continue
            short = key[len(prefix):]
            if short.startswith('group:') or (short.startswith('user:') and short != 'user:'):
                effective_mask |= bits(value)
        acl[prefix + 'mask:'] = perms(effective_mask)
    return ','.join(f'{key}:{value}' for key, value in acl.items())


def apply_entry(entry, gid, uid=None, checkout=False, parent=None, administrator=None):
    with pinned(entry) as fd:
        st = os.fstat(fd)
        directory = stat.S_ISDIR(st.st_mode)
        text = acl_text(fd)
        if parent:
            acl = parse_acl(text)
            mask = bits(acl.get('mask:', 'rwx'))
            group_keys = ([f'group:{gid}'] if f'group:{gid}' in acl else [])
            if st.st_gid == gid:
                group_keys.append('group:')
            group_rights = (0 if group_keys else bits(acl['other:']))
            for key in group_keys:
                group_rights |= bits(acl[key]) & mask
            user_rights = group_rights
            if uid is not None:
                if st.st_uid == uid:
                    user_rights = bits(acl['user:'])
                elif f'user:{uid}' in acl:
                    user_rights = bits(acl[f'user:{uid}']) & mask
            if (group_rights & bits(parent) == bits(parent) and
                    user_rights & bits(parent) == bits(parent)):
                return  # Publicly traversable system ancestors need no ACL changes.
        if administrator is not None:
            original = parse_acl(text)
            needed = 'rwx' if directory or st.st_mode & 0o111 else 'rw-'
            original[f'user:{administrator}'] = needed
            if directory and 'default:user:' in original:
                original[f'default:user:{administrator}'] = 'rwx'
            # Set the existing mask wide enough for this intentional grant;
            # first freeze all unrelated entries at their current effective rights.
            for prefix in ('', 'default:'):
                if prefix and prefix + 'user:' not in original:
                    continue
                mask = bits(original.get(prefix + 'mask:', 'rwx'))
                for key in list(original):
                    short = key[len(prefix):]
                    if key.startswith('default:') != bool(prefix) or short == f'user:{administrator}':
                        continue
                    if short.startswith('group:') or (short.startswith('user:') and short != 'user:'):
                        original[key] = perms(bits(original[key]) & mask)
                original[prefix + 'mask:'] = perms(mask | bits(needed))
            text = '\n'.join(f'{key}:{value}' for key, value in original.items())
        if checkout and st.st_gid != gid:
            previous = parse_acl(text)
            previous_group = bits(previous['group:']) & bits(previous.get('mask:', 'rwx'))
            key = f'group:{st.st_gid}'
            previous[key] = perms(bits(previous.get(key, '---')) | previous_group)
            if 'default:group:' in previous:
                inherited = bits(previous['default:group:']) & bits(previous.get('default:mask:', 'rwx'))
                key = f'default:group:{st.st_gid}'
                previous[key] = perms(bits(previous.get(key, '---')) | inherited)
            text = '\n'.join(f'{key}:{value}' for key, value in previous.items())
        updated = acl_update(text, gid, uid, directory, bool(st.st_mode & 0o111), parent)
        if parent and uid == st.st_uid:
            updated_acl = parse_acl(updated.replace(',', '\n'))
            updated_acl['user:'] = perms(bits(updated_acl['user:']) | bits(parent))
            updated = ','.join(f'{key}:{value}' for key, value in updated_acl.items())
        if checkout:
            os.fchown(fd, uid if uid is not None else -1, gid)
        ACL_API.set(fd, updated)
        if checkout and directory:
            os.fchmod(fd, stat.S_IMODE(os.fstat(fd).st_mode) | stat.S_ISGID)


def parent_entries(paths, workspace):
    parents = set()
    for path in paths:
        parents.update(path.parents)
    result = []
    for path in sorted(parents, key=lambda p: (len(p.parts), str(p))):
        if path == Path('/'):
            continue
        checked_path(path)
        st = path.stat()
        result.append(((path, st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode)),
                       'r-x' if path.is_relative_to(workspace) else '--x'))
    return result


def verify(worktree, common, private, owner, workspace):
    # No project hooks, filters, fsmonitor, installations or real Git mutations.
    code = '''import os,tempfile,pathlib,stat
p=pathlib.Path(os.environ['HOME'])
args=__import__('sys').argv
root=pathlib.Path(args[1]); workspace=pathlib.Path(args[2])
for parent in root.parents:
 if parent != pathlib.Path('/') and not os.access(parent, os.X_OK): raise RuntimeError('cannot traverse '+str(parent))
for path in [root]+[pathlib.Path(p) for p in args[3:]]:
 for parent in path.parents:
  if parent.is_relative_to(workspace): os.listdir(parent)
with tempfile.TemporaryDirectory(prefix='.swarm-access-check-',dir=root) as d:
 f=pathlib.Path(d)/'file'; f.write_text('check'); f.chmod(0o600); f.rename(pathlib.Path(d)/'renamed')
for d in args[3:]:
 with tempfile.NamedTemporaryFile(prefix='swarm-access-check-',dir=d): pass
'''
    run(['/usr/bin/python3', '-I', '-c', code, str(worktree), str(workspace), str(common), str(private)], user=owner)
    git(worktree, owner, 'rev-parse', '--verify', 'HEAD')
    # Configure only this checkout, running as the target user (never as root).
    config = str(Path(owner.pw_dir) / '.gitconfig')
    current = run(['/usr/bin/git', 'config', '--file', config, '--get-all', 'safe.directory'],
                  user=owner, check=False)
    if current.returncode not in (0, 1):
        fail(f'cannot read {owner.pw_name}\'s Git trust configuration: {current.stderr.strip()}')
    if str(worktree) not in current.stdout.splitlines():
        run(['/usr/bin/git', 'config', '--file', config, '--add', 'safe.directory', str(worktree)], user=owner)
    run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
         '-C', str(worktree), 'rev-parse', '--verify', 'HEAD'], user=owner, global_config=config)


def main(argv=None):
    global ACL_API
    parser = argparse.ArgumentParser(prog='swarm access', description='Allocate an existing Swarm worktree to trusted collaborators (Linux).',
        epilog='Users must already exist. -u transfers checkout ownership and adds group membership. '
               'After allocation, log in again. Manual membership: sudo usermod -aG GROUP USER; '
               'inspect: getent group GROUP; id USER; remove: sudo gpasswd -d USER GROUP. '
               'Shared Git write access applies to the entire repository. No users are created.')
    parser.add_argument('targets', nargs='*', metavar='TARGET')
    parser.add_argument('-u', '--owner', help='existing user to own this checkout and join its group')
    parser.add_argument('--group', help='group name (default: swarm-REPO-WORK)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('-y', '--yes', action='store_true', help='accept reuse of an existing group')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        fail('access currently supports Linux only')
    # Account lookup deliberately precedes workspace discovery or any mutation.
    owner = account(args.owner) if args.owner else None
    if owner and owner.pw_uid == 0:
        fail('refusing to allocate a worktree to root')
    caller = actor()
    if not args.dry_run and os.geteuid() != 0:
        fail('applying access requires sudo; preview with --dry-run')
    if owner and os.geteuid() == 0:
        home = run(['/usr/bin/python3', '-I', '-c',
                    'import os,sys; sys.exit(0 if os.path.isdir(os.environ["HOME"]) and os.access(os.environ["HOME"], os.W_OK | os.X_OK) else 1)'],
                   user=owner, check=False)
        if home.returncode:
            fail(f'{owner.pw_name} needs an existing, writable home directory; no changes made')
    for tool in ('git', 'getfacl', 'setfacl', 'groupadd', 'usermod'):
        if not Path('/usr/bin' if tool in ('git', 'getfacl', 'setfacl') else '/usr/sbin', tool).is_file():
            fail(f'required tool missing: {tool} (install git, acl and account-management tools)')
    root, name, work, worktree, common, private = discover(args.targets, caller)
    group = args.group or f'swarm-{name}-{work}'
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', group):
        fail('group must be a Linux group name of at most 32 characters; choose --group')
    try:
        existing = grp.getgrnam(group)
    except KeyError:
        existing = None
    if existing and existing.gr_gid == 0:
        fail('refusing to reuse root group')
    ACL_API = ACL()
    checkout = inventory(worktree)
    metadata = inventory(common, metadata=True)
    parents = parent_entries([worktree, common, private], root)
    # ACL support is checked without writing, including default ACL syntax.
    for entry in checkout + metadata + [e for e, _ in parents]:
        with pinned(entry) as fd:
            acl_text(fd)
    print(f'Worktree: {worktree}\nOwner: {args.owner or "preserve existing owners"}\nGroup: {group}')
    print(f'Shared Git (ownership preserved): {common}\nPrivate Git: {private}')
    print(f'Scope: {len(checkout)} checkout entries; {len(metadata)} shared Git entries')
    for entry, rights in parents:
        print(f'Parent {rights}: {entry[0]}')
    print('Parent listing exposes sibling names. Shared Git access includes other branches and worktree metadata.')
    if existing:
        print(f'Existing group: {group} (GID {existing.gr_gid}); members: {", ".join(existing.gr_mem) or "none listed"}')
    else:
        print(f'Create group: {group}')
    if owner:
        print(f'Add {owner.pw_name} to {group}; transfer ownership of checkout entries only.')
        print(f'Add exact checkout safe.directory to {Path(owner.pw_dir) / ".gitconfig"} as that user.')
    print(f'Preserve administrator {caller.pw_name} access through named checkout and Git ACLs.')
    if args.dry_run:
        print('DRY-RUN: no changes made. Stop active writers before applying.')
        return
    if existing and not args.yes:
        if not sys.stdin.isatty() or input('Reuse this existing group? [y/N]: ').lower() not in ('y', 'yes'):
            fail('existing-group reuse requires confirmation or --yes; no changes made')
    completed = []
    current = 'revalidate paths'
    try:
        # Recheck all inventoried inodes before the first mutation.
        for entry in checkout + metadata + [e for e, _ in parents]:
            with pinned(entry):
                pass
        if not existing:
            current = f'create group {group}'
            run(['/usr/sbin/groupadd', '--', group])
            existing = grp.getgrnam(group)
            completed.append(current)
        if owner:
            current = f'add {owner.pw_name} to {group}'
            run(['/usr/sbin/usermod', '-a', '-G', group, '--', owner.pw_name])
            completed.append(current)
        for entry, rights in parents:
            current = f'parent access: {entry[0]}'
            apply_entry(entry, existing.gr_gid, owner.pw_uid if owner else None, parent=rights)
        completed.append('parent access')
        for entry in metadata:
            current = f'Git metadata access: {entry[0]}'
            apply_entry(entry, existing.gr_gid, owner.pw_uid if owner else None,
                        administrator=caller.pw_uid)
        completed.append('shared Git ACLs (ownership preserved)')
        for entry in checkout:
            current = f'checkout access: {entry[0]}'
            apply_entry(entry, existing.gr_gid, owner.pw_uid if owner else None,
                        checkout=True, administrator=caller.pw_uid)
        completed.append('checkout ownership and inherited permissions')
        if owner:
            current = f'verify access as {owner.pw_name}'
            verify(worktree, common, private, owner, root)
            completed.append(current)
    except (AccessError, OSError) as exc:
        fail(f'partial allocation stopped at {current}: {exc}\nCompleted: {", ".join(completed) or "none"}. '
             'Changes are not rolled back; correct the failure and rerun.')
    print('Access allocated successfully.')
    if owner:
        print(f'Log out and back in as {owner.pw_name}, then install dependencies as that user.')
    print('Existing private interpreter targets/caches outside this checkout may need separate setup.')
    print('Commit identity, signing and remote push credentials remain the user\'s responsibility.')


if __name__ == '__main__':
    try:
        main()
    except (AccessError, OSError, ValueError, KeyError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        sys.exit(1)
