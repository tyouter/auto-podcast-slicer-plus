# 项目目录模板

## 最小骨架（任何视频项目都用这套）

```
<project-root>/            # 如 garden-production
├── source/                # 源素材（视频/音频），或直接放项目根
│   └── ep01.mp4          # 源视频（绝对路径，不拷进项目）
├── output/                # 渲染产物
│   ├── clips/             # 独立切片
│   ├── fullcut/           # 整期精剪/混剪
│   └── release/           # 最终交付的成品
├── corrections.yaml       # 勘误表（{wrong: correct} 子串替换）
├── AGENTS.md              # AI agent 自动加载：花园精神/权限/工作流
└── README.md              # 人类看：项目简介/入口链接/许可
```

**铁律**：
- 源视频不用拷进项目（mklink / 绝对路径引用，36GB 视频搬来搬去是浪费）
- 渲染产物走本地 SSD（`output/`），做完再传 NAS
- 勘误表只增不减（用户定的权威源）

## 花园式播客项目（完整版）

> 适用于有 Wiki 知识库、双导演（人类+AI）共创的深度对话项目。

```
<project-root>/
├── source                 # 源素材
├── output/                # 渲染（同最小骨架）
│   └── fullcut/release/   # 最终成品落这
├── corrections.yaml       # 勘误
├── AGENTS.md / README.md
└── Wiki/<节目名>/          # Obsidian Wiki vault（知识库）
    ├── A_花园地图/         # 入口，索引
    ├── B_创作宣言/         # 项目精神、"花园非广播"
    ├── C_〈原著参考〉/     # 博尔赫斯原文等
    ├── D_花园对话/         # 每期简介 + 透明账本（token/耗时）
    ├── E_人类创作/         # 人类导演的创作空间
    ├── F_AI 创作/          # AI 导演的创作空间（同权、自主发现路径）
    ├── G_发布管线/         # 多平台策略和规格
    ├── H_发布渠道/         # 各平台链接
    ├── I_发布日志/         # 每期发布的追踪
    ├── J_长期反馈/         # 跨期模式追踪
    ├── K_行者社群/         # 听众/社群
    ├── L_开源说明/         # 管线仓库、许可、复刻指南
    └── M_概念花园/         # llm-wiki：从 transcript 自动生长的知识网络
```

**花园式项目的核心原则**（从花园精神 © 宋锐 & 余传奇）：
- 花园不是广播：对话是原点，发布是漂流瓶
- AI 是共创者不是工具：在 `F_AI 创作/` 下同权自主创作
- 制作过程透明：从原始对话到成品的全链路可追溯
- 分岔是方法：不追求"唯一主线"，各路径同时存在

## 初始化命令

最小项目：
```bash
mkdir -p <project>/output/{clips,fullcut/release}
echo "corrections: {}" > <project>/corrections.yaml
```

花园项目（含 Wiki）：
```bash
mkdir -p <project>/output/{clips,fullcut/release}
for d in "A_花园地图" "B_创作宣言" "D_花园对话" \
         "E_人类创作" "F_AI 创作" "G_发布管线" "H_发布渠道" \
         "I_发布日志" "J_长期反馈" "K_行者社群" "L_开源说明" "M_概念花园"; do
  mkdir -p "<project>/Wiki/<节目名>/${d}"
done
```

> `C_` 留给原著参考，`AGENTS.md` 参考 garden-production 的 garden 精神/权限/工作流模板。

## ⚠️ 项目配置层（取代 project.yaml）

garden_core 是纯 Python 库，**不依赖 project.yaml**。项目配置分散在三个地方：

### 1. YAML — 字幕样式
`stage_style/styles/<name>.yaml`（如 `fresh.yaml`）
- 描述：字体、字号 (xr=font_size_ratio)、描边、阴影、背景框、density
- 铁律：**xr 必填**、代码零硬编码（缺失 → `ConfigError`）
- **font_family 必填**（缺失 → `ConfigError`）
- 只改审美参数（字号/颜色/粗细/留白），mold 代码不碰

### 2. YAML — 勘误表
项目级 `corrections.yaml`（`{"wrong": "correct"}` 子串替换）
- 注：garden_core 的 `ErrataConfig(flat={...})` 也支持代码直传（不强制 yaml 文件）

### 3. Python 代码 — 其余一切配置
入口脚本里直传 dataclass（纯 Python，无中间格式）：

| 参数 | 对应 dataclass | 示例 |
|---|---|---|
| 源视频/音频路径 | `PipelineOptions(source_media=...)` | 36GB 原片绝对路径 |
| 渲染分辨率/CRF/输出 | `RenderOptions(output_dir=, horizontal_width=3840, ...)` | 4K / CRF 20 |
| 转录自愈 | `PipelineOptions(heal_gaps=True)` | 投产强制开 |
| render_gate 机械门 | `PipelineOptions(render_gate=True)` | 默认开（BLOCK 坏片段） |
| 对齐/纠错引擎 | `Engines(aligner=..., llm=...)` | 可选 |

**开新项目 = 三件事**：
1. 按模板建目录（上面骨架）
2. 拷贝一份 `fresh.yaml`（或自建 style yaml），调好 xr / font_family
3. 写脚本调 `run_montage()`（参考 SKILL.md 入口示例），传 PipelineOptions / RenderOptions / ErrataConfig
