#!/usr/bin/env bash
# Install + auth treg for team use (CLI, skill, Cursor MCP).
# Usage:
#   TREG_TOKEN=<team-token> ./scripts/setup-treg.sh
#   ./scripts/setup-treg.sh --token <team-token>
set -euo pipefail

TOKEN="${TREG_TOKEN:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2 ;;
    --token=*) TOKEN="${1#--token=}"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$TOKEN" ]]; then
  echo "Missing token. Set TREG_TOKEN or pass --token <team-token>." >&2
  echo "Docs: https://treg.to/llms.txt" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

curl -fsSL https://treg.to/install.sh | sh -s -- --token "$TOKEN"

# Prefer a stable PATH entry for login / non-interactive shells
if [[ -x "$HOME/.local/bin/treg" ]]; then
  if command -v sudo >/dev/null 2>&1; then
    sudo ln -sf "$HOME/.local/bin/treg" /usr/local/bin/treg || true
    sudo ln -sf "$HOME/.local/bin/uv" /usr/local/bin/uv || true
  fi
fi

echo
echo "Verify:"
echo "  treg --version"
echo "  treg balance"
echo "  treg catalog search \"web search\""
echo
echo "Cloud Agents: add secret TREG_TOKEN in the environment dashboard,"
echo "then enable the treg MCP (https://treg.to/mcp/) with Authorization: Bearer <token>."
