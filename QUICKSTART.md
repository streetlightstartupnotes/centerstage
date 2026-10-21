# 运行 CenterStage

在仓库目录执行：

```sh
uv sync --frozen
uv run centerstage serve --port 8640
```

浏览器打开 http://127.0.0.1:8640。模型就绪后导入视频；可选择边分析边播放或完整分析后播放。首次模型下载不包含在视频缓冲等待中。保持本地进程运行。

macOS 可运行 `启动.command`；`快速开始.sh` 与 `run.sh` 使用同一入口。不要同时启动多个服务写入同一个 `.centerstage`。现有 Agent 的操作流程见 [AGENT_GUIDE](AGENT_GUIDE.md)。

时间轴颜色表示单 C、双 C、未判定、尚无结果；悬停查看区间，点击定位。成员榜只有有依据的姓名。姓名待对应、轨迹片段、来源名单不能互相替代。当前不能承诺任意视频全自动认名和稳定跨镜头身份。详见 [README](README.md)。
