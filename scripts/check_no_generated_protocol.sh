#!/usr/bin/env bash
# Generated protobuf output is always rebuilt by `just generate-protocol` and
# must never be tracked. The ignore rules are the first line of defence; this
# guard catches `git add -f` and misplaced files in `just check`/CI.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

tracked="$(git ls-files \
    | grep -E '(_pb2(_grpc)?\.pyi?|_pb\.(ts|js)|_connect\.ts)$|(^|/)dataforge_protocol/|(^|/)buf/validate/|^packages/frontend/src/lib/protocol/' \
    | grep -v '^packages/protocol/proto/' || true)"

if [[ -n "$tracked" ]]; then
    echo 'Generated protobuf output must not be committed (run `just generate-protocol` instead):' >&2
    echo "$tracked" >&2
    exit 1
fi
