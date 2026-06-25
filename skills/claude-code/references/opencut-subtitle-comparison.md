# OpenCut-AI 字幕系统逆向分析（2026-06-08）

## 核心发现

OpenCut-AI 的字幕系统是 Whisper 生态的标准实现范式。架构清晰分层，与我们的 FunASR 路线形成对比。

## 架构

```
Whisper Service (微服务，FastAPI)
  POST /transcribe → Whisper 模型 → {segments[{start, end, text, words[{word, start, end}]}]}
  ↓
Speaker Service (微服务)
  说话人分离 → 每 segment 标注 speaker 标签 + 颜色编码
  ↓
Subtitle Service (本地，无重量依赖)
  segments → _split_text() 智能断行（42字符，词边界）→ SRT/VTT/ASS
  ASS 默认: Arial 20px 白字黑边，底部居中
  ↓
前端 Canvas 渲染 (Next.js)
  三种样式: karaoke / pill / classic
  说话人颜色编码
  Edit-by-text: 删文字 → 自动切 timeline
```

## 与我们对比

| 维度 | OpenCut-AI | 我们 |
|------|-----------|------|
| ASR | Whisper（词级时间戳原生） | FunASR + MMS_FA 后对齐 |
| 步骤数 | 1步 | 2步（多一步对齐，CUDA 依赖） |
| 断行 | _split_text() 42字符词边界 | subtitle_formatter 禁则+行长 |
| 字幕格式 | SRT/VTT/ASS，Arial 白字黑边 | ASS + Mold 体系，cinematic 电影级 |
| 说话人 | 自动分离+颜色编码 | transcript 有 speaker 但字幕不用 |
| 样式 | 3种预设 | 6种 mold + autoresearch 优化 |
| 交互 | Edit-by-text | ❌ 无 |
| 封装 | 微服务 + FastAPI | Python CLI 单体 |

## 我们的独特优势

- **DeepSeek 纠错**：中文播客场景净正向（OpenCut 完全无纠错层）
- **Mold 字幕体系**：跨分辨率适配，cinematic 电影级输出
- **checker+healer 自愈**：VAD gap 检测 + 自动补转录
- **花园哲学**：AI 同权共创者

## 我们的劣势

- **词级时间戳依赖 MMS_FA**：多一步，有 ~1.7% 失败率，CUDA 依赖
- **无交互编辑**：clips.yaml 手写时间戳，没有 Edit-by-text
- **无说话人显示**：字幕不区分说话人

## 关键代码片段

### Subtitle Service (subtitle_service.py)
```python
def _split_text(text: str, max_chars: int) -> list[str]:
    """按词边界拆分，尊重 max_chars"""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}".strip() if current_line else word
        if len(candidate) <= max_chars:
            current_line = candidate
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

def segments_to_ass(segments, style=None):
    """默认 Arial 20px 白字黑边，PlayResX=1920"""
    s = style or {}
    font_name = s.get("font_name", "Arial")
    font_size = s.get("font_size", 20)
    primary_color = s.get("primary_color", "&H00FFFFFF")
    outline_color = s.get("outline_color", "&H00000000")
    # ...
```

### Transcription API (transcribe.py)
```python
@router.post("/transcribe")
async def transcribe(file: UploadFile, language: str = None):
    """代理到 whisper-service，返回 segments + word-level timestamps"""
    resp = await _proxy_file_upload(
        settings.WHISPER_SERVICE_URL, "/transcribe", file, ...
    )
    return resp.json()
```

## 来源

- OpenCut-AI GitHub: https://github.com/Ekaanth/OpenCut-AI
- 核心文件: `services/ai-backend/app/services/subtitle_service.py`
- 核心文件: `services/ai-backend/app/routes/transcribe.py`
