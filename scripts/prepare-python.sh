#!/usr/bin/env bash
# prepare-python.sh
# Downloads a standalone Python and installs all dependencies for macOS/Linux
# distribution.
#
# Dependencies are read from uv.lock (via `uv export`) — pyproject.toml is the
# single source of truth. No hardcoded dependency lists.
#
# Uses python-build-standalone (https://github.com/astral-sh/python-build-standalone)
# which provides relocatable Python builds for macOS and Linux.
#
# Environment knobs:
#   PYTHON_VERSION      Full X.Y.Z Python version (default: from backend/.python-version,
#                       resolved to a known-good patch release when only X.Y is pinned)
#   PBS_TAG             python-build-standalone release tag
#   ARCH                Target arch (default: uname -m)
#   LTX_PYTHON_DEPS     "full" (default) installs every locked dependency;
#                       "skip" produces a runtime-only bundle (Python + pip, no
#                       ML deps) for CI/smoke packaging tests — NOT for release.
#
# Prerequisites:
#   - uv must be installed (https://docs.astral.sh/uv/)
#   - curl must be available
#   - git must be available (for git-based Python packages)

set -euo pipefail

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"
OUTPUT_DIR="python-embed"
OUTPUT_PATH="$PROJECT_DIR/$OUTPUT_DIR"
TEMP_DIR="$(mktemp -d)"

PYTHON_VERSION="${PYTHON_VERSION:-$(tr -d '[:space:]' < "$BACKEND_DIR/.python-version")}"
# python-build-standalone needs a full X.Y.Z version; resolve a bare X.Y pin
# to the patch release the pinned PBS tag (20260211) actually ships.
case "$PYTHON_VERSION" in
  3.12) PYTHON_VERSION="3.12.12" ;;
  3.13) PYTHON_VERSION="3.13.12" ;;
esac

PBS_TAG="${PBS_TAG:-20260211}"
ARCH="${ARCH:-$(uname -m)}"
DEPS_MODE="${LTX_PYTHON_DEPS:-full}"

# Map architecture names for python-build-standalone
case "$ARCH" in
  arm64|aarch64) PBS_ARCH="aarch64" ;;
  x86_64|amd64)  PBS_ARCH="x86_64" ;;
  *) echo "ERROR: Unsupported architecture: $ARCH"; exit 1 ;;
esac

# Map OS to the python-build-standalone platform triple
OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin) PBS_PLATFORM="apple-darwin"; PLATFORM_LABEL="macOS" ;;
  Linux)  PBS_PLATFORM="unknown-linux-gnu"; PLATFORM_LABEL="Linux" ;;
  *) echo "ERROR: Unsupported OS: $OS_NAME (use prepare-python.ps1 on Windows)"; exit 1 ;;
esac

PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}+${PBS_TAG}-${PBS_ARCH}-${PBS_PLATFORM}-install_only_stripped.tar.gz"

echo "========================================"
echo "  LTX Video - Python Environment Setup"
echo "  Platform: $PLATFORM_LABEL ($ARCH)"
echo "  Python: $PYTHON_VERSION"
echo "  Dependencies: $DEPS_MODE"
echo "========================================"

# ============================================================
# Step 1: Verify prerequisites
# ============================================================
echo ""
echo "Step 1: Verifying prerequisites..."

if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install it: https://docs.astral.sh/uv/"
    exit 1
fi
echo "  uv: $(command -v uv)"

if ! command -v curl &>/dev/null; then
    echo "ERROR: curl not found."
    exit 1
fi
echo "  curl: $(command -v curl)"

if ! command -v git &>/dev/null; then
    echo "ERROR: git not found (needed for git-based Python packages)."
    exit 1
fi
echo "  git: $(command -v git)"

echo ""
echo "Ensuring Wan2GP checkout..."
bash "$SCRIPT_DIR/ensure-wan2gp.sh"

# ============================================================
# Step 2: Generate requirements.txt from uv.lock
# ============================================================
echo ""
echo "Step 2: Generating requirements.txt from uv.lock..."

REQUIREMENTS_FILE="$BACKEND_DIR/requirements-dist.txt"

# Export pinned deps, excluding the project itself. Platform markers in
# pyproject.toml keep out packages that don't apply to this OS.
uv export --frozen --no-hashes --no-editable --no-emit-project \
    --no-header --no-annotate \
    --project "$BACKEND_DIR" \
    > "$REQUIREMENTS_FILE"

