#!/usr/bin/env bash
set -eu
tool="$(cd "$(dirname "$0")/../bin" && pwd)/shell-lock"
demo_dir="$(mktemp -d "${TMPDIR:-/tmp}/shell-lock-demo.XXXXXX")"
trap 'rm -rf "$demo_dir"' EXIT
for worker in 1 2 3 4; do
  "$tool" --timeout 5 "$demo_dir/demo.lock" -- sh -c \
    'printf "start %s\n" "$1"; sleep 0.1; printf "finish %s\n" "$1"' _ "$worker" &
done
wait
