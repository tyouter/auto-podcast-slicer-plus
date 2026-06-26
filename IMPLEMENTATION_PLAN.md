# 实施推进计划

> 范围：把 `DEVELOPMENT_PLAN.md`（T1-T13，Ray 已认可，D1-D6 全部已定）落到**串行闭环执行节奏**上。
> 本文件不含代码，只定义推进顺序、每个任务的闭环步骤、风险标注。
> 执行铁律：单任务严格串行，**绝不并行**——多任务同时改代码库会冲突（如 T2/T4 都改 `pipeline.py`；T4 breaking 改 `CutPoint` 影响全局构造点）。
> T1 已由 Reasonix 完成并验收通过，本计划从 **T2** 起排。

---

## 1. 串行推进序列

### 第一层（剩余 5 个，小改 API，互相独立但本计划强制串行）

```
T2  Engines.from_env()                  [P0] 无依赖        (改 pipeline.py)
T3  render_gate.audit_dir()             [P0] 无依赖        (改 stage_render/render_gate.py + 删 tesla_audit.py)
T4  CutPoint.source_media 必填          [P0] ⚠️ breaking  (改 types.py + stage_cut + pipeline.py + 全仓构造点迁移)
T5  RenderOptions.skip_existing         [P1] 无依赖        (改 stage_render/__init__.py)
T6  step API 命名 + 文档化              [P2] 依赖 T1(已完成)
```

### 第二层（项目管理系统，硬串行）

```
T7  project.yaml schema + ProjectConfig + 校验    [P1] 无依赖
T8  create_project（建目录 + 生成 project.yaml）  [P1] 依赖 T7
T9  load_project（project.yaml / 目录 → ProjectConfig）  [P1] 依赖 T7
T10 项目修改 + 配置管理（CRUD + 重校验 + 持久化）  [P1] 依赖 T7 + T9
T11 ProjectRun + run_manifest.json（schema_version）  [P1] 依赖 T1/T2/T3/T4/T5/T7/T9
T12 run.rerender / run.reproofread（标准重跑入口）  [P2] 依赖 T11
T13 SKILL.md「投产标准流程」改写                    [P2] 依赖 T11 + T12
```

**串行依赖链（精简）**

```
T2 → T3 → T4 → T5 → T6
                                   ┌─→ T8
T7 ─┼─→ T9 ─→ T10
                                   └──────────→ T11 ─→ T12 ─→ T13
(T1 已完成，是 T6/T11 的前置)
```

- T8 / T9 在 T7 之后，理论上可并行，但**本计划仍按 T8 → T9 串行**，避免 RX 在同一 `project/` 包目录下并发创建文件冲突。
- T11 是第二层的汇聚点，吃掉 T1-T5 + T7 + T9 全部产出；它之前必须把第一层全部落地。
- T13 是纯文档，见下方「风险标注」——可能由 Hermes 直接做，不走 RX 闭环。

---

## 2. 每个任务的闭环步骤（①-⑦）

每个任务必须走完一整圈才进下一个，**中途不开下一个任务的 brief**：

| 步 | 角色 | 动作 | 产物 |
|----|------|------|------|
| ① | GLM（脑） | 基于对应 plan 节出一份 RX 执行 brief | `D:\Hermes\scripts\briefs\rx_T{n}.md` |
| ② | Hermes | 读 brief + 把关（范围/验收/AGENTS 合规） | 通过 / 打回 GLM 修订 |
| ③ | Ray | 看一眼 brief（可选一秒过） | OK |
| ④ | Hermes | 下发给 rx（带 brief 路径） | rx 执行 |
| ⑤ | Hermes | 验证（跑 `pytest tests/` 不回归 + plan 验收项 + 三入口冒烟） | 通过 / 打回 rx 修 |
| ⑥ | GLM（脑） | 审核产物（对照 plan 验收 + breaking 迁移完整性，如 T4） | 通过 / 打回 |
| ⑦ | GLM（脑） | 出下一份 brief（跳回 ①，n+1） | `rx_T{n+1}.md` |

**节奏约束**

- ①-⑦ 全部走完且绿灯，才允许开 T{n+1} 的 ①。
- 任一步打回，则在**当前任务**内循环，不切任务。
- breaking 任务（T4）⑥要额外做「全仓无残留旧式构造」的 grep 复核。

---

## 3. 风险标注（哪些任务要特别当心）

