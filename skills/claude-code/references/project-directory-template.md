# 项目目录模板

`create_project()` 生成的目录结构。

## 最小骨架（默认）

```
<root>/
├── source/                # 源素材（视频/音频）
├── output/
│   ├── clips/             # 独立切片
│   ├── fullcut/           # 整期精剪/混剪
│   └── release/           # 最终交付成品
├── project.yaml           # 项目配置（唯一入口）
├── corrections.yaml       # 勘误表
├── AGENTS.md              # Agent 行为约束
└── README.md              # 项目简介
```

- 源视频用绝对路径，不拷进 `source/`
- 渲染走本地 SSD（`output/`），完成后传 NAS

## 带 Wiki（`wiki=True`）

开启后额外生成 Obsidian vault，用于深度对话项目的知识管理。

```
<root>/
├── ...                    # 同上骨架
└── Wiki/<name>/           # Obsidian vault
    ├── A_花园地图/        # 入口、全站导航
    ├── B_创作宣言/        # 项目精神、创作原则
    ├── D_花园对话/        # 每期简介 + 制作账本
    ├── E_人类创作/        # 人类导演独立空间
    ├── F_AI 创作/         # AI 导演独立空间（同权、自主发现路径）
    ├── G_发布管线/        # 多平台策略与规格
    ├── I_发布日志/        # 按日期记录发布
    ├── J_长期反馈/        # 跨期模式追踪
    ├── L_开源说明/        # 管线仓库、复刻指南
    └── M_概念花园/        # llm-wiki：从 transcript 自动生长
```

默认 `wiki=False`（最小骨架），`wiki=True` 打开。
