#!/usr/bin/env bash
# Walks the snapshot -> check -> allow loop on two small specs. Exits 0 when
# every step behaves as described in README.md.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -R specs pyproject.toml "$work"/
cd "$work"

api-contract snapshot --source file:specs/v1.yaml        # 1. record v1
api-contract check --source file:specs/v1.yaml           # 2. unchanged: exit 0

set +e
api-contract check                                        # 3. v2 breaks it: exit 1
status=$?
set -e
[ "$status" -eq 1 ] || { echo "expected exit 1, got $status" >&2; exit 1; }

api-contract allow 'GET /orders/{}:response:200:total:type-changed' \
  --reason "Clients read total_display instead" --expires "$(date -v+30d +%F 2>/dev/null || date -d '+30 days' +%F)"
api-contract check                                        # 4. acknowledged: exit 0
echo "example OK"
