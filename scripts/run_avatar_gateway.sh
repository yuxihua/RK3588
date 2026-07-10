#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CAMERA="${CAMERA:-/dev/video0}"
RENDER_MODE="${RENDER_MODE:-beauty}"
OUTPUT_MODE="${OUTPUT_MODE:-network}"
OUTPUT_DEVICE="${OUTPUT_DEVICE:-/dev/video43}"
NETWORK_HOST="${NETWORK_HOST:-0.0.0.0}"
NETWORK_PORT="${NETWORK_PORT:-8080}"
NETWORK_PATH="${NETWORK_PATH:-/mjpeg}"
NETWORK_JPEG_QUALITY="${NETWORK_JPEG_QUALITY:-70}"
FALLBACK_STYLE="${FALLBACK_STYLE:-normal}"
BACKGROUND_MODE="${BACKGROUND_MODE:-camera}"
AVATAR_SCALE="${AVATAR_SCALE:-1.0}"
EYE_ANIMATION="${EYE_ANIMATION:-subtle}"
MOUTH_ANIMATION="${MOUTH_ANIMATION:-normal}"
MOUTH_STYLE="${MOUTH_STYLE:-normal}"
MOUTH_GAIN="${MOUTH_GAIN:-1.0}"
MOUTH_Y_OFFSET="${MOUTH_Y_OFFSET:-0.00}"
MOUTH_X_OFFSET="${MOUTH_X_OFFSET:-0.00}"
MAX_FACES="${MAX_FACES:-1}"
DETECT_EVERY="${DETECT_EVERY:-2}"
BEAUTY_STRENGTH="${BEAUTY_STRENGTH:-0.45}"

AVATAR_NAME="${AVATAR_NAME:-avatar_male}"
GPIO_AVATAR_SELECT="${GPIO_AVATAR_SELECT:-0}"
GPIO0_PIN="${GPIO0_PIN:-0}"
GPIO1_PIN="${GPIO1_PIN:-1}"
AVATAR_GPIO_00="${AVATAR_GPIO_00:-avatar_00}"
AVATAR_GPIO_01="${AVATAR_GPIO_01:-avatar_01}"
AVATAR_GPIO_10="${AVATAR_GPIO_10:-avatar_10}"
AVATAR_GPIO_11="${AVATAR_GPIO_11:-avatar_11}"

WIDTH="${WIDTH:-960}"
HEIGHT="${HEIGHT:-540}"
FPS="${FPS:-15}"

normalize_video_device() {
	local raw="$1"
	local first
	first="$(printf '%s' "$raw" | grep -oE '/dev/video[0-9]+' | head -n 1 || true)"
	if [[ -n "$first" ]]; then
		echo "$first"
	else
		echo "$raw"
	fi
}

resolve_avatar_fallback() {
	local candidates=(
		"$ROOT_DIR/assets/avatars/avatar_male.png"
		"$ROOT_DIR/assets/avatars/avatar_female.png"
		"$ROOT_DIR/assets/avatar.png"
	)
	local candidate
	for candidate in "${candidates[@]}"; do
		if [[ -f "$candidate" ]]; then
			echo "$candidate"
			return 0
		fi
	done
	echo "$ROOT_DIR/assets/avatar.png"
}

