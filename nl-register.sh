#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "Missing .env in ${ROOT_DIR}"
  exit 1
fi

set -a
source "${ROOT_DIR}/.env"
set +a

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Missing OPENAI_API_KEY in .env"
  exit 1
fi

if [[ -z "${GROCY_APIKEY_VALUE:-}" ]]; then
  echo "Missing GROCY_APIKEY_VALUE in .env"
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: ./nl-register.sh \"牛乳 2本 2024-12-31 198円\""
  exit 1
fi

node "${ROOT_DIR}/mcp-grocy-api/scripts/nl-register.mjs" "$@"
