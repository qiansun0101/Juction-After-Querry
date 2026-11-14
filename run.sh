#!/bin/bash
# Usage:
#   ./run.sh oracle                        reference solution (no API key needed)
#   ./run.sh nop                           do-nothing baseline (no API key needed)
#   ./run.sh openrouter/anthropic/claude-sonnet-4.5   OpenCode playing with that model
#   ./run.sh anthropic/claude-sonnet-4-5 3             ... 3 attempts
#   HARBOR_ENV=modal ./run.sh oracle      run on Modal instead of local Docker
# Results: ./jobs/<timestamp>/*/verifier/{reward.txt,report.json}
set -euo pipefail
cd "$(dirname "$0")"
TARGET="${1:?usage: ./run.sh oracle|nop|<provider/model> [attempts]}"
ATTEMPTS="${2:-1}"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
for v in OPENROUTER_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do
  [ -z "${!v:-}" ] && unset "$v"
done
case "$TARGET" in
  oracle|nop) harbor run -p . -a "$TARGET" -e "${HARBOR_ENV:-docker}" -y -o ./jobs ;;
  *)          harbor run -p . -a opencode -m "$TARGET" -e "${HARBOR_ENV:-docker}" -k "$ATTEMPTS" -y -o ./jobs ;;
esac
