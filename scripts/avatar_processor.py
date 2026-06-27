#!/usr/bin/env python3
"""Real-time USB camera avatar processor for RK3588."""

from __future__ import annotations

import argparse
import os
import random
import re
import signal
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http import server as http_server
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np


@dataclass
class FrameSpec:
    width: int
    height: int
    fps: int


@dataclass
class FaceState:
    face: Tuple[int, int, int, int]
    angle: float = 0.0
    mouth_open: float = 0.0
    eye_open: float = 1.0


@dataclass
class TrackingState:
    face: Optional[Tuple[float, float, float, float]] = None
    angle: float = 0.0
    mouth_open: float = 0.0
    eye_open: float = 1.0
    blink_progress: float = 0.0
    next_blink_at: float = 0.0


STOP_REQUESTED = False
TRACKING_STATE = TrackingState()
BUILD_TAG = "2026-06-26-uvc-probe-v2"
STATIC_STAGE_CACHE: Dict[Tuple[int, int], np.ndarray] = {}
AVATAR_FACE_BOX_CACHE: Dict[int, Optional[Tuple[int, int, int, int]]] = {}
random.seed()


def get_static_stage_bgr(width: int, height: int) -> np.ndarray:
    key = (int(width), int(height))
    cached = STATIC_STAGE_CACHE.get(key)
    if cached is not None:
        return cached.copy()

    phase = 0.0
    stage = create_stage_background(width, height, phase)
    stage = add_vignette(stage)
    stage = add_grid_overlay(stage, phase)
    stage = add_side_panels(stage, phase)
    stage = add_frame_accents(stage, phase)
    stage = add_bottom_band(stage, phase)
    stage = apply_cyber_grade(stage, phase)
    STATIC_STAGE_CACHE[key] = stage[:, :, :3].copy()
    return STATIC_STAGE_CACHE[key].copy()


