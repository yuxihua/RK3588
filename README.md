# RK3588 USB 虚拟摄像头网关

这个项目面向 RK3588 网关板，完成下面这条链路：

USB 摄像头 -> 形象处理 -> RK3588 USB OTG 口 -> 其它电脑上的虚拟摄像头

当前方案不再使用 PHP 管理，改成 Ubuntu 22.04 上更直接的 systemd + C++/OpenCV + UVC gadget 方案；管理脚本仍然保留在 `scripts/` 里，方便安装和切换。

## 适用前提

1. 你的 RK3588 板子必须有可切换为设备模式的 USB OTG 口。
2. 内核需要启用 configfs 和 UVC gadget 相关功能。
3. USB 摄像头接在 RK3588 的主机口上。
4. 连接到其它电脑的那根线要插在 RK3588 的 OTG 口上。
5. 系统是 Ubuntu 22.04。

## 依赖安装

如果你准备构建新的 C++ 运行时，Ubuntu 22.04 常见环境先安装这些包：

```bash
sudo apt update
sudo apt install -y cmake g++ libopencv-dev v4l-utils ffmpeg usbutils
```

如果你还想保留 Python 回退路径，也可以再装这组包：

```bash
sudo apt install -y python3 python3-pip python3-opencv python3-numpy
```

## 项目安装

1. 先确认 RK3588 的 USB OTG 口已经连到目标电脑。
2. 执行安装脚本：

```bash
sudo bash scripts/install_avatar_gateway.sh
```

安装脚本会把项目复制到 `/opt/rk3588-avatar-gateway`，然后注册 systemd 服务。

3. 如果你想手动配置 UVC gadget，也可以单独执行：

```bash
sudo bash scripts/setup_uvc_gadget.sh
```

4. C++ 运行时源码放在 `CPP/` 下，建议先构建再启动：

```bash
cd CPP
cmake -S . -B build
cmake --build build -j
```

构建完成后，`scripts/run_avatar_gateway.sh` 会优先启动 `CPP/build/avatar_gateway`，否则回退到原来的 Python 实现。

Windows 开发机（MSYS2 clang64）建议使用：

```powershell
& "C:/msys64/usr/bin/bash.exe" -lc "export PATH=/clang64/bin:/usr/bin:$PATH; cd /c/data/BaiduSyncdisk/2026/直播课堂/RK3588/CPP && cmake -S . -B build-clang -G Ninja && cmake --build build-clang -j"
```

Windows 启动建议使用 PowerShell 脚本，它会自动注入 clang64 运行时路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_avatar_gateway_windows.ps1 --help
```

如果你的 MSYS2 不在默认位置，可先设置 `AVATAR_CLANG_BIN`，例如：

```powershell
$env:AVATAR_CLANG_BIN = "D:/msys64/clang64/bin"
powershell -ExecutionPolicy Bypass -File scripts/run_avatar_gateway_windows.ps1 --help
```

5. 启动后用 `systemctl` 管理服务。

## 日常操作

```bash
sudo systemctl start avatar-gateway
sudo systemctl stop avatar-gateway
sudo systemctl restart avatar-gateway
sudo systemctl status avatar-gateway
```

也可以用脚本：

```bash
bash scripts/avatarctl.sh start
bash scripts/avatarctl.sh stop
bash scripts/avatarctl.sh restart
bash scripts/avatarctl.sh status
```

头像选择：

```bash
bash scripts/avatarctl.sh list-avatars
bash scripts/avatarctl.sh select-avatar cyber_girl
bash scripts/avatarctl.sh set-scale 1.3
```

`select-avatar` 传入的是文件名（不带 `.png`），脚本会写入 `/etc/default/avatar-gateway` 并自动重启服务。
`set-scale` 用于设置虚拟形象缩放系数（`AVATAR_SCALE`），脚本会写入 `/etc/default/avatar-gateway` 并自动重启服务。

GPIO 选择头像（GPIO0/GPIO1 两位共四种）：

- `GPIO1 GPIO0 = 00` -> `avatar_00.png`
- `GPIO1 GPIO0 = 01` -> `avatar_01.png`
- `GPIO1 GPIO0 = 10` -> `avatar_10.png`
- `GPIO1 GPIO0 = 11` -> `avatar_11.png`

头像文件放在 `/opt/rk3588-avatar-gateway/assets/avatars/`，名称与上面对应即可。

## 默认参数

- 输入摄像头：`/dev/video0`
- 输出虚拟摄像头：`/dev/video11`
- 默认头像（兜底）：`/opt/rk3588-avatar-gateway/assets/avatar.png`
- 可选头像目录：`/opt/rk3588-avatar-gateway/assets/avatars`
- 输出背景模式：默认 `camera`（使用摄像头真实背景）
- 渲染模式：默认 `RENDER_MODE=beauty`（可选 `beauty` 或 `avatar`）
- 美颜强度：默认 `BEAUTY_STRENGTH=0.45`
- 头像缩放参数：`AVATAR_SCALE=1.0`（可调）
- GPIO 选头像：默认关闭（`GPIO_AVATAR_SELECT=0`）
- 眼睛动画：默认 `subtle`
- 口型动画：默认 `normal`
- 口型上下偏移：`MOUTH_Y_OFFSET=0.00`（可调，正值下移，负值上移）
- 口型左右偏移：`MOUTH_X_OFFSET=0.00`（可调，正值右移，负值左移）
- 重检测间隔：`DETECT_EVERY=2`（每2帧做一次重检测，降低CPU占用）
- 分辨率：`960x540`
- 帧率：`15`
- 网络 JPEG 质量：`70`

网络模式下可直接使用浏览器调参：

- 视频流地址：`http://<板子IP>:8080/mjpeg`
- 控制页面：`http://<板子IP>:8080/ui`
- 设置接口：`GET/POST http://<板子IP>:8080/api/settings`

