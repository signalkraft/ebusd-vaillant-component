#!/usr/bin/env bash
# Usage: wait_for_logs.sh <timeout_seconds> <grep_pattern>
# Polls docker compose logs until pattern matches or timeout expires.
set -eu

TIMEOUT="${1:?Usage: $0 <timeout_seconds> <grep_pattern>}"
PATTERN="${2:?Usage: $0 <timeout_seconds> <grep_pattern>}"
ELAPSED=0
INTERVAL=3

while [[ $ELAPSED -lt $TIMEOUT ]]; do
    if docker compose logs 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -qE "$PATTERN"; then
        echo "Matched after ${ELAPSED}s:"
        docker compose logs 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "$PATTERN"
        exit 0
    fi
    sleep "$INTERVAL"
    ELAPSED=$(( ELAPSED + INTERVAL ))
done

echo "Timed out after ${TIMEOUT}s  -  no match for: $PATTERN"
docker compose logs --tail=30 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
exit 1
