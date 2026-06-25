# VAD 交叉验证字幕覆盖

通过 VAD（Voice Activity Detection）获取音频中所有语音段时间戳，与字幕 transcript 交叉比对，自动发现：
- 有语音但无字幕的「跟丢」缺口
- 字幕时间戳与实际语音的偏移
- 字幕覆盖弱（部分覆盖）的区域

## 使用场景

- 用户反馈「字幕时间不对」「有跟丢」「前 10 分钟很差」
- 新转录完成后做质量验证
- 纠错/合并 transcript 后确认完整性

## 步骤

### 1. VAD 获取全量语音段

```python
# 用 FunASR 做 VAD，得到全量语音段（返回 ms 区间列表）
vad_result = run_funasr_vad(audio_path="<project>/full_audio.mp3")  # 示意：FunASR VAD 能力
vad_segments = [(s/1000, e/1000) for s, e in vad_result['segments']]  # ms → s
```

VAD 模型：`iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`，48kHz 采样率。

### 2. 加载已校准 transcript

⚠️ **先检查 `corrections/chunk_*_corrected.json`**——主 `transcript.json` 可能时间戳全为零。

```python
import json, glob

all_segs = []
for f in sorted(glob.glob("corrections/chunk_*_corrected.json")):
    with open(f) as fp:
        data = json.load(fp)
    for s in data['segments']:
        all_segs.append({
            'start': s['start_ms'] / 1000,
            'end': s['end_ms'] / 1000,
            'text': s['text']
        })
```

### 3. 交叉比对

```python
uncovered = []
weak = []

for vs, ve in vad_segments:
    overlaps = [s for s in all_segs if s['start'] < ve and s['end'] > vs]
    
    if not overlaps:
        uncovered.append((vs, ve))
    else:
        cov_start = min(s['start'] for s in overlaps)
        cov_end = max(s['end'] for s in overlaps)
        gap_before = cov_start - vs
        gap_after = ve - cov_end
        if gap_before > 1 or gap_after > 1:
            weak.append({'vad': (vs, ve), 'coverage': (cov_start, cov_end),
                         'gap_before': gap_before, 'gap_after': gap_after})
```

### 4. 解读结果

| 发现 | 含义 | 处理 |
|------|------|------|
| `uncovered` 非空 | VAD 检测到语音但字幕完全缺失 | 提取该段音频 → 重转录 → 插入 transcript |
| `weak` 非空 | 字幕有覆盖但首尾有 >1s 缺口 | 轻微偏移，调整字幕时间戳 |
| 前 10 分钟片段数异常 | 可能转录质量差 | 重转录前 10 分钟并用 DeepSeek 纠错 |

### 5. 缺口修复：提取 → 重转录 → 偏移合并

```python
# 对每个 uncovered 区域
OFFSET = uncovered_start  # 如 2421.0

# 1. ffmpeg 提取缺口音频
ffmpeg -y -ss {OFFSET} -t {duration} -i source.mp4 -vn \
  -acodec libmp3lame -q:a 2 gap_audio.mp3

# 2. 用 FunASR 重转录缺口音频
result = run_funasr_transcribe(audio_path="<project>/gap_audio.mp3")  # 示意：FunASR 重转录能力

# 3. 获取 sentence_info，偏移时间戳
for s in result['sentence_info']:
    new_segs.append({
        'start': OFFSET + s['start'] / 1000,
        'end': OFFSET + s['end'] / 1000,
        'text': s['text']
    })

# 4. 合并：保留缺口前的段 + 新段 + 缺口后的段
keep_before = [s for s in old_segs if s['end'] <= OFFSET]  # 含边界
keep_after  = [s for s in old_segs if s['start'] >= resume_point]
final = keep_before + new_gap_segs + keep_after
```

⚠️ 合并时注意：`keep_before` 用 `end <= OFFSET`（保留等于边界值的最后一段），`keep_after` 用 `start >= resume_point`。误删边界段会产生新的伪缺口。

### 6. 前 N 分钟质量重建

VAD 覆盖检查只能发现「有无字幕」的缺口，无法发现「字幕有但内容错误」的质量问题。用户反馈「前 10 分钟很差」时：

```python
# 1. 提取前 N 分钟音频
ffmpeg -y -ss 0 -t 600 -i source.mp4 -vn \
  -acodec libmp3lame -q:a 2 first_Nmin.mp3

# 2. 用 FunASR 重转录（Paraformer-large）
result = run_funasr_transcribe(audio_path="<project>/first_Nmin.mp3")  # 示意：FunASR 重转录能力

# 3. 用 sentence_info 的 timestamp 完全替换该区间
new_Nmin = [{'start': s['start']/1000, 'end': s['end']/1000, 
             'text': s['text']} for s in result['sentence_info']]
keep_after = [s for s in old_segs if s['start'] >= N]
final = new_Nmin + keep_after
```

质量对比（小径分岔 EP01 前 10 分钟）：
- 旧版："抱起来了"（误）→ 新版："报喜了"（正）
- 旧版："代表自然了"（误）→ 新版："白头的是代表智慧"（正）

### 7. 数据源优先级

| 文件 | 时间戳 | 文本质量 | 用途 |
|------|--------|----------|------|
| `corrections/chunk_*_corrected.json` | ✅ ms 级 | ✅ DeepSeek 纠错后 | **首选源** |
| FunASR `sentence_info` | ✅ ms 级 | ⚠️ 粗胚 | 缺口回填 |
| `transcript.json` | ❌ 常为 0 | ❌ 未纠错 | 仅作参考 |
| `transcript_aligned.json` | ❌ 常为 0 | ❌ | 不可用 |

## 已验证案例

**小径分岔的花园 EP01（86 分钟）**：
- VAD 段：619 个，校准 transcript：1375 段
- 🔴 缺口：5 段（2421-2468s，45.5 秒）→ 「灵魂与成功」段落完全缺失
  - **修复**：提取 50s 音频 → FunASR 重转录 → 合并入 13 句 → 续接处零断点
- 🟡 前 10 分钟：重转录 254 句替换，修正残余语音错误
- 📐 最终：1383 段，0~5168s 完整覆盖，零断点

**根因**：DeepSeek 纠错管线在 chunk 09/10 边界跳过 45s 内容（分割点切在连续对话中）。前 10 分钟的 Paraformer 粗胚未经 DeepSeek 纠错，残余 ASR 幻觉。
