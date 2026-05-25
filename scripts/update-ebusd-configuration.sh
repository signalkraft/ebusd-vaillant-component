#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

REPO="https://github.com/john30/ebusd-configuration.git"
TARGET="ebusd-configuration"
SUB="src/vaillant"

if [ -d "$TARGET" ]; then
  echo "Updating $TARGET..."
  git init --quiet "$TARGET" 2>/dev/null || true
  git -C "$TARGET" fetch --depth 1 --filter=blob:none "$REPO" master
  git -C "$TARGET" checkout master -- "$SUB"
  rm -rf "$TARGET/.git"
else
  echo "Cloning $TARGET (sparse checkout, $SUB only)..."
  git clone --depth 1 --filter=blob:none --no-checkout --single-branch "$REPO" "$TARGET"
  git -C "$TARGET" sparse-checkout set --no-cone "$SUB"
  git -C "$TARGET" checkout master
  rm -rf "$TARGET/.git"
fi
