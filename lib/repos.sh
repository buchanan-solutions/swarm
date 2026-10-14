# Shared repository/path rules for swarm and its bundled worktree helper.
validate_repo_name() {
  local repo="$1" part
  [[ -n "$repo" && "$repo" != /* && "$repo" != *$'\n'* && "$repo" != *$'\t'* && "$repo" != *'__'* ]] || die "invalid repository path: $repo"
  local parts=()
  IFS=/ read -r -a parts <<< "$repo"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. ]] || die "invalid repository path: $repo"
  done
  [[ "$repo" != */ ]] || die "invalid repository path: $repo"
}

is_checkout_root() {
  local root
  [[ -d "$1" ]] || return 1
  root="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [[ "$(realpath "$1")" == "$(realpath "$root")" ]]
}

linked_main_checkout() {
  local gd common
  gd="$(git -C "$1" rev-parse --absolute-git-dir 2>/dev/null)" || return 1
  common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [[ "$gd" != "$common" ]] || return 1
  local worktree
  worktree="$(git --git-dir="$common" config --get core.worktree || true)"
  if [[ -n "$worktree" ]]; then
    if [[ "$worktree" == /* ]]; then realpath -m "$worktree"
    else realpath -m "$common/$worktree"; fi
  else
    git -C "$1" worktree list --porcelain | sed -n '1s/^worktree //p'
  fi
}

require_main_checkout() {
  local main
  if main="$(linked_main_checkout "$1")"; then
    die "linked worktree cannot be initialized or registered; main checkout: $main"
  fi
}

safe_repo_path() {
  validate_repo_name "$1"
  local resolved
  resolved="$(realpath -m "$2/$1")"
  [[ "$resolved" == "$2/"* ]] || die "repository path escapes repos_dir: $1"
  printf '%s\n' "$resolved"
}
