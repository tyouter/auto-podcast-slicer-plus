# 强制对齐：精准字幕时间戳方案

## 问题

ASR 转录的时间戳不可靠：
- **Paraformer 词级输出**：片段太碎（0.4-1.3s），字幕闪现即消失
- **DeepSeek 纠错合并**：chunk 文件时间戳不均匀——早期 chunk 粗（17s 一段），后期 chunk 细（1.3s）
- **手工补丁**：合并短段、拆长段——可以临时修但不可靠，用户评价"太不靠谱了"

## 正确方案：强制对齐（CUDA 加速）

**原理**：你已经知道说了什么（corrections 文字），只需要找到在音频的哪个位置。比 ASR 同时猜文字+猜时间要精准得多。

```
ASR:       音频 → [猜文字 + 猜时间] → 两个都不准
强制对齐:   音频 + 已知文字 → [只猜时间] → 毫秒级精准
```

### 技术栈

- **MMS_FA**（Meta Massively Multilingual Speech - Forced Alignment）：1.18GB 模型
- **GPU**：CUDA 显卡（如 16GB 显存），每句约 0.5-1s
- **接口**：garden_core 的 `align()` API（`garden_core.stage_align`）

### 工作流

强制对齐通过 garden_core 的 `align()` 一步完成——传入已知文字的 transcript、对齐器和音频路径，直接返回带词级时间戳的 transcript：

```python
from garden_core.stage_align import align
from garden_core.stage_align.mms_aligner import MMSAligner

# t 是带 text 字段的 transcript；audio_path 指向音频文件
t = align(t, MMSAligner(device='cuda'), audio_path)
# t 现在带有逐句/逐词的精准时间戳
```

要点：

1. 准备 transcript（来自 corrections/chunks），每个 segment 必须有 `text` 字段
2. 对齐前先做已知勘误替换（见下文「对齐前勘误」）——文字定型后再对齐
3. 调 `align()` → 加载 MMS_FA → 逐句对齐 → 得到词级时间戳
4. 对齐后处理：把词级时间戳合并为可读字幕段（见下文「对齐后处理」）

### 对齐前勘误（💡 生产教训）

在提交对齐任务之前，先对 transcript 文字做已知勘误替换。对齐是"已知文字→找时间"，如果文字本身有错，对齐会精确地把错误文字对到正确时间——等于把错误锁死了。

```python
# 对齐前替换
text = text.replace('分叉', '分岔')
```

常见勘误来源：
- ASR 同音错误（分叉/分岔、传奇/传奇）
- DeepSeek 纠错未覆盖的残余错误
- 项目级 corrections.yaml 中的规则

对齐后再改文字 = 时间戳和文字脱节，需要重新对齐。

### 对齐后处理

对齐输出为词级时间戳，需合并为可读字幕段：

1. 按 。！？ 断句
2. 合并相邻短句（间隙 < 0.4s，总长 < 5.5s）
3. 拆分超长句（> 7s 且无句号可拆的，按时间均分）
4. 勘误替换（如"分叉→分岔"）
5. 保存 `transcript.json` 到 production 目录

## 对比

| 方案 | 时间戳精度 | 文字质量 | 速度 | 可靠性 |
|------|-----------|---------|------|--------|
| ASR 词级输出 | 词级（太碎） | ASR 原始 | 慢 | 中 |
| corrections 直接合并 | 不均匀 | DeepSeek 纠错后 | 快 | 低（用户否决） |
| **强制对齐** | **毫秒级** | DeepSeek 纠错后 | **GPU 加速** | **高** |

## 陷阱

- corrections/chunks 的时间戳不能直接用于字幕——必须经过对齐
- `align()` 要求 transcript 中每个 segment 都有 `text` 字段
- 对齐失败时，应将该 segment 的 `words` 设为空数组，不阻塞后续句