`/ui` 页面支持实时调整 `camera_device`（视频源）、`render_mode`、`beauty_strength`、`avatar_scale`、`mouth_x_offset`、`mouth_y_offset`、`detect_every`、`network_jpeg_quality`，提交后立即生效。

如果当前选中的摄像头打不开，`/ui` 和 `/mjpeg` 仍会保持可访问，画面会显示摄像头不可用提示，同时后台会自动重试恢复。

视频源区域支持“推荐/全部”筛选和关键词过滤：默认“推荐”只显示更可能的外接摄像头，找不到时再切到“全部”。

现在美颜还可以选预设和细项：

- 美颜预设：`natural`、`soft`、`bright`、`clear`、`glow`
- 磨皮：`skin_smoothness`
- 提亮：`skin_brightness`
- 锐化：`skin_sharpen`
- 脸部：`face_slim`、`face_round`
- 眼睛：`eye_enlarge`、`eye_spacing`
- 眉毛：`eyebrow_height`、`eyebrow_angle`
- 鼻子：`nose_bridge`、`nose_highlight`
- 嘴巴：`mouth_size`、`lip_color`
- 全身：`body_slim`
- 美妆滤镜：`filter_style`

如果你想要更明显的美颜效果，通常先选 `bright` 或 `glow`，再把 `beauty_strength`、`skin_brightness` 和 `face_slim` 往上调一点。

如果你的设备号不同，可以在页面里改。

GPIO 引脚和头像映射可在 `/etc/default/avatar-gateway` 修改，例如：

```bash
GPIO_AVATAR_SELECT=1
GPIO0_PIN=0
GPIO1_PIN=1
AVATAR_GPIO_00=avatar_00
AVATAR_GPIO_01=avatar_01
AVATAR_GPIO_10=avatar_10
AVATAR_GPIO_11=avatar_11
```

## 处理方式

当前实现默认做两层处理：

1. 如果提供了头像 PNG，会根据人脸位置、眼睛连线倾角和口部强度动态叠加到画面上。
2. 如果没有头像或没检测到人脸，就使用卡通化风格作为降级效果。
3. 当前处理器还会做时间平滑，并生成一个简单的半身底图，让画面更稳定。
4. 还包含随机眨眼效果，并会根据眼睛检测结果自动增强闭眼效果，让虚拟形象看起来不那么僵硬。
5. 当前输出已经带有舞台式背景和柔和边缘分离，不再直接暴露原始摄像头背景。
6. 为了降低资源占用，舞台背景和主体默认改为静态（已关闭呼吸与摇摆动态）。
7. 当前背景进一步加入了虚拟屏幕、边缘轮廓灯和底部灯带，更接近演播室风格。
8. 现在还加入了正式的下三分之一标题条、微弱网格和侧边灯箱，更像可输出的直播成片。
9. 视觉主题已统一到一套青蓝霓虹演播室风格，并增加了角标框线。
10. 画面还叠加了轻微扫描线和信号条，让输出更像直播链路里的成片。
11. 现在进一步加入了斜向霓虹光束，整体已经更偏赛博直播间风格。
12. 还加入了很轻的色散偏移，整体更接近赛博朋克直播信号。
13. 当前版本已经把对比度、霓虹轮廓和色散进一步拉强，偏高对比赛博朋克直播棚。
14. 画面还加入了漂浮粒子和中心光晕，主体周围的能量感会更明显。
15. 漂浮粒子密度和下三分之一标题条的脉冲感也进一步加强了。
16. 现在还加入了 HUD 弧线和角标标记，让画面更像实时节目控制台。
17. 为优先保障形象驱动算力，整体抖动与高频光效动态默认关闭。
18. 新增了 bloom 发光和 glitch 条，赛博朋克失真感更强。
19. 进一步加入了数字雨和综合色调，直播信号风格更明显。
20. 还加入了纵向脉冲柱和流动雾化，让高压赛博棚的层次更厚。
21. 新增了细粒信号噪声和底部色带，实时流式观感更完整。
22. 现在又补了边缘闪烁和信号尾迹，让直播信号残影更明显。
23. 进一步加入了移动扫描光带，舞台前景的动感更强。
24. 现在默认优先把摄像头中的人脸替换成头像脸部，而不是整个人物贴图，保留原视频背景更自然。

这比直接在 PHP 里做像素处理更适合实时场景，也更容易在 RK3588 上跑起来。
当前实现不需要额外安装 mediapipe 或 dlib，依赖仍然只有 OpenCV 自带的人脸、眼睛和微笑分类器。

## 文件说明

- `CPP/src/main.cpp`：新的 C++ 视频处理主入口
- `scripts/avatar_processor.py`：旧的 Python 回退实现
- `scripts/setup_uvc_gadget.sh`：UVC gadget 配置脚本
- `scripts/run_avatar_gateway.sh`：处理进程启动入口
- `scripts/run_avatar_gateway_windows.ps1`：Windows 启动入口（自动设置 clang64 PATH）
- `scripts/install_avatar_gateway.sh`：安装 systemd 服务
- `scripts/avatarctl.sh`：systemd 管理快捷入口
- `CPP/`：C++ 运行时源码和构建文件
- `systemd/avatar-gateway.service`：服务模板
- `assets/avatar.png`：你自己的头像素材，建议带透明通道
- `assets/avatars/*.png`：可切换头像素材库

## 说明

如果你的板子没有 UVC gadget 能力，或者没有可用的 OTG 口，这个方案就无法直接变成 USB 虚拟摄像头。那种情况下只能改成 RTSP、NFS、WebRTC，或者增加一个支持 gadget 的 USB 控制器。