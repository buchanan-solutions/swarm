# Public identities are repo-name + work-ID; locations are resolved through Git.
managed_id_for_path() {
  local name="$1" path="$2" work
  work="$(managed_work_id "$name" "$path" "$(repo_abs "$name")" "$WORKTREES_DIR" "$(repo_relative "$name")" "$(legacy_mode "$name" "$(repo_relative "$name")" "$SWARM_ROOT")")" || return 1
  printf '%s___%s' "$name" "$work"
}

normalize_worktree_id() {
  local arg="${1:-}" name work id
  if [[ "$arg" == /* ]]; then
    arg="$(realpath -m "$arg")"
    for name in "${REPOS_LIST[@]}"; do
      if id="$(managed_id_for_path "$name" "$arg")"; then printf '%s' "$id"; return; fi
    done
    die "not a managed worktree path: $arg"
  fi
  [[ "$arg" == *___* ]] || die "expected repo-name___work-ID: $arg"
  name="${arg%%___*}"; work="${arg#*___}"
  repo_authorized "$name" || die "repo not registered: $name"
  validate_work_id "$work"
  printf '%s___%s' "$name" "$work"
}

resolve_work_target() {
  local name work
  if [[ $# -eq 2 ]]; then name="$(resolve_repo_selector "$1")"; work="$2"
  elif [[ $# -eq 1 ]]; then
    if repo_authorized "$1"; then die "work ID required after repo name: $1"; fi
    if [[ "$1" == /* || "$1" == *___* ]]; then normalize_worktree_id "$1"; return; fi
    [[ -n "$CURRENT_REPO" ]] || die "supply a repo name and work ID, or run inside a registered checkout"
    name="$CURRENT_REPO"; work="$1"
  else die "expected [repo-name] <work-ID>"; fi
  validate_work_id "$work"
  printf '%s___%s' "$name" "$work"
}

infer_current_repo() {
  local top name canonical
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || return 0
  top="$(realpath "$top")"
  for name in "${REPOS_LIST[@]}"; do
    canonical="$(repo_abs "$name")"
    if [[ "$top" == "$canonical" ]]; then printf '%s' "$name"; return; fi
    if managed_id_for_path "$name" "$top" >/dev/null && is_checkout_root "$canonical" && same_repository "$top" "$canonical"; then
      printf '%s' "$name"; return
    fi
  done
}

worktree_abs() {
  local id name
  id="$(normalize_worktree_id "$1")"; name="${id%%___*}"
  resolve_managed_worktree "$name" "${id#*___}" "$(repo_abs "$name")" "$WORKTREES_DIR" "$(repo_relative "$name")" "$(legacy_mode "$name" "$(repo_relative "$name")" "$SWARM_ROOT")"
}
canonical_abs() { local id; id="$(normalize_worktree_id "$1")"; repo_abs "${id%%___*}"; }
parse_id() { _id="$(normalize_worktree_id "$1")"; _repo="${_id%%___*}"; _work="${_id#*___}"; }
marker_path() { printf '%s/%s' "$SUBMISSIONS_DIR" "$(normalize_worktree_id "$1")"; }
has_submission() { [[ -f "$(marker_path "$1")" ]]; }
is_submitted() { has_submission "$1"; }
touch_submission() { local m; m="$(marker_path "$1")"; : > "$m"; info "submitted: ${m##*/}"; }
clear_submission() { local m; m="$(marker_path "$1")"; if [[ -f "$m" ]]; then rm -- "$m"; info "cleared submission marker: ${m##*/}"; fi; }

ensure_worktree() {
  local id canonical wt registered
  id="$(normalize_worktree_id "$1")"
  canonical="$(require_repo "${id%%___*}")"
  wt="$(worktree_abs "$id")"
  is_checkout_root "$wt" || die "worktree missing or invalid: $wt"
  same_repository "$wt" "$canonical" || die "worktree belongs to another repository: $wt"
  registered_worktree_paths "$canonical" | grep -Fx -- "$wt" >/dev/null || die "checkout is not a registered worktree: $wt"
  printf '%s' "$wt"
}

resolve_path_target() {
  if [[ $# -eq 0 ]]; then
    [[ -n "$CURRENT_REPO" ]] || die "supply a repo name or run inside a registered checkout"
    require_repo "$CURRENT_REPO"
  elif [[ $# -eq 1 ]] && repo_authorized "$1"; then require_repo "$1"
  else ensure_worktree "$(resolve_work_target "$@")"; fi
}
cmd_path() { local path; path="$(resolve_path_target "$@")"; printf '%s\n' "$path"; }
cmd_open() {
  local launcher="" flag path args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --cursor|--claude|--codex)
        [[ -z "$launcher" ]] || die "choose only one of --cursor, --claude, or --codex"
        launcher="${1#--}" ;;
      -*) die "unknown open flag: $1" ;;
      *) args+=("$1") ;;
    esac
    shift
  done
  launcher="${launcher:-$DEFAULT_IDE}"
  [[ -n "$launcher" ]] || die "No default IDE configured. Pass --cursor, --claude, or --codex, or set default_ide in swarm.json."
  command -v "$launcher" >/dev/null 2>&1 || die "launcher executable not found: $launcher"
  path="$(resolve_path_target "${args[@]}")"
  case "$launcher" in
    cursor) cursor --new-window "$path" ;;
    claude) (cd "$path" && exec claude) ;;
    codex) codex --cd "$path" ;;
  esac
}

# A worktree of a workspace-root repo contains a tracked copy of swarm.json.
# Resolve that copy back to its owning workspace rather than creating a new root.
is_copied_root_config() {
  local candidate="$1" top main name legacy=0
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || return 1
  [[ "$candidate" == "$top" ]] || return 1
  main="$(linked_main_checkout "$PWD")" || return 1
  [[ -f "$main/swarm.json" ]] || return 1
  while IFS= read -r name; do
    if managed_work_id "$name" "$top" "$main" "$main/.swarm/worktrees" . "$(legacy_mode "$name" . "$main")" >/dev/null; then return 0; fi
  done < <(jq -r '.repos | objects | to_entries[] | select(.value == ".") | .key' "$main/swarm.json" 2>/dev/null)
  return 1
}
