# Migration snapshots describe the old configuration, never active worktrees.
cmd_migrate() {
  require_jq
  local dry=0 yes=0
  while [[ $# -gt 0 ]]; do
    case "$1" in --dry-run) dry=1 ;; --yes|-y) yes=1 ;; *) die "usage: swarm migrate [--dry-run] [--yes]" ;; esac
    shift
  done
  jq -e 'type == "object"' "$SWARM_CONFIG_PATH" >/dev/null 2>&1 || die "invalid Swarm configuration JSON"
  local version shape original_hash default_ide
  version="$(jq -r '.version' "$SWARM_CONFIG_PATH")"
  shape="$(jq -r '.repos | type' "$SWARM_CONFIG_PATH")"
  if [[ "$version" == 2 && "$shape" == object ]]; then
    load_swarm_config_from_path
    if [[ "$dry" == 0 ]]; then finish_migration_cleanup; ensure_gitignore_swarm_block; fi
    info "Already named-repo version 2: $SWARM_CONFIG_PATH"; return
  fi
  [[ ( "$version" == 1 || "$version" == 2 ) && "$shape" == array ]] || die "migration expects version 1 or early version 2 with a repos array"
  jq -e '(if has("default_ide") then .default_ide else "" end) as $ide | ($ide | type) == "string" and (["", "cursor", "claude", "codex"] | index($ide) != null)' "$SWARM_CONFIG_PATH" >/dev/null || die "invalid default_ide"
  jq -e '.repos | all(.[]; type == "string" and (test("[\n\r\t]") | not))' "$SWARM_CONFIG_PATH" >/dev/null || die "invalid old repo paths"
  original_hash="$(sha256sum "$SWARM_CONFIG_PATH" | cut -d' ' -f1)"
  local prefix="" old_state="$SWARM_ROOT/.swarm" repo_base="$SWARM_ROOT" rel
  if [[ "$version" == 1 ]]; then
    jq -e '(.repos_dir | type) == "string" and (.state_dir | type) == "string"' "$SWARM_CONFIG_PATH" >/dev/null || die "version 1 requires repos_dir and state_dir"
    repo_base="$(safe_repo_path "$(jq -r .repos_dir "$SWARM_CONFIG_PATH")" "$SWARM_ROOT")"
    old_state="$(safe_repo_path "$(jq -r .state_dir "$SWARM_CONFIG_PATH")" "$SWARM_ROOT")"
  fi
  local target="$SWARM_ROOT/.swarm" backup="$SWARM_ROOT/.swarm/migration"
  local entry path name answer default entries=() relatives=() paths=() mapping='{}' keys='{}' conflict=0 existing
  while IFS= read -r entry; do
    path="$(safe_repo_path "$entry" "$repo_base")"
    [[ "$path" != "$target" && "$path" != "$target/"* ]] || die "repo points inside .swarm: $entry"
    for existing in "${paths[@]}"; do [[ "$existing" != "$path" ]] || die "duplicate canonical checkout: $entry"; done
    paths+=("$path"); entries+=("$entry")
    relatives+=("$(realpath -m --relative-to="$SWARM_ROOT" "$path")")
  done < <(jq -r '.repos[]' "$SWARM_CONFIG_PATH")
  inspect_swarm_managed_block "$SWARM_ROOT/.gitignore"
  [[ "$_SWARM_BLOCK_STATE" != malformed ]] || die_malformed_managed_block "$SWARM_ROOT/.gitignore" gitignore 'swarm migrate'
  local i
  # A persisted plan is reused only for the identical source configuration.
  if [[ -f "$backup/config.json" && -f "$backup/plan.json" ]]; then
    cmp -s "$backup/config.json" "$SWARM_CONFIG_PATH" || die "migration snapshot differs from config; inspect $backup"
    mapping="$(jq -c .repos "$backup/plan.json")"
    keys="$(jq -c .keys "$backup/plan.json")"
    info "Resuming saved migration naming plan."
  else
    if [[ "$dry" == 0 && "$yes" == 0 && ${#entries[@]} -gt 0 && ! -t 0 ]]; then
      die "migration naming requires a terminal; use --yes to accept unique folder-name defaults"
    fi
    for ((i=0;i<${#entries[@]};i++)); do
      path="${paths[i]}"; default="$(basename "$path")"
      info "Repo: $path"
      while true; do
        name="$default"
        if [[ "$dry" == 0 && "$yes" == 0 ]]; then
          printf 'What do you want to name this repo? [%s]\nPress Enter to use the repo folder name: ' "$default" >&2
          read -r answer || die "migration cancelled; configuration and submissions unchanged"
          name="${answer:-$default}"
        fi
        if ! valid_repo_name "$name" || jq -e --arg name "$name" 'has($name)' <<< "$mapping" >/dev/null; then
          warn "invalid or duplicate repo name: $name; choose a unique name"
          if [[ "$dry" == 1 ]]; then conflict=1; break; fi
          [[ "$yes" == 0 ]] || die "default names conflict; rerun migration interactively"
          continue
        fi
        break
      done
      if valid_repo_name "$name" && ! jq -e --arg name "$name" 'has($name)' <<< "$mapping" >/dev/null; then
        mapping="$(jq --arg name "$name" --arg path "${relatives[i]}" '.[$name]=$path' <<< "$mapping")"
        keys="$(jq --arg entry "${entries[i]}" --arg name "$name" '.[$entry]=$name' <<< "$keys")"
      fi
    done
  fi
  if [[ "$dry" == 1 ]]; then
    info "DRY-RUN: proposed named-repo version 2; existing checkouts stay in place."
    jq --argjson repos "$mapping" '.version=2 | .repos=$repos | .default_ide=(.default_ide // "") | del(.repos_dir,.state_dir)' "$SWARM_CONFIG_PATH"
    [[ "$conflict" == 0 ]] || die "resolve naming conflicts with interactive swarm migrate"
    return
  fi
  # Names are settled. Validate state boundaries before creating the journal.
  local dir
  for dir in "$target" "$target/worktrees" "$target/submissions" "$backup"; do
    [[ "$(realpath -m "$dir")" == "$SWARM_ROOT/"* ]] || die "migration state escapes workspace: $dir"
  done
  mkdir -p "$target"
  (
    flock -x 9
    [[ "$(sha256sum "$SWARM_CONFIG_PATH" | cut -d' ' -f1)" == "$original_hash" ]] || die "config changed while naming repos; rerun migration"
    mkdir -p "$backup/submissions" "$target/submissions"
    [[ -f "$backup/config.json" ]] || cp -p "$SWARM_CONFIG_PATH" "$backup/config.json"
    local tmp
    tmp="$(mktemp "$backup/.plan.XXXXXX")"
    jq -n --argjson repos "$mapping" --argjson keys "$keys" '{repos:$repos,keys:$keys}' > "$tmp"
    mv "$tmp" "$backup/plan.json"
    if [[ ! -f "$backup/submissions.complete" ]]; then
      [[ ! -d "$old_state/submissions" ]] || cp -a "$old_state/submissions/." "$backup/submissions/"
      : > "$backup/submissions.complete"
    fi
    local marker relative old_id work dest logical matched source
    local pending=() sources=() destinations=()
    while IFS= read -r -d '' marker; do
      relative="${marker#"$backup/submissions"/}"; old_id="$relative"
      if [[ "$old_id" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+__(.+__.+)$ ]]; then old_id="${BASH_REMATCH[1]}"; fi
      matched=0
      for entry in "${entries[@]}"; do
        if [[ "$old_id" == "${entry}__"* ]]; then
          work="${old_id#"${entry}__"}"
          if valid_identifier "$work"; then
            name="$(jq -r --arg entry "$entry" '.[$entry]' <<< "$keys")"
            logical="${name}___${work}"; matched=1; break
          fi
        fi
      done
      if [[ "$matched" == 0 ]]; then logical="legacy-orphans/$relative"; fi
      dest="$target/submissions/$logical"; source="$old_state/submissions/$relative"
      if [[ -f "$dest" && "$source" != "$dest" ]]; then cmp -s "$marker" "$dest" || die "submission collision: $dest"; fi
      sources+=("$marker"); destinations+=("$dest")
      if [[ "$old_state" == "$target" && "$source" != "$dest" ]]; then pending+=("$source"); fi
    done < <(find "$backup/submissions" -type f -print0)
    tmp="$(mktemp "$backup/.pending.XXXXXX")"
    if [[ ${#pending[@]} -gt 0 ]]; then printf '%s\n' "${pending[@]}" | jq -R -s 'split("\n")[:-1]' > "$tmp"; else printf '[]\n' > "$tmp"; fi
    mv "$tmp" "$backup/pending-cleanup.json"
    for ((i=0;i<${#sources[@]};i++)); do
      dest="${destinations[i]}"; mkdir -p "$(dirname "$dest")"; cp -p "${sources[i]}" "$dest"
    done
    tmp="$(mktemp "$SWARM_ROOT/.swarm-config.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    jq --argjson repos "$mapping" '.version=2 | .repos=$repos | .default_ide=(.default_ide // "") | del(.repos_dir,.state_dir)' "$SWARM_CONFIG_PATH" > "$tmp"
    chmod --reference="$SWARM_CONFIG_PATH" "$tmp"
    mv "$tmp" "$SWARM_CONFIG_PATH"
  ) 9>"$target/config.lock"
  load_swarm_config_from_path
  finish_migration_cleanup
  ensure_gitignore_swarm_block
  info "Migrated to named-repo version 2. Checkouts and swarm.md stayed in place."
  info "Config and submission snapshots: $backup"
}

finish_migration_cleanup() {
  local journal="$STATE_DIR/migration/pending-cleanup.json" marker
  [[ -f "$journal" ]] || return 0
  while IFS= read -r marker; do
    [[ "$marker" == "$STATE_DIR/submissions/"* && "$(realpath -m "$marker")" == "$STATE_DIR/submissions/"* ]] || die "invalid migration cleanup path: $marker"
    if [[ -f "$marker" ]]; then rm -- "$marker"; fi
  done < <(jq -r '.[]' "$journal")
  rm -- "$journal"
}
