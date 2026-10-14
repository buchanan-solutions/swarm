# Explicit v1 -> v2 migration. Existing Git worktrees are never moved.
cmd_migrate() {
  local dry=0
  case "${1:-}" in '' ) ;; --dry-run) dry=1; shift ;; *) die "usage: swarm migrate [--dry-run]" ;; esac
  [[ $# -eq 0 ]] || die "usage: swarm migrate [--dry-run]"
  if [[ "$CONFIG_VERSION" == 2 ]]; then
    if [[ "$dry" == 0 ]]; then finish_migration_cleanup; ensure_gitignore_swarm_block; fi
    info "Already version 2: $SWARM_CONFIG_PATH"
    return
  fi
  local target="$SWARM_ROOT/.swarm" prefix old_state="$STATE_DIR"
  prefix="$(realpath --relative-to="$SWARM_ROOT" "$REPOS_DIR")"
  [[ "$prefix" != . ]] || prefix=""
  inspect_swarm_managed_block "$SWARM_ROOT/.gitignore"
  [[ "$_SWARM_BLOCK_STATE" != malformed ]] || die_malformed_managed_block "$SWARM_ROOT/.gitignore" gitignore 'swarm migrate'
  # All target directories must remain under the workspace, including symlinks.
  local resolved
  resolved="$(realpath -m "$target")"
  [[ "$resolved" == "$SWARM_ROOT/"* ]] || die ".swarm escapes the workspace"
  if [[ "$dry" == 1 ]]; then
    info "DRY-RUN: convert repo paths to workspace-relative paths; fix state at .swarm; preserve existing worktrees and swarm.md"
    jq --arg prefix "$prefix" '.version=2 | .repos |= map(if $prefix == "" then . else $prefix + "/" + . end) | del(.repos_dir,.state_dir)' "$SWARM_CONFIG_PATH"
    return
  fi
  (
    flock -x 9
    # Another migration may have completed while this process waited.
    if [[ "$(jq -r .version "$SWARM_CONFIG_PATH")" == 2 ]]; then
      info "Already version 2: $SWARM_CONFIG_PATH"; exit 0
    fi
    local backup="$target/migration-v1" tmp marker relative new_relative dest old_id repo
    mkdir -p "$backup/submissions" "$target/submissions"
    if [[ -f "$backup/config.json" ]]; then
      cmp -s "$backup/config.json" "$SWARM_CONFIG_PATH" || die "migration backup differs from current config; inspect $backup before retrying"
    else cp -p "$SWARM_CONFIG_PATH" "$backup/config.json"; fi
    if [[ ! -f "$backup/submissions.complete" ]]; then
      cp -a "$SUBMISSIONS_DIR/." "$backup/submissions/"
      : > "$backup/submissions.complete"
    fi
    local pending=() sources=() destinations=()
    while IFS= read -r -d '' marker; do
      relative="${marker#"$backup/submissions"/}"
      old_id="$relative"
      if [[ "$relative" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+__)(.+__.+)$ ]]; then
        old_id="${BASH_REMATCH[2]}"
      fi
      repo="${old_id%%__*}"
      if [[ -n "$prefix" ]]; then new_relative="$prefix/$old_id"; else new_relative="$old_id"; fi
      # Canonicalize known timestamp markers; retain unknown orphan identities.
      if ! repo_authorized "$repo"; then new_relative="${prefix:+$prefix/}$relative"; fi
      dest="$target/submissions/$new_relative"
      if [[ -f "$dest" && "$SUBMISSIONS_DIR/$relative" != "$dest" ]]; then
        cmp -s "$marker" "$dest" || die "submission collision: $dest"
      fi
      sources+=("$marker"); destinations+=("$dest")
      if [[ "$old_state" == "$target" && "$SUBMISSIONS_DIR/$relative" != "$dest" ]]; then pending+=("$SUBMISSIONS_DIR/$relative"); fi
    done < <(find "$backup/submissions" -type f -print0)
    # Persist the cleanup journal first, allowing safe retry after interruption.
    tmp="$(mktemp "$backup/.pending.XXXXXX")"
    if [[ ${#pending[@]} -gt 0 ]]; then printf '%s\n' "${pending[@]}" | jq -R -s 'split("\n")[:-1]' > "$tmp"
    else printf '[]\n' > "$tmp"; fi
    mv "$tmp" "$backup/pending-cleanup.json"
    local i
    for ((i=0;i<${#sources[@]};i++)); do
      marker="${sources[i]}"; dest="${destinations[i]}"
      relative="${marker#"$backup/submissions"/}"
      mkdir -p "$(dirname "$dest")"
      cp -p "$marker" "$dest"
    done
    tmp="$(mktemp "$SWARM_ROOT/.swarm-config.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    jq --arg prefix "$prefix" '.version=2 | .repos |= map(if $prefix == "" then . else $prefix + "/" + . end) | del(.repos_dir,.state_dir)' "$SWARM_CONFIG_PATH" > "$tmp"
    chmod --reference="$SWARM_CONFIG_PATH" "$tmp"
    mv "$tmp" "$SWARM_CONFIG_PATH"
  ) 9>"$STATE_DIR/config.lock"
  load_swarm_config_from_path
  finish_migration_cleanup
  ensure_gitignore_swarm_block
  info "Migrated to version 2. Existing worktrees stayed in place; new worktrees use .swarm/worktrees/."
  info "Version 1 config and submission backup: $STATE_DIR/migration-v1"
}

finish_migration_cleanup() {
  local journal="$STATE_DIR/migration-v1/pending-cleanup.json" marker
  [[ -f "$journal" ]] || return 0
  while IFS= read -r marker; do
    # Journal cleanup must never touch anything outside the old local inbox.
    [[ "$marker" == "$STATE_DIR/submissions/"* && "$(realpath -m "$marker")" == "$STATE_DIR/submissions/"* ]] || die "invalid migration cleanup path: $marker"
    [[ -f "$marker" ]] && rm -- "$marker"
  done < <(jq -r '.[]' "$journal")
  rm -- "$journal"
}
