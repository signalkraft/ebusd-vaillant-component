#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <commit message>"
    exit 1
fi

commit_msg="$*"

# --- read current version from pyproject.toml ---
current=$(grep -oP '^version = "\K[0-9]+\.[0-9]+\.[0-9]+' pyproject.toml)
if [ -z "$current" ]; then
    echo "Error: could not read version from pyproject.toml"
    exit 1
fi

major=$(echo "$current" | cut -d. -f1)
minor=$(echo "$current" | cut -d. -f2)
patch=$(echo "$current" | cut -d. -f3)

new_minor=$((minor + 1))
new_ver="${major}.${new_minor}.${patch}"

# --- update pyproject.toml ---
sed -i 's/^version = "'"${current}"'"/version = "'"${new_ver}"'"/' pyproject.toml

# --- update manifest.json ---
sed -i 's/"version": "'"${current}"'"/"version": "'"${new_ver}"'"/' custom_components/ebusd_vaillant/manifest.json

# --- commit and tag ---
git add pyproject.toml custom_components/ebusd_vaillant/manifest.json
git commit -m "$commit_msg"
git tag "v${new_ver}"

echo "Bumped ${current} → ${new_ver}, committed, tagged v${new_ver}"
