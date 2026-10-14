# Workspace registration and health reporting (sourced by swarm).
cmd_init() {
  [[ $# -eq 0 ]] || die "usage: swarm init"
  require_jq
  require_main_checkout "$PWD"
  SWARM_ROOT="$(pwd -P)"
  SWARM_CONFIG_PATH="$SWARM_ROOT/$SWARM_CONFIG_NAME"
  if [[ -e "$SWARM_CONFIG_PATH" ]]; then
    load_swarm_config_from_path
    info "Already initialized: $SWARM_ROOT"
    return
  fi
  init_new_workspace explicit
  load_swarm_config_from_path
  ensure_gitignore_swarm_block
  ensure_swarm_md
}

cmd_add() {
  [[ $# -eq 1 ]] || die "usage: swarm add <path>"
  local path repo tmp
  path="$(realpath -e -- "$1")" || die "path does not exist: $1"
  is_checkout_root "$path" || die "not a Git checkout root: $path"
  require_main_checkout "$path"
  [[ "$path" == "$REPOS_DIR/"* ]] || die "repo must be beneath the workspace repo root: $REPOS_DIR"
  repo="${path#"$REPOS_DIR"/}"
  validate_repo_name "$repo"
  [[ "$CONFIG_VERSION" != 2 || "$repo" != .swarm && "$repo" != .swarm/* ]] || die "cannot register a repo inside Swarm state"
  if repo_authorized "$repo"; then
    info "Already registered: $repo"
    return
  fi
  # Serialize registration updates and rename a sibling tempfile atomically.
  (
    flock -x 9
    if jq -e --arg repo "$repo" '.repos | index($repo) != null' "$SWARM_CONFIG_PATH" >/dev/null; then
      info "Already registered: $repo"
      exit 0
    fi
    tmp="$(mktemp "$SWARM_ROOT/.swarm-config.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    jq --arg repo "$repo" '.repos += [$repo]' "$SWARM_CONFIG_PATH" > "$tmp"
    chmod --reference="$SWARM_CONFIG_PATH" "$tmp"
    mv -- "$tmp" "$SWARM_CONFIG_PATH"
    info "Registered: $repo"
  ) 9>"$STATE_DIR/config.lock"
}

# TSV rows are formatted after collection so long paths keep columns aligned.
aligned_table() {
  awk -F '\t' '
    { for (i=1;i<=NF;i++) { cell[NR,i]=$i; if(length($i)>width[i])width[i]=length($i) } rows=NR; cols=NF }
    END { for(r=1;r<=rows;r++) { for(i=1;i<=cols;i++) printf "%-*s%s",width[i],cell[r,i],(i==cols ? "\n" : "  ") } }
  '
}

checkout_size() {
  local path="$1" scan="$2" refresh="$3" key cache identity now timestamp bytes stored
  [[ -d "$path" ]] || { printf 'unknown'; return; }
  key="$(printf '%s' "$path" | sha256sum | cut -d' ' -f1)"
  cache="$STATE_DIR/sizes/$key.json"
  local gitdir
  gitdir="$(git -C "$path" rev-parse --absolute-git-dir 2>/dev/null || true)"
  identity="$(stat -c '%d:%i' "$path")/$gitdir/$(stat -c '%d:%i' "$gitdir" 2>/dev/null || true)"
  now="$(date +%s)"
  timestamp=0; bytes=""; stored=""
  local cached
  if [[ -f "$cache" ]] && cached="$(jq -er '
    select((.timestamp | type) == "number" and (.bytes | type) == "number" and (.identity | type) == "string") |
    select(.timestamp >= 0 and .bytes >= 0 and .timestamp == (.timestamp | floor) and .bytes == (.bytes | floor)) |
    [.timestamp, .bytes, .identity] | @tsv' "$cache" 2>/dev/null)"; then
    IFS=$'\t' read -r timestamp bytes stored <<< "$cached"
  fi
  if [[ "$stored" != "$identity" ]]; then bytes=""; fi
  if [[ "$scan" == 1 && ( "$refresh" == 1 || -z "$bytes" || $((now-timestamp)) -ge 86400 ) ]]; then
    if bytes="$(du -s -B1 -- "$path" 2>/dev/null)"; then
      bytes="${bytes%%$'\t'*}"
      timestamp="$now"
      mkdir -p "$STATE_DIR/sizes"
      local tmp
      tmp="$(mktemp "$STATE_DIR/sizes/.size.XXXXXX")"
      jq -n --arg identity "$identity" --argjson bytes "$bytes" --argjson timestamp "$timestamp" \
        '{identity:$identity,bytes:$bytes,timestamp:$timestamp}' > "$tmp"
      mv "$tmp" "$cache"
    else
      printf 'unreadable'; return
    fi
  fi
  if [[ -n "$bytes" ]]; then
    printf '%s (cached %s)' "$(numfmt --to=iec --suffix=B "$bytes")" "$(date -u -d "@$timestamp" '+%Y-%m-%dT%H:%MZ')"
  else
    printf 'unknown'
  fi
}

status_tables() {
  local selected="$1" scan="$2" refresh="$3" list_only="${4:-0}"
  local repo canon wt branch line health count id dirty kind size record primary
  local summaries=() details=() seen=()
  summaries+=($'REPO\tHEALTH\tLINKED WORKTREES')
  details+=($'REPO\tCHECKOUT / WORKTREE\tBRANCH\tGIT\tSWARM\tHEALTH\tSIZE')
  for repo in "${REPOS_LIST[@]}"; do
    [[ -z "$selected" || "$repo" == "$selected" ]] || continue
    canon="$REPOS_DIR/$repo"
    health=OK; count=0
    if ! is_checkout_root "$canon"; then
      health=MISSING/INVALID
      summaries+=("$repo"$'\t'"$health"$'\t'"?")
      continue
    fi
    if linked_main_checkout "$canon" >/dev/null; then
      summaries+=("$repo"$'\t'"LINKED-WORKTREE"$'\t'"?")
      continue
    fi
    wt=""; branch=""; record=""; primary=1
    while IFS= read -r line; do
      case "$line" in
        worktree\ *) wt="${line#worktree }"
          # Git may report a submodule's common gitdir as its primary path.
          if [[ "$primary" == 1 ]]; then wt="$canon"; primary=0; fi
          branch=DETACHED; record=OK ;;
        branch\ *) branch="${line#branch refs/heads/}" ;;
        prunable*) record=PRUNABLE ;;
        locked*) record=LOCKED ;;
        '')
          [[ -n "$wt" ]] || continue
          kind=EXTERNAL; id=""
          if [[ "$wt" == "$canon" ]]; then kind=CANONICAL
          else count=$((count+1)); fi
          if id="$(managed_id_for_path "$repo" "$wt")"; then
            kind=ACTIVE
            seen+=("$id")
          fi
          dirty=unknown
          if is_checkout_root "$wt" && [[ "$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir)" == "$(git -C "$canon" rev-parse --path-format=absolute --git-common-dir)" ]]; then
            dirty="$(working_tree_state "$wt")"
            if [[ -n "$id" ]]; then kind="$(swarm_state "$wt")"; fi
          else record=MISSING/INVALID; fi
          size=unknown
          if [[ "$list_only" != 1 && "$record" != MISSING/INVALID ]]; then size="$(checkout_size "$wt" "$scan" "$refresh")"; fi
          if [[ "$list_only" != 1 || -n "$id" ]]; then
            details+=("$repo"$'\t'"${wt#"$SWARM_ROOT"/}"$'\t'"$branch"$'\t'"$dirty"$'\t'"$kind"$'\t'"$record"$'\t'"$size")
          fi
          wt="" ;;
      esac
    done < <(git -C "$canon" worktree list --porcelain; printf '\n')
    summaries+=("$repo"$'\t'"$health"$'\t'"$count")
  done
  local marker found entry
  while IFS= read -r -d '' marker; do
    id="${marker#"$SUBMISSIONS_DIR"/}"
    if [[ "$id" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+__(.+__.+)$ ]]; then id="${BASH_REMATCH[1]}"; fi
    repo="${id%%__*}"
    [[ -z "$selected" || "$selected" == "$repo" ]] || continue
    found=0
    for entry in "${seen[@]}"; do [[ "$entry" != "$id" ]] || found=1; done
    if [[ "$found" == 0 ]]; then
      details+=("$repo"$'\t'"$id"$'\t-\tunknown\tSUBMITTED\tORPHAN\tunknown')
    fi
  done < <(find "$SUBMISSIONS_DIR" -type f -print0)
  info "Workspace: $SWARM_ROOT"
  if [[ "$list_only" != 1 ]]; then printf '\n'; printf '%s\n' "${summaries[@]}" | aligned_table; fi
  printf '\n'; printf '%s\n' "${details[@]}" | aligned_table
  if [[ "$list_only" != 1 ]]; then info ""; info "Sizes are allocated per-directory usage, including ignored files; cached measurements are not reclaimable-space estimates."; fi
}

cmd_status() {
  local selected="" scan=0 refresh=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sizes) scan=1 ;;
      --refresh-sizes) scan=1; refresh=1 ;;
      -*) die "unknown status flag: $1" ;;
      *) [[ -z "$selected" ]] || die "usage: swarm status [repo-path] [--sizes | --refresh-sizes]"
         selected="$1" ;;
    esac
    shift
  done
  if [[ -n "$selected" ]]; then
    selected="$(resolve_repo_selector "$selected")"
    if ! repo_authorized "$selected"; then
      local resolved
      resolved="$(realpath -m "$selected")"
      selected="${resolved#"$REPOS_DIR"/}"
    fi
    repo_authorized "$selected" || die "repo not registered: $selected"
  fi
  status_tables "$selected" "$scan" "$refresh"
}

resolve_repo_selector() {
  local arg="$1" resolved
  if repo_authorized "$arg"; then printf '%s' "$arg"; return; fi
  if [[ -n "$LEGACY_REPOS_PREFIX" ]] && repo_authorized "$LEGACY_REPOS_PREFIX/$arg"; then
    printf '%s/%s' "$LEGACY_REPOS_PREFIX" "$arg"; return
  fi
  resolved="$(realpath -m "$arg")"
  arg="${resolved#"$REPOS_DIR"/}"
  if repo_authorized "$arg"; then printf '%s' "$arg"; return; fi
  return 1
}

# Keep only precise ignores for legacy worktrees; never hide unrelated __ dirs.
gitignore_literal() {
  local text="$1"
  text="${text//\\/\\\\}"; text="${text//\*/\\*}"
  text="${text//\?/\\?}"; text="${text//\[/\\[}"
  text="${text// /\\ }"
  printf '/%s/\n' "$text"
}

workspace_ignore_rules() {
  printf '# Swarm local state and worktrees\n.swarm/\n'
  if [[ "$CONFIG_VERSION" == 1 ]]; then
    printf '\n# Legacy sibling worktrees (run swarm migrate to use precise rules)\n*__*/\n'
    return
  fi
  local repo path legacy_state
  if [[ -f "$STATE_DIR/migration-v1/config.json" ]]; then
    legacy_state="$(jq -r '.state_dir' "$STATE_DIR/migration-v1/config.json")"
    if [[ "$legacy_state" == . ]]; then
      gitignore_literal submissions; gitignore_literal sizes
    elif [[ "$legacy_state" != .swarm ]]; then gitignore_literal "$legacy_state"; fi
  fi
  for repo in "${REPOS_LIST[@]}"; do
    while IFS= read -r path; do
      path="${path#worktree }"
      if [[ "$path" == "$REPOS_DIR/${repo}__"* ]]; then
        gitignore_literal "${path#"$SWARM_ROOT"/}"
      fi
    done < <(git -C "$REPOS_DIR/$repo" worktree list --porcelain 2>/dev/null | sed -n '/^worktree /p')
  done
}
