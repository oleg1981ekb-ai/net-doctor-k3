#!/usr/bin/env bash
set -euo pipefail

echo "=== Running AI Infrastructure Smoke Test ==="

if [ ! -f ".env.example" ]; then
  echo "[FAIL] .env.example not found" >&2
  exit 1
fi

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "[FAIL] .env is tracked by Git! Remove it immediately." >&2
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "[WARN] Local .env not found. Copy .env.example to .env and fill required keys."
else
  while IFS= read -r line; do
    if [[ "$line" =~ ^([A-Z0-9_]+)=.*#\ *required ]]; then
      var_name="${BASH_REMATCH[1]}"
      if ! grep -Eq "^${var_name}=.+" .env; then
        echo "[FAIL] Required variable ${var_name} is missing or empty in .env" >&2
        exit 1
      fi
    fi
  done < .env.example
fi

python3 scripts/validate_governance.py
echo "=== Smoke Test Completed Successfully ==="
