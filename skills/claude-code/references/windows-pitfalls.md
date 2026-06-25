# Windows PowerShell 环境变量陷阱

`set VAR=value` 是 cmd 语法，PowerShell 里**不报错也不生效**。程序启动后 `Root:` 显示错误路径就是这个原因。

```powershell
# ❌ 无效（PowerShell 中静默失败）
set PROJECTS_ROOT=D:\path\to\projects

# ✅ 正确
$env:PROJECTS_ROOT = "D:\path\to\projects"
```

永久方案：写入 `.bat` 启动脚本，用 `SET VAR=value`（cmd 语法在 .bat 中有效）。

## transcribe_chunked 音频分段 WAV→MP3 失败

`-c copy` 从 WAV (pcm_s16le) 到 MP3 容器不可行——codec 不兼容。同格式（WAV→WAV）`-c copy` 可以。

```python
# ❌ 错误
str(chunks_dir / "chunk_%03d.mp3")
chunks = sorted(chunks_dir.glob("chunk_*.mp3"))

# ✅ 正确
str(chunks_dir / "chunk_%03d.wav")
chunks = sorted(chunks_dir.glob("chunk_*.wav"))
```
