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

if [[ ! -d "$CONFIGFS" ]]; then
  echo "configfs 未挂载，先执行: mount -t configfs none /sys/kernel/config" >&2
  exit 1
fi

if [[ -d "$GADGET_DIR" ]]; then
  if [[ -f "$GADGET_DIR/UDC" ]]; then
    echo "" > "$GADGET_DIR/UDC" || true
  fi
  find "$GADGET_DIR" -type l -delete || true
  rm -rf "$GADGET_DIR"
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

ln -s functions/uvc.0/control/header/main functions/uvc.0/control/class/fs || true
ln -s functions/uvc.0/control/header/main functions/uvc.0/control/class/hs || true
ln -s functions/uvc.0/streaming/header/main functions/uvc.0/streaming/class/fs || true
ln -s functions/uvc.0/streaming/header/main functions/uvc.0/streaming/class/hs || true

# 下面的节点在不同内核版本里名字可能略有差异，保留最常见配置。
echo 1280 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/wWidth || true
echo 720 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/wHeight || true
echo 333333 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/dwFrameInterval || true
echo 1843200 > functions/uvc.0/streaming/uncompressed/mjpeg/720p/dwMaxVideoFrameBufferSize || true
ln -s functions/uvc.0/streaming/uncompressed/mjpeg/720p functions/uvc.0/streaming/header/main || true
ln -s functions/uvc.0 configs/c.1/uvc.0 || true

UDC_NAME="$(ls /sys/class/udc | head -n 1)"
if [[ -z "$UDC_NAME" ]]; then
  echo "未找到可用 UDC，确认 RK3588 该 USB 口是否支持设备模式。" >&2
  exit 1
fi

echo "$UDC_NAME" > UDC

echo "UVC gadget 已绑定到: $UDC_NAME"
