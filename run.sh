#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: ./run.sh <chess.com-username> [options]" >&2
  exit 64
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
reports_dir="$script_dir/reports"
mkdir -p "$reports_dir"

image="${CHESS_EVAL_IMAGE:-chess-eval-v1:1.0}"
container="chess-eval-v1-$(date +%s)-$$"
container_args=("$@")
has_html=0
for arg in "$@"; do
  if [ "$arg" = "--html" ] || [[ "$arg" == --html=* ]]; then
    has_html=1
    break
  fi
done
if [ "$has_html" -eq 0 ]; then
  container_args+=("--html" "/reports/")
fi
exit_code=0

cleanup() {
  docker rm -f -v "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker create --name "$container" "$image" "${container_args[@]}" >/dev/null
set +e
docker start -a "$container"
exit_code=$?
set -e

docker cp "$container:/reports/." "$reports_dir/" >/dev/null
echo "HTML reports copied to $reports_dir" >&2

exit "$exit_code"
