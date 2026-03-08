#!/usr/bin/env bash
# Export Garmin OAuth tokens as a base64 string for use as a GitHub secret.
#
# Prerequisites:
#   1. Run `python main.py --period weekly` locally at least once to complete
#      the initial Garmin MFA login (6-digit code). This creates cached tokens
#      at ~/.garminconnect.
#
# Usage:
#   bash export_garmin_tokens.sh
#
# Then copy the output and add it as a GitHub repository secret named
# GARMIN_TOKENS_B64 (Settings → Secrets and variables → Actions → New secret).
#
# Tokens last ~1 year. If GitHub Actions runs start failing with auth errors,
# re-run a local login and re-export.

set -euo pipefail

TOKEN_DIR="${HOME}/.garminconnect"

if [ ! -d "$TOKEN_DIR" ]; then
    echo "Error: ${TOKEN_DIR} not found." >&2
    echo "Run 'python main.py --period weekly' locally first to complete the initial Garmin login." >&2
    exit 1
fi

echo "Exporting Garmin tokens from ${TOKEN_DIR}..."
echo ""
echo "=== Copy everything between the lines below ==="
echo "---"
tar cz -C "$TOKEN_DIR" . | base64 -w 0
echo ""
echo "---"
echo ""
echo "Add this as a GitHub secret named: GARMIN_TOKENS_B64"
