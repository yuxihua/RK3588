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

如果你的系统自带 `usbdevice` 服务并且与 UVC gadget 冲突（例如反复 bind/unbind 或长期 `not attached`），可强制使用原生 configfs 流程：

```bash
sudo sed -i '/^USB_GADGET_FORCE_CONFIGFS=/d' /etc/default/avatar-gateway
echo 'USB_GADGET_FORCE_CONFIGFS=1' | sudo tee -a /etc/default/avatar-gateway
sudo systemctl disable --now usbdevice.service
sudo systemctl restart uvc-gadget-setup.service
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

## UVC 排障重点

如果你现在的目标是解决 UVC gadget 不附着、一直显示 `not attached`，请优先只看 RK3588 的 USB3 Type-C OTG 这一路，不要把它和板上的 USB2-A 主机口混在一起看。

这块板子上，USB3 口走的是 Type-C / OTG / VBUS / extcon 角色链路；USB2-A 主机口是另一条链路，通常不会直接决定 UVC 是否能枚举。真正需要确认的是：

1. `usb@fc000000` 或对应的 dwc3 节点是否已经强制成 `dr_mode = "peripheral"`。
2. 这一路是否还挂着 `extcon`、`usb-role-switch` 或 `role-switch-default-mode`，如果有，先删掉。
3. OTG PHY 是否有稳定的 `vbus-supply`，必要时先用固定 5V regulator 做最小验证。
4. 同一路上的 host 节点是否还在初始化，如果还在，先临时禁掉，排除角色被抢回 host 的情况。

建议先按下面的最小改法试一轮，只改 UVC 这一路：

```dts
&usbdrd_dwc3_0 {
	status = "okay";
	dr_mode = "peripheral";
	maximum-speed = "high-speed";

	/delete-property/ extcon;
	/delete-property/ usb-role-switch;
	/delete-property/ role-switch-default-mode;
};
```

如果你的 BSP 节点名不是 `usbdrd_dwc3_0`，就把上面的节点替换成实际生效的那一个，但修改思路保持不变：先把这一路固定成 device，再验证 UDC 是否能从 `not attached` 变成 `attached` 或 `configured`。

### 最小实验版

如果你只想先验证“USB3 Type-C OTG 这一路能不能稳定进 device 模式”，先只改最少的几项：

```dts
&usbdrd_dwc3_0 {
	status = "okay";
	dr_mode = "peripheral";
	maximum-speed = "high-speed";

	/delete-property/ extcon;
	/delete-property/ usb-role-switch;
	/delete-property/ role-switch-default-mode;
};
```

这版的目的不是一次性把所有问题修完，而是先确认 UDC 能不能从 `not attached` 变成 `attached`。如果这一版都不行，说明问题还在角色链路，不在 UVC 描述符或应用层。

### 强制专用口

如果最小实验版仍然会被拉回 host，可以再把这一路做成“只给 gadget 用”的专用口：

```dts
vcc5v0_usb_gadget: vcc5v0-usb-gadget {
	compatible = "regulator-fixed";
	regulator-name = "vcc5v0_usb_gadget";
	regulator-min-microvolt = <5000000>;
	regulator-max-microvolt = <5000000>;
	regulator-always-on;
	regulator-boot-on;
};

&usb2phy0_otg {
	status = "okay";
	phy-supply = <&vcc5v0_usb_gadget>;
};

&usb2phy0_otg_port {
	status = "okay";
	phy-supply = <&vcc5v0_usb_gadget>;
	vbus-supply = <&vcc5v0_usb_gadget>;
};

&usbdrd_dwc3_0 {
	status = "okay";
	dr_mode = "peripheral";
	maximum-speed = "high-speed";

	/delete-property/ extcon;
	/delete-property/ usb-role-switch;
	/delete-property/ role-switch-default-mode;
};
```

这个版本的目标是尽量把 OTG 角色判断链简化掉，让 DWC3 只当 gadget 用。不同 BSP 的节点名可能略有差异，如果你的原理图或 DTS 里不是 `usb2phy0_otg` / `usb2phy0_otg_port`，就替换成对应的实际节点名。

### 验证顺序

改完以后，先不要跑复杂的 UVC 业务，只验证这几个状态：

1. 启动后看 `/sys/class/udc/fc000000.usb/state` 是否还停在 `not attached`。
2. 看 extcon 状态里是否还长期显示 `USB-HOST=1`。
3. 先起最小 ACM gadget，再起 UVC gadget，确认是“角色链路没起来”还是“UVC 描述符/函数协商失败”。
4. 只要最小 ACM 都不稳，就继续回头查 extcon、Type-C controller 和同口 host 节点，而不是继续调应用层。

### 具体操作指令

如果你要自己改源码，按下面顺序做。

1. 找到板级 DTS 文件。

在内核源码树里执行：

```bash
grep -RIn "usb@fc000000\|usbdrd_dwc3_0\|usb2phy0_otg\|extcon\|usb-role-switch\|role-switch-default-mode" arch/ arm64/ dts/
```

你要找到的是 NanoPi M6V2 实际使用的板级 dts 或 dtsi 文件，不是通用 rk3588 文件。

如果你只想要一个固定格式，可以按下面这个模板来改：

```bash
# 1) 找到板级 DTS
grep -RIn "usb@fc000000\|usbdrd_dwc3_0\|usb2phy0_otg\|extcon\|usb-role-switch\|role-switch-default-mode" arch/ arm64/ dts/

