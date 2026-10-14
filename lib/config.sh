# The final named-repository v2 schema. Old schemas are handled only by migrate.
load_swarm_config_from_path() {
  require_jq
  [[ -f "$SWARM_CONFIG_PATH" ]] || die "config not found: $SWARM_CONFIG_PATH"
  jq -e 'type == "object"' "$SWARM_CONFIG_PATH" >/dev/null 2>&1 || die "invalid Swarm configuration JSON: $SWARM_CONFIG_PATH"
  CONFIG_VERSION="$(jq -r '.version // empty' "$SWARM_CONFIG_PATH")"
  if [[ "$CONFIG_VERSION" == 1 ]] || jq -e '.repos | type == "array"' "$SWARM_CONFIG_PATH" >/dev/null; then
    die "old Swarm configuration; run swarm migrate to name the registered repos"
  fi
  [[ "$CONFIG_VERSION" == 2 ]] || die "unsupported config version: $CONFIG_VERSION (need 2)"
  jq -e '(.repos | type) == "object" and (has("repos_dir") | not) and (has("state_dir") | not)' "$SWARM_CONFIG_PATH" >/dev/null || die "version 2 requires a repos name-to-path object and fixed .swarm storage"
  jq -e '(if has("default_ide") then .default_ide else "" end) as $ide | ($ide | type) == "string" and (["", "cursor", "claude", "codex"] | index($ide) != null)' "$SWARM_CONFIG_PATH" >/dev/null || die "invalid default_ide; use an empty string, cursor, claude, or codex"
  DEFAULT_IDE="$(jq -r '.default_ide // ""' "$SWARM_CONFIG_PATH")"
  REPOS_DIR="$SWARM_ROOT"
  STATE_DIR="$SWARM_ROOT/.swarm"
  WORKTREES_DIR="$STATE_DIR/worktrees"
  SUBMISSIONS_DIR="$STATE_DIR/submissions"
  REPOS_LIST=()
  local name relative path existing paths=()
  jq -e '.repos | all(.[]; type == "string" and (test("[\n\r\t]") | not))' "$SWARM_CONFIG_PATH" >/dev/null || die "repo paths must be strings without control whitespace"
  while IFS= read -r name; do
    validate_repo_name "$name"
    relative="$(jq -r --arg name "$name" '.repos[$name]' "$SWARM_CONFIG_PATH")"
    path="$(safe_repo_path "$relative" "$SWARM_ROOT")"
    [[ "$path" != "$STATE_DIR" && "$path" != "$STATE_DIR/"* ]] || die "cannot register a repo inside .swarm: $name"
    for existing in "${paths[@]}"; do [[ "$existing" != "$path" ]] || die "checkout registered under multiple names: $relative"; done
    paths+=("$path"); REPOS_LIST+=("$name")
    if ! is_checkout_root "$path"; then warn "registered repo is missing or not a Git checkout: $name ($relative)"
    elif linked_main_checkout "$path" >/dev/null; then warn "registered repo is a linked worktree: $name ($relative)"; fi
  done < <(jq -r '.repos | keys_unsorted[]' "$SWARM_CONFIG_PATH")
  # Validate fixed directory boundaries before creating any runtime state.
  local dir resolved
  for dir in "$STATE_DIR" "$WORKTREES_DIR" "$SUBMISSIONS_DIR"; do
    resolved="$(realpath -m "$dir")"
    [[ "$resolved" == "$SWARM_ROOT/"* ]] || die "Swarm state escapes the workspace: $dir"
  done
  mkdir -p "$WORKTREES_DIR" "$SUBMISSIONS_DIR"
  CURRENT_REPO="$(infer_current_repo)"
}

repo_relative() { jq -er --arg name "$1" '.repos[$name] // empty' "$SWARM_CONFIG_PATH"; }
repo_abs() { local rel; rel="$(repo_relative "$1")" || die "repo not registered: $1"; safe_repo_path "$rel" "$SWARM_ROOT"; }
resolve_repo_selector() { repo_authorized "$1" || die "repo not registered: $1"; printf '%s' "$1"; }
require_repo() {
  local canonical
  canonical="$(repo_abs "$1")"
  is_checkout_root "$canonical" || die "registered repo unavailable: $1 ($canonical)"
  require_main_checkout "$canonical"
  printf '%s' "$canonical"
}
