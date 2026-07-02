# RK3588/RK3522 C++ 升级路线（分阶段）

本文目标：在不打断现有可用版本的前提下，把当前 OpenCV + Haar 的实现逐步升级到“稳定 30FPS+、侧脸低头鲁棒、音口同步”的工程形态。

## 0. 当前状态（已实现）

- 语言：C++17
- 视频采集：OpenCV VideoCapture (V4L2)
- 人脸检测：OpenCV Haar（frontal/profile，含旋转和短时保持补偿）
- 美颜：OpenCV 双边滤波 + 锐化
- 渲染：2D 头像叠加
- 输出：MJPEG HTTP / V4L2 写入（USB 模式）

结论：当前版本已可用，但在大角度侧脸、低头、光照变化下仍会漏检，且不是 NPU 加速链路。

## 1. 阶段一（优先，先解决漏检）

### 1.1 目标

- 人脸检测稳定性明显提升（侧脸、低头场景）
- 保持现有 UI/API 与输出接口不变

### 1.2 技术方案

- 引入 RKNN 人脸检测模型（建议 RetinaFace 或 YOLO-face）
- 引入 106 关键点模型（RKNN）
- 新增轻量跟踪器（KCF/光流/卡尔曼三选一）用于短时遮挡补偿

### 1.3 模块边界

新增接口（建议）：

```cpp
struct FaceResult {
    cv::Rect box;
    std::vector<cv::Point2f> landmarks106;
    float score;
};

class IFaceEstimator {
public:
    virtual ~IFaceEstimator() = default;
    virtual bool init() = 0;
    virtual bool infer(const cv::Mat& bgr, std::vector<FaceResult>& faces) = 0;
};
```

说明：先把主循环改为依赖 IFaceEstimator，底层可以先用 Haar 实现，再切 RKNN 实现，主流程不需要大改。

### 1.4 验收指标

- 720p 输入时，人脸漏检率较当前下降 >= 50%
- 侧脸 45°、低头 30° 可持续跟踪 >= 3 秒

## 2. 阶段二（性能，降低 CPU 并提帧）

### 2.1 目标

- 稳定 30FPS（目标分辨率按你的直播配置）
- 总延迟下降，CPU 占用可控

### 2.2 技术方案

- 采集切换到 libcamera
- 前处理使用 RGA（缩放、裁剪、色彩空间转换）
- 推理输入走零拷贝/低拷贝路径

### 2.3 建议架构

- 线程 A：采集线程（libcamera）
- 线程 B：推理线程（RKNN）
- 线程 C：渲染线程（先保留 2D，再升级 3D）
- 线程 D：输出线程（MJPEG/UVC）

线程间使用无锁环形队列，统一帧序号与时间戳。

### 2.4 验收指标

- 1080p 输入下输出 720p，FPS >= 25，平均延迟 <= 120ms
- CPU 使用率明显低于当前 OpenCV 全 CPU 方案

## 3. 阶段三（体验，3D 头像 + 音口同步）

### 3.1 目标

- 口型与语音同步
- 头部姿态和表情更自然

### 3.2 技术方案

- 渲染：OpenGLES 3D 模型驱动
- 音频：ALSA 采集 + 音频特征（能量/梅尔谱）
- 同步：统一 monotonic 时钟，按时间戳对齐音视频

### 3.3 数据流

- 视频：landmark + head pose -> rig 参数
- 音频：特征 -> viseme（嘴型）
- 渲染：rig + viseme -> OpenGLES

### 3.4 验收指标

- 正常语速下音口偏差 <= 80ms
- 快速说话时嘴型延迟不出现明显拖尾

## 4. 输出链路（UVC Gadget）

- 保持现有 UVC 输出路径可用
- 建议把“推流帧”与“本地预览帧”分离，避免相互阻塞
- UVC 出问题时自动降级到 MJPEG 网络输出（服务不中断）

## 5. 里程碑建议（最小风险）

1. M1：接口抽象完成（IFaceEstimator），旧逻辑不变
2. M2：RKNN 人脸检测接入，替代 Haar
3. M3：106 关键点接入，驱动 2D 贴图增强
4. M4：libcamera + RGA 接入
5. M5：ALSA + 音口同步
6. M6：OpenGLES 3D 头像渲染

## 6. 你当前应先做什么

1. 先部署本次“鲁棒检测增强版”（已完成代码）验证侧脸低头改善幅度
2. 同时创建 IFaceEstimator 抽象层（下一次迭代）
3. 再接 RKNN 模型，不要和 OpenGLES/音频同步同一迭代并行上

这样能保证每一步都可验证、可回退，避免一次性大改导致整体不可用。
