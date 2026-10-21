# 开发与贡献

先阅读 [README](README.md)、[AGENTS](AGENTS.md) 和 [当前架构](ARCHITECTURE.md)。不假设已有持续集成。

```sh
uv sync --frozen
uv run pytest -q
node --check centerstage/static/app.js
node --test tests/*.test.mjs
uv build --wheel
```

运行项目用 `uv run centerstage serve`；可选模型预热用 `uv run centerstage prepare`。当前只允许一个服务进程写入同一数据目录。不要为了测试另起模型服务覆盖使用中的任务。

修改计时、追踪、切镜、标注或保存逻辑时，先写能复现问题的回归用例；实时运行与缓存回放必须共用 AnalysisPipeline。合成模型输出用于工程契约测试，不是识别准确率。性能用 `scripts/benchmark.py` 测量现有服务，记录硬件、采样率、首段与总耗时。准确率需要独立的逐帧真值，不能用名单匹配、未知减少或检测置信度代替。

界面保持白棕色工作台，必须在真实浏览器验证拖动、暂停、倒退、双 C、片尾和窄屏。修改统计后核对 JS、API 与 CSV，并明确成员、轨迹片段和暂定服装关联的不同含义。

提交时不包含 `.centerstage`、用户视频、模型、凭据或本机私人路径。README 中的界面案例截图除外，且不包含原视频。公开发布、推送和发布安装包需要用户授权。本地核验材料放 `evidence/`，已排除 Git。历史记录见 [实际验证](docs/VALIDATION.md)。
