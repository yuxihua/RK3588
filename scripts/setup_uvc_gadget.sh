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
# Keep Rockchip-friendly defaults while still allowing override via environment.
UVC_FUNC="${USB_GADGET_UVC_FUNC:-uvc.gs7}"
CFG_NAME="${USB_GADGET_CFG_NAME:-b.1}"
CFG_DIR="configs/$CFG_NAME"
USB_GADGET_FORCE_CONFIGFS="${USB_GADGET_FORCE_CONFIGFS:-0}"

ensure_cfg_dir() {
  local requested="${1:-$CFG_NAME}"
  local candidate alt existing

  candidate="$requested"
  alt="c.1"
  [[ "$candidate" == "c.1" ]] && alt="b.1"

  if [[ -d "$GADGET_DIR/configs/$candidate" ]]; then
    CFG_NAME="$candidate"
    CFG_DIR="configs/$CFG_NAME"
    return 0
  fi

  if mkdir -p "$GADGET_DIR/configs/$candidate/strings/0x409" 2>/dev/null; then
    CFG_NAME="$candidate"
    CFG_DIR="configs/$CFG_NAME"
    return 0
  fi

  if [[ -d "$GADGET_DIR/configs/$alt" ]]; then
    CFG_NAME="$alt"
    CFG_DIR="configs/$CFG_NAME"
    return 0
  fi

  if mkdir -p "$GADGET_DIR/configs/$alt/strings/0x409" 2>/dev/null; then
    CFG_NAME="$alt"
    CFG_DIR="configs/$CFG_NAME"
    return 0
  fi

  for existing in "$GADGET_DIR"/configs/*; do
    [[ -d "$existing" ]] || continue
    CFG_NAME="$(basename "$existing")"
    CFG_DIR="configs/$CFG_NAME"
    mkdir -p "$GADGET_DIR/$CFG_DIR/strings/0x409" 2>/dev/null || true
    return 0
  done

  return 1
}

has_usbdevice_service() {
  local load_state
  load_state="$(systemctl show -p LoadState --value usbdevice.service 2>/dev/null || true)"
  [[ "$load_state" == "loaded" ]]
}

try_vendor_usbdevice_and_exit() {
  if [[ "$USB_GADGET_FORCE_CONFIGFS" == "1" ]]; then
    return 1
  fi

  if ! command -v /usr/bin/usbdevice >/dev/null 2>&1; then
    return 1
  fi

  # Prefer direct invocation to avoid systemd forking/stop cycles on some vendor images.
  /usr/bin/usbdevice start >/dev/null 2>&1 || true

  local udc_file
  for udc_file in "$CONFIGFS"/usb_gadget/*/UDC; do
    [[ -e "$udc_file" ]] || continue
    if [[ -s "$udc_file" ]]; then
      echo "使用 vendor usbdevice 命令流程: ${udc_file%/UDC}"
      exit 0
    fi
  done

  # Some vendor service variants leave gadget unbound; force-bind once.
  local udc_name gadget_path owner_link owner_path owner_name owner_udc
  udc_name="$(ls /sys/class/udc 2>/dev/null | head -n 1 || true)"
  if [[ -n "$udc_name" ]]; then
    owner_link="/sys/class/udc/$udc_name/device/gadget"
    owner_path="$(readlink -f "$owner_link" 2>/dev/null || true)"
    owner_name="$(basename "$owner_path" 2>/dev/null || true)"
    if [[ -n "$owner_name" && "$owner_name" != "gadget" ]]; then
      owner_udc="$CONFIGFS/usb_gadget/$owner_name/UDC"
      if [[ -w "$owner_udc" ]]; then
        echo "" > "$owner_udc" 2>/dev/null || true
      fi
    fi

    for gadget_path in "$CONFIGFS"/usb_gadget/rockchip "$CONFIGFS"/usb_gadget/rk3588_uvc; do
      [[ -d "$gadget_path" ]] || continue
      [[ -w "$gadget_path/UDC" ]] || continue
      echo "$udc_name" > "$gadget_path/UDC" 2>/dev/null || true
      if [[ -s "$gadget_path/UDC" ]]; then
        echo "vendor 流程已强制绑定 UDC: $gadget_path -> $udc_name"
        exit 0
      fi
    done
  fi

  # Even if host is not attached yet, keep vendor flow and avoid conflicting writes.
  echo "使用 vendor usbdevice 命令流程，等待主机枚举连接。"
  exit 0
}

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