| 任务 | 风险等级 | 风险点 | 处置 |
|------|----------|--------|------|
| **T2** | 低 | 纯新增 classmethod，D3 已定（env_path 调用方传）。注意 `transcriber/aligner` 不在 from_env 里默认构造（重对象）。 | 正常走闭环。 |
| **T3** | 低-中 | 纯新增，但范围含「删除 `tesla_audit.py`」这一独立验收项；ffprobe 缺失需兜底为 `skipped` 不 BLOCK。 | 删 `tesla_audit.py` 作为 ⑤验收的显式条目；mock ffprobe 跑单测。 |
| **T4** | ⚠️ **高（breaking）** | `CutPoint.source_media` 改必填，迁移全仓所有 `CutPoint(...)` 构造点（scripts/tests/SKILL/references）。**一次 RX 执行内必须完成「改字段 + 迁移所有构造点 + 更新测试」三件事，否则仓库进入不可运行状态。** | ④要求 rx **先 grep 出全部构造点清单**贴出来，再逐个改；⑥GLM 复核 `grep -rn "CutPoint("` 为空残留；⑤跑全量回归 + `run_from_transcript` 单源冒烟。 |
| **T5** | 低 | 默认 False 无破坏；只做朴素文件存在性跳过，参数哈希留 T11。 | 正常走闭环。 |
| **T6** | 低 | 纯文档 + re-export，依赖 T1（已完成）。 | 正常走闭环。 |
| **T7** | 中 | 新模块但形状定全局（T8-T11 全靠它）；schema 一次定错后面连锁。 | ①brief 要把 schema 字段表列清；⑥GLM 重点核 `validate()` 的 4 类非法场景。 |
| **T8** | 低 | 新模块；不拷源素材（绝对路径引用，模板铁律）。 | 正常走闭环。 |
| **T9** | 低 | 新模块；errata 合并策略二选一要 brief 里定死。 | 正常走闭环。 |
| **T10** | 低-中 | frozen + 返回新实例；`remove_source` 被引用时的 force 策略要明确。 | ①brief 锁定 force 默认值（默认禁止删被引用 source）。 |
| **T11** | 中 | 汇聚层，吃掉 T1-T5+T7+T9；不动现有三入口是硬约束；多源翻译 + manifest schema_version 是核心。 | ①brief 明确「不改 run_from_*/run_montage」；⑥重点核多源翻译与 resume 行为。 |
| **T12** | 低 | 建立在 T11 之上。 | 正常走闭环。 |
| **T13** | 低（文档） | 纯文档，但**可能由 Hermes 直接做**（见下方注）。 | 见下。 |

### 关于 T13（文档类）的处置

T13 是 `SKILL.md` + `references/` 改写，**无代码改动**。两种处置，由 Hermes 在 T12 验收后拍板：

- **A（推荐）**：仍走 RX 闭环（①-⑦），但 brief 由 GLM 出，保证文档与 T11/T12 API 一致性有人逐字校对。
- **B**：Hermes 直接手工改（对照 T11/T12 落地后的真实 API），跳过 ①-④，只走 ⑤（人工 review）+ ⑥（GLM 审一致性）。

无论 A/B，T13 **必须在 T11/T12 合并之后**才能改，否则文档与 API 错位。

---

## 4. 全局回归基线（每个任务 ⑤都要跑）

无论哪个任务，Hermes 验证（⑤）的统一基线：

1. **`pytest tests/` 全绿**，命令：
   ```
   cd D:\Hermes\projects\auto-podcast-slicer-plus
   set PYTHONPATH=src
   C:\Users\10903\anaconda3\python.exe -m pytest tests/ -q
   ```
   （用 base python，**不**用 garden env——plan 自测只验逻辑层。）
2. **三入口不回归**：`run_from_audio` / `run_from_transcript` / `run_montage` 行为不变（用 `tests/smoke_*` 里最小的一个冒烟）。
3. **T4 额外**：`grep -rn "CutPoint(" src scripts tests skills` 确认无旧式省略 source_media 的残留 + 单源场景产物不变。

---

## 5. 当前进度

- [x] T1 save_transcript_json（已完成验收）
- [ ] T2 Engines.from_env() ← **下一个，brief 已出：`D:\Hermes\scripts\briefs\rx_T2.md`**
- [ ] T3 / T4 / T5 / T6
- [ ] T7 / T8 / T9 / T10 / T11 / T12 / T13
