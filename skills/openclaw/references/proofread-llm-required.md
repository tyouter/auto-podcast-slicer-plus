# Proofread LLM 强制配置

## 问题

`stage_proofread.proofread()` 的 `ProofOptions` 默认 `enable_llm=False`。只传 `ProofOptions()` 或 `ProofOptions(enable_normalize=True)` → LLM 纠错层静默跳过，transcript 带着 ASR 错误进渲染。

## 症状

- `corrections_applied: ()` — 空元组
- normalize/phonetic 层可能也跑空（ASR 输出已是简体+同音字不在规则内）
- 肉眼可见的 ASR 错误未修正

## 正确调用

```python
from garden_core.stage_proofread import proofread, ProofOptions, ErrataConfig
from garden_core.infra.llm_client import LLMClient

# Step 1: Inject API key（garden conda env 默认没有）
import os
_env_path = ".env"  # 项目根的 .env
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.startswith("DEEPSEEK_API_KEY="):
                os.environ["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip()
                break

# Step 2: Create LLM client
llm = LLMClient(default_model="deepseek-chat")

# Step 3: ProofOptions with ALL layers enabled
opts = ProofOptions(
    enable_normalize=True,     # 繁→简
    enable_errata=True,        # 勘误表
    enable_phonetic=True,      # 同音字修复
    enable_llm=True,           # ← 关键：默认 False，必须显式开
    enable_dual_channel=True,  # 音频+文本双重校对
)

# Step 4: Run proofread
t = proofread(t, errata=ErrataConfig.empty(), llm=llm, opts=opts, audio_path=AUDIO)
```

## 执行顺序

`proofread` 内部按固定顺序执行：normalize → errata → phonetic → llm → dual_channel。各层独立返回修改计数，最终汇总到 `corrections_applied` 元组。

## LLMClient

- 默认 base_url: `https://api.deepseek.com/v1`
- 默认 model: `deepseek-chat`
- `api_key=None` 时自动读 `os.environ["DEEPSEEK_API_KEY"]`
- `available` property 检查 `bool(self.api_key)`

⚠️ **超时陷阱**：默认 `timeout=30.0`，重试 2 次（指数退避：1s→2s→放弃）。`llm_correct_segments()` 把**全部 segments 一次塞进一个 API 调用**，不拆分。实测数据：

| segments | 表现 |
|---|---|
| ≤100 | 30s 内完成 |
| ~200 | 有可能超时 |
| 789 | 3 次重试全超时 → DEGRADED → 静默跳过 |

**投产必须 `timeout=300.0`**（5 分钟）。789 segments 实测 ~90s 完成：

```python
llm = LLMClient(default_model="deepseek-chat", timeout=300.0)
```

## 陷阱

- garden conda env 只提供 PATH/PYTHONPATH，不注入任何 API key。必须脚本内显式注入。
- `enable_llm=True` 但 `llm=None` → `NoLLMClient()` 兜底，`available=False`，静默跳过。
- 789 segments 的 LLM 调用可能超 30s，需 `timeout=300.0`（见上方超时陷阱）。

## errata 迭代工作流

LLM 纠错后仍有残留 ASR 错误（本次 Tesla 项目：70 处修正后仍有 8 处）。步骤：

1. **跑完 proofread → 肉眼扫 transcript**  
   重点关注品牌名、专有名词、口音重的段落。

2. **写 errata 到代码而非 yaml**  
   `ErrataConfig(flat={"途材": "FSD", "逗哈": "都行", ...})` —— garden_core 的 errata 是**子串替换**，不需要精确匹配整句。⚠️ 避免太短的字串（如 `"丑闻": "它"` 可能误伤正常文本）。

3. **重新跑 proofread**  
   errata 层先于 LLM 层执行 → 修复后的文本再送 LLM → LLM 可能发现新的错误。

4. **循环到 ALL CLEAN**  
   本次实际：第一轮 5 条 errata → 修了 5 处，发现剩余 4 处 → 第二轮 4 条 errata → 全清。两轮共 9 条 errata。
