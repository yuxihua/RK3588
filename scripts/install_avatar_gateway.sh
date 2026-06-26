#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="/opt/rk3588-avatar-gateway"
SERVICE_FILE="/etc/systemd/system/avatar-gateway.service"
ENV_FILE="/etc/default/avatar-gateway"

install -d /etc/systemd/system
install -d "$INSTALL_ROOT"
cp -a "$PROJECT_ROOT"/. "$INSTALL_ROOT"/
chmod +x "$INSTALL_ROOT"/scripts/*.sh "$INSTALL_ROOT"/scripts/*.py
install -d "$INSTALL_ROOT/assets/avatars"

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
AVATAR_NAME=avatar
GPIO_AVATAR_SELECT=1
GPIO0_PIN=0
GPIO1_PIN=1
AVATAR_GPIO_00=avatar_00
AVATAR_GPIO_01=avatar_01
AVATAR_GPIO_10=avatar_10
AVATAR_GPIO_11=avatar_11
EOF
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=RK3588 USB Avatar Gateway
After=network.target local-fs.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT
EnvironmentFile=-$ENV_FILE
Environment=AVATAR_NAME=avatar
Environment=GPIO_AVATAR_SELECT=1
Environment=GPIO0_PIN=0
Environment=GPIO1_PIN=1
Environment=AVATAR_GPIO_00=avatar_00
Environment=AVATAR_GPIO_01=avatar_01
Environment=AVATAR_GPIO_10=avatar_10
Environment=AVATAR_GPIO_11=avatar_11
ExecStart=/usr/bin/python3 $INSTALL_ROOT/scripts/avatar_processor.py --camera /dev/video41 --output /dev/video11 --avatar $INSTALL_ROOT/assets/avatar.png --avatar-dir $INSTALL_ROOT/assets/avatars --avatar-name \${AVATAR_NAME} --gpio-avatar-select --gpio0 \${GPIO0_PIN} --gpio1 \${GPIO1_PIN} --avatar-gpio-00 \${AVATAR_GPIO_00} --avatar-gpio-01 \${AVATAR_GPIO_01} --avatar-gpio-10 \${AVATAR_GPIO_10} --avatar-gpio-11 \${AVATAR_GPIO_11} --width 1280 --height 720 --fps 30
Restart=always
RestartSec=1
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now avatar-gateway

echo "已安装并启动 avatar-gateway 服务。"
echo "可用命令: systemctl status avatar-gateway"