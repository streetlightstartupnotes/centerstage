> 历史草案（2026-10-21 核验）：本文不是当前能力、启动方法或验收结论。文中的自动认名、准确率和加速百分比缺少相应验证；部分接口与现行服务不兼容。当前入口见 [README](README.md)，核验见 [项目逻辑审计](docs/LOGIC_AUDIT.md)。原文保留用于追溯。

# 🎭 CenterStage - 女团C位监测系统 V2

**AI驱动的女团表演C位实时监测系统 · 自动成员识别**

## ✨ 核心功能

### 🎯 完全自动化的成员识别
- **跨镜头追踪**: 使用DeepSORT算法实现跨镜头同一人物的持续追踪
- **人脸特征提取**: 基于HSV颜色直方图的人脸特征提取
- **自动身份匹配**: 智能匹配同一成员在不同镜头中的出现
- **姓名自动标注**: 根据出现频率和特征稳定性自动分配成员名字
- **无需手动标注**: 系统全自动识别，用户无需任何输入

### 📊 C位实时监测
- **实时C位识别**: 基于画面中心位置、面部大小和清晰度
- **累计时长统计**: 精确统计每位成员的C位累计时间
- **实时排行榜**: 动态更新C位时长排行
- **可视化展示**: 实时标注当前C位和所有成员

### 🚀 性能优化
- **轻量级模型**: YOLOv8n + DeepSORT，速度快
- **流式处理**: 边处理边展示，无需等待全部完成
- **结果缓存**: 自动保存识别结果，避免重复处理
- **增量学习**: 持续优化特征匹配准确度

## 🛠 技术架构

```
Frontend (HTML/JS)
    ↓
Flask API Server
    ↓
VideoProcessorV2
    ├── YOLOv8 (人物检测)
    ├── DeepSORT (跨帧追踪)
    ├── AgentDrivenIdentifier (身份识别)
    │   ├── 人脸特征提取
    │   ├── 特征匹配
    │   └── 自动姓名分配
    └── CenterPositionDetector (C位检测)
```

## 📦 安装

```bash
# 1. 克隆项目
git clone <项目地址>
cd centerstage

# 2. 安装依赖
pip install -r requirements.txt
# 或使用uv
uv pip install -r requirements.txt

# 3. 下载YOLOv8模型（首次运行自动下载）
```

## 🎬 使用方法

### 启动系统

```bash
# 方式1: 使用Python
python3 run_v2.py

# 方式2: 使用启动脚本
./启动.command
```

### 处理视频

1. 打开浏览器访问 `http://127.0.0.1:8640`
2. 上传女团表演视频（支持MP4, AVI, MOV）
3. 系统自动开始处理：
   - 检测和追踪所有人物
   - 自动识别并固定每个成员的身份
   - 根据出现频率自动分配姓名
   - 实时监测C位变化
   - 统计C位时长并排行

### 识别流程

```
1. 人物检测 (YOLOv8)
   └─> 检测画面中所有人物

2. 跨帧追踪 (DeepSORT)
   └─> 为每个人物分配track_id

3. 身份统一 (AgentDrivenIdentifier)
   ├─> 提取人脸特征
   ├─> 匹配历史特征库
   ├─> 同一人物统一identity_id
   └─> 跨镜头保持身份一致

4. 自动命名
   ├─> 统计每个identity出现次数
   ├─> 按频率排序
   └─> 自动分配成员名字

5. C位监测
   ├─> 计算画面中心距离
   ├─> 评估面部大小
   └─> 实时更新C位统计
```

## 🎯 核心算法

### 人脸特征提取
```python
# 使用HSV颜色直方图
- H通道: 30bins (色调)
- S通道: 32bins (饱和度)  
- V通道: 32bins (明度)
→ 总计94维特征向量
```

### 身份匹配
```python
# 余弦相似度计算
similarity = dot(feat1, feat2) / (norm(feat1) * norm(feat2))

# 阈值: 0.75
if similarity > 0.75:
    → 认为是同一人
else:
    → 创建新身份
```

### C位判定
```python
# 综合评分
score = distance_score * 0.5 + size_score * 0.3 + clarity_score * 0.2

# 最高得分者为C位
```

## 📁 项目结构

```
centerstage/
├── centerstage/
│   ├── __init__.py
│   ├── video_processor_v2.py      # 视频处理器V2
│   ├── agent_identifier.py        # Agent驱动的识别器
│   ├── member_identifier.py       # 成员身份识别
│   ├── center_detector.py         # C位检测器
│   ├── api_v2.py                  # Flask API V2
│   └── static/
│       └── index_v2.html          # 前端界面V2
├── run_v2.py                      # 启动脚本V2
├── README_V2.md                   # 本文档
└── requirements.txt               # 依赖列表
```

## 🎨 界面展示

### 主要区域
- **视频上传**: 拖拽或点击上传视频
- **处理进度**: 实时显示处理进度和帧数
- **视频画面**: 实时标注检测结果
- **当前C位**: 高亮显示当前C位成员
- **识别成员数**: 显示已识别的成员总数
- **C位排行榜**: 按时长排序的所有成员

## 🔧 配置选项

### 识别参数
```python
# 在 agent_identifier.py 中调整

# 特征匹配阈值 (越高越严格)
similarity_threshold = 0.75

# 特征历史保留数量
max_features_per_identity = 5

# 自动命名触发间隔
auto_naming_interval = 30  # 每30帧
```

### C位检测参数
```python
# 在 center_detector.py 中调整

# 权重配置
distance_weight = 0.5  # 距离权重
size_weight = 0.3      # 大小权重
clarity_weight = 0.2   # 清晰度权重
```

## 🐛 常见问题

### Q: 为什么有的成员没有名字？
A: 系统按出现频率自动分配名字。出现次数较少的成员可能显示为"成员 X"。

### Q: 如何提高识别准确度？
A: 
1. 使用高清视频
2. 确保视频中成员面部清晰
3. 调低 `similarity_threshold` 使匹配更宽松

### Q: 能否手动指定成员名字？
A: 当前版本自动识别。手动标注功能在开发中。

### Q: 支持哪些女团？
A: 支持任意女团视频。系统会自动检测和识别所有出现的成员。

## 📝 开发计划

- [ ] 集成真实人脸识别模型（DeepFace/InsightFace）
- [ ] 支持手动修正成员名字
- [ ] 导出分析报告（JSON/PDF）
- [ ] 视频片段导出（某成员的所有C位时刻）
- [ ] 多视频对比分析
- [ ] 成员标签数据库（可复用）

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！

---

**技术栈**: Python · Flask · YOLOv8 · DeepSORT · OpenCV · HTML/CSS/JS