DEP_COUNT=$(grep -c '^\S' "$REQUIREMENTS_FILE" || true)
echo "  Exported $DEP_COUNT dependencies from uv.lock"

# ============================================================
# Step 3: Prepare directories
# ============================================================
echo ""
echo "Step 3: Preparing directories..."

if [ -d "$OUTPUT_PATH" ]; then
    echo "  Removing existing $OUTPUT_DIR directory..."
    rm -rf "$OUTPUT_PATH"
fi

mkdir -p "$OUTPUT_PATH"

# ============================================================
# Step 4: Download and extract standalone Python
# ============================================================
echo ""
echo "Step 4: Downloading Python $PYTHON_VERSION standalone ($PBS_ARCH-$PBS_PLATFORM)..."
echo "  URL: $PBS_URL"

PYTHON_TAR="$TEMP_DIR/python-standalone.tar.gz"
curl -L --fail --progress-bar -o "$PYTHON_TAR" "$PBS_URL"
echo "  Downloaded Python standalone package"

# python-build-standalone extracts to a `python/` directory
echo "  Extracting..."
tar -xzf "$PYTHON_TAR" -C "$TEMP_DIR"

# Move contents from python/ into our output path
mv "$TEMP_DIR/python/"* "$OUTPUT_PATH/"
echo "  Extracted to $OUTPUT_PATH"

# Verify the Python binary exists
PYTHON_EXE="$OUTPUT_PATH/bin/python3"
if [ ! -f "$PYTHON_EXE" ]; then
    echo "ERROR: Python binary not found at $PYTHON_EXE"
    exit 1
fi

echo "  Python binary: $PYTHON_EXE"
"$PYTHON_EXE" --version

# ============================================================
# Step 5: Ensure pip is available
# ============================================================
echo ""
echo "Step 5: Setting up pip..."

# python-build-standalone install_only usually includes pip, but verify
if ! "$PYTHON_EXE" -m pip --version &>/dev/null; then
    echo "  Installing pip..."
    curl -sL https://bootstrap.pypa.io/get-pip.py -o "$TEMP_DIR/get-pip.py"
    "$PYTHON_EXE" "$TEMP_DIR/get-pip.py" --no-warn-script-location
fi
echo "  pip: $("$PYTHON_EXE" -m pip --version)"

# ============================================================
# Step 6: Install all dependencies from requirements.txt
# ============================================================
if [ "$DEPS_MODE" = "skip" ]; then
    echo ""
    echo "Step 6: SKIPPING dependency installation (LTX_PYTHON_DEPS=skip)."
    echo "  !! Runtime-only bundle for CI/smoke packaging tests."
    echo "  !! Do NOT ship this build to users — the backend cannot run without its dependencies."
else
    echo ""
    echo "Step 6: Installing dependencies from requirements.txt..."
    echo "  (This may take a while — PyTorch + ML libraries are large)"

    # macOS: standard PyPI torch includes MPS support, no extra index needed.
    # Linux: CUDA torch comes from the PyTorch cu128 index (matching uv.lock).
    PIP_INDEX_ARGS=()
    if [ "$OS_NAME" = "Linux" ]; then
        PIP_INDEX_ARGS+=(--extra-index-url "https://download.pytorch.org/whl/cu128")
    fi

    "$PYTHON_EXE" -m pip install -r "$REQUIREMENTS_FILE" \
        "${PIP_INDEX_ARGS[@]+"${PIP_INDEX_ARGS[@]}"}" \
        --no-warn-script-location --quiet

    echo "  All dependencies installed"

    # Linux: the bundled runtime auto-detects the sibling Wan2GP checkout and
    # loads the in-process bridge, so the bridge's own dependencies must be in
    # the bundle too (Windows does the same in prepare-python.ps1). macOS keeps
    # the bridge disabled (no CUDA), so only the backend deps are installed.
    WANGP_REQUIREMENTS="$PROJECT_DIR/Wan2GP/requirements.txt"
    if [ "$OS_NAME" = "Linux" ] && [ -f "$WANGP_REQUIREMENTS" ]; then
        echo ""
        echo "Step 6b: Installing Wan2GP bridge dependencies (Linux)..."
        "$PYTHON_EXE" -m pip install -r "$WANGP_REQUIREMENTS" \
            "${PIP_INDEX_ARGS[@]+"${PIP_INDEX_ARGS[@]}"}" \
            --no-warn-script-location --quiet
        echo "  Wan2GP bridge dependencies installed"
    elif [ "$OS_NAME" = "Linux" ]; then
        echo "  !! Wan2GP/requirements.txt not found — bridge dependencies NOT installed."
        echo "  !! The packaged app will fall back to API mode for generation."
    fi
