# RK3588 USB 虚拟摄像头网关

这个项目面向 RK3588 网关板，完成下面这条链路：

USB 摄像头 -> 形象处理 -> RK3588 USB OTG 口 -> 其它电脑上的虚拟摄像头

当前方案不再使用 PHP 管理，改成 Ubuntu 22.04 上更直接的 systemd + Python/OpenCV + UVC gadget 方案。

## 适用前提

1. 你的 RK3588 板子必须有可切换为设备模式的 USB OTG 口。
2. 内核需要启用 configfs 和 UVC gadget 相关功能。
3. USB 摄像头接在 RK3588 的主机口上。
4. 连接到其它电脑的那根线要插在 RK3588 的 OTG 口上。
5. 系统是 Ubuntu 22.04。

## 依赖安装

Ubuntu 22.04 常见环境可先安装这些包：

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-opencv python3-numpy v4l-utils ffmpeg usbutils
```

如果你打算用 pip 装 OpenCV，也可以改成：

```bash
python3 -m pip install opencv-python numpy
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

4. 启动后用 `systemctl` 管理服务。

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
- 头像缩放参数：`AVATAR_SCALE=1.0`（可调）
- GPIO 选头像：默认关闭（`GPIO_AVATAR_SELECT=0`）
- 眼睛动画：默认 `subtle`
- 口型动画：默认 `subtle`
- 分辨率：`1280x720`
- 帧率：`15`
- 网络 JPEG 质量：`70`

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

- `scripts/avatar_processor.py`：视频逐帧处理
- `scripts/setup_uvc_gadget.sh`：UVC gadget 配置脚本
- `scripts/run_avatar_gateway.sh`：处理进程启动入口
- `scripts/install_avatar_gateway.sh`：安装 systemd 服务
- `scripts/avatarctl.sh`：systemd 管理快捷入口
- `systemd/avatar-gateway.service`：服务模板
- `assets/avatar.png`：你自己的头像素材，建议带透明通道
- `assets/avatars/*.png`：可切换头像素材库

## 说明

如果你的板子没有 UVC gadget 能力，或者没有可用的 OTG 口，这个方案就无法直接变成 USB 虚拟摄像头。那种情况下只能改成 RTSP、NFS、WebRTC，或者增加一个支持 gadget 的 USB 控制器。