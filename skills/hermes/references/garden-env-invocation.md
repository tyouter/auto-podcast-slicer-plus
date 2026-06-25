# garden conda env 调用诊断 + FunASRLocal 进程内转录验证

跑 garden_core 任何 python 入口（尤其进程内 ASR）的环境约束，以及一次完整的"为什么 import 全炸"诊断。

## 症状

直接 `envs/garden/python.exe -c "import torch"`（git-bash 直调，不 activate）：
```
No module named 'numpy._core._multiarray_umath'
FileNotFoundError: [WinError 206] 文件名或扩展名太长。: '...\conda\envs\garden\Lib\site-packages\torch\lib'
```
base env 同样炸，conda 自己也报 `pydantic_core._pydantic_core` 缺失。三个独立包（numpy C 扩展 / torch DLL / pydantic Rust 扩展）同时加载失败。

## 排除掉的误导假设（别再走这些弯路）

1. **「PATH 超长导致 WinError 206」→ 错**。实测 PATH 只有 2187 字符 64 条目，没满。WinError 206「文件名或扩展名太长」在 `add_dll_directory` 上下文是**误导性错误码**，真实含义是"DLL 搜索目录没设好"，跟长度无关。
2. **「numpy 要降到 1.26.4」（旧 MCP setup bat 干的事）→ 不需要**。实测 numpy 2.4.6 + funasr 1.3.9 兼容，import 正常。
3. **「env 坏了 / 要重装」→ 错**。env 完全好，只是调用方式不对。

## 真因 + 正解

根因：**没 activate / conda 科学栈的 DLL 目录（MKL、CUDA）没进 PATH**。conda env 的 numpy(MKL)/torch(CUDA) 靠 `activate` 把 `Library\bin` 等塞进 PATH 才能加载 C 扩展。

决定性验证 = 子 shell prepend 这些目录后 import 全绿：
```bash
# Linux/macOS:
(
  G="$CONDA_PREFIX"
  export PATH="$G/bin:$PATH"
  cd /path/to/repo
  PYTHONPATH=src python <脚本>
)

# Windows (git-bash):
(
  G="$CONDA_PREFIX"
  export PATH="$G:$G/Library/bin:$G/Library/usr/bin:$G/Library/mingw-w64/bin:$G/Scripts:$G/DLLs:$G/bin:$PATH"
  cd /path/to/repo
  PYTHONPATH=src "$G/python.exe" <脚本>
)
```
结果：`numpy 2.4.6 / torch 2.7.1+cu118 cuda=True RTX 4060 Ti / funasr 1.3.9 / garden_core OK`。

## 两个连带坑

- **terminal export PATH 持久污染**：terminal 工具的 env 跨调用保持。我做"精简 PATH 实验"时 `export PATH=只含garden+System32` 替换掉了 `/usr/bin` → 后续 cat/rm/tail/write_file 全 `command not found`（git-bash 工具都在 /usr/bin）。恢复：`export PATH="/usr/bin:/bin:/usr/local/bin:/mingw64/bin:/c/Windows/System32:/c/Windows:$PATH"`。**预防：改 PATH 一律用子 shell `( )` 隔离，且 prepend 不替换。**
- **ffmpeg 不在默认 PATH**：渲染漏了它报 `ffmpeg binary not found on PATH`，但转录/SRT/ASS 仍能出（不依赖 ffmpeg）。conda `environment.yml` 已包含 ffmpeg；手动安装请确认 `ffmpeg -version` 可用。
- **cmd //c 在 git-bash+MSYS 下不可靠**：`cmd //c file.bat` 参数没传进去，cmd 进交互模式立刻 EOF。多层 activate+python 调用别拼引号，直接子 shell + prepend DLL 目录调 python.exe 最干净（不必经 cmd/activate）。

## FunASRLocal 进程内转录 = MCP 的等价替代（已验证）

`tests/smoke_full_pipeline_local.py` 里的 `FunASRLocal`：`from funasr import AutoModel` 直接在 GPU 加载 Paraformer+VAD+Punc+SPK，进程内转录。端到端实跑：
```
ASR done: 25 segments in 3.0s     # 60s 音频，CUDA，含标点+时间戳+speaker
SRT 1327B + ASS 2218B
render_gate: passed
Horizontal MP4 5.5MB + Vertical MP4 28.2MB
RESULT: PASS — full pipeline (ASR→render) end-to-end
```
模型走 modelscope 共享缓存（`~/.cache/modelscope`，和 MCP server 同款，不重下）。中间 joblib `_count_physical_cores` 的 traceback 是无害 noise（fallback 逻辑核），转录照常完成。

**架构结论**：MCP（`FunASRMCPBackend` + `funasr_backend.py` 手写 `_MCP` + `setup_funasr_mcp.bat` server + 8000 端口）整条可退役。`stage_asr/__init__.py` 文档自承 MCP backend 定位是「容器化部署 / GPU 在专用主机」——正是已消失的 Docker 场景。待 Reasonix 把 `FunASRLocal` 从 test 扶正为 `src/garden_core/stage_asr/funasr_local.py`。

代价（trade-off）：进程内 ASR 要求**调 `run_from_audio` 的进程本身是 garden env python**（带上面那串 DLL+ffmpeg PATH）。建议收进一个 `run_garden` wrapper（封装 activate + ffmpeg PATH），skill/投产命令只调 wrapper。
