# 字幕审计：VAD 交叉比对 + 缺段回填

当用户反馈「字幕不准」「中途跟丢」「时间错乱」时，执行此审计流程。

## Phase 0: 先查 corrections/ 目录 ⚠️

**在重新跑转录之前，先检查 `corrections/chunk_*_corrected.json`。**

DeepSeek 纠错管线产出的 chunk 文件可能已有正确时间戳（`start_ms`/`end_ms`），只是从未回灌到主 `transcript.json`。跳过这一步 = 浪费大量时间在零时间戳 transcript 上反复排查。

```python
import glob, json
chunks = sorted(glob.glob("corrections/chunk_*_corrected.json"))
if chunks:
    # 合并为完整 transcript
    all_segs = []
    for f in chunks:
        with open(f) as fp:
            data = json.load(fp)
        for s in data['segments']:
            all_segs.append({
                'start': s['start_ms'] / 1000,
                'end': s['end_ms'] / 1000,
                'text': s['text']
            })
    # 块间应零间隙。如果发现 >3s 间隙 → 有跟丢区域
```

**已验证案例**：86 分钟播客 → 19 个 chunk_corrected 文件 → 1375 段，时间戳 0-5168s，块间零间隙。而主 `transcript.json` 全为零时间戳。直接合并 chunk 文件比重新转录快一个量级。

## 工作流

### Phase 1: 时间戳健康检查

```python
import json
with open("transcript.json") as f:
    t = json.load(f)
segs = t['segments']

# 1. 零时间戳检测
zero_count = sum(1 for s in segs if s['start'] == 0 and s['end'] == 0)
# 如果 zero_count == len(segs) → 转录管线丢了时间戳，需要重录

# 2. 段间大间隙（>10s）
for i in range(len(segs)-1):
    gap = segs[i+1]['start'] - segs[i]['end']
    if gap > 10:
        print(f"⚠️ {gap:.0f}s gap at {segs[i]['end']:.0f}s")
```

### Phase 2: VAD 语音段 ↔ 字幕段交叉比对

用 FunASR MCP VAD 获取所有语音段时间戳，与字幕段对比：

1. 跑 VAD：`mcp_funasr_get_voice_activity_segments(audio_path=...)`
2. 提取语音段 `[start_ms, end_ms]` 列表
3. 对每个 VAD 段，检查是否有字幕段覆盖：

```python
vad_segs = [(s/1000, e/1000) for s, e in vad_raw]  # ms → s
uncovered = []
for vs, ve in vad_segs:
    overlaps = [s for s in sub_segs if s['start'] < ve and s['end'] > vs]
    if not overlaps:
        uncovered.append((vs, ve))
```

4. 报告：未覆盖段（VAD 说有人说话但字幕为空）+ 弱覆盖段（边缘缺口>1s）

### Phase 3: 缺段回填

对每个未覆盖区域：

1. 提取缺口音频：`ffmpeg -ss {start} -t {duration} -i source.mp4 -vn -acodec libmp3lame audio/gap_{id}.mp3`
2. 送 MCP 重转录：`mcp_funasr_start_speech_transcription(audio_path=windows_path)`
3. 取结果：`mcp_funasr_get_transcription_result(task_id)`
4. 时间戳偏移：相对时间 + 缺口起始 = 绝对时间
5. 插入 transcript：保留缺口前的段 → 插入新段 → 保留缺口后的段
6. 验证连续性：确认无 >2s 间隙

### Phase 4: 前 N 分钟重新录

如果用户报告某段时间质量差（如「前 10 分钟很差」）：

1. 提取该段音频
2. MCP 重转录（`sentence_info` 带时间戳）
3. 删除原 transcript 该时段所有段
4. 插入新段
5. 验证接口处零间隙

## 前置条件

- FunASR MCP Server 在 Windows 端运行（CUDA）
- 音频文件路径用 Windows 格式（如 `D:\Hermes\projects\...\audio.mp3`）
- MCP VAD 只接受 MP3/WAV，不接受 MP4

## 常见陷阱

- **MCP transcription 可能不返回时间戳**：检查 `result[0]` 是否有 `sentence_info` 字段。只有带 `sentence_info` 的才有逐句时间戳。无时间戳版本只能作文本参考。
- **chunk_corrected 文件可能已有时间戳**：先检查 `corrections/chunk_*_corrected.json`，这些是 DeepSeek 纠错后的产物，可能已有 `start_ms`/`end_ms`。
- **VAD 是 ms，transcript 是 s**：合并时注意单位转换。
- **偏移计算**：MCP 转录的时间戳是相对于提取的音频片段的，需要加偏移量得到绝对时间。
