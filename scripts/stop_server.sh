#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME=stylespectrum.service

if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl stop "$SERVICE_NAME"
fi
