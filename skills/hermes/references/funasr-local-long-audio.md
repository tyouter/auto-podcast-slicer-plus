# FunASRLocal 长音频转录（VAD 分块防 OOM）

## 原则（用户铁律）

长音频转录的 **OOM 防护是 garden_core 代码层的职责**——分块 + 显存释放内建在 `FunASRLocal` 里，**不靠 Hermes 跑时盯着、OOM 了再补救**。用户原话：「应该是代码来保证不 OOM，而不是你跟着」。这是「发现反复出错就代码化、别手动盯」原则在转录上的落地。

## 为什么需要

`FunASRLocal.transcribe()` 早期版本一次性把整段音频喂 `AutoModel.generate(input=audio.path)`，靠 `batch_size_s` 内部分批。60 秒 smoke 没事，但长音频（如 86 分钟播客）会重演 MCP 时代的坑：**约 8 个 5 分钟块后 CUDA 显存累积泄漏 → `CUDA error: unknown error` / OOM**。

## 设计（commit 后的 funasr_local.py，已验证）

VAD 驱动的**静音对齐外部切块**，四步：
1. **VAD 规划切点**：懒加载一个 vad-only `AutoModel`，对整段跑一次（轻量单次 forward），拿语音段 `[[start_ms,end_ms],…]`。
2. **静音对齐分块**（`_plan_chunks`）：把语音段贪心聚合成 ~`chunk_target_s`（默认 300s）的块，**块边界一律落在语音段之间的静音里** → 句子永不被切断（不丢句/不重句）。这比当年 transcribe_chunked 的固定 5min 切块更聪明（固定切块会切在句中）。
3. **逐块转 + 块间释放显存**：`soundfile` 读 16k 单声道 numpy，按块切片喂主模型；每块后 `del + gc.collect() + torch.cuda.empty_cache() + cooldown` → 根治累积泄漏。
4. **时间戳偏移合并**（`_build_segments(offset_s=cs)`）：每块 ms 时间戳加块起始秒，绝对时间贯穿到片尾。

对外 `transcribe(audio, hotwords) -> Transcript` 接口、4 个模型 id 不变。

## 验证（86min 实跑）

`C0257_mixed_normalized.wav`（86min）：17 块全跑通，**无 OOM/unknown error**；2019 segments；末段 end_s=5168.15s / 音频 5168.16s；时间戳单调；首尾带标点；speaker 有值。

## ⚠️ Tradeoff：speaker 跨块只块内一致

cam++ 在**每块独立聚类**，块5 的 `"0"` 不保证等于块3 的 `"0"`（只有整段单次 generate 才全局一致）。

- **对「按内容剪」无影响**（去废料 / 混剪 / 高光——靠文字内容判断，不靠说话人；fresh/cinematic 字幕只显示文字、不显示说话人名）→ 接受现状。
- **若要 speaker 全局一致**（按说话人剪、字幕标说话人）：需跨块携带 embedding 重聚类，是独立的后续任务，当前未做。