fi
echo "  Wan2GP checkout present for packaging"

# ============================================================
# Step 7: Write dependency hash files
# ============================================================
# python-setup.ts compares the bundled python-deps-hash.txt against the
# runtime's deps-hash.txt to decide whether a downloaded/staged Python
# environment is current. Both derive from the exported lock state.
echo ""
echo "Step 7: Writing dependency hash..."
if command -v sha256sum &>/dev/null; then
    DEPS_HASH=$(sha256sum "$REQUIREMENTS_FILE" | cut -d' ' -f1)
else
    DEPS_HASH=$(shasum -a 256 "$REQUIREMENTS_FILE" | cut -d' ' -f1)
fi
printf '%s\n' "$DEPS_HASH" > "$PROJECT_DIR/python-deps-hash.txt"
printf '%s\n' "$DEPS_HASH" > "$OUTPUT_PATH/deps-hash.txt"
echo "  Hash: $DEPS_HASH"

# ============================================================
# Step 8: Clean up
# ============================================================
echo ""
echo "Step 8: Cleaning up..."

# Remove __pycache__ and .pyc files
find "$OUTPUT_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.pyc" -delete 2>/dev/null || true

# Remove pip cache and pip itself (not needed at runtime) — keep pip in
# runtime-only bundles so smoke environments can still install into them.
if [ "$DEPS_MODE" != "skip" ]; then
    rm -rf "$OUTPUT_PATH/lib/python"*/site-packages/pip 2>/dev/null || true
    rm -rf "$OUTPUT_PATH/lib/python"*/site-packages/pip-*.dist-info 2>/dev/null || true
    rm -rf "$OUTPUT_PATH/lib/python"*/site-packages/setuptools 2>/dev/null || true
    rm -rf "$OUTPUT_PATH/lib/python"*/site-packages/setuptools-*.dist-info 2>/dev/null || true
fi

# Remove test directories to save space
find "$OUTPUT_PATH/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$OUTPUT_PATH/lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true

# Remove files only needed for building native extensions, not at runtime.
# This cuts ~14k files and speeds up macOS codesigning dramatically.
# NOTE: Windows needs .h files for sageattention/triton — this script never
# targets Windows (see prepare-python.ps1).
rm -rf "$OUTPUT_PATH/include" "$OUTPUT_PATH/share" 2>/dev/null || true
find "$OUTPUT_PATH/lib" -type d -name "include" -exec rm -rf {} + 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.pyi" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.pxd" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.pyx" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.hpp" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.cpp" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.h" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.cuh" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.cu" -delete 2>/dev/null || true
find "$OUTPUT_PATH" -name "*.cmake" -delete 2>/dev/null || true

# Remove temp directory
rm -rf "$TEMP_DIR"

# ============================================================
# Step 9: Verify critical imports
# ============================================================
if [ "$DEPS_MODE" != "skip" ]; then
echo ""
echo "Step 9: Verifying critical imports..."
"$PYTHON_EXE" -c "
import sys
print(f'  Python: {sys.version}')
try:
    import torch
    print(f'  PyTorch: {torch.__version__}')
except ImportError as e:
    print(f'  PyTorch import FAILED: {e}')
    sys.exit(1)
try:
    import fastapi
    print(f'  FastAPI: {fastapi.__version__}')
except ImportError as e:
    print(f'  FastAPI import FAILED: {e}')
    sys.exit(1)
try:
    import diffusers
    print(f'  Diffusers: {diffusers.__version__}')
except ImportError as e:
    print(f'  Diffusers import FAILED: {e}')
    sys.exit(1)
try:
    from ltx_pipelines import distilled
    print(f'  ltx-pipelines: OK')
except ImportError as e:
    print(f'  ltx-pipelines: FAILED - {e}')
    sys.exit(1)
"
fi

# Calculate size
SIZE_BYTES=$(du -sb "$OUTPUT_PATH" 2>/dev/null | cut -f1 || du -sk "$OUTPUT_PATH" | awk '{print $1 * 1024}')
SIZE_GB=$(awk "BEGIN {printf \"%.2f\", $SIZE_BYTES / 1073741824}")

echo ""
echo "========================================"
echo "  Python environment ready!"
echo "  Location: $OUTPUT_PATH"
echo "  Size: ${SIZE_GB} GB"
echo "========================================"
