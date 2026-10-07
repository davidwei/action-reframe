#!/usr/bin/env bash
set -euo pipefail

model_service="${ACTION_REFRAME_MODEL_SERVICE:-vllm-vl.service}"
review_service="${ACTION_REFRAME_REVIEW_SERVICE:-action-reframe-review.service}"
queue_service="${ACTION_REFRAME_QUEUE_SERVICE:-action-reframe-queue.service}"
access_url="${ACTION_REFRAME_URL:-http://127.0.0.1:8766/library}"

services=("$model_service" "$review_service" "$queue_service")

for service in "${services[@]}"; do
  load_state="$(systemctl --user show --property=LoadState --value "$service")"
  if [[ "$load_state" != "loaded" ]]; then
    echo "Required user service is not installed: $service" >&2
    echo "See the 'Review and model startup after reboot' section in README.md." >&2
    exit 1
  fi
done

echo "Starting Action Reframe services..."
systemctl --user start "$model_service"
systemctl --user start "$review_service"
systemctl --user start "$queue_service"

failed=0
for service in "${services[@]}"; do
  if systemctl --user is-active --quiet "$service"; then
    printf '  %-38s %s\n' "$service" "running"
  else
    printf '  %-38s %s\n' "$service" "FAILED"
    failed=1
  fi
done

if (( failed )); then
  echo >&2
  echo "One or more services failed to start. Inspect them with:" >&2
  printf '  systemctl --user status %q %q %q\n' \
    "$model_service" "$review_service" "$queue_service" >&2
  exit 1
fi

echo
echo "Action Reframe is ready:"
echo "  $access_url"
echo
echo "The queue supervisor is running. If the saved queue is paused, open the URL"
echo "and select 'Start/resume queue'."
