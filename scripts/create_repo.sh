#!/usr/bin/env bash
set -euo pipefail

git init
mkdir -p docs/SRS docs/SAD docs/RAS docs/DDG docs/ADR
mkdir -p backend frontend data scripts

git add .
git commit -m "Initial Trading Intelligence Platform scaffold"

echo "Local repository initialized."
echo "To push to GitHub:"
echo "  gh repo create trading-intelligence-platform --private --source=. --remote=origin --push"
