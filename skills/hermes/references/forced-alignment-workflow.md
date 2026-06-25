# 强制对齐：精准字幕时间戳方案

## 问题

ASR 转录的时间戳不可靠：
- **Paraformer 词级输出**：片段太碎（0.4-1.3s），字幕闪现即消失
- **DeepSeek 纠错合并**：chunk 文件时间戳不均匀——早期 chunk 粗（17s 一段），后期 chunk 细（1.3s）
- **手工补丁**：合并短段、拆长段——可以临时修但不可靠，用户评价"太不靠谱了"

## 正确方案：强制对齐 + Windows CUDA

**原理**：你已经知道说了什么（corrections 文字），只需要找到在音频的哪个位置。比 ASR 同时猜文字+猜时间要精准得多。

```
ASR:       音频 → [猜文字 + 猜时间] → 两个都不准
强制对齐:   音频 + 已知文字 → [只猜时间] → 毫秒级精准
```

### 技术栈

- **MMS_FA**（Meta Massively Multilingual Speech - Forced Alignment）：1.18GB 模型
- **GPU**：RTX 4060 Ti 16GB（CUDA），每句 0.5-1s
- **脚本**：`<repo>/.hermes/align_queue/align_watchdog.py`

### 工作流

```
1. 准备 transcript（来自 corrections/chunks，1375 句）
   → 写入 `<project>/transcript_for_alignment.json`
   
2. 创建对齐任务 JSON
   → `<repo>/.hermes/align_queue/task_xxx.json`
   
3. Windows 启动 watchdog
   → `<conda-env>/python.exe align_watchdog.py`
   
4. watchdog 轮询（5s 间隔）→ 发现 pending 任务 → 加载 MMS_FA → 逐句对齐
   → 输出 `<project>/transcript_aligned.json`
   
5. 容器侧监控 cron（每 1 分钟）→ 发现 done → 合并词级时间戳 → 生成最终 transcript.json
```

### 任务 JSON 格式

```json
{
  "id": "12位hash",
  "audio_path": "<project>/podcast.mp4",
  "transcript_path": "<project>/transcript_for_alignment.json",
  "output_path": "<project>/transcript_aligned.json",
  "language": "zho",
  "status": "pending",
  "created_at": "2026-06-04 22:00:00"
}
```

任务文件命名：`task_{id}.json`（必须 `task_` 前缀，watchdog 只扫描这个模式）

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
| MCP 转录 | 词级（太碎） | ASR 原始 | 慢（18 段轮询） | 中 |
| corrections 直接合并 | 不均匀 | DeepSeek 纠错后 | 快 | 低（用户否决） |
| **强制对齐** | **毫秒级** | DeepSeek 纠错后 | **GPU 加速** | **高** |

## 陷阱

- 容器内的 `transcribe_chunked.py` 走 MCP HTTP，速度慢且受限于 Windows 网络
- corrections/chunks 的时间戳不能直接用于字幕——必须经过对齐
- align_watchdog.py 需要 transcript 中 segment 有 `text` 字段
- 对齐失败时，watchdog 将该 segment 的 `words` 设为空数组，不阻塞后续句
