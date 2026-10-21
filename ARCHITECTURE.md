# CenterStage 当前运行架构

本页描述实际启动的 0.2 服务。早期文档混入独立 Flask / YOLO 原型和未接入的批量、异步评分模块，导致入口与能力声明互相矛盾；旧文保存在本地核验材料，不能据此认定功能完成。

## 一条运行路径

`run.sh`、`启动.command`、`快速开始.sh`、`centerstage serve` 与 `python -m centerstage serve` 均进入 `centerstage.app:create_app`。`run_v2.py` 是这个服务的兼容入口。仅绑定 127.0.0.1，使用一个 Uvicorn 进程、一个分析队列、一个模型实例。

| 层 | 实际模块 | 责任 |
| --- | --- | --- |
| 浏览器 | static/index.html、app.js、playback.js、statistics.js | 导入、播放、叠加框、半开区间时间轴、成员计时、导出 |
| HTTP | app.py | 同源检查、参数校验、Range 视频读取、分页帧数据、来源与标注接口 |
| 调度 / 保存 | engine.py | 排队、取消、状态、JSONL 持久化、损坏前缀恢复 |
| 解码 / 切镜 | video.py | 原始媒体时间戳、旋转、采样、有限前视切镜检测、真实解码终点 |
| 检测 | model.py | RTMO-s ONNX；单帧推理；CoreML / CUDA 可用时加速，CPU 回退 |
| 跟踪 | pipeline.py | 三种社区追踪器；切镜重置；一帧暂定轨迹确认；实时与缓存回放共用 |
| C 位 | scoring.py | 视觉几何 / 可见性规则与 0.3 秒前视稳定性；输出当前轨迹 ID |
| 服装关联 | appearance.py | 肩髋服装特征、分组歧义拒绝、同屏排斥、矛盾撤销；不确认身份或传播姓名 |
| 文本提示 | captions.py | 独立线程、最多两张排队图片；不阻塞 C 位；只产生文字线索 |
| 姓名证据 | annotations.py | 来源标注、时间 / 轨迹覆盖校验、版本冲突、审阅范围 |
| 计时 | statistics.py | 与 JS 相同的媒体区间口径；导出与 API 共用 |
| 现有 Agent | agent_worker.py / CLI | 可选 JSON/stdin 适配器；搜索公开文字依据，提交有证据的标注 |

## 时间和身份不变量

1. 每个结果属于 `[t, end)`；时间必须有限、递增且不重叠。`centers` 必须属于该样本可见的轨迹。文件未解码的尾部不填充上一个 C 位。
2. 网页按呈现的视频帧时间绘制框；拖动期间隐藏旧框，跨切镜或数据空隙不插值。时间轴按区间真实宽度绘制，颜色表示判定状态。
3. 单 C 的秒数等于区间长度。双 C 每个分别计秒，等分秒数各分一半；同一有依据姓名在同一时刻只计算一次。未对应姓名的区间取并集。
4. 暂停、回退和重播只是查询视频时间，不累加播放墙钟。所有统计截止时间都截断区间；未来轨迹不生成零秒排行。
5. `track_count` 是轨迹片段数，`appearance_links` 是暂定服装关联。两者都不是成员数。名单与字幕不自动形成具体人物姓名。
6. Agent 结果绑定实际审阅的帧数和标注版本。冲突返回 409；越界、无轨迹或跨缺失片段的标注返回 422。

## 能力边界

当前没有可靠跨镜头人物身份记忆、任意视频自动认名、独立 C 位准确率或十秒就绪的普遍保证。不能把关系阈值放宽、未知减少或读取到九个姓名当作准确率提高。

实验模块 `async_pipeline`、`batch_inference`、`enhanced_scoring`、`video_processor_v2` 等未接入运行链路，不进入发行包；保留源文件用于追溯。运行中的全局配置改写返回 409，避免中途换算法或启用接口不兼容的模块。仅导入参数中的采样率、追踪器、观看模式属于当前支持的选择。

## 验证

`uv run pytest -q`；`node --check centerstage/static/app.js`；`node --test tests/*.test.mjs`。

真实视频性能通过现有本地服务测试：`uv run python scripts/benchmark.py VIDEO_PATH`；核查已有任务用 `--job JOB_ID`。不启动第二套引擎，不把名单重合率作为识别准确率。逐项核验和未完成项见 [实际验证记录](docs/VALIDATION.md)。
