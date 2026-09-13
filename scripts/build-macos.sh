#!/bin/bash
# Developer build only. End users run the .app, with no external runtime.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "NON VERIFICATO: macOS .app/.dmg creation and installation tests require a Mac." >&2
  exit 2
fi

for build_tool in cargo rustc node npm hdiutil xcrun codesign ditto; do
  if ! command -v "$build_tool" >/dev/null 2>&1; then
    echo "Missing developer build dependency: $build_tool. See docs/MACOS_BUILD.md." >&2
    exit 2
  fi
done
xcrun --find clang >/dev/null
PYTHON_BUILD="${GRIDBOT_BUILD_PYTHON:-python3.12}"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BUILD="$PROJECT_ROOT/.venv/bin/python"
elif ! command -v "$PYTHON_BUILD" >/dev/null 2>&1; then
  echo "Python 3.12+ is required on the developer build machine." >&2
  exit 2
fi
"$PYTHON_BUILD" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  "$PYTHON_BUILD" -m venv "$PROJECT_ROOT/.venv"
  PYTHON_BUILD="$PROJECT_ROOT/.venv/bin/python"
fi
"$PYTHON_BUILD" -m pip install --upgrade pip==26.2.1
"$PYTHON_BUILD" -m pip install -r backend/requirements-dev.txt -r scripts/requirements-packaging.txt
npm --prefix desktop ci
"$PYTHON_BUILD" scripts/validate_desktop_config.py
export ALLOW_MAINNET_TRADING=false
export APPLE_SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:--}"
# This applies to the Rust/Tauri executable, the PyInstaller bootloader and any
# native extensions built during packaging.  The post-build Mach-O gate below
# rejects the candidate if a bundled executable silently raises this target.
export MACOSX_DEPLOYMENT_TARGET=12.0

# Remove stale binaries and packages before running any release gate.
rm -rf "$PROJECT_ROOT/build" "$PROJECT_ROOT/frontend/dist" "$PROJECT_ROOT/desktop/target"
rm -rf "$PROJECT_ROOT/dist/Grid Hedge Bot.app" "$PROJECT_ROOT/dist/Grid Hedge Bot.dmg"
rm -rf "$PROJECT_ROOT/dist/BUILD_MANIFEST.json" "$PROJECT_ROOT/dist/reports"
rm -f "$PROJECT_ROOT"/desktop/binaries/gridbot-backend-*-apple-darwin
mkdir -p "$PROJECT_ROOT/build/reports" "$PROJECT_ROOT/dist"

"$PYTHON_BUILD" -m pip_audit --local --strict --format=json --output=build/reports/python-native-dependency-audit.json

"$PYTHON_BUILD" -m ruff check backend tests scripts desktop/tests
"$PYTHON_BUILD" -m pytest tests desktop/tests -q --junitxml=build/reports/backend-tests.xml
"$PYTHON_BUILD" -m compileall -q backend scripts
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend test -- --reporter=json --outputFile=../build/reports/frontend-tests.json
npm --prefix frontend run build
"$PYTHON_BUILD" scripts/run_frontend_backend_e2e.py
"$PYTHON_BUILD" scripts/generate_desktop_assets.py
NATIVE_TARGET="$(rustc --print host-tuple)"
"$PYTHON_BUILD" scripts/build_backend.py --target "$NATIVE_TARGET"
"$PYTHON_BUILD" scripts/verify_frozen_backend.py "desktop/binaries/gridbot-backend-$NATIVE_TARGET" --report build/reports/frozen-backend.json

if [[ ! -f desktop/Cargo.lock ]]; then
  cargo generate-lockfile --manifest-path desktop/Cargo.toml
fi
cp desktop/Cargo.lock build/reports/Cargo.lock
cargo metadata --manifest-path desktop/Cargo.toml --locked --features custom-protocol --format-version 1 --filter-platform "$NATIVE_TARGET" > build/reports/rust-native-metadata.json
"$PYTHON_BUILD" scripts/record_native_rust_scope.py build/reports/rust-native-metadata.json --target "$NATIVE_TARGET"
cargo fmt --manifest-path desktop/Cargo.toml
cargo fmt --manifest-path desktop/Cargo.toml --check
cargo test --manifest-path desktop/Cargo.toml --locked 2>&1 | tee build/reports/desktop-rust-tests.txt
cargo clippy --manifest-path desktop/Cargo.toml --locked --all-targets -- -D warnings
(cd desktop && npm run tauri -- build --target "$NATIVE_TARGET" --bundles app,dmg -- --locked)

PACKAGE_DIR="$PROJECT_ROOT/desktop/target/$NATIVE_TARGET/release/bundle"
DMG_SOURCE=("$PACKAGE_DIR"/dmg/*.dmg)
if [[ ${#DMG_SOURCE[@]} -ne 1 || ! -f "${DMG_SOURCE[0]}" ]]; then
  echo "Expected exactly one genuine generated DMG." >&2
  exit 1
fi
"$PYTHON_BUILD" scripts/verify_macos_package.py "${DMG_SOURCE[0]}" --report build/reports/macos-package.json

# Post-build full suite. A failed gate never produces a release manifest.
"$PYTHON_BUILD" -m pytest tests desktop/tests -q --junitxml=build/reports/final-backend-tests.xml
npm --prefix frontend test -- --reporter=json --outputFile=../build/reports/final-frontend-tests.json
"$PYTHON_BUILD" scripts/run_frontend_backend_e2e.py
ditto "$PACKAGE_DIR/macos/Grid Hedge Bot.app" "$PROJECT_ROOT/dist/Grid Hedge Bot.app"
cp "${DMG_SOURCE[0]}" "$PROJECT_ROOT/dist/Grid Hedge Bot.dmg"
"$PYTHON_BUILD" scripts/write_build_manifest.py
echo "Local macOS package tested; see dist/BUILD_MANIFEST.json for evidence and external limits."
