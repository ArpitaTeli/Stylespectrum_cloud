#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME=stylespectrum.service

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

for attempt in $(seq 1 30); do
    if curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null; then
        echo "StyleSpectrum is healthy."
        exit 0
    fi
    sleep 2
done

echo "StyleSpectrum did not become healthy; recent service logs:" >&2
journalctl -u "$SERVICE_NAME" --no-pager -n 100 >&2
exit 1
