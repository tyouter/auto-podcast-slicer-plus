# 字幕可读性、字体许可与烧帧调参

来源：2026-06-22 从 cinematic 演化出 fresh（清新黑体）风格的实战。

## 1. 可读性根因：字体字重 > 描边

字幕「看不清」的第一诊断方向是**字体族/字重**，不是描边。

- **宋体（Serif，如 Noto Serif SC）** 基因是「横细竖粗」，横画细如发丝。无背景框时横画一糊就看不清。
- 此时加黑描边 = 用黑边补字体的瘦。**与「清新 / 干净 / 增大白色区域」直接矛盾**：描边越粗，画面黑色越多，纯白字芯占比反而越小。
- **正解：换笔画饱满的黑体（Sans，如 Noto Sans SC Medium/Bold）。** 黑体横竖一样粗，字芯自己够白够饱满，描边只需留极细一根（@4K ≈1.5–2.8px）做亮背景保命边，甚至可去阴影。

「增大白色区域」最自然的实现 = 弱化描边让黑边吃掉的字缘变少 + 用饱满黑体让字芯本身变粗，**不是**给字加 bold（bold 会让字变重，反而不清新）。

判断顺序：可读性差 → ①字体族是不是宋体？换黑体 → ②字重够不够？Regular→Medium→Bold → ③才考虑描边/阴影微调。

## 2. 字体商用许可（Windows 系统现成字体）

| 字体 | 类型 | 许可 | 商用 |
|---|---|---|---|
| Noto Serif SC / Noto Sans SC / Noto Sans SC Medium | 思源宋/黑 | SIL OFL 1.1 | ✅ 完全免费商用 |
| Source Han Serif/Sans（思源系列各字重，如 Heavy） | 思源 | SIL OFL 1.1 | ✅ |
| 微软雅黑 Microsoft YaHei (msyh.ttc) | 黑体 | 系统字体 | ❌ 受限 |
| 宋体 SimSun / 黑体 SimHei | — | 系统字体 | ❌ 受限 |
| 等线 DengXian (Deng*.ttf) | 黑体 | 系统字体 | ❌ 受限 |

OFL 1.1 = 商业视频/印刷/产品都能用、可嵌入、无需付费/授权/署名；唯一限制是「不能单独打包卖字体本身」，对做字幕毫无影响。

验证字体许可：读字体文件内嵌的 license 字段（name table），找 "SIL Open Font License" 即 OFL。

新建样式声明字体时，**只用确认 OFL 的字体名**。否则 libass 找不到声明的字体会 fallback，可能落到系统受限字体（雅黑/宋体）→ 商用风险。建议给新样式流程加一道字体白名单校验。

## 3. libass 字体匹配坑

- **精确匹配才不 fallback**：ASS Style 行的 `Fontname` 必须精确等于字体的 family name（如 `Noto Serif SC`、`Noto Sans SC Medium`），libass 才命中；否则按 fontconfig 规则 fallback 到别的字体。
- **VF + 静态同名冲突**：系统里若同时存在可变字体（如 `NotoSansSC-VF.ttf`，family `Noto Sans SC` weight=100）和静态字重文件（`Noto Sans SC` weight 400/700），fontconfig 按请求 weight 选最接近的——`Bold=1`(700) 选静态 Bold，`Bold=0`(400) 选静态 Regular（distance 0 优于 VF 的 100）。但为彻底避险，用**独立 family name 的字重**（如 `Noto Sans SC Medium`，family 唯一、无 VF 同名干扰）最稳。
- 查系统字体 family name + weight：用 `fontTools.ttLib`（TTFont/TTCollection）读 name table 第 1/16 项 + OS/2.usWeightClass。

## 4. ASS 烧帧对照调参法（快速验证，不走全管线）

调字幕样式（描边/阴影/字体/颜色）时，逐参数烧帧对照比跑全管线快一个量级：

1. 拿一份已渲的 `.ass` 作底板（含正确的 PlayResX/Y、Style 行、几条 Dialogue）。
2. 复制 .ass，只改 Style 行的目标字段：`Fontname`(第2)、`Bold`(第8)、`Outline`(第17)、`Shadow`(第18)、`PrimaryColour`(第4)。
3. 从**无字幕母版**用 ffmpeg 烧帧抽图（`subtitles` filter）：
   ```bash
   cd <ass目录>   # cd 进去用相对 ass 名，避开 Windows subtitles filter 路径转义地狱
   ffmpeg -y -ss <切片内秒数> -i "<无字幕母版.mp4>" -vf "subtitles=variant.ass" -frames:v 1 -q:v 2 frame.jpg
   ```
   `-ss` 用 input seek（在 -i 前），输出 PTS 从 0 起，subtitles filter 渲染 ASS 0:00:00 的字幕——文字对、背景是该时间点画面。
4. 多个候选并排发用户对比（描边/阴影是亚像素差异、肉眼裁决最快）。

ASS Style 字段速记（Format 顺序）：
`Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding`

- Outline/Shadow 像素值 = ratio × font_size（如 outline_ratio 0.0167 × 168px ≈ 2.8px）。
- 颜色 `&H00FFFFFF`=纯白，`&H00000000`=黑，`&H96000000`=半透明黑（alpha 0x96 ≈ 59% 透明）。

## 5. 配置层落地（garden_core）

新样式做成配置而非代码硬编码：`font_family` 与 `xr`(font_size_ratio) 一样，是 style yaml 必填、代码无兜底、缺失抛 ConfigError。yaml 覆盖描边/阴影必须用 **StyleDef 字段名** `outline_width` / `shadow_depth`，不是 mold 的 `outline_ratio` / `shadow_ratio`——写错会被 `_apply_overrides` 静默丢弃、参数不生效。新建样式只需在 `stage_style/styles/` 加一个 `<name>.yaml`（`mold: <base>` + override 字段），不必动 molds.py 代码。
