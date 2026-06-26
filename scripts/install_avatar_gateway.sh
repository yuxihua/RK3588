#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="/opt/rk3588-avatar-gateway"
SERVICE_FILE="/etc/systemd/system/avatar-gateway.service"
UVC_SETUP_SERVICE_FILE="/etc/systemd/system/uvc-gadget-setup.service"
ENV_FILE="/etc/default/avatar-gateway"
USBDEVICE_OVERRIDE_DIR="/etc/usbdevice.d"
USBDEVICE_UVC_OVERRIDE_FILE="$USBDEVICE_OVERRIDE_DIR/uvc.sh"

install -d /etc/systemd/system
install -d "$INSTALL_ROOT"
cp -a "$PROJECT_ROOT"/. "$INSTALL_ROOT"/
chmod +x "$INSTALL_ROOT"/scripts/*.sh "$INSTALL_ROOT"/scripts/*.py
install -d "$INSTALL_ROOT/assets/avatars"

install -d "$USBDEVICE_OVERRIDE_DIR"
cat > "$USBDEVICE_UVC_OVERRIDE_FILE" <<'EOF'
#!/bin/sh

uvc_prepare()
{
  UVC_DIR=$(pwd)

  mkdir -p "$UVC_DIR/control/header/h"
  mkdir -p "$UVC_DIR/control/class/fs" "$UVC_DIR/control/class/ss"
  mkdir -p "$UVC_DIR/streaming/header/h"
  mkdir -p "$UVC_DIR/streaming/class/fs" "$UVC_DIR/streaming/class/hs" "$UVC_DIR/streaming/class/ss"
  mkdir -p "$UVC_DIR/streaming/uncompressed/u/240p"
  mkdir -p "$UVC_DIR/streaming/mjpeg/m/240p"
  mkdir -p "$UVC_DIR/streaming/color_matching/default"

  usb_symlink "$UVC_DIR/control/header/h" "$UVC_DIR/control/class/fs/h"
  usb_symlink "$UVC_DIR/control/header/h" "$UVC_DIR/control/class/ss/h"

  usb_try_symlink "$UVC_DIR/streaming/uncompressed/u" "$UVC_DIR/streaming/header/h/u"
  usb_try_symlink "$UVC_DIR/streaming/mjpeg/m" "$UVC_DIR/streaming/header/h/m"

  usb_symlink "$UVC_DIR/streaming/header/h" "$UVC_DIR/streaming/class/fs/h"
  usb_symlink "$UVC_DIR/streaming/header/h" "$UVC_DIR/streaming/class/hs/h"
  usb_symlink "$UVC_DIR/streaming/header/h" "$UVC_DIR/streaming/class/ss/h"

  cd "$UVC_DIR/streaming/uncompressed/u"
  uvc_add_yuyv 320x240

  cd "$UVC_DIR/streaming/mjpeg/m"
  uvc_add_mjpeg 320x240
}
EOF
chmod 0644 "$USBDEVICE_UVC_OVERRIDE_FILE"

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
OUTPUT_DEVICE=auto
EOF
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=RK3588 USB Avatar Gateway
After=network.target local-fs.target usbdevice.service
Wants=usbdevice.service

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
Environment=OUTPUT_DEVICE=auto
ExecStart=/usr/bin/python3 $INSTALL_ROOT/scripts/avatar_processor.py --camera /dev/video41 --output \${OUTPUT_DEVICE} --avatar $INSTALL_ROOT/assets/avatar.png --avatar-dir $INSTALL_ROOT/assets/avatars --avatar-name \${AVATAR_NAME} --gpio-avatar-select --gpio0 \${GPIO0_PIN} --gpio1 \${GPIO1_PIN} --avatar-gpio-00 \${AVATAR_GPIO_00} --avatar-gpio-01 \${AVATAR_GPIO_01} --avatar-gpio-10 \${AVATAR_GPIO_10} --avatar-gpio-11 \${AVATAR_GPIO_11} --width 1280 --height 720 --fps 30
Restart=always
RestartSec=1
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

cat > "$UVC_SETUP_SERVICE_FILE" <<EOF
[Unit]
Description=Setup RK3588 UVC Gadget (ConfigFS)
After=local-fs.target
Before=avatar-gateway.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$INSTALL_ROOT/scripts/setup_uvc_gadget.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable usbdevice.service 2>/dev/null || true
systemctl enable uvc-gadget-setup.service 2>/dev/null || true
systemctl enable --now avatar-gateway

echo "已安装并启动 avatar-gateway 服务。"
echo "可用命令: systemctl status avatar-gateway"