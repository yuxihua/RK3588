#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "请使用 root 执行此脚本。" >&2
  exit 1
fi

MODPROBE="${MODPROBE:-modprobe}"
CONFIGFS=/sys/kernel/config
GADGET_DIR="$CONFIGFS/usb_gadget/rk3588_uvc"
UDC_NAME=""
UVC_FUNC="uvc.0"

set_usb_device_role() {
  local role_path

  for role_path in \
    /sys/class/usb_role/*/role \
    /sys/devices/platform/fc000000.usb/otg_role \
    /sys/devices/platform/fc000000.usb/role \
    /sys/kernel/debug/usb/fc000000.usb/mode
  do
    [[ -e "$role_path" ]] || continue
    echo device > "$role_path" 2>/dev/null || echo peripheral > "$role_path" 2>/dev/null || true
  done
}

unbind_all_gadgets() {
  local udc_file
  for udc_file in "$CONFIGFS"/usb_gadget/*/UDC; do
    [[ -e "$udc_file" ]] || continue
    echo "" > "$udc_file" 2>/dev/null || true
  done
}

link_into_node() {
  local target="$1"
  local node="$2"
  local node_parent

  node_parent="$(dirname "$node")"
  mkdir -p "$node_parent"

  if [[ -L "$node" || ( -e "$node" && ! -d "$node" ) ]]; then
    rm -f "$node" || true
  fi

  if [[ -d "$node" ]]; then
    rm -f "$node/main" || true
    ln -s "$target" "$node/main" || true
  else
    ln -s "$target" "$node" || true
  fi
}