# 2) 打开找到的板级 dts/dtsi 文件，把 USB3 Type-C OTG 这一路改成 device
#    需要替换成你实际找到的节点名和文件名

# 3) 重新编译 dtb
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- <你的 dtb 目标>

# 4) 替换到当前系统正在使用的 dtb
#    如果是 boot 分区就替换 boot 里的 dtb；如果是 resource 分区就替换打包后的 dtb

# 5) 重启后先看 UDC 状态
cat /sys/class/udc/fc000000.usb/state

# 6) 先验证最小 ACM gadget，再验证 UVC gadget
dmesg | grep -Ei 'dwc3|gadget|extcon|typec|usb'
```

模板里你只需要替换两个地方：

1. `<你的 dtb 目标>`，换成你工程里实际的 dtb 编译目标。
2. 节点名和文件名，换成你在第 1 步里找到的 NanoPi M6V2 板级源码。

如果你要的是能直接照着敲的命令格式，可以按下面这个顺序来：

```bash
# 进入你的内核源码树
cd /path/to/your/kernel-source

# 搜索和 USB OTG 相关的节点
grep -RIn "usb@fc000000\|usbdrd_dwc3_0\|usb2phy0_otg\|extcon\|usb-role-switch\|role-switch-default-mode" arch/arm64/boot/dts/

# 打开找到的板级 dts/dtsi 文件，改 USB3 Type-C OTG 这一路
# 例如：vim arch/arm64/boot/dts/rockchip/<your-board>.dts

# 编译 dtb
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- <your-dtb-target>

# 看编译结果
ls -l arch/arm64/boot/dts/rockchip/*.dtb

# 把编出来的 dtb 替换到你的启动介质里
# 如果是 boot 分区，就替换 boot 里的 dtb
# 如果是 resource 分区，就替换打包后的 dtb

# 重启后先看 UDC
cat /sys/class/udc/fc000000.usb/state

# 再看内核日志
dmesg | grep -Ei 'dwc3|gadget|extcon|typec|usb'
```

如果你是从 WSL 或 Windows 这边改源码，可以先在 Windows 终端里打开源码目录，再进入 WSL/Ubuntu 编译环境执行上面的命令；重点是命令顺序不要变：先 grep 找文件，再改 dts，再编 dtb，最后替换和验证。

2. 修改 USB3 Type-C OTG 这一路。

把对应节点改成下面这种最小版本：

```dts
&usbdrd_dwc3_0 {
	status = "okay";
	dr_mode = "peripheral";
	maximum-speed = "high-speed";

	/delete-property/ extcon;
	/delete-property/ usb-role-switch;
	/delete-property/ role-switch-default-mode;
};
```

如果你的节点名不是 `usbdrd_dwc3_0`，就改成实际存在的那个节点名，但修改思路不变。

3. 如果最小版本还不行，再加固定 5V 供电。

在同一个 dts 里加入一个固定 regulator，再把 OTG PHY 绑过去：

```dts
vcc5v0_usb_gadget: vcc5v0-usb-gadget {
	compatible = "regulator-fixed";
	regulator-name = "vcc5v0_usb_gadget";
	regulator-min-microvolt = <5000000>;
	regulator-max-microvolt = <5000000>;
	regulator-always-on;
	regulator-boot-on;
};

&usb2phy0_otg {
	status = "okay";
	phy-supply = <&vcc5v0_usb_gadget>;
};

&usb2phy0_otg_port {
	status = "okay";
	phy-supply = <&vcc5v0_usb_gadget>;
	vbus-supply = <&vcc5v0_usb_gadget>;
};
```

4. 如果同口还有 host 控制器，就先禁掉。

如果你在同一路物理口上看到了 xhci、ehci、ohci 之类节点，先把它们临时设成 disabled，只保留 gadget 侧，避免角色被 host 抢回去。

5. 编译 dtb。

在内核源码目录执行：

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- <板级 dtb 目标>
```

如果你用的是 FriendlyElec 的现成内核树，也可以直接编译整个 dtb 目标，再从输出目录拿到新的 dtb 文件。

6. 刷入新 dtb 并重启。

如果你的系统是通过 resource 分区或打包镜像加载 dtb，就把新 dtb 按当前启动链路替换进去；如果是直接从 boot 分区加载，就替换 boot 里的 dtb。

7. 先做最小 ACM 验证，再做 UVC 验证。

重启后先执行：

```bash
cat /sys/class/udc/fc000000.usb/state
dmesg | grep -Ei 'dwc3|gadget|extcon|typec|usb'
```

然后先起最小 ACM gadget。只要 ACM 还是不稳定，就先别继续调 UVC。

8. 只有 ACM 稳了，再回到 UVC。

如果 ACM 已经能稳定枚举，再启用 UVC gadget，重点看 `/sys/class/udc/fc000000.usb/state` 是否进入 `attached` 或 `configured`，以及 Windows 端是否正确识别虚拟摄像头。