cleanup_node() {
  local node="$1"
  [[ -e "$node" || -L "$node" ]] || return 0
  rm -f "$node" 2>/dev/null || true
  rmdir "$node" 2>/dev/null || true
  rm -rf "$node" 2>/dev/null || true
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
  local link_name="f-uvc.${UVC_FUNC#uvc.}"

  # configfs is picky about how function links are created; try common forms.
  cleanup_node "$GADGET_DIR/$CFG_DIR/$UVC_FUNC"
  cleanup_node "$GADGET_DIR/$CFG_DIR/f1"
  cleanup_node "$GADGET_DIR/$CFG_DIR/$link_name"

  # Some vendor kernels require target relative to config dir.
  (
    cd "$GADGET_DIR/$CFG_DIR"
    ln -s "../../functions/$UVC_FUNC" "$UVC_FUNC" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/$UVC_FUNC" ]] && return 0

  (
    cd "$GADGET_DIR/$CFG_DIR"
    ln -s "../../functions/$UVC_FUNC" "f1" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/f1" ]] && return 0

  # Prefer the same link style verified by acm.usb0 on this board.
  (
    cd "$GADGET_DIR"
    ln -s "functions/$UVC_FUNC" "$CFG_DIR/$UVC_FUNC" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/$UVC_FUNC" ]] && return 0

  # Some vendor kernels only accept explicit link names like f1.
  (
    cd "$GADGET_DIR"
    ln -s "functions/$UVC_FUNC" "$CFG_DIR/f1" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/f1" ]] && return 0

  # Rockchip vendor kernels often use f-uvc.* naming.
  (
    cd "$GADGET_DIR"
    ln -s "functions/$UVC_FUNC" "$CFG_DIR/$link_name" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/$link_name" ]] && return 0

  # Last relative style seen on vendor trees.
  (
    cd "$GADGET_DIR/$CFG_DIR"
    ln -s "../../../../usb_gadget/$(basename "$GADGET_DIR")/functions/$UVC_FUNC" "$link_name" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/$link_name" ]] && return 0

  # Last fallback with absolute target.
  (
    cd "$GADGET_DIR"
    ln -s "$(pwd)/functions/$UVC_FUNC" "$CFG_DIR/f1" 2>/dev/null || true
  )
  [[ -L "$GADGET_DIR/$CFG_DIR/f1" ]] && return 0

  return 1
}

write_cfg() {
  local value="$1"
  local path="$2"

  # Vendor kernels may expose some attributes as read-only; skip quietly.
  [[ -e "$path" ]] || return 0
  { printf '%s\n' "$value" > "$path"; } 2>/dev/null || true
}

write_cfg_lines() {
  local path="$1"
  shift

  [[ -e "$path" ]] || return 0
  {
    local line
    for line in "$@"; do
      printf '%s\n' "$line"
    done
  } > "$path" 2>/dev/null || true
}

fallback_vendor_usbdevice() {
  local service_name="usbdevice.service"
  local udc_file

  if [[ "$USB_GADGET_FORCE_CONFIGFS" == "1" ]]; then
    return 1
  fi

  # If board vendor manages gadget via usbdevice, delegate to it.
  if ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  if ! has_usbdevice_service; then
    return 1
  fi

  systemctl enable "$service_name" >/dev/null 2>&1 || true
  systemctl restart "$service_name" >/dev/null 2>&1 || return 1

  # Success when any gadget is bound to a UDC.
  for udc_file in "$CONFIGFS"/usb_gadget/*/UDC; do
    [[ -e "$udc_file" ]] || continue
    if [[ -s "$udc_file" ]]; then
      echo "已切换到 vendor usbdevice UVC 流程: ${udc_file%/UDC}" >&2
      return 0
    fi
  done

  return 1
}

if [[ ! -d "$CONFIGFS" ]]; then
  echo "configfs 未挂载，先执行: mount -t configfs none /sys/kernel/config" >&2
  exit 1
fi

if [[ "$USB_GADGET_FORCE_CONFIGFS" == "1" ]]; then
  echo "USB_GADGET_FORCE_CONFIGFS=1，跳过 vendor usbdevice，使用原生 configfs UVC。"
fi

# Continue with native configfs flow when vendor path is unavailable or disabled.
try_vendor_usbdevice_and_exit || true

if [[ -d "$GADGET_DIR" ]]; then
  if [[ -e "$GADGET_DIR/UDC" ]]; then
    echo "" > "$GADGET_DIR/UDC" 2>/dev/null || true
  fi

  # configfs 下很多节点是内核导出的目录或属性，不能直接 rm。
  # 这里只清理我们可能创建过的符号链接，避免报错刷屏。
  cleanup_node "$GADGET_DIR/$CFG_DIR/$UVC_FUNC"
  cleanup_node "$GADGET_DIR/$CFG_DIR/f1"
  cleanup_node "$GADGET_DIR/$CFG_DIR/f-uvc.${UVC_FUNC#uvc.}"
  cleanup_node "$GADGET_DIR/configs/c.1/uvc.0"
  cleanup_node "$GADGET_DIR/configs/c.1/f1"
  cleanup_node "$GADGET_DIR/configs/c.1/f-uvc.0"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/control/class/fs/h"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/control/class/ss/h"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/streaming/header/h/u"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/streaming/header/h/m"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/fs/h"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/hs/h"
  cleanup_node "$GADGET_DIR/functions/$UVC_FUNC/streaming/class/ss/h"
fi

set_usb_device_role
unbind_all_gadgets

$MODPROBE libcomposite
$MODPROBE usb_f_uvc 2>/dev/null || true
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

if ! ensure_cfg_dir "$CFG_NAME"; then
  echo "无法创建可用的 gadget config 目录（尝试过 b.1/c.1）。" >&2
  exit 1
fi

echo 0x1d6b > idVendor
echo 0x0104 > idProduct
mkdir -p strings/0x409
mkdir -p "$CFG_DIR/strings/0x409" 2>/dev/null || true

echo "RK3588" > strings/0x409/manufacturer
echo "USB Virtual Camera Gateway" > strings/0x409/product
echo "0001" > strings/0x409/serialnumber
echo "UVC gadget configuration" > "$CFG_DIR/strings/0x409/configuration"
echo 120 > "$CFG_DIR/MaxPower"

if [[ ! -d "functions/$UVC_FUNC" ]]; then
  mkdir "functions/$UVC_FUNC"
fi

mkdir -p "functions/$UVC_FUNC/control/header/h"
mkdir -p "functions/$UVC_FUNC/control/class"
mkdir -p "functions/$UVC_FUNC/streaming/header"
mkdir -p "functions/$UVC_FUNC/streaming/header/h"
mkdir -p "functions/$UVC_FUNC/streaming/class"
mkdir -p "functions/$UVC_FUNC/streaming/uncompressed/u/240p"
mkdir -p "functions/$UVC_FUNC/streaming/mjpeg/m/240p"
mkdir -p "functions/$UVC_FUNC/streaming/color_matching/default"

# Uncompressed YUYV 320x240 @ 15/30 fps
write_cfg 1 "functions/$UVC_FUNC/streaming/uncompressed/u/bFormatIndex"
write_cfg 1 "functions/$UVC_FUNC/streaming/uncompressed/u/bNumFrameDescriptors"
write_cfg YUY2 "functions/$UVC_FUNC/streaming/uncompressed/u/guidFormat"
write_cfg 16 "functions/$UVC_FUNC/streaming/uncompressed/u/bBitsPerPixel"

write_cfg 1 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/bFrameIndex"
write_cfg 320 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/wWidth"
write_cfg 240 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/wHeight"
write_cfg 1152000 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMinBitRate"
write_cfg 2304000 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMaxBitRate"
write_cfg 153600 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwMaxVideoFrameBufferSize"
write_cfg 666666 "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwDefaultFrameInterval"
write_cfg_lines "functions/$UVC_FUNC/streaming/uncompressed/u/240p/dwFrameInterval" 666666 333333

# MJPEG 320x240 @ 15/30 fps
write_cfg 2 "functions/$UVC_FUNC/streaming/mjpeg/m/bFormatIndex"
write_cfg 1 "functions/$UVC_FUNC/streaming/mjpeg/m/bNumFrameDescriptors"

write_cfg 1 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/bFrameIndex"
write_cfg 320 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/wWidth"
write_cfg 240 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/wHeight"
write_cfg 1152000 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMinBitRate"
write_cfg 4608000 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMaxBitRate"
write_cfg 153600 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwMaxVideoFrameBufferSize"
write_cfg 666666 "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwDefaultFrameInterval"
write_cfg_lines "functions/$UVC_FUNC/streaming/mjpeg/m/240p/dwFrameInterval" 666666 333333

# Link control/streaming headers into class directories.
cleanup_node "functions/$UVC_FUNC/control/class/fs/h"
cleanup_node "functions/$UVC_FUNC/control/class/ss/h"
cleanup_node "functions/$UVC_FUNC/streaming/header/h/u"
cleanup_node "functions/$UVC_FUNC/streaming/header/h/m"
cleanup_node "functions/$UVC_FUNC/streaming/class/fs/h"
cleanup_node "functions/$UVC_FUNC/streaming/class/hs/h"
cleanup_node "functions/$UVC_FUNC/streaming/class/ss/h"
ln -s header/h "functions/$UVC_FUNC/control/class/fs/h" 2>/dev/null || true
ln -s header/h "functions/$UVC_FUNC/control/class/ss/h" 2>/dev/null || true
ln -s ../../uncompressed/u "functions/$UVC_FUNC/streaming/header/h/u" 2>/dev/null || true
ln -s ../../mjpeg/m "functions/$UVC_FUNC/streaming/header/h/m" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/fs/h" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/hs/h" 2>/dev/null || true
ln -s ../../header/h "functions/$UVC_FUNC/streaming/class/ss/h" 2>/dev/null || true
if ! link_uvc_function; then
  echo "无法把 functions/$UVC_FUNC 链接到 $CFG_DIR，UVC 配置不完整。" >&2
  ls -la "functions" >&2 || true
  ls -la "$CFG_DIR" >&2 || true
  if fallback_vendor_usbdevice; then
    exit 0
  fi
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