resolve_camera_device() {
	local requested="$1"
	if [[ -n "$requested" && -e "$requested" ]]; then
		echo "$requested"
		return 0
	fi

	local byid
	for byid in /dev/v4l/by-id/*-video-index0; do
		if [[ -e "$byid" ]]; then
			readlink -f "$byid"
			return 0
		fi
	done

	local candidate
	for candidate in /dev/video*; do
		if [[ -e "$candidate" ]]; then
			echo "$candidate"
			return 0
		fi
	done

	echo "$requested"
}

resolve_usb_output_device() {
	local requested="$1"
	if [[ -n "$requested" && -e "$requested" ]]; then
		if command -v v4l2-ctl >/dev/null 2>&1; then
			if v4l2-ctl -d "$requested" --all 2>/dev/null | grep -qi "Video Output"; then
				echo "$requested"
				return 0
			fi
		else
			# Without v4l2-ctl we cannot validate capabilities; keep requested device.
			echo "$requested"
			return 0
		fi
	fi

	local class_dir name_file node name
	for class_dir in /sys/class/video4linux/video*; do
		[[ -e "$class_dir" ]] || continue
		name_file="$class_dir/name"
		node="/dev/$(basename "$class_dir")"
		[[ -e "$node" ]] || continue
		[[ "$node" != "$CAMERA" ]] || continue

		# Prefer real output nodes when v4l2-ctl is available.
		if command -v v4l2-ctl >/dev/null 2>&1; then
			if ! v4l2-ctl -d "$node" --all 2>/dev/null | grep -qi "Video Output"; then
				continue
			fi
		fi

		if [[ -r "$name_file" ]]; then
			name="$(tr '[:upper:]' '[:lower:]' < "$name_file" 2>/dev/null || true)"
			if [[ "$name" == *"g_uvc"* || "$name" == *"dwc3-gadget"* || "$name" == *"uvc gadget"* ]]; then
				echo "$node"
				return 0
			fi
		fi
	done

	local candidate
	for candidate in /dev/video*; do
		[[ -e "$candidate" ]] || continue
		[[ "$candidate" != "$CAMERA" ]] || continue
		if command -v v4l2-ctl >/dev/null 2>&1; then
			if ! v4l2-ctl -d "$candidate" --all 2>/dev/null | grep -qi "Video Output"; then
				continue
			fi
		fi
		echo "$candidate"
		return 0
	done

	echo "$requested"
}

AVATAR_FALLBACK_PATH="$(resolve_avatar_fallback)"
CAMERA="$(resolve_camera_device "$CAMERA")"
OUTPUT_DEVICE="$(normalize_video_device "$OUTPUT_DEVICE")"
if [[ "$OUTPUT_MODE" == "usb" ]]; then
	OUTPUT_DEVICE="$(resolve_usb_output_device "$OUTPUT_DEVICE")"
fi

ARGS=(
	--camera "$CAMERA"
	--render-mode "$RENDER_MODE"
	--output-mode "$OUTPUT_MODE"
	--output "$OUTPUT_DEVICE"
	--network-host "$NETWORK_HOST"
	--network-port "$NETWORK_PORT"
	--network-path "$NETWORK_PATH"
	--network-jpeg-quality "$NETWORK_JPEG_QUALITY"
	--fallback-style "$FALLBACK_STYLE"
	--background-mode "$BACKGROUND_MODE"
	--avatar-scale "$AVATAR_SCALE"
	--eye-animation "$EYE_ANIMATION"
	--mouth-animation "$MOUTH_ANIMATION"
	--mouth-style "$MOUTH_STYLE"
	--mouth-gain "$MOUTH_GAIN"
	--mouth-y-offset "$MOUTH_Y_OFFSET"
	--mouth-x-offset "$MOUTH_X_OFFSET"
	--max-faces "$MAX_FACES"
	--detect-every "$DETECT_EVERY"
	--beauty-strength "$BEAUTY_STRENGTH"
	--avatar "$AVATAR_FALLBACK_PATH"
	--avatar-dir "$ROOT_DIR/assets/avatars"
	--avatar-name "$AVATAR_NAME"
	--gpio0 "$GPIO0_PIN"
	--gpio1 "$GPIO1_PIN"
	--avatar-gpio-00 "$AVATAR_GPIO_00"
	--avatar-gpio-01 "$AVATAR_GPIO_01"
	--avatar-gpio-10 "$AVATAR_GPIO_10"
	--avatar-gpio-11 "$AVATAR_GPIO_11"
	--width "$WIDTH"
	--height "$HEIGHT"
	--fps "$FPS"
)

if [[ "$GPIO_AVATAR_SELECT" == "1" || "$GPIO_AVATAR_SELECT" == "true" || "$GPIO_AVATAR_SELECT" == "on" ]]; then
	ARGS+=(--gpio-avatar-select)
fi

CPP_BIN="$ROOT_DIR/CPP/build/avatar_gateway"
if [[ -x "$CPP_BIN" ]]; then
	exec "$CPP_BIN" "${ARGS[@]}" "$@"
fi

exec "$PYTHON_BIN" "$ROOT_DIR/scripts/avatar_processor.py" "${ARGS[@]}" "$@"
