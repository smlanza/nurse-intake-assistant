#!/usr/bin/env bash
set -euo pipefail

# Prepare uniquely named copies of the authoritative Nurse Intake Assistant
# project-source documents for upload to ChatGPT Projects.
#
# Canonical repo files are never modified.
# Temporary upload copies are recreated on each run.

if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  :
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

SOURCE_FILES=(
  "docs/architecture.md"
  "docs/ai-103-mapping.md"
  "docs/progress.md"
)

OUTPUT_DIR="${TMPDIR:-/tmp}/nurse-intake-project-sources"
STAMP="$(date '+%Y%m%d-%H%M%S')"

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

echo "Preparing ChatGPT Project Sources..."
echo "Repository: ${REPO_ROOT}"
echo

for relative_path in "${SOURCE_FILES[@]}"; do
  source_path="${REPO_ROOT}/${relative_path}"

  if [[ ! -f "${source_path}" ]]; then
    echo "ERROR: Required source file not found:"
    echo "  ${source_path}"
    exit 1
  fi

  filename="$(basename "${source_path}")"
  stem="${filename%.*}"
  extension="${filename##*.}"
  target_path="${OUTPUT_DIR}/${stem}-${STAMP}.${extension}"

  cp "${source_path}" "${target_path}"
  echo "Created: $(basename "${target_path}")"
done

echo
echo "Upload these files from:"
echo "  ${OUTPUT_DIR}"
echo
echo "Canonical repository files were not changed."

# On macOS, open the upload directory in Finder automatically.
if [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "${OUTPUT_DIR}"
fi
