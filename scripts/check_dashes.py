"""Pre-commit hook: reject files containing en dashes or em dashes."""

import re
import sys

DASH_RE = re.compile(r"[\u2013\u2014]")

HINT = """en dash (\u2013) or em dash (\u2014) found. Replace with shorter alternatives
  (e.g. rephrase to a shorter sentence)."""


def main() -> int:
    files = sys.argv[1:]
    rc = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        matches = DASH_RE.findall(content)
        if matches:
            print(f"{path}: {HINT}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
