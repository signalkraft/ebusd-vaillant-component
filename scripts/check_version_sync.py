"""Check that pyproject.toml and manifest.json versions are in sync."""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
MANIFEST = REPO_ROOT / "custom_components/ebusd_vaillant/manifest.json"


def main() -> int:
    # Read pyproject.toml version
    pyproject_text = PYPROJECT.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
    if not match:
        print("ERROR: Could not find version in pyproject.toml", file=sys.stderr)
        return 1
    pyproject_version = match.group(1)

    # Read manifest.json version
    manifest = json.loads(MANIFEST.read_text())
    manifest_version = manifest.get("version")
    if not manifest_version:
        print("ERROR: Could not find version in manifest.json", file=sys.stderr)
        return 1

    if pyproject_version != manifest_version:
        print(
            f"ERROR: Version mismatch!\n"
            f"  pyproject.toml:        {pyproject_version}\n"
            f"  manifest.json:         {manifest_version}\n"
            f"\n"
            f"Both must be the same version before committing.\n",
            file=sys.stderr,
        )
        return 1

    print(f"Versions are in sync: {pyproject_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