def get_haarcascade_dir() -> Path:
    candidates = []

    cv2_data = getattr(cv2, "data", None)
    if cv2_data is not None:
        cascade_root = getattr(cv2_data, "haarcascades", "")
        if cascade_root:
            candidates.append(Path(cascade_root))

    cv2_module_dir = Path(cv2.__file__).resolve().parent
    candidates.extend(
        [
            cv2_module_dir / "data" / "haarcascades",
            Path("/usr/share/opencv4/haarcascades"),
            Path("/usr/share/opencv/haarcascades"),
            Path("/usr/local/share/opencv4/haarcascades"),
            Path("/usr/local/share/opencv/haarcascades"),
        ]
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    raise RuntimeError("无法找到 OpenCV haarcascade 目录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USB camera avatar processor")
    parser.add_argument("--output-mode", choices=["usb", "network"], default="usb", help="Output mode")
    parser.add_argument("--camera", default="/dev/video0", help="Input USB camera device")
    parser.add_argument("--output", default="auto", help="Output UVC gadget device, or auto")
    parser.add_argument("--network-host", default="0.0.0.0", help="Network output bind host")
    parser.add_argument("--network-port", type=int, default=8080, help="Network output port")
    parser.add_argument("--network-path", default="/mjpeg", help="Network output path")
    parser.add_argument("--network-jpeg-quality", type=int, default=85, help="Network output JPEG quality")
    parser.add_argument("--avatar", default="", help="PNG avatar with alpha channel")
    parser.add_argument("--avatar-dir", default="", help="Directory that stores selectable avatar PNG files")
    parser.add_argument(
        "--avatar-name",
        nargs="?",
        const="",
        default="",
        help="Avatar name to load from avatar-dir (without .png)",
    )
    parser.add_argument("--gpio-avatar-select", action="store_true", help="Enable GPIO based avatar select")
    parser.add_argument("--gpio0", type=int, default=0, help="GPIO pin index for avatar select bit0")
    parser.add_argument("--gpio1", type=int, default=1, help="GPIO pin index for avatar select bit1")
    parser.add_argument("--gpio-poll-interval", type=float, default=0.20, help="GPIO polling interval in seconds")
    parser.add_argument("--avatar-gpio-00", default="avatar_00", help="Avatar name when GPIO1 GPIO0 = 00")
    parser.add_argument("--avatar-gpio-01", default="avatar_01", help="Avatar name when GPIO1 GPIO0 = 01")
    parser.add_argument("--avatar-gpio-10", default="avatar_10", help="Avatar name when GPIO1 GPIO0 = 10")
    parser.add_argument("--avatar-gpio-11", default="avatar_11", help="Avatar name when GPIO1 GPIO0 = 11")
    parser.add_argument("--width", type=int, default=1280, help="Frame width")
    parser.add_argument("--height", type=int, default=720, help="Frame height")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate")
    parser.add_argument("--mirror", action="store_true", help="Mirror the camera image")
    parser.add_argument(
        "--background-mode",
        choices=["virtual", "camera"],
        default="virtual",
        help="Background mode: virtual stage or original camera background",
    )
    parser.add_argument(
        "--fallback-style",
        choices=["cartoon", "normal"],
        default="cartoon",
        help="Style used when no avatar is loaded",
    )
    return parser


def handle_signal(signum: int, frame) -> None:  # noqa: D401, ARG001
    global STOP_REQUESTED
    STOP_REQUESTED = True


for _sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(_sig, handle_signal)


def load_avatar(path: str) -> Optional[np.ndarray]:
    if not path:
        return None
    avatar_path = Path(path)
    if not avatar_path.is_file():
        return None
    image = cv2.imread(str(avatar_path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        return None
    return image


def resolve_avatar_path(avatar_path: str, avatar_dir: str, avatar_name: str) -> str:
    def _normalize_avatar_filename(name: str) -> str:
        text = (name or "").strip().lower()
        return re.sub(r"\s*\.png$", ".png", text)

    selected_name = avatar_name.strip()
    selected_dir = avatar_dir.strip()

    if selected_name:
        candidate_names = [selected_name]
        if not selected_name.lower().endswith(".png"):
            candidate_names.append(f"{selected_name}.png")

        candidate_dirs = []
        if selected_dir:
            candidate_dirs.append(Path(selected_dir))

        if avatar_path:
            candidate_dirs.append(Path(avatar_path).parent)

        default_dir = Path(__file__).resolve().parent.parent / "assets" / "avatars"
        candidate_dirs.append(default_dir)

        for directory in candidate_dirs:
            for filename in candidate_names:
                candidate = directory / filename
                if candidate.is_file():
                    return str(candidate)

        normalized_targets = {_normalize_avatar_filename(name) for name in candidate_names}
        for directory in candidate_dirs:
            if not directory.is_dir():
                continue
            for candidate in directory.glob("*.png"):
                if _normalize_avatar_filename(candidate.name) in normalized_targets:
                    return str(candidate)

    return avatar_path


def ensure_gpio_input(pin: int) -> None:
    gpio_node = Path(f"/sys/class/gpio/gpio{pin}")
    if not gpio_node.exists():
        try:
            Path("/sys/class/gpio/export").write_text(f"{pin}\n", encoding="utf-8")
        except OSError:
            return

    direction_file = gpio_node / "direction"
    if direction_file.exists():
        try:
            direction_file.write_text("in\n", encoding="utf-8")
        except OSError:
            return


def read_gpio_value(pin: int) -> Optional[int]:
    value_file = Path(f"/sys/class/gpio/gpio{pin}/value")
    try:
        value = value_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if value.startswith("1"):
        return 1
    if value.startswith("0"):
        return 0
    return None


@dataclass
class GpioAvatarSelector:
    enabled: bool
    gpio0: int
    gpio1: int
    avatar_dir: str
    fallback_avatar: str
    gpio_poll_interval: float
    mapping: Dict[int, str]
    last_poll_at: float = 0.0
    last_code: int = -1

    def select(self, now: float, current_path: str, current_avatar: Optional[np.ndarray]) -> Tuple[str, Optional[np.ndarray]]:
        if not self.enabled:
            return current_path, current_avatar

        if now - self.last_poll_at < max(0.03, self.gpio_poll_interval):
            return current_path, current_avatar

        self.last_poll_at = now
        bit0 = read_gpio_value(self.gpio0)
        bit1 = read_gpio_value(self.gpio1)
        if bit0 is None or bit1 is None:
            return current_path, current_avatar

        code = (bit1 << 1) | bit0
        if code == self.last_code:
            return current_path, current_avatar

        self.last_code = code
        avatar_name = self.mapping.get(code, "")
        selected_path = resolve_avatar_path(self.fallback_avatar, self.avatar_dir, avatar_name)
        selected_avatar = load_avatar(selected_path)
        if selected_avatar is None:
            selected_path = self.fallback_avatar
            selected_avatar = load_avatar(selected_path)

        if selected_avatar is not None and selected_path != current_path:
            print(f"gpio_avatar_switch code={code:02b} name={avatar_name or 'fallback'} path={selected_path}")
            sys.stdout.flush()
            return selected_path, selected_avatar

        return current_path, current_avatar


def load_cascade(filename: str) -> cv2.CascadeClassifier:
    cascade_dir = get_haarcascade_dir()
    cascade = cv2.CascadeClassifier(str(cascade_dir / filename))
    if cascade.empty():
        raise RuntimeError(f"无法加载模型: {filename}")
    return cascade


def load_cascade_optional(filename: str) -> Optional[cv2.CascadeClassifier]:
    cascade_dir = get_haarcascade_dir()
    cascade = cv2.CascadeClassifier(str(cascade_dir / filename))
    if cascade.empty():
        return None
    return cascade


def create_capture(device: str, spec: FrameSpec) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开输入摄像头: {device}")

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, spec.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, spec.height)
    capture.set(cv2.CAP_PROP_FPS, spec.fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


class FfmpegPipeWriter:
    def __init__(self, process: subprocess.Popen[bytes], device: str, spec: FrameSpec):
        self.process = process
        self.device = device
        self.spec = spec

    def _error_detail(self) -> str:
        if self.process.stderr is None:
            return ""
        try:
            data = self.process.stderr.read()
        except Exception:
            return ""
        if not data:
            return ""
        text = data.decode("utf-8", errors="ignore").strip()
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        return " | ".join(lines[-4:])

    def write(self, frame: np.ndarray) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            detail = self._error_detail()
            if detail:
                raise RuntimeError(f"ffmpeg 输出进程已退出: {self.device}; {detail}")
            raise RuntimeError(f"ffmpeg 输出进程已退出: {self.device}")
        frame_to_write = np.ascontiguousarray(frame)
        self.process.stdin.write(frame_to_write.tobytes())

    def release(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except Exception:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except Exception:
                self.process.kill()


def _pack_bgr_to_yuyv(frame: np.ndarray) -> bytes:
    height, width = frame.shape[:2]
    if width % 2 != 0:
        raise RuntimeError("YUYV 输出要求宽度为偶数")

    yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
    y_plane = yuv[:, :, 0].astype(np.uint8)
    u_plane = yuv[:, :, 1].astype(np.uint16)
    v_plane = yuv[:, :, 2].astype(np.uint16)

    left_y = y_plane[:, 0::2]
    right_y = y_plane[:, 1::2]
    avg_u = ((u_plane[:, 0::2] + u_plane[:, 1::2]) // 2).astype(np.uint8)
    avg_v = ((v_plane[:, 0::2] + v_plane[:, 1::2]) // 2).astype(np.uint8)

    packed = np.empty((height, width // 2, 4), dtype=np.uint8)
    packed[:, :, 0] = left_y
    packed[:, :, 1] = avg_u
    packed[:, :, 2] = right_y
    packed[:, :, 3] = avg_v
    return packed.tobytes()


class RawDeviceWriter:
    def __init__(self, device: str, spec: FrameSpec):
        self.device = device
        self.spec = spec
        self.handle = open(device, "wb", buffering=0)

    def write(self, frame: np.ndarray) -> None:
        frame_to_write = frame
        if frame_to_write.shape[1] != self.spec.width or frame_to_write.shape[0] != self.spec.height:
            frame_to_write = cv2.resize(frame_to_write, (self.spec.width, self.spec.height), interpolation=cv2.INTER_AREA)
        self.handle.write(_pack_bgr_to_yuyv(np.ascontiguousarray(frame_to_write)))

    def release(self) -> None:
        try:
            self.handle.close()
        except Exception:
            pass


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http_server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class NetworkMjpegWriter:
    def __init__(self, host: str, port: int, path: str, jpeg_quality: int):
        self.host = host
        self.port = int(port)
        self.path = path if path.startswith("/") else f"/{path}"
        self.jpeg_quality = max(30, min(100, int(jpeg_quality)))

        self._lock = threading.Condition()
        self._jpeg_frame: Optional[bytes] = None
        self._generation = 0
        self._stopped = False

        writer = self

        class MjpegHandler(http_server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path not in (writer.path, "/"):
                    self.send_response(404)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Connection", "close")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()

                last_generation = -1
                while True:
                    with writer._lock:
                        while not writer._stopped and writer._generation == last_generation:
                            writer._lock.wait(timeout=2.0)

                        if writer._stopped:
                            return

                        payload = writer._jpeg_frame
                        last_generation = writer._generation

                    if payload is None:
                        continue

                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(payload)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        return

            def log_message(self, format: str, *args):  # noqa: A003
                return

        self._server = _ThreadedHTTPServer((self.host, self.port), MjpegHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def write(self, frame: np.ndarray) -> None:
        ok, encoded = cv2.imencode(
            ".jpg",
            np.ascontiguousarray(frame),
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            raise RuntimeError("网络输出 JPEG 编码失败")

        with self._lock:
            self._jpeg_frame = encoded.tobytes()
            self._generation += 1
            self._lock.notify_all()

    def release(self) -> None:
        with self._lock:
            self._stopped = True
            self._lock.notify_all()

        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass


def create_network_writer(args, spec: FrameSpec) -> Tuple[object, FrameSpec, str]:
    writer = NetworkMjpegWriter(
        host=args.network_host,
        port=args.network_port,
        path=args.network_path,
        jpeg_quality=args.network_jpeg_quality,
    )
    display_host = args.network_host if args.network_host not in {"0.0.0.0", "::"} else "<board-ip>"
    stream_url = f"http://{display_host}:{args.network_port}{writer.path}"
    return writer, FrameSpec(width=spec.width, height=spec.height, fps=spec.fps), stream_url


def create_output_writer(args, spec: FrameSpec) -> Tuple[object, FrameSpec, str]:
    if args.output_mode == "network":
        return create_network_writer(args, spec)

    writer, output_spec = create_writer(args.output, spec)
    return writer, output_spec, args.output


def _try_open_cv_writer(candidate: str, codec: str, fps: int, width: int, height: int):
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(candidate, cv2.CAP_V4L2, fourcc, fps, (width, height))
    if writer.isOpened():
        return writer
    writer.release()
    return None


def _configure_v4l2_output(candidate: str, fps: int, width: int, height: int, codec: str) -> bool:
    pixfmt = "MJPG" if codec.upper() == "MJPG" else "YUYV"
    cmd_set_fmt = [
        "v4l2-ctl",
        "-d",
        candidate,
        f"--set-fmt-video=width={width},height={height},pixelformat={pixfmt}",
    ]
    cmd_set_fps = ["v4l2-ctl", "-d", candidate, f"--set-parm={fps}"]

    try:
        result_fmt = subprocess.run(cmd_set_fmt, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        return True

    if result_fmt.returncode != 0:
        return True

    subprocess.run(cmd_set_fps, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return True


def _try_open_ffmpeg_writer(candidate: str, fps: int, width: int, height: int, codec: str):
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
    ]

    if codec.upper() == "MJPG":
        command.extend(["-vcodec", "mjpeg", "-q:v", "5"])
    else:
        command.extend(["-vcodec", "rawvideo", "-pix_fmt", "yuyv422"])

    command.extend(["-f", "v4l2", candidate])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return None

    time.sleep(0.05)
    if process.poll() is not None:
        try:
            process.kill()
        except Exception:
            pass
        return None

    if process.stdin is None:
        try:
            process.kill()
        except Exception:
            pass
        return None

    # Write one probe frame so unsupported format/size combinations fail immediately.
    probe = bytes(width * height * 3)
    try:
        process.stdin.write(probe)
        process.stdin.flush()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        return None

    time.sleep(0.05)
    if process.poll() is not None:
        try:
            process.kill()
        except Exception:
            pass
        return None

    return FfmpegPipeWriter(process, candidate, FrameSpec(width=width, height=height, fps=fps))


def _try_open_raw_writer(candidate: str, fps: int, width: int, height: int, codec: str):
    if codec.upper() != "YUYV":
        return None
    if width != 320 or height != 240:
        return None
    if not re.fullmatch(r"/dev/video(\d+)", candidate):
        return None
    try:
        return RawDeviceWriter(candidate, FrameSpec(width=width, height=height, fps=fps))
    except OSError:
        return None


def _is_likely_uvc_output_node(video_index: int) -> bool:
    name_file = Path(f"/sys/class/video4linux/video{video_index}/name")
    try:
        node_name = name_file.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False

    if "dwc3-gadget" in node_name:
        return True
    if "uvc" in node_name and "gadget" in node_name:
        return True
    if node_name in {"g_uvc", "uvc-gadget", "uvc gadget"}:
        return True
    return False


def _list_auto_output_candidates() -> list[str]:
    output_nodes = []

    for path in Path("/dev").glob("video*"):
        name = path.name
        match = re.fullmatch(r"video(\d+)", name)
        if not match:
            continue

        index = int(match.group(1))
        candidate = str(path)
        if _is_likely_uvc_output_node(index):
            output_nodes.append((index, candidate))

    output_nodes.sort(key=lambda item: item[0])
    return [path for _, path in output_nodes]


def create_writer(device: str, spec: FrameSpec) -> Tuple[object, FrameSpec]:
    preferred = (device or "").strip()
    preferred_is_auto = preferred.lower() == "auto"
    codec_candidates = ("MJPG", "YUYV")
    size_candidates = [
        (spec.width, spec.height),
        (1280, 720),
        (640, 480),
        (320, 240),
    ]
    fps_candidates = [spec.fps, 15, 30, 25]

    unique_sizes = []
    seen_sizes = set()
    for width, height in size_candidates:
        key = (int(width), int(height))
        if key in seen_sizes:
            continue
        seen_sizes.add(key)
        unique_sizes.append(key)

    unique_fps = []
    seen_fps = set()
    for fps in fps_candidates:
        value = int(fps)
        if value <= 0 or value in seen_fps:
            continue
        seen_fps.add(value)
        unique_fps.append(value)

    def candidate_sizes(candidate_path: str) -> list[Tuple[int, int]]:
        match = re.fullmatch(r"/dev/video(\d+)", candidate_path)
        if match and _is_likely_uvc_output_node(int(match.group(1))):
            gadget_sizes = [(320, 240)]
            merged = gadget_sizes + unique_sizes
            dedup = []
            seen_local = set()
            for item in merged:
                if item in seen_local:
                    continue
                seen_local.add(item)
                dedup.append(item)
            return dedup
        return unique_sizes

    def candidate_fps(candidate_path: str) -> list[int]:
        match = re.fullmatch(r"/dev/video(\d+)", candidate_path)
        if match and _is_likely_uvc_output_node(int(match.group(1))):
            preferred = [15, 30]
            merged = preferred + unique_fps
            dedup = []
            seen_local = set()
            for item in merged:
                if item in seen_local:
                    continue
                seen_local.add(item)
                dedup.append(item)
            return dedup
        return unique_fps

    def candidate_codecs(candidate_path: str) -> list[str]:
        match = re.fullmatch(r"/dev/video(\d+)", candidate_path)
        if match and _is_likely_uvc_output_node(int(match.group(1))):
            return ["YUYV", "MJPG"]
        return list(codec_candidates)

    last_error = None
    for _ in range(60):
        candidates = []
        if preferred and not preferred_is_auto:
            candidates.append(preferred)

        candidates.extend(_list_auto_output_candidates())

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            unique_candidates.append(candidate)

        for candidate in unique_candidates:
            sizes_for_candidate = candidate_sizes(candidate)
            fps_for_candidate = candidate_fps(candidate)
            codecs_for_candidate = candidate_codecs(candidate)
            for codec in codecs_for_candidate:
                for fps in fps_for_candidate:
                    for width, height in sizes_for_candidate:
                        _configure_v4l2_output(candidate, fps, width, height, codec)

                        raw_writer = _try_open_raw_writer(candidate, fps, width, height, codec)
                        if raw_writer is not None:
                            if preferred_is_auto or candidate != preferred or width != spec.width or height != spec.height or fps != spec.fps:
                                print(f"output_auto_selected={candidate} method=raw codec={codec} size={width}x{height} fps={fps}")
                                sys.stdout.flush()
                            return raw_writer, FrameSpec(width=width, height=height, fps=fps)

                        writer = _try_open_cv_writer(candidate, codec, fps, width, height)
                        if writer is not None:
                            if preferred_is_auto or candidate != preferred or width != spec.width or height != spec.height or fps != spec.fps:
                                print(f"output_auto_selected={candidate} method=cv2 codec={codec} size={width}x{height} fps={fps}")
                                sys.stdout.flush()
                            return writer, FrameSpec(width=width, height=height, fps=fps)
                        last_error = f"无法打开输出设备: {candidate}"

                        ffmpeg_writer = _try_open_ffmpeg_writer(candidate, fps, width, height, codec)
                        if ffmpeg_writer is not None:
                            if preferred_is_auto or candidate != preferred or width != spec.width or height != spec.height or fps != spec.fps:
                                print(f"output_auto_selected={candidate} method=ffmpeg codec={codec} size={width}x{height} fps={fps}")
                                sys.stdout.flush()
                            return ffmpeg_writer, FrameSpec(width=width, height=height, fps=fps)

        time.sleep(1.0)

    if preferred and not preferred_is_auto:
        raise RuntimeError(last_error or f"无法打开输出设备: {preferred}")
    raise RuntimeError(last_error or "无法自动找到可写输出设备")


def overlay_rgba(background: np.ndarray, foreground: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    if w <= 0 or h <= 0:
        return background

    foreground = cv2.resize(foreground, (w, h), interpolation=cv2.INTER_AREA)
    bg_h, bg_w = background.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(bg_w, x + w)
    y2 = min(bg_h, y + h)

    if x1 >= x2 or y1 >= y2:
        return background

    fg_x1 = x1 - x
    fg_y1 = y1 - y
    fg_x2 = fg_x1 + (x2 - x1)
    fg_y2 = fg_y1 + (y2 - y1)

    fg_region = foreground[fg_y1:fg_y2, fg_x1:fg_x2]
    alpha = fg_region[:, :, 3:4].astype(np.float32) / 255.0
    rgb = fg_region[:, :, :3].astype(np.float32)

    bg_region = background[y1:y2, x1:x2].astype(np.float32)
    bg_rgb = bg_region[:, :, :3]
    blended = rgb * alpha + bg_rgb * (1.0 - alpha)
    background[y1:y2, x1:x2, :3] = blended.astype(np.uint8)

    if background.shape[2] == 4:
        bg_alpha = bg_region[:, :, 3:4]
        out_alpha = np.maximum(bg_alpha, fg_region[:, :, 3:4].astype(np.float32))
        background[y1:y2, x1:x2, 3:4] = out_alpha.astype(np.uint8)
    return background


def smooth_value(previous: float, current: float, factor: float = 0.82) -> float:
    return previous * factor + current * (1.0 - factor)


def smooth_face(previous: Optional[Tuple[float, float, float, float]], current: Tuple[int, int, int, int]) -> Tuple[float, float, float, float]:
    if previous is None:
        return tuple(float(value) for value in current)

    return (
        smooth_value(previous[0], float(current[0])),
        smooth_value(previous[1], float(current[1])),
        smooth_value(previous[2], float(current[2])),
        smooth_value(previous[3], float(current[3])),
    )


def rotate_rgba(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    if abs(angle_degrees) < 0.1:
        return image

    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)

    cos_value = abs(matrix[0, 0])
    sin_value = abs(matrix[0, 1])
    new_width = int((height * sin_value) + (width * cos_value))
    new_height = int((height * cos_value) + (width * sin_value))

    matrix[0, 2] += (new_width / 2) - center[0]
    matrix[1, 2] += (new_height / 2) - center[1]

    return cv2.warpAffine(
        image,
        matrix,
        (new_width, new_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def create_body_canvas(width: int, height: int, face_height: int, phase: float = 0.0) -> np.ndarray:
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    center_x = width // 2
    breathe = 1.0 + 0.018 * np.sin(phase * 2.0)

    body_top = int(face_height * 0.88)
    body_bottom = height - 8
    body_width = int(face_height * 1.15 * breathe)
    shoulder_width = int(body_width * 1.35)

    cv2.ellipse(canvas, (center_x, body_top + int(face_height * 0.48)), (shoulder_width // 2, int(face_height * 0.95 * breathe)), 0, 180, 360, (36, 48, 68, 255), -1)
    cv2.ellipse(canvas, (center_x, body_top + int(face_height * 0.35)), (body_width // 2, int(face_height * 0.72 * breathe)), 0, 180, 360, (58, 73, 104, 255), -1)
    cv2.rectangle(canvas, (center_x - body_width // 3, body_top), (center_x + body_width // 3, body_bottom), (66, 84, 118, 255), -1)

    collar_top = body_top + int(face_height * 0.18)
    collar_width = int(body_width * 0.72)
    pts = np.array([
        [center_x - collar_width // 2, collar_top],
        [center_x, collar_top + int(face_height * 0.18)],
        [center_x + collar_width // 2, collar_top],
        [center_x, collar_top - int(face_height * 0.05)],
    ], dtype=np.int32)
    cv2.fillConvexPoly(canvas, pts, (90, 108, 144, 255))
    return canvas


def add_soft_shadow(canvas: np.ndarray, x: int, y: int, w: int, h: int, phase: float = 0.0) -> np.ndarray:
    shadow = np.zeros_like(canvas)
    shadow_width = int(w * (0.42 + 0.02 * np.sin(phase * 1.3)))
    cv2.ellipse(shadow, (x + w // 2, y + h + h // 10), (shadow_width, int(h * 0.10)), 0, 0, 360, (0, 0, 0, 120), -1)
    blurred = cv2.GaussianBlur(shadow, (0, 0), 16)
    alpha = blurred[:, :, 3:4].astype(np.float32) / 255.0
    canvas[:, :, :3] = (canvas[:, :, :3].astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
    canvas[:, :, 3] = np.maximum(canvas[:, :, 3], blurred[:, :, 3])
    return canvas


def create_stage_background(width: int, height: int, phase: float = 0.0) -> np.ndarray:
    background = np.zeros((height, width, 4), dtype=np.uint8)

    top = np.array([28, 10, 48], dtype=np.float32)
    bottom = np.array([6, 4, 18], dtype=np.float32)
    for row in range(height):
        ratio = row / max(1, height - 1)
        color = (top * (1.0 - ratio) + bottom * ratio).astype(np.uint8)
        background[row, :, :3] = color
        background[row, :, 3] = 255

    overlay = np.zeros_like(background)
    cv2.ellipse(overlay, (int(width * 0.16), int(height * 0.18)), (int(width * 0.24), int(height * 0.18)), -18, 0, 360, (255, 74, 178, 120), -1)
    cv2.ellipse(overlay, (int(width * 0.84), int(height * 0.14)), (int(width * 0.20), int(height * 0.15)), 12, 0, 360, (88, 178, 255, 110), -1)
    cv2.ellipse(overlay, (int(width * 0.50), int(height * 0.82)), (int(width * 0.34), int(height * 0.12)), 0, 0, 360, (0, 0, 0, 105), -1)

    screen_x1 = int(width * 0.22)
    screen_y1 = int(height * 0.09)
    screen_x2 = int(width * 0.78)
    screen_y2 = int(height * 0.54)
    cv2.rectangle(overlay, (screen_x1, screen_y1), (screen_x2, screen_y2), (34, 12, 58, 150), -1)
    cv2.rectangle(overlay, (screen_x1, screen_y1), (screen_x2, screen_y2), (255, 74, 178, 75), 2)
    cv2.line(overlay, (screen_x1 + 20, screen_y2 - 28), (screen_x2 - 20, screen_y2 - 28), (88, 178, 255, 92), 3)
    cv2.line(overlay, (screen_x1 + 20, screen_y1 + 28), (screen_x2 - 20, screen_y1 + 28), (255, 74, 178, 60), 1)

    light_offset = int(12 * np.sin(phase * 1.3))
    cv2.ellipse(overlay, (int(width * 0.10), int(height * 0.24 + light_offset)), (int(width * 0.12), int(height * 0.07)), -14, 0, 360, (255, 74, 178, 55), -1)
    cv2.ellipse(overlay, (int(width * 0.90), int(height * 0.26 - light_offset)), (int(width * 0.12), int(height * 0.07)), 16, 0, 360, (88, 178, 255, 48), -1)

    blurred = cv2.GaussianBlur(overlay, (0, 0), 22)
    alpha = blurred[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + blurred[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)

    pulse = 0.5 + 0.5 * np.sin(phase * 1.8)
    ring = np.zeros_like(background)
    cv2.circle(ring, (int(width * (0.50 + 0.03 * np.sin(phase * 0.7))), int(height * 0.58)), int(min(width, height) * (0.18 + 0.01 * pulse)), (255, 74, 178, 42), 2)
    cv2.circle(ring, (int(width * 0.50), int(height * 0.58)), int(min(width, height) * 0.27), (88, 178, 255, 12), 1)
    ring = cv2.GaussianBlur(ring, (0, 0), 18)
    alpha = ring[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + ring[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)

    strip = np.zeros_like(background)
    strip_y = int(height * 0.89)
    cv2.rectangle(strip, (0, strip_y), (width, height), (6, 12, 18, 255), -1)
    cv2.line(strip, (0, strip_y), (width, strip_y), (255, 74, 178, 80), 2)
    cv2.line(strip, (0, strip_y + 6), (width, strip_y + 6), (88, 178, 255, 40), 1)
    strip = cv2.GaussianBlur(strip, (0, 0), 6)
    alpha = strip[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + strip[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_vignette(background: np.ndarray) -> np.ndarray:
    height, width = background.shape[:2]
    y, x = np.ogrid[:height, :width]
    center_y = height / 2.0
    center_x = width / 2.0
    distance = ((x - center_x) / max(1.0, width * 0.52)) ** 2 + ((y - center_y) / max(1.0, height * 0.58)) ** 2
    mask = np.clip(1.0 - 0.45 * distance, 0.58, 1.0).astype(np.float32)
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * mask[..., None]).astype(np.uint8)
    return background


def add_grid_overlay(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    column_step = max(80, width // 10)
    row_step = max(70, height // 9)
    for column in range(0, width, column_step):
        color = (58, 96, 144, 18 if column % (column_step * 2) else 26)
        cv2.line(overlay, (column, int(height * 0.08)), (column, int(height * 0.80)), color, 1)
    for row in range(int(height * 0.10), int(height * 0.82), row_step):
        alpha = 14 if row % (row_step * 2) else 22
        cv2.line(overlay, (int(width * 0.10), row), (int(width * 0.90), row), (58, 96, 144, alpha), 1)

    drift = int(10 * np.sin(phase * 0.8))
    cv2.line(overlay, (int(width * 0.12), int(height * 0.22) + drift), (int(width * 0.88), int(height * 0.22) + drift), (95, 235, 186, 24), 2)
    cv2.line(overlay, (int(width * 0.12), int(height * 0.26) - drift), (int(width * 0.88), int(height * 0.26) - drift), (88, 178, 255, 22), 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_side_panels(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    left_x1 = int(width * 0.04)
    left_x2 = int(width * 0.17)
    right_x1 = int(width * 0.83)
    right_x2 = int(width * 0.96)
    top_y1 = int(height * 0.14)
    top_y2 = int(height * 0.76)

    cv2.rectangle(overlay, (left_x1, top_y1), (left_x2, top_y2), (24, 40, 64, 100), -1)
    cv2.rectangle(overlay, (right_x1, top_y1), (right_x2, top_y2), (24, 40, 64, 100), -1)
    cv2.rectangle(overlay, (left_x1, top_y1), (left_x2, top_y2), (88, 178, 255, 28), 2)
    cv2.rectangle(overlay, (right_x1, top_y1), (right_x2, top_y2), (95, 235, 186, 26), 2)

    pulse = 0.5 + 0.5 * np.sin(phase * 1.4)
    cv2.ellipse(overlay, (int(width * 0.105), int(height * 0.44)), (int(width * 0.022), int(height * (0.08 + 0.01 * pulse))), 0, 0, 360, (88, 178, 255, 120), -1)
    cv2.ellipse(overlay, (int(width * 0.895), int(height * 0.44)), (int(width * 0.022), int(height * (0.08 + 0.01 * pulse))), 0, 0, 360, (95, 235, 186, 110), -1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 14)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_frame_accents(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    margin_x = int(width * 0.055)
    margin_y = int(height * 0.055)
    line_color = (255, 74, 178, 90)
    line_color_alt = (88, 178, 255, 82)
    pulse = 0.5 + 0.5 * np.sin(phase * 1.2)

    cv2.rectangle(overlay, (margin_x, margin_y), (width - margin_x, height - margin_y), (255, 255, 255, 26), 1)
    cv2.line(overlay, (margin_x, margin_y + 12), (margin_x + int(width * 0.20), margin_y + 12), line_color, 4)
    cv2.line(overlay, (width - margin_x - int(width * 0.20), margin_y + 12), (width - margin_x, margin_y + 12), line_color_alt, 4)
    cv2.line(overlay, (margin_x, height - margin_y - 12), (margin_x + int(width * 0.14), height - margin_y - 12), line_color_alt, 4)
    cv2.line(overlay, (width - margin_x - int(width * 0.14), height - margin_y - 12), (width - margin_x, height - margin_y - 12), line_color, 4)

    corner_len = int(min(width, height) * (0.06 + 0.01 * pulse))
    corners = [
        ((margin_x, margin_y), (margin_x + corner_len, margin_y)),
        ((margin_x, margin_y), (margin_x, margin_y + corner_len)),
        ((width - margin_x, margin_y), (width - margin_x - corner_len, margin_y)),
        ((width - margin_x, margin_y), (width - margin_x, margin_y + corner_len)),
        ((margin_x, height - margin_y), (margin_x + corner_len, height - margin_y)),
        ((margin_x, height - margin_y), (margin_x, height - margin_y - corner_len)),
        ((width - margin_x, height - margin_y), (width - margin_x - corner_len, height - margin_y)),
        ((width - margin_x, height - margin_y), (width - margin_x, height - margin_y - corner_len)),
    ]
    for start, end in corners:
        cv2.line(overlay, start, end, (255, 255, 255, 60), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 2)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_scanlines(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    offset = int((phase * 22.0) % 6)

    for row in range(offset, height, 6):
        alpha = 8 if (row // 6) % 2 == 0 else 5
        cv2.line(overlay, (0, row), (width, row), (255, 255, 255, alpha), 1)

    scan_x = int((width * 0.5) + np.sin(phase * 0.9) * width * 0.08)
    cv2.line(overlay, (scan_x, 0), (scan_x, height), (95, 235, 186, 12), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 0.8)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_neon_beams(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    beam_specs = [
        (0.08, 0.22, 0.42, 0.10, 255, 74, 178, 54),
        (0.90, 0.16, 0.58, 0.18, 88, 178, 255, 44),
        (0.14, 0.72, 0.40, 0.58, 255, 74, 178, 34),
    ]

    sway = int(24 * np.sin(phase * 0.6))
    for x1r, y1r, x2r, y2r, b, g, r, a in beam_specs:
        start = (int(width * x1r) + sway, int(height * y1r))
        end = (int(width * x2r) - sway, int(height * y2r))
        cv2.line(overlay, start, end, (b, g, r, a), 14)
        cv2.line(overlay, start, end, (255, 255, 255, max(10, a // 4)), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 16)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_particle_field(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    for index in range(30):
        t = phase * 0.9 + index * 0.29
        px = int((width * 0.08) + (width * 0.84) * ((np.sin(t) * 0.5) + 0.5))
        py = int((height * 0.10) + (height * 0.72) * ((np.cos(t * 1.17) * 0.5) + 0.5))
        radius = 1 + (index % 4)
        color = (255, 74, 178, 85 if index % 2 == 0 else 65)
        if index % 3 == 1:
            color = (88, 178, 255, color[3])
        cv2.circle(overlay, (px, py), radius, color, -1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 2)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_center_halo(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    pulse = 0.5 + 0.5 * np.sin(phase * 2.2)

    center = (width // 2, int(height * 0.60))
    outer_radius = int(min(width, height) * (0.22 + 0.02 * pulse))
    inner_radius = int(min(width, height) * 0.10)

    cv2.circle(overlay, center, outer_radius, (255, 74, 178, 24), 2)
    cv2.circle(overlay, center, inner_radius, (88, 178, 255, 20), 2)
    cv2.ellipse(overlay, center, (int(outer_radius * 0.92), int(outer_radius * 0.46)), 0, 0, 360, (95, 235, 186, 14), 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 18)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_hud_arcs(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    center = (width // 2, int(height * 0.58))
    pulse = 0.5 + 0.5 * np.sin(phase * 1.9)

    for index, radius_scale in enumerate((0.16, 0.20, 0.24)):
        radius = int(min(width, height) * (radius_scale + 0.01 * pulse))
        start_angle = int((phase * 36.0 + index * 28) % 360)
        end_angle = start_angle + 130
        color = (255, 74, 178, 44 if index == 0 else 34 if index == 1 else 28)
        cv2.ellipse(overlay, center, (radius, int(radius * 0.48)), 0, start_angle, end_angle, color, 2)

    cv2.ellipse(overlay, center, (int(min(width, height) * 0.30), int(min(width, height) * 0.14)), 0, 215, 325, (88, 178, 255, 26), 2)
    cv2.ellipse(overlay, center, (int(min(width, height) * 0.34), int(min(width, height) * 0.18)), 0, 25, 95, (95, 235, 186, 22), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_corner_ticks(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    tick = int(min(width, height) * 0.05)
    pulse = 0.5 + 0.5 * np.sin(phase * 2.2)
    alpha_a = int(70 + 40 * pulse)
    alpha_b = int(60 + 30 * (1.0 - pulse))

    marks = [
        ((int(width * 0.12), int(height * 0.12)), 1),
        ((int(width * 0.88), int(height * 0.12)), -1),
        ((int(width * 0.12), int(height * 0.88)), 1),
        ((int(width * 0.88), int(height * 0.88)), -1),
    ]
    for (x, y), direction in marks:
        cv2.line(overlay, (x, y), (x + direction * tick, y), (255, 74, 178, alpha_a), 2)
        cv2.line(overlay, (x, y), (x, y + direction * tick), (88, 178, 255, alpha_b), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_bloom_glow(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    blurred = cv2.GaussianBlur(background[:, :, :3], (0, 0), 8)
    pulse = 0.5 + 0.5 * np.sin(phase * 0.8)
    strength = 0.10 + 0.08 * pulse
    background[:, :, :3] = np.clip(
        background[:, :, :3].astype(np.float32) * (1.0 - strength) + blurred.astype(np.float32) * strength,
        0,
        255,
    ).astype(np.uint8)
    return background


def add_glitch_bands(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    band_count = 3
    for band_index in range(band_count):
        if (int(phase * 6) + band_index) % 4 != 0:
            continue
        band_height = int(height * (0.012 + band_index * 0.003))
        y = int((height * 0.18) + ((band_index * 0.27 + phase * 0.15) % 0.52) * height * 0.62)
        x_offset = int(np.sin(phase * 2.3 + band_index) * width * 0.04)
        y2 = min(height, y + band_height)
        x1 = max(0, x_offset)
        x2 = min(width, width + x_offset)
        if x1 < x2:
            cv2.rectangle(overlay, (x1, y), (x2, y2), (255, 74, 178, 40 if band_index % 2 == 0 else 28), -1)
            cv2.rectangle(overlay, (x1, y), (x2, y2), (88, 178, 255, 14), 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_digital_rain(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    column_step = max(42, width // 18)

    for column_index, column in enumerate(range(0, width, column_step)):
        offset = int((phase * 24.0 + column_index * 7) % height)
        for drop_index in range(6):
            y = (offset + drop_index * int(height * 0.09)) % height
            length = int(height * (0.04 + 0.008 * (drop_index % 3)))
            alpha = 28 - drop_index * 3
            color = (95, 235, 186, alpha) if column_index % 2 == 0 else (255, 74, 178, alpha)
            cv2.line(overlay, (column, y), (column, min(height - 1, y + length)), color, 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_signal_noise(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(int(phase * 1000) % 2_147_483_647)
    noise = rng.integers(0, 18, size=background[:, :, :3].shape, dtype=np.uint8)
    alpha = 0.02 + 0.01 * (0.5 + 0.5 * np.sin(phase * 1.1))
    background[:, :, :3] = np.clip(
        background[:, :, :3].astype(np.float32) * (1.0 - alpha) + (background[:, :, :3].astype(np.float32) + noise.astype(np.float32)) * alpha,
        0,
        255,
    ).astype(np.uint8)
    return background


def add_bottom_band(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    band_y = int(height * 0.93)
    pulse = 0.5 + 0.5 * np.sin(phase * 1.9)

    cv2.rectangle(overlay, (0, band_y), (width, height), (12, 6, 22, 160), -1)
    cv2.line(overlay, (0, band_y), (width, band_y), (255, 74, 178, int(70 + 30 * pulse)), 2)
    cv2.line(overlay, (0, band_y + 6), (width, band_y + 6), (88, 178, 255, int(40 + 20 * (1.0 - pulse))), 1)
    cv2.line(overlay, (0, band_y + 12), (width, band_y + 12), (95, 235, 186, 24), 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 4)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_edge_shimmer(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    shimmer = 0.5 + 0.5 * np.sin(phase * 2.6)
    margin = int(min(width, height) * 0.04)
    inset = int(min(width, height) * (0.015 + 0.004 * shimmer))

    cv2.rectangle(overlay, (margin, margin), (width - margin, height - margin), (255, 74, 178, 24), 1)
    cv2.rectangle(overlay, (margin + inset, margin + inset), (width - margin - inset, height - margin - inset), (88, 178, 255, 18), 1)

    for idx in range(6):
        x = int((width * 0.15) + idx * width * 0.14 + np.sin(phase * 2.1 + idx) * width * 0.01)
        y = int(height * (0.10 + 0.01 * idx))
        cv2.line(overlay, (x, y), (x + int(width * 0.05), y), (95, 235, 186, 22), 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 1)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_signal_trail(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]
    trail_y = int(height * 0.60)

    for index in range(7):
        x1 = int(width * (0.12 + index * 0.12) + np.sin(phase * 1.8 + index) * width * 0.015)
        y1 = trail_y + int(np.sin(phase * 2.4 + index) * height * 0.015)
        x2 = x1 + int(width * 0.06)
        y2 = y1 + int(height * 0.01)
        color = (255, 74, 178, 28 if index % 2 == 0 else 20)
        if index % 3 == 1:
            color = (88, 178, 255, color[3])
        cv2.line(overlay, (x1, y1), (x2, y2), color, 2)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 6)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_scan_sweep(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    sweep_width = max(12, int(width * 0.08))
    travel = 0.5 + 0.5 * np.sin(phase * 0.85)
    center_x = int(width * (0.10 + 0.80 * travel))
    center_y = int(height * (0.16 + 0.10 * np.sin(phase * 1.2)))

    cv2.line(
        overlay,
        (center_x - sweep_width, 0),
        (center_x + sweep_width, height),
        (255, 255, 255, 18),
        8,
    )
    cv2.line(
        overlay,
        (center_x - sweep_width // 2, 0),
        (center_x + sweep_width // 2, height),
        (88, 178, 255, 42),
        3,
    )
    cv2.circle(overlay, (center_x, center_y), max(10, int(width * 0.015)), (95, 235, 186, 34), -1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 7)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_plasma_fog(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    for index in range(5):
        center_x = int(width * (0.18 + index * 0.18 + 0.03 * np.sin(phase * 0.8 + index)))
        center_y = int(height * (0.22 + 0.12 * np.cos(phase * 0.6 + index * 0.9)))
        radius_x = int(width * (0.11 + 0.01 * np.sin(phase * 1.5 + index)))
        radius_y = int(height * (0.08 + 0.008 * np.cos(phase * 1.3 + index)))
        color = (255, 74, 178, 24 if index % 2 == 0 else 18)
        if index % 2 == 1:
            color = (88, 178, 255, color[3])
        cv2.ellipse(overlay, (center_x, center_y), (radius_x, radius_y), 0, 0, 360, color, -1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 24)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_vertical_pulses(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    for column_index in range(4):
        x = int(width * (0.18 + column_index * 0.22) + np.sin(phase * 1.7 + column_index) * width * 0.02)
        bar_height = int(height * (0.18 + 0.03 * np.sin(phase * 1.5 + column_index)))
        y1 = int(height * 0.22 + (column_index % 2) * height * 0.08)
        y2 = min(height, y1 + bar_height)
        color = (255, 74, 178, 34 if column_index % 2 == 0 else 24)
        if column_index % 3 == 1:
            color = (88, 178, 255, color[3])
        cv2.rectangle(overlay, (x - 4, y1), (x + 4, y2), color, -1)
        cv2.line(overlay, (x - 7, y1), (x + 7, y1), (255, 255, 255, 18), 1)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 4)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def add_chromatic_aberration(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    shift = int(1 + (np.sin(phase * 1.1) + 1.0) * 2.0)
    b = np.roll(background[:, :, 0], shift, axis=1)
    g = background[:, :, 1]
    r = np.roll(background[:, :, 2], -shift, axis=0)
    background[:, :, 0] = b
    background[:, :, 1] = g
    background[:, :, 2] = r
    return background


def apply_cyber_grade(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    b, g, r = cv2.split(background[:, :, :3])
    contrast = 1.10 + 0.05 * np.sin(phase * 0.9)
    b = np.clip(b.astype(np.float32) * 1.12 * contrast, 0, 255).astype(np.uint8)
    g = np.clip(g.astype(np.float32) * 0.92 * contrast, 0, 255).astype(np.uint8)
    r = np.clip(r.astype(np.float32) * 1.08 * contrast, 0, 255).astype(np.uint8)

    merged = cv2.merge((b, g, r))
    merged = cv2.convertScaleAbs(merged, alpha=1.08, beta=4)
    background[:, :, :3] = merged
    return background


def add_lower_third(background: np.ndarray, phase: float = 0.0) -> np.ndarray:
    overlay = np.zeros_like(background)
    height, width = background.shape[:2]

    bar_height = int(height * 0.12)
    bar_y1 = height - bar_height - int(height * 0.035)
    bar_y2 = height - int(height * 0.035)
    bar_x1 = int(width * 0.14)
    bar_x2 = int(width * 0.86)

    pulse = 0.5 + 0.5 * np.sin(phase * 1.4)
    cv2.rectangle(overlay, (bar_x1, bar_y1), (bar_x2, bar_y2), (18, 8, 36, 180), -1)
    cv2.rectangle(overlay, (bar_x1, bar_y1), (bar_x2, bar_y2), (255, 74, 178, int(70 + 20 * pulse)), 2)
    cv2.line(overlay, (bar_x1 + 22, bar_y1 + 18), (bar_x2 - 22, bar_y1 + 18), (88, 178, 255, int(66 + 18 * pulse)), 2)

    accent_width = int(width * 0.10)
    accent_shift = int(8 * np.sin(phase * 1.2))
    cv2.rectangle(overlay, (bar_x1 - accent_width // 2 + accent_shift, bar_y1), (bar_x1 + accent_width // 2 + accent_shift, bar_y2), (255, 74, 178, 130), -1)
    cv2.rectangle(overlay, (bar_x2 - accent_width // 2 - accent_shift, bar_y1), (bar_x2 + accent_width // 2 - accent_shift, bar_y2), (88, 178, 255, 122), -1)

    text_color = (235, 245, 255)
    cv2.putText(overlay, "RK3588 Virtual Studio", (bar_x1 + 28, bar_y1 + int(bar_height * 0.50)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2, cv2.LINE_AA)
    cv2.putText(overlay, "USB Camera -> Avatar -> UVC Gadget", (bar_x1 + 28, bar_y1 + int(bar_height * 0.80)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (205, 190, 235), 1, cv2.LINE_AA)

    overlay = cv2.GaussianBlur(overlay, (0, 0), 6)
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    background[:, :, :3] = (background[:, :, :3].astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return background


def _squeeze_rgba_region(region: np.ndarray, vertical_scale: float) -> np.ndarray:
    rh, rw = region.shape[:2]
    if rh <= 1 or rw <= 1:
        return region

    clamped_scale = float(np.clip(vertical_scale, 0.12, 1.0))
    target_h = max(1, int(rh * clamped_scale))
    scaled = cv2.resize(region, (rw, target_h), interpolation=cv2.INTER_LINEAR)

    out = region.copy()
    y = max(0, (rh - target_h) // 2)
    out[y:y + target_h, :] = scaled
    return out


def animate_avatar_features(avatar_rgba: np.ndarray, blink_progress: float, mouth_open: float) -> np.ndarray:
    if avatar_rgba.ndim != 3 or avatar_rgba.shape[2] != 4:
        return avatar_rgba

    animated = avatar_rgba.copy()
    h, w = animated.shape[:2]
    blink = float(np.clip(blink_progress, 0.0, 1.0))
    mouth_raw = float(np.clip(mouth_open, 0.0, 1.0))
    # Stronger amplification for low-resolution camera input.
    mouth = float(np.clip((mouth_raw - 0.005) * 5.0, 0.0, 1.0))

    eye_box_w = max(12, int(w * 0.24))
    eye_box_h = max(10, int(h * 0.16))
    eye_y_center = int(h * 0.34)
    eye_scale = max(0.18, 1.0 - blink * 0.78)

    for cx_ratio in (0.34, 0.66):
        cx = int(w * cx_ratio)
        x1 = max(0, cx - eye_box_w // 2)
        x2 = min(w, cx + eye_box_w // 2)
        y1 = max(0, eye_y_center - eye_box_h // 2)
        y2 = min(h, eye_y_center + eye_box_h // 2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        eye_roi = animated[y1:y2, x1:x2]
        squeezed = _squeeze_rgba_region(eye_roi, eye_scale)

        animated[y1:y2, x1:x2] = squeezed

    mouth_box_w = max(22, int(w * 0.26))
    mouth_box_h = max(14, int(h * 0.14))
    mouth_cx = int(w * 0.50)
    # Portrait avatars often include torso; place mouth ROI in upper face area.
    mouth_cy = int(h * 0.46)
    mx1 = max(0, mouth_cx - mouth_box_w // 2)
    mx2 = min(w, mouth_cx + mouth_box_w // 2)
    my1 = max(0, mouth_cy - mouth_box_h // 2)
    my2 = min(h, mouth_cy + mouth_box_h // 2)

    if mouth > 0.005 and mx2 - mx1 >= 2 and my2 - my1 >= 2:
        mouth_roi = animated[my1:my2, mx1:mx2]
        roi_h, roi_w = mouth_roi.shape[:2]
        lip_line = max(1, int(roi_h * 0.58))
        upper = mouth_roi[:lip_line, :].copy()
        lower = mouth_roi[lip_line:, :].copy()

        shift = max(1, int(roi_h * 0.34 * mouth))
        modified = mouth_roi.copy()
        modified[:lip_line, :] = upper

        dst_start = min(roi_h - 1, lip_line + shift)
        avail = min(lower.shape[0], roi_h - dst_start)
        if avail > 0 and lower.size > 0:
            modified[dst_start:dst_start + avail, :] = lower[:avail, :]

        if dst_start > lip_line:
            seam = mouth_roi[max(0, lip_line - 1):lip_line, :]
            if seam.size > 0:
                seam_fill = np.repeat(seam, dst_start - lip_line, axis=0)
                modified[lip_line:dst_start, :] = seam_fill

        blend_mask = np.zeros((roi_h, roi_w, 1), dtype=np.float32)
        blend_mask[max(0, lip_line - 1):, :, 0] = float(np.clip(0.55 + mouth * 0.30, 0.55, 0.85))
        mixed = mouth_roi.astype(np.float32) * (1.0 - blend_mask) + modified.astype(np.float32) * blend_mask
        mixed_u8 = np.clip(mixed, 0, 255).astype(np.uint8)

        # Recover local sharpness only around the mouth band to avoid smearing the whole face.
        mouth_bgr = mixed_u8[max(0, lip_line - 2):, :, :3]
        blur = cv2.GaussianBlur(mouth_bgr, (0, 0), 1.0)
        sharp = cv2.addWeighted(mouth_bgr, 1.85, blur, -0.85, 0)
        mixed_u8[max(0, lip_line - 2):, :, :3] = np.clip(sharp, 0, 255).astype(np.uint8)

        animated[my1:my2, mx1:mx2] = mixed_u8

    return animated


def cartoonize(frame: np.ndarray) -> np.ndarray:
    color = cv2.bilateralFilter(frame, d=9, sigmaColor=75, sigmaSpace=75)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 7)
    edges = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY,
        9,
        2,
    )
    edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    return cv2.bitwise_and(color, edges)


def detect_face(
    frame: np.ndarray,
    cascade: cv2.CascadeClassifier,
    profile_cascade: Optional[cv2.CascadeClassifier] = None,
) -> Optional[Tuple[int, int, int, int]]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    candidates = []

    frontal_faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(72, 72))
    for face in frontal_faces:
        candidates.append(tuple(int(value) for value in face))

    if profile_cascade is not None:
        profile_left = profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(72, 72))
        for face in profile_left:
            candidates.append(tuple(int(value) for value in face))

        gray_flipped = cv2.flip(gray, 1)
        profile_right = profile_cascade.detectMultiScale(gray_flipped, scaleFactor=1.1, minNeighbors=4, minSize=(72, 72))
        frame_w = gray.shape[1]
        for face in profile_right:
            x, y, w, h = (int(value) for value in face)
            mirrored_x = frame_w - (x + w)
            candidates.append((mirrored_x, y, w, h))

    if len(candidates) == 0:
        return None
    candidates = sorted(candidates, key=lambda item: item[2] * item[3], reverse=True)
    return tuple(int(value) for value in candidates[0])


def detect_avatar_face_box(
    avatar: np.ndarray,
    face_cascade: cv2.CascadeClassifier,
    profile_cascade: Optional[cv2.CascadeClassifier] = None,
) -> Optional[Tuple[int, int, int, int]]:
    cache_key = id(avatar)
    if cache_key in AVATAR_FACE_BOX_CACHE:
        return AVATAR_FACE_BOX_CACHE[cache_key]

    if avatar.ndim != 3 or avatar.shape[2] < 3:
        AVATAR_FACE_BOX_CACHE[cache_key] = None
        return None

    bgr = avatar[:, :, :3]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    min_side = max(24, min(h, w) // 10)

    candidates = []
    frontal_faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(min_side, min_side))
    for face in frontal_faces:
        candidates.append(tuple(int(value) for value in face))

    if profile_cascade is not None:
        profile_left = profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(min_side, min_side))
        for face in profile_left:
            candidates.append(tuple(int(value) for value in face))

        gray_flipped = cv2.flip(gray, 1)
        profile_right = profile_cascade.detectMultiScale(gray_flipped, scaleFactor=1.1, minNeighbors=4, minSize=(min_side, min_side))
        for face in profile_right:
            x, y, fw, fh = (int(value) for value in face)
            mirrored_x = w - (x + fw)
            candidates.append((mirrored_x, y, fw, fh))

    if len(candidates) == 0:
        AVATAR_FACE_BOX_CACHE[cache_key] = None
        return None

    candidates = sorted(candidates, key=lambda item: item[2] * item[3], reverse=True)
    AVATAR_FACE_BOX_CACHE[cache_key] = tuple(int(value) for value in candidates[0])
    return AVATAR_FACE_BOX_CACHE[cache_key]


def crop_avatar_near_face(
    avatar: np.ndarray,
    face_box: Tuple[int, int, int, int],
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    ax, ay, aw, ah = face_box
    h, w = avatar.shape[:2]

    x1 = max(0, int(ax - 0.9 * aw))
    x2 = min(w, int(ax + 1.9 * aw))
    y1 = max(0, int(ay - 0.55 * ah))
    y2 = min(h, int(ay + 2.5 * ah))

    if x2 - x1 < 8 or y2 - y1 < 8:
        return avatar, face_box

    cropped = avatar[y1:y2, x1:x2].copy()
    return cropped, (ax - x1, ay - y1, aw, ah)


def choose_eye_pair(eyes: np.ndarray) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
    if len(eyes) < 2:
        return None

    eye_centers = []
    for eye in eyes:
        ex, ey, ew, eh = (int(value) for value in eye)
        eye_centers.append((ex + ew // 2, ey + eh // 2, ew * eh))

    eye_centers.sort(key=lambda item: item[2], reverse=True)
    selected = eye_centers[:4]
    selected.sort(key=lambda item: item[0])

    left_eye = (selected[0][0], selected[0][1])
    right_eye = (selected[1][0], selected[1][1])
    return left_eye, right_eye


def estimate_pose(
    frame: np.ndarray,
    face_cascade: cv2.CascadeClassifier,
    eye_cascade: cv2.CascadeClassifier,
    mouth_cascade: cv2.CascadeClassifier,
    profile_cascade: Optional[cv2.CascadeClassifier] = None,
) -> Optional[FaceState]:
    face = detect_face(frame, face_cascade, profile_cascade)
    if face is None:
        return None

    x, y, w, h = face
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi_gray = gray[y:y + h, x:x + w]

    eyes_region = roi_gray[: max(1, h // 2), :]
    eyes = eye_cascade.detectMultiScale(
        eyes_region,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(max(24, w // 10), max(18, h // 12)),
    )
    eye_pair = choose_eye_pair(eyes)

    eye_open = 0.0
    if len(eyes) > 0:
        eye_samples = []
        for eye in eyes[:3]:
            ex, ey, ew, eh = (int(value) for value in eye)
            eye_samples.append(min(1.0, max(0.12, eh / max(1.0, h * 0.18))))
        eye_open = float(sum(eye_samples) / len(eye_samples))

    angle = 0.0
    if eye_pair is not None:
        left_eye, right_eye = eye_pair
        dy = right_eye[1] - left_eye[1]
        dx = max(1, right_eye[0] - left_eye[0])
        angle = float(np.degrees(np.arctan2(dy, dx)))

    mouth_region = roi_gray[h // 2 :, :]
    mouths = mouth_cascade.detectMultiScale(
        mouth_region,
        scaleFactor=1.12,
        minNeighbors=8,
        minSize=(max(24, w // 8), max(16, h // 12)),
    )

    mouth_open = 0.0
    if len(mouths) > 0:
        mouths = sorted(mouths, key=lambda item: item[2] * item[3], reverse=True)
        mx, my, mw, mh = (int(value) for value in mouths[0])
        mouth_open = min(1.0, mh / max(1.0, h * 0.24))
    else:
        # Fallback heuristic when cascade misses the mouth in low resolution.
        y1 = int(h * 0.58)
        y2 = int(h * 0.92)
        x1 = int(w * 0.20)
        x2 = int(w * 0.80)
        lower_roi = roi_gray[y1:y2, x1:x2]
        if lower_roi.size > 0:
            blur = cv2.GaussianBlur(lower_roi, (5, 5), 0)
            _, dark = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            dark_ratio = float(np.mean(dark > 0))
            mouth_open = float(np.clip((dark_ratio - 0.14) * 2.4, 0.0, 0.45))

    return FaceState(face=face, angle=angle, mouth_open=mouth_open, eye_open=eye_open)


def update_blink_state(state: FaceState, now: float) -> float:
    global TRACKING_STATE

    if TRACKING_STATE.next_blink_at == 0.0:
        TRACKING_STATE.next_blink_at = now + random.uniform(2.5, 5.5)

    if now >= TRACKING_STATE.next_blink_at:
        TRACKING_STATE.blink_progress = 1.0
        TRACKING_STATE.next_blink_at = now + random.uniform(2.5, 5.5)

    if TRACKING_STATE.blink_progress > 0.0:
        TRACKING_STATE.blink_progress = max(0.0, TRACKING_STATE.blink_progress - 0.22)

    visible_eyes = max(0.0, min(1.0, TRACKING_STATE.eye_open))
    actual_blink = 1.0 - visible_eyes
    return max(TRACKING_STATE.blink_progress, actual_blink * 0.85)


def update_tracking(state: FaceState) -> FaceState:
    global TRACKING_STATE

    TRACKING_STATE.face = smooth_face(TRACKING_STATE.face, state.face)
    TRACKING_STATE.angle = smooth_value(TRACKING_STATE.angle, state.angle, 0.78)
    TRACKING_STATE.mouth_open = smooth_value(TRACKING_STATE.mouth_open, state.mouth_open, 0.45)
    TRACKING_STATE.eye_open = smooth_value(TRACKING_STATE.eye_open, state.eye_open, 0.72)

    smoothed_face = TRACKING_STATE.face
    if smoothed_face is None:
        return state

    return FaceState(
        face=(
            int(smoothed_face[0]),
            int(smoothed_face[1]),
            int(smoothed_face[2]),
            int(smoothed_face[3]),
        ),
        angle=TRACKING_STATE.angle,
        mouth_open=TRACKING_STATE.mouth_open,
        eye_open=TRACKING_STATE.eye_open,
    )


def _default_idle_face(frame: np.ndarray) -> FaceState:
    frame_h, frame_w = frame.shape[:2]
    face_w = int(frame_w * 0.30)
    face_h = int(frame_h * 0.46)
    face_x = int((frame_w - face_w) * 0.5)
    face_y = int(frame_h * 0.12)
    return FaceState(face=(face_x, face_y, face_w, face_h), angle=0.0, mouth_open=0.0, eye_open=0.95)


def composite_avatar(
    frame: np.ndarray,
    avatar: np.ndarray,
    state: FaceState,
    now: float,
    replace_background: bool = True,
    avatar_face_box: Optional[Tuple[int, int, int, int]] = None,
) -> np.ndarray:
    x, y, w, h = state.face
    face_center_x = x + w / 2.0
    face_center_y = y + h * 0.40

    source_avatar = avatar
    source_face_box = avatar_face_box
    if source_face_box is not None:
        source_avatar, source_face_box = crop_avatar_near_face(source_avatar, source_face_box)

    if source_face_box is not None:
        _, _, sfw, _ = source_face_box
        target_face_w = max(32, int(w * 1.35))
        scale = target_face_w / max(1.0, float(sfw))
        head_w = max(48, int(source_avatar.shape[1] * scale))
        head_h = max(48, int(source_avatar.shape[0] * scale))
    else:
        head_w = int(w * 1.65)
        head_h = int(h * (1.95 + state.mouth_open * 0.08))

    resized_avatar = cv2.resize(source_avatar, (head_w, head_h), interpolation=cv2.INTER_AREA)
    blink_level = max(TRACKING_STATE.blink_progress, 1.0 - state.eye_open)
    animated_avatar = animate_avatar_features(resized_avatar, blink_level, state.mouth_open)
    # Keep alignment stable: avoid adding rotation offset when fitting face-to-face.
    rotated_avatar = animated_avatar

    canvas_h = rotated_avatar.shape[0]
    canvas_w = rotated_avatar.shape[1]
    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    canvas = overlay_rgba(canvas, rotated_avatar, 0, 0, canvas_w, canvas_h)

    if source_face_box is not None:
        sfx, sfy, sfw, sfh = source_face_box
        scale_x = head_w / max(1.0, float(source_avatar.shape[1]))
        scale_y = head_h / max(1.0, float(source_avatar.shape[0]))
        avatar_face_cx = (sfx + sfw * 0.50) * scale_x
        avatar_face_cy = (sfy + sfh * 0.45) * scale_y
        out_x = int(face_center_x - avatar_face_cx)
        out_y = int(face_center_y - avatar_face_cy)
    else:
        out_x = int(face_center_x - canvas_w / 2.0)
        out_y = int(face_center_y - canvas_h * 0.45)

    if replace_background:
        stage_bgr = get_static_stage_bgr(frame.shape[1], frame.shape[0])
        return overlay_rgba(stage_bgr, canvas, out_x, out_y, canvas_w, canvas_h)

    return overlay_rgba(frame, canvas, out_x, out_y, canvas_w, canvas_h)


def process_frame(
    frame: np.ndarray,
    avatar: Optional[np.ndarray],
    face_cascade: cv2.CascadeClassifier,
    eye_cascade: cv2.CascadeClassifier,
    mouth_cascade: cv2.CascadeClassifier,
    profile_cascade: Optional[cv2.CascadeClassifier],
    fallback_style: str,
    background_mode: str,
) -> np.ndarray:
    if avatar is None:
        if fallback_style == "normal":
            return frame
        return cartoonize(frame)

    state = estimate_pose(frame, face_cascade, eye_cascade, mouth_cascade, profile_cascade)
    now = time.monotonic()
    avatar_face_box = detect_avatar_face_box(avatar, face_cascade, profile_cascade)

    if state is not None:
        state = update_tracking(state)
    else:
        if TRACKING_STATE.face is not None:
            smoothed_face = TRACKING_STATE.face
            state = FaceState(
                face=(
                    int(smoothed_face[0]),
                    int(smoothed_face[1]),
                    int(smoothed_face[2]),
                    int(smoothed_face[3]),
                ),
                angle=TRACKING_STATE.angle,
                mouth_open=TRACKING_STATE.mouth_open * 0.90,
                eye_open=max(0.75, TRACKING_STATE.eye_open),
            )
        else:
            state = _default_idle_face(frame)

    update_blink_state(state, now)
    return composite_avatar(
        frame,
        avatar,
        state,
        now,
        replace_background=(background_mode != "camera"),
        avatar_face_box=avatar_face_box,
    )


def main() -> int:
    args = build_parser().parse_args()
    spec = FrameSpec(width=args.width, height=args.height, fps=args.fps)

    avatar_path = resolve_avatar_path(args.avatar, args.avatar_dir, args.avatar_name)
    avatar = load_avatar(avatar_path)
    gpio_selector = GpioAvatarSelector(
        enabled=bool(args.gpio_avatar_select),
        gpio0=int(args.gpio0),
        gpio1=int(args.gpio1),
        avatar_dir=args.avatar_dir,
        fallback_avatar=args.avatar,
        gpio_poll_interval=float(args.gpio_poll_interval),
        mapping={
            0: args.avatar_gpio_00,
            1: args.avatar_gpio_01,
            2: args.avatar_gpio_10,
            3: args.avatar_gpio_11,
        },
    )

    if gpio_selector.enabled:
        ensure_gpio_input(gpio_selector.gpio0)
        ensure_gpio_input(gpio_selector.gpio1)
    face_cascade = load_cascade("haarcascade_frontalface_default.xml")
    profile_cascade = load_cascade_optional("haarcascade_profileface.xml")
    eye_cascade = load_cascade("haarcascade_eye_tree_eyeglasses.xml")
    mouth_cascade = load_cascade("haarcascade_smile.xml")

    capture = create_capture(args.camera, spec)
    writer, output_spec, output_desc = create_output_writer(args, spec)

    print(f"camera={args.camera}")
    print(f"output_mode={args.output_mode}")
    print(f"output={output_desc}")
    print(f"build_tag={BUILD_TAG}")
    print(f"output_size={output_spec.width}x{output_spec.height}")
    print(f"output_fps={output_spec.fps}")
    print(f"avatar={'yes' if avatar is not None else 'no'}")
    print(f"avatar_path={avatar_path or 'none'}")
    print(f"fallback_style={args.fallback_style}")
    print(f"background_mode={args.background_mode}")
    print(f"gpio_avatar_select={'on' if gpio_selector.enabled else 'off'}")
    print("processing_started=true")
    sys.stdout.flush()

    try:
        frame_delay = 1.0 / max(spec.fps, 1)
        while not STOP_REQUESTED:
            ok, frame = capture.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            frame = cv2.resize(frame, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
            if args.mirror:
                frame = cv2.flip(frame, 1)

            now = time.monotonic()
            avatar_path, avatar = gpio_selector.select(now, avatar_path, avatar)

            output_frame = process_frame(
                frame,
                avatar,
                face_cascade,
                eye_cascade,
                mouth_cascade,
                profile_cascade,
                args.fallback_style,
                args.background_mode,
            )
            if output_frame.shape[1] != output_spec.width or output_frame.shape[0] != output_spec.height:
                output_frame = cv2.resize(output_frame, (output_spec.width, output_spec.height), interpolation=cv2.INTER_AREA)
            try:
                writer.write(output_frame)
            except Exception as exc:
                print(f"writer_error={exc}")
                sys.stdout.flush()
                writer.release()
                time.sleep(0.2)
                writer, output_spec, output_desc = create_output_writer(args, spec)
            time.sleep(frame_delay * 0.15)
    finally:
        capture.release()
        writer.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
