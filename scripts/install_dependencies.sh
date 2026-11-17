#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/var/www/stylespectrum
VENV_DIR=/opt/stylespectrum/venv
SERVICE_FILE=/etc/systemd/system/stylespectrum.service
SERVICE_USER=stylespectrum

if [[ "$(id -u)" -ne 0 ]]; then
    echo "This hook must run as root." >&2
    exit 1
fi

if [[ ! -f "$APP_DIR/requirements.txt" || ! -f "$APP_DIR/app.py" ]]; then
    echo "Deployment files are missing from $APP_DIR." >&2
    exit 1
fi

install -d -o root -g root -m 0755 /opt/stylespectrum
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$APP_DIR" \
        --shell /sbin/nologin "$SERVICE_USER"
fi

python3.11 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR/uploads"

cat > "$SERVICE_FILE" <<'UNIT'
[Unit]
Description=StyleSpectrum Flask application
After=network.target

[Service]
Type=simple
User=stylespectrum
Group=stylespectrum
WorkingDirectory=/var/www/stylespectrum
Environment=PORT=8000
EnvironmentFile=-/etc/stylespectrum/stylespectrum.env
ExecStart=/opt/stylespectrum/venv/bin/gunicorn --workers 2 --threads 2 --timeout 120 --bind 0.0.0.0:8000 --access-logfile - --error-logfile - app:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/www/stylespectrum/uploads

[Install]
WantedBy=multi-user.target
UNIT

chmod 0644 "$SERVICE_FILE"
systemctl daemon-reload
