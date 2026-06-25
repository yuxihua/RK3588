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

link_into_node() {
  local target="$1"
  local node="$2"

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

if [[ ! -d "$CONFIGFS" ]]; then
  echo "configfs 未挂载，先执行: mount -t configfs none /sys/kernel/config" >&2
  exit 1
fi

if [[ -d "$GADGET_DIR" ]]; then
  if [[ -e "$GADGET_DIR/UDC" ]]; then
    echo "" > "$GADGET_DIR/UDC" 2>/dev/null || true
  fi

  # configfs 下很多属性节点不可直接 rm，清理我们创建过的符号链接即可。
  rm -f "$GADGET_DIR/configs/c.1/uvc.0" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/fs" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/hs" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/ss" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/fs/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/hs/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/control/class/ss/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/fs" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/hs" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/ss" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/fs/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/hs/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/class/ss/main" || true
  rm -f "$GADGET_DIR/functions/uvc.0/streaming/header/main" || true
fi

$MODPROBE libcomposite
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

mkdir -p functions/uvc.0/control/header/main
mkdir -p functions/uvc.0/control/class
mkdir -p functions/uvc.0/streaming/header
mkdir -p functions/uvc.0/streaming/class
mkdir -p functions/uvc.0/streaming/uncompressed/mjpeg/720p
mkdir -p functions/uvc.0/control/class/fs
mkdir -p functions/uvc.0/control/class/hs
mkdir -p functions/uvc.0/control/class/ss
mkdir -p functions/uvc.0/streaming/class/fs
mkdir -p functions/uvc.0/streaming/class/hs
mkdir -p functions/uvc.0/streaming/class/ss

link_into_node "$GADGET_DIR/functions/uvc.0/control/header/main" "$GADGET_DIR/functions/uvc.0/control/class/fs"
link_into_node "$GADGET_DIR/functions/uvc.0/control/header/main" "$GADGET_DIR/functions/uvc.0/control/class/hs"
link_into_node "$GADGET_DIR/functions/uvc.0/streaming/header/main" "$GADGET_DIR/functions/uvc.0/streaming/class/fs"
link_into_node "$GADGET_DIR/functions/uvc.0/streaming/header/main" "$GADGET_DIR/functions/uvc.0/streaming/class/hs"

# 下面的节点在不同内核版本里名字可能略有差异，保留最常见配置。
echo 1280 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/wWidth || true
echo 720 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/wHeight || true
echo 333333 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/dwFrameInterval || true
echo 1843200 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/dwMaxVideoFrameBufferSize || true
ln -s functions/uvc.0/streaming/uncompressed/mjpeg/720p functions/uvc.0/streaming/header/main || true
link_into_node "$GADGET_DIR/functions/uvc.0" "$GADGET_DIR/configs/c.1/uvc.0"

UDC_NAME="$(ls /sys/class/udc | head -n 1)"
if [[ -z "$UDC_NAME" ]]; then
  echo "未找到可用 UDC，确认 RK3588 该 USB 口是否支持设备模式。" >&2
  exit 1
fi

echo "$UDC_NAME" > UDC

echo "UVC gadget 已绑定到: $UDC_NAME"
