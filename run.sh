#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 [auth|discover|configure|build]"
    echo "  No argument runs all phases in sequence."
    exit 1
}

cmd="${1:-run}"

case "$cmd" in
    auth|discover|configure|build|run)
        uv run python -m src "$cmd"
        ;;
    -h|--help)
        usage
        ;;
    *)
        echo "Unknown command: $cmd"
        usage
        ;;
esac
