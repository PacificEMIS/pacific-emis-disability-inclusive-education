#!/usr/bin/env bash
set -euo pipefail

# ——— Settings (can be overridden by .gpt-bundle.json) ———
DEFAULT_NAME="$(basename "$(pwd)")"
MAX_MB_DEFAULT=5

# Utilities
jq_safe() { command -v jq >/dev/null 2>&1; }
git_safe() { command -v git >/dev/null 2>&1; }
ts() { date +"%Y%m%d-%H%M%S"; }

# Read JSON config if present
NAME="$DEFAULT_NAME"
MAX_MB="$MAX_MB_DEFAULT"
INCLUDE_GLOBS=()
EXCLUDE_GLOBS=()

if [[ -f ".gpt-bundle.json" ]] && jq_safe; then
  NAME=$(jq -r '.name // empty' .gpt-bundle.json || echo "$DEFAULT_NAME")
  [[ -z "$NAME" ]] && NAME="$DEFAULT_NAME"
  MAX_MB=$(jq -r '.maxFileMB // empty' .gpt-bundle.json || echo "$MAX_MB_DEFAULT")
  [[ -z "$MAX_MB" || "$MAX_MB" == "null" ]] && MAX_MB="$MAX_MB_DEFAULT"

  readarray -t INCLUDE_GLOBS < <(jq -r '.includeGlobs[]?' .gpt-bundle.json)
  readarray -t EXCLUDE_GLOBS < <(jq -r '.excludeGlobs[]?' .gpt-bundle.json)
fi

# Defaults if not set
if [[ ${#INCLUDE_GLOBS[@]} -eq 0 ]]; then
  INCLUDE_GLOBS=( "**/*" )
fi

if [[ ${#EXCLUDE_GLOBS[@]} -eq 0 ]]; then
  EXCLUDE_GLOBS=(
    "venv/**" ".venv/**" "node_modules/**" "dist/**" "build/**"
    "__pycache__/**" "**/*.pyc" "**/*.pyo" ".git/**" ".idea/**" ".vscode/**"
    "migrations/**" "media/**" "staticfiles/**"
    "**/*.zip" "**/*.7z" "**/*.tar" "**/*.tar.gz" "**/*.tgz"
    "*.pem" "*.key" "*.pfx" "*.p12" "*.crt" "*.env" ".env" ".env.*"
    "*.log" "*.bak" "*.tmp" "*.swp" ".DS_Store"
    "**/*.png" "**/*.jpg" "**/*.jpeg" "**/*.gif" "**/*.mp4" "**/*.mov"
  )
fi

# Merge .gpt-bundle-ignore into EXCLUDE_GLOBS
if [[ -f ".gpt-bundle-ignore" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    EXCLUDE_GLOBS+=("$line")
  done < .gpt-bundle-ignore
fi

DIST_DIR="dist"
mkdir -p "$DIST_DIR"

STAMP="$(ts)"
OUTBASE="${NAME}_gpt_bundle_${STAMP}"
ZIP="${DIST_DIR}/${OUTBASE}.zip"
MANIFEST="${DIST_DIR}/${OUTBASE}.manifest.txt"

# Build candidate file list (tracked + relevant untracked, respecting .gitignore)
FILES=()
if git_safe && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # tracked
  mapfile -t tracked < <(git ls-files)
  # untracked but not ignored
  mapfile -t untracked < <(git ls-files --others --exclude-standard)
  FILES=( "${tracked[@]}" "${untracked[@]}" )
else
  # fallback: all files (minus common junk)
  mapfile -t FILES < <(find . -type f | sed 's|^\./||')
fi

# Include / exclude by globs
include_match() {
  local f="$1"; local g
  for g in "${INCLUDE_GLOBS[@]}"; do
    [[ "$f" == $g ]] && return 0
  done
  return 1
}
exclude_match() {
  local f="$1"; local g
  for g in "${EXCLUDE_GLOBS[@]}"; do
    [[ "$f" == $g ]] && return 0
  done
  return 1
}

# Filter + size limit
CAND=()
MAX_BYTES=$(( MAX_MB * 1024 * 1024 ))
for f in "${FILES[@]}"; do
  # normalize
  [[ ! -f "$f" ]] && continue
  include_match "$f" || continue
  exclude_match "$f" && continue
  # size
  sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")
  [[ "$sz" -le "$MAX_BYTES" ]] || continue
  CAND+=("$f")
done

# Write manifest (metadata + file list)
{
  echo "GPT Bundle Manifest"
  echo "-------------------"
  echo "Name:         $NAME"
  echo "Timestamp:    $STAMP"
  if git_safe && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Git branch:   $(git rev-parse --abbrev-ref HEAD)"
    echo "Git commit:   $(git rev-parse --short HEAD)"
    git diff --quiet || echo "Git dirty:    yes"
  fi
  echo "Python:       $(command -v python >/dev/null 2>&1 && python --version 2>&1 || echo 'n/a')"
  echo "Node:         $(command -v node >/dev/null 2>&1 && node --version 2>&1 || echo 'n/a')"
  echo "Max file MB:  $MAX_MB"
  echo
  echo "Included globs:"
  printf "  - %s\n" "${INCLUDE_GLOBS[@]}"
  echo "Excluded globs:"
  printf "  - %s\n" "${EXCLUDE_GLOBS[@]}"
  echo
  echo "Files (${#CAND[@]}):"
  for f in "${CAND[@]}"; do
    echo "  $f"
  done
} > "$MANIFEST"

# Create zip
# shellcheck disable=SC2086
zip -q -r "$ZIP" "${CAND[@]}" "$MANIFEST"

echo "Created:"
echo "  $ZIP"
echo "  $MANIFEST"
