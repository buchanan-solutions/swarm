# Shared repository/path rules for swarm and its bundled worktree helper.
valid_identifier() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$1" != *___* ]]
}
validate_work_id() { valid_identifier "$1" || die "invalid work ID: $1 (reserve ___ as the separator)"; }
valid_repo_name() { valid_identifier "$1" && [[ "$1" != *_ ]]; }
validate_repo_name() { valid_repo_name "$1" || die "invalid repo name: $1 (reserve ___ and do not end with _)"; }

validate_repo_path() {
  local path="$1" part
  [[ -n "$path" && "$path" != /* && "$path" != *$'\n'* && "$path" != *$'\t'* && "$path" != *$'\r'* ]] || die "invalid repo path: $path"
  [[ "$path" != . ]] || return 0
  local parts=()
  IFS=/ read -r -a parts <<< "$path"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. ]] || die "invalid repo path: $path"
  done
  [[ "$path" != */ ]] || die "invalid repo path: $path"
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
  validate_repo_path "$1"
  local resolved
  resolved="$(realpath -m "$2/$1")"
  [[ "$resolved" == "$2" || "$resolved" == "$2/"* ]] || die "repository path escapes its workspace boundary: $1"
  printf '%s\n' "$resolved"
}

# Both the public CLI and the internal helper use these location rules.
# Historical forms are enabled only by a static migration snapshot.
managed_work_id() {
  local name="$1" path="$2" canonical="$3" trees="$4" relative="$5" legacy="${6:-0}"
  local prefix work prefixes=("$trees/${name}___")
  if [[ "$legacy" == 1 ]]; then prefixes+=("${canonical}__" "$trees/${relative}__"); fi
  for prefix in "${prefixes[@]}"; do
    if [[ "$path" == "$prefix"* ]]; then
      work="${path#"$prefix"}"
      valid_identifier "$work" || return 1
      printf '%s' "$work"; return
    fi
  done
  return 1
}

registered_worktree_paths() {
  git -C "$1" -c core.quotePath=false worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p'
}

same_repository() {
  local first second
  first="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  second="$(git -C "$2" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [[ "$first" == "$second" ]]
}

resolve_managed_worktree() {
  local name="$1" work="$2" canonical="$3" trees="$4" relative="$5" legacy="${6:-0}"
  local path found_work matches=()
  while IFS= read -r path; do
    if found_work="$(managed_work_id "$name" "$path" "$canonical" "$trees" "$relative" "$legacy")" && [[ "$found_work" == "$work" ]]; then
      matches+=("$path")
    fi
  done < <(registered_worktree_paths "$canonical")
  [[ ${#matches[@]} -le 1 ]] || die "multiple worktrees for $name/$work; resolve duplicate checkouts first"
  if [[ ${#matches[@]} -eq 1 ]]; then printf '%s\n' "${matches[0]}"
  else printf '%s/%s___%s\n' "$trees" "$name" "$work"; fi
}

legacy_mode() {
  local name="$1" relative="$2" root="$3"
  if [[ -f "$root/.swarm/migration/config.json" && -f "$root/.swarm/migration/plan.json" ]] &&
     jq -e --arg name "$name" --arg relative "$relative" '.repos[$name] == $relative' "$root/.swarm/migration/plan.json" >/dev/null; then
    printf 1
  else printf 0; fi
}
