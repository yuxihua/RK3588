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
USBDEVICE_OVERRIDE_FILE="$USBDEVICE_OVERRIDE_DIR/00-avatar-usbdevice.sh"

install -d /etc/systemd/system
install -d "$INSTALL_ROOT"
cp -a "$PROJECT_ROOT"/. "$INSTALL_ROOT"/
chmod +x "$INSTALL_ROOT"/scripts/*.sh "$INSTALL_ROOT"/scripts/*.py
install -d "$INSTALL_ROOT/assets/avatars"

# Remove build caches copied from other machines (for example, Windows)
# to avoid CMake source/cache mismatch on target boards.
rm -rf "$INSTALL_ROOT/CPP/build" \
       "$INSTALL_ROOT/CPP/build-clang" \
       "$INSTALL_ROOT/CPP/build-mingw"

if command -v cmake >/dev/null 2>&1 && command -v g++ >/dev/null 2>&1; then
  if [[ -f "$INSTALL_ROOT/CPP/CMakeLists.txt" ]]; then
    cmake -S "$INSTALL_ROOT/CPP" -B "$INSTALL_ROOT/CPP/build"
    cmake --build "$INSTALL_ROOT/CPP/build" -j
  fi
fi

install -d "$USBDEVICE_OVERRIDE_DIR"
cat > "$USBDEVICE_OVERRIDE_FILE" <<'EOF'
#!/bin/sh

# Ensure vendor usbdevice starts both UVC and ADB by default.
USB_FUNCS="uvc adb"
UVC_INSTANCES="uvc.gs7"

uvc_prepare()
{
  set -- $(usb_instances uvc 2>/dev/null)
  UVC_INSTANCE="${1:-uvc.gs7}"
  UVC_DIR="$USB_FUNCTIONS_DIR/$UVC_INSTANCE"

  [ -d "$UVC_DIR" ] || return 0

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
chmod 0644 "$USBDEVICE_OVERRIDE_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
AVATAR_NAME=avatar_male
GPIO_AVATAR_SELECT=0
GPIO0_PIN=0
GPIO1_PIN=1
AVATAR_GPIO_00=avatar_00
AVATAR_GPIO_01=avatar_01
AVATAR_GPIO_10=avatar_10
AVATAR_GPIO_11=avatar_11
RENDER_MODE=beauty
OUTPUT_MODE=network
OUTPUT_DEVICE=/dev/video43
NETWORK_HOST=0.0.0.0
NETWORK_PORT=8080
NETWORK_PATH=/mjpeg
NETWORK_JPEG_QUALITY=70
FALLBACK_STYLE=cartoon
BACKGROUND_MODE=camera
AVATAR_SCALE=1.0
EYE_ANIMATION=off
MOUTH_ANIMATION=normal
MOUTH_STYLE=normal
MOUTH_GAIN=1.0
MOUTH_Y_OFFSET=0.00
MOUTH_X_OFFSET=0.00
MAX_FACES=1
DETECT_EVERY=2
BEAUTY_STRENGTH=0.45
WIDTH=960
HEIGHT=540
FPS=15
EOF
fi

if ! grep -q '^OUTPUT_MODE=' "$ENV_FILE"; then
  echo 'OUTPUT_MODE=network' >> "$ENV_FILE"
fi
if ! grep -q '^RENDER_MODE=' "$ENV_FILE"; then
  echo 'RENDER_MODE=beauty' >> "$ENV_FILE"
fi
if ! grep -q '^OUTPUT_DEVICE=' "$ENV_FILE"; then
  echo 'OUTPUT_DEVICE=/dev/video43' >> "$ENV_FILE"
fi
if ! grep -q '^NETWORK_HOST=' "$ENV_FILE"; then
  echo 'NETWORK_HOST=0.0.0.0' >> "$ENV_FILE"
fi
if ! grep -q '^NETWORK_PORT=' "$ENV_FILE"; then
  echo 'NETWORK_PORT=8080' >> "$ENV_FILE"
fi
if ! grep -q '^NETWORK_PATH=' "$ENV_FILE"; then
  echo 'NETWORK_PATH=/mjpeg' >> "$ENV_FILE"
fi
if ! grep -q '^NETWORK_JPEG_QUALITY=' "$ENV_FILE"; then
  echo 'NETWORK_JPEG_QUALITY=70' >> "$ENV_FILE"
fi
if ! grep -q '^FALLBACK_STYLE=' "$ENV_FILE"; then
  echo 'FALLBACK_STYLE=normal' >> "$ENV_FILE"
fi
if ! grep -q '^BACKGROUND_MODE=' "$ENV_FILE"; then
  echo 'BACKGROUND_MODE=camera' >> "$ENV_FILE"
fi
if ! grep -q '^AVATAR_SCALE=' "$ENV_FILE"; then
  echo 'AVATAR_SCALE=1.0' >> "$ENV_FILE"
fi
if ! grep -q '^EYE_ANIMATION=' "$ENV_FILE"; then
  echo 'EYE_ANIMATION=subtle' >> "$ENV_FILE"
fi
if ! grep -q '^MOUTH_ANIMATION=' "$ENV_FILE"; then
  echo 'MOUTH_ANIMATION=normal' >> "$ENV_FILE"
fi
if ! grep -q '^MOUTH_STYLE=' "$ENV_FILE"; then
  echo 'MOUTH_STYLE=normal' >> "$ENV_FILE"
fi
if ! grep -q '^MOUTH_GAIN=' "$ENV_FILE"; then
  echo 'MOUTH_GAIN=1.0' >> "$ENV_FILE"
fi
if ! grep -q '^MOUTH_Y_OFFSET=' "$ENV_FILE"; then
  echo 'MOUTH_Y_OFFSET=0.00' >> "$ENV_FILE"
fi
if ! grep -q '^MOUTH_X_OFFSET=' "$ENV_FILE"; then
  echo 'MOUTH_X_OFFSET=0.00' >> "$ENV_FILE"
fi
if ! grep -q '^MAX_FACES=' "$ENV_FILE"; then
  echo 'MAX_FACES=1' >> "$ENV_FILE"
fi
if ! grep -q '^DETECT_EVERY=' "$ENV_FILE"; then
  echo 'DETECT_EVERY=2' >> "$ENV_FILE"
fi
if ! grep -q '^BEAUTY_STRENGTH=' "$ENV_FILE"; then
  echo 'BEAUTY_STRENGTH=0.45' >> "$ENV_FILE"
fi
if ! grep -q '^WIDTH=' "$ENV_FILE"; then
  echo 'WIDTH=960' >> "$ENV_FILE"
fi
if ! grep -q '^HEIGHT=' "$ENV_FILE"; then
  echo 'HEIGHT=540' >> "$ENV_FILE"
fi
if ! grep -q '^FPS=' "$ENV_FILE"; then
  echo 'FPS=15' >> "$ENV_FILE"
fi

# Migrate legacy defaults from older installs so virtual avatar works out-of-box.
if grep -q '^AVATAR_NAME=avatar$' "$ENV_FILE"; then
  sed -i 's/^AVATAR_NAME=avatar$/AVATAR_NAME=avatar_male/' "$ENV_FILE"
fi
if grep -q '^GPIO_AVATAR_SELECT=1$' "$ENV_FILE"; then
  sed -i 's/^GPIO_AVATAR_SELECT=1$/GPIO_AVATAR_SELECT=0/' "$ENV_FILE"
fi
if grep -q '^FALLBACK_STYLE=cartoon$' "$ENV_FILE"; then
  sed -i 's/^FALLBACK_STYLE=cartoon$/FALLBACK_STYLE=normal/' "$ENV_FILE"
fi
if grep -q '^EYE_ANIMATION=off$' "$ENV_FILE"; then
  sed -i 's/^EYE_ANIMATION=off$/EYE_ANIMATION=subtle/' "$ENV_FILE"
fi
if grep -q '^MOUTH_ANIMATION=off$' "$ENV_FILE"; then
  sed -i 's/^MOUTH_ANIMATION=off$/MOUTH_ANIMATION=normal/' "$ENV_FILE"
fi
if grep -q '^MOUTH_ANIMATION=subtle$' "$ENV_FILE"; then
  sed -i 's/^MOUTH_ANIMATION=subtle$/MOUTH_ANIMATION=normal/' "$ENV_FILE"
fi
if grep -q '^WIDTH=640$' "$ENV_FILE"; then
  sed -i 's/^WIDTH=640$/WIDTH=960/' "$ENV_FILE"
fi
if grep -q '^HEIGHT=360$' "$ENV_FILE"; then
  sed -i 's/^HEIGHT=360$/HEIGHT=540/' "$ENV_FILE"
fi
if grep -q '^WIDTH=1280$' "$ENV_FILE"; then
  sed -i 's/^WIDTH=1280$/WIDTH=960/' "$ENV_FILE"
fi
if grep -q '^HEIGHT=720$' "$ENV_FILE"; then
  sed -i 's/^HEIGHT=720$/HEIGHT=540/' "$ENV_FILE"
fi
if grep -q '^FPS=30$' "$ENV_FILE"; then
  sed -i 's/^FPS=30$/FPS=15/' "$ENV_FILE"
fi
if grep -q '^FPS=20$' "$ENV_FILE"; then
  sed -i 's/^FPS=20$/FPS=15/' "$ENV_FILE"
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=RK3588 USB Avatar Gateway
After=network.target local-fs.target usbdevice.service uvc-gadget-setup.service
Wants=usbdevice.service uvc-gadget-setup.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT
EnvironmentFile=-$ENV_FILE
Environment=AVATAR_NAME=avatar_male
Environment=GPIO_AVATAR_SELECT=0
Environment=GPIO0_PIN=0
Environment=GPIO1_PIN=1
Environment=AVATAR_GPIO_00=avatar_00
Environment=AVATAR_GPIO_01=avatar_01
Environment=AVATAR_GPIO_10=avatar_10
Environment=AVATAR_GPIO_11=avatar_11
Environment=RENDER_MODE=beauty
Environment=OUTPUT_MODE=network
Environment=OUTPUT_DEVICE=/dev/video43
Environment=NETWORK_HOST=0.0.0.0
Environment=NETWORK_PORT=8080
Environment=NETWORK_PATH=/mjpeg
Environment=NETWORK_JPEG_QUALITY=70
Environment=FALLBACK_STYLE=normal
Environment=BACKGROUND_MODE=camera
Environment=AVATAR_SCALE=1.0
Environment=EYE_ANIMATION=subtle
Environment=MOUTH_ANIMATION=normal
Environment=MOUTH_STYLE=normal
Environment=MOUTH_GAIN=1.0
Environment=MOUTH_Y_OFFSET=0.00
Environment=MOUTH_X_OFFSET=0.00
Environment=MAX_FACES=1
Environment=DETECT_EVERY=2
Environment=BEAUTY_STRENGTH=0.45
Environment=WIDTH=960
Environment=HEIGHT=540
Environment=FPS=15
ExecStart=$INSTALL_ROOT/scripts/run_avatar_gateway.sh
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