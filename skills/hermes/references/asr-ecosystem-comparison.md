# ASR 生态对比：Whisper vs FunASR 选型分析

> 2026-06-08 通过 subsai、OpenCut-AI、faster-whisper 等项目的代码研究得出结论。

## 核心发现

**整个开源字幕生态都在用 Whisper 家族，FunASR 是少数派。**

| 工具 | ASR 后端 | 词级时间戳 |
|------|---------|-----------|
| OpenCut-AI | Whisper (faster-whisper) | ✅ 原生 |
| subsai | Whisper (5 种变体) | ✅ 原生 / wav2vec2 |
| auto-subtitle | openai/whisper | ✅ word_timestamps=True |
| faster-auto-subtitle | faster-whisper | ✅ 原生 |
| LTX Desktop | Whisper | ✅ 原生 |
| **我们** | **FunASR Paraformer** | ❌ 需 MMS_FA 后对齐 |

## 为什么都用 Whisper

Whisper 是自回归模型——逐 token 预测，attention 权重天然对应音频帧位置。`word_timestamps=True` 一个参数出词级时间戳。Paraformer 是非自回归——一次前向出整句，快但丢掉了逐 token 的注意力分布。

## 我们的代价

```
主流: faster-whisper → {segments + words} → 字幕 (一步)
我们: FunASR → transcript → MMS_FA → {segments + words} → 字幕 (两步)
                                              ↑ CUDA + 对齐失败
```

MMS_FA 对齐实测：926 段成功 910，16 段时间戳是估算的。

## faster-whisper 性能

- RTX 4060 Ti 16GB: large-v3 ~12x 实时（86 分钟 → ~7 分钟）
- float16 GPU / int8 CPU 自动切换
- 显存 ~2.5GB（int8 量化）
- VAD 过滤内置，减少幻觉

## 已实施方案

新增 `pipeline/transcribe_whisper.py` 作为独立转录通道，不改动现有 FunASR 管线。DeepSeek 纠错层照常运行。输出格式与 FunASR 完全兼容。

**集成状态（2026-06-09）**：
- ✅ 模块可独立运行（CLI + Python API）
- ✅ 输出 `transcript.json` 格式与 FunASR chunked 一致（含 `words` 字段）
- ❌ 未接入 `production_watcher.py` — Watcher 仍然只走 FunASR 路径
- ❌ 未接入 `transcribe_chunked.py` — 分块逻辑未适配 Whisper
- 📋 待 CC brief：将 Whisper 作为 Watcher 的可选转录引擎（`protocol.yaml` 加 `transcriber: whisper|funasr` 开关）

## 参考

- subsai: https://github.com/absadiki/subsai — 5 种 Whisper 后端统一接口
- faster-whisper: https://github.com/SYSTRAN/faster-whisper — CTranslate2 加速
- whisperX: https://github.com/m-bain/whisperX — 70x batch + 说话人分离
- OpenCut-AI: https://github.com/Ekaanth/OpenCut-AI — 完整字幕+编辑管线