link_uvc_function() {
  # configfs is picky about how function links are created; try common forms.
  rm -f "$GADGET_DIR/configs/c.1/$UVC_FUNC" 2>/dev/null || true
  rm -f "$GADGET_DIR/configs/c.1/f1" 2>/dev/null || true

  # Prefer the same link style verified by acm.usb0 on this board.
  (
    cd "$GADGET_DIR"
    ln -s "functions/$UVC_FUNC" "configs/c.1/$UVC_FUNC" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/configs/c.1/$UVC_FUNC" ]] && return 0

  # Some vendor kernels only accept explicit link names like f1.
  (
    cd "$GADGET_DIR"
    ln -s "functions/$UVC_FUNC" "configs/c.1/f1" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/configs/c.1/f1" ]] && return 0

  # Last fallback with absolute target.
  (
    cd "$GADGET_DIR"
    ln -s "$(pwd)/functions/$UVC_FUNC" "configs/c.1/f1" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/configs/c.1/f1" ]] && return 0

  return 1
}

if [[ ! -d "$CONFIGFS" ]]; then
  echo "configfs 未挂载，先执行: mount -t configfs none /sys/kernel/config" >&2
  exit 1
fi

if [[ -d "$GADGET_DIR" ]]; then
  if [[ -e "$GADGET_DIR/UDC" ]]; then
    echo "" > "$GADGET_DIR/UDC" 2>/dev/null || true
  fi

  # configfs 下很多节点是内核导出的目录或属性，不能直接 rm。
  # 这里只清理我们可能创建过的符号链接，避免报错刷屏。
  rm -f "$GADGET_DIR/configs/c.1/uvc.0" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/control/class/fs/h" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/control/class/ss/h" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/streaming/header/h/u" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/streaming/header/h/m" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/fs/h" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/hs/h" || true
  rm -f "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/ss/h" || true
fi

set_usb_device_role
unbind_all_gadgets

$MODPROBE libcomposite
$MODPROBE usb_f_uvc 2>/dev/null || true
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

echo 0x1d6b > idVendor
echo 0x0104 > idProduct
mkdir -p strings/0x409
mkdir -p configs/c.1/strings/0x409

echo "RK3588" > strings/0x409/manufacturer
echo "USB Virtual Camera Gateway" > strings/0x409/product
echo "0001" > strings/0x409/serialnumber
echo "UVC gadget configuration" > configs/c.1/strings/0x409/configuration
echo 120 > configs/c.1/MaxPower

if [[ ! -d "functions/$UVC_FUNC" ]]; then
  mkdir "functions/$UVC_FUNC"
fi

mkdir -p "functions/$UVC_FUNC/control/header/h"
mkdir -p "functions/$UVC_FUNC/control/class"
mkdir -p "functions/$UVC_FUNC/streaming/header"
mkdir -p "functions/$UVC_FUNC/streaming/class"
mkdir -p "functions/$UVC_FUNC/streaming/uncompressed/u/240p"
mkdir -p "functions/$UVC_FUNC/streaming/mjpeg/m/240p"
mkdir -p "functions/$UVC_FUNC/streaming/color_matching/default"

# Uncompressed YUYV 320x240 @ 15/30 fps
echo 1 > "functions/$UVC_FUNC/streaming/uncompressed/u/bFormatIndex" || true
echo 1 > "functions/$UVC_FUNC/streaming/uncompressed/u/bNumFrameDescriptors" || true
echo YUY2 > "functions/$UVC_FUNC/streaming/uncompressed/u/guidFormat" || true
echo 16 > "functions/$UVC_FUNC/streaming/uncompressed/u/bBitsPerPixel" || true

echo 1 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/bFrameIndex" || true
echo 320 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/wWidth" || true
echo 240 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/wHeight" || true
echo 1152000 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMinBitRate" || true
echo 2304000 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMaxBitRate" || true
echo 153600 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMaxVideoFrameBufferSize" || true
echo 666666 > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwDefaultFrameInterval" || true
cat > "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwFrameInterval" <<'EOF'
666666
333333
EOF

# MJPEG 320x240 @ 15/30 fps
echo 2 > "functions/$UVC_FUNC/streaming/mjpeg/m/bFormatIndex" || true
echo 1 > "functions/$UVC_FUNC/streaming/mjpeg/m/bNumFrameDescriptors" || true

echo 1 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/bFrameIndex" || true
echo 320 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/wWidth" || true
echo 240 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/wHeight" || true
echo 1152000 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMinBitRate" || true
echo 4608000 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMaxBitRate" || true
echo 153600 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMaxVideoFrameBufferSize" || true
echo 666666 > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwDefaultFrameInterval" || true
cat > "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwFrameInterval" <<'EOF'
666666
333333
EOF

# Link control/streaming headers into class directories.
ln -s header/h "functions/$UVC_FUNC/control/class/fs/h" 2>/dev/null || true
ln -s header/h "functions/$UVC_FUNC/control/class/ss/h" 2>/dev/null || true
ln -s ../../uncompressed/u "functions/$UVC_FUNC/streaming/header/h/u" 2>/dev/null || true
ln -s ../../mjpeg/m "functions/$UVC_FUNC/streaming/header/h/m" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/fs/h" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/hs/h" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/ss/h" 2>/dev/null || true
if ! link_uvc_function; then
  echo "无法把 functions/$UVC_FUNC 链接到 configs/c.1，UVC 配置不完整。" >&2
  ls -la "functions" >&2 || true
  ls -la "configs/c.1" >&2 || true
  exit 1
fi

UDC_NAME="$(ls /sys/class/udc | head -n 1)"
if [[ -z "$UDC_NAME" ]]; then
  echo "未找到可用 UDC，确认 RK3588 该 USB 口是否支持设备模式。" >&2
  exit 1
fi

if ! echo "$UDC_NAME" > UDC 2>/dev/null; then
  # Retry once after forcing peripheral role and unbinding all gadgets again.
  set_usb_device_role
  unbind_all_gadgets
  if ! echo "$UDC_NAME" > UDC 2>/dev/null; then
    echo "绑定 UDC 失败: $UDC_NAME（可能仍处于 host 角色或被其它功能占用）" >&2
    exit 1
  fi
fi

echo "UVC gadget 已绑定到: $UDC_NAME"
