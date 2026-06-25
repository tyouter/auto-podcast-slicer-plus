# 字幕样式快速调试 + 字体选型

调字幕外观（字号/描边/阴影/颜色/字体）时，**不要每改一次就重渲整条切片**。
直接改生成出来的 `.ass` 的 Style 行 + ffmpeg 烧一帧，1 秒出对比图。

## 一、快速一帧对比工作流（核心技巧）

前置：手头有一份 garden_core 已生成的 `.ass`（拿它当模板）+ **无字幕母版视频** +
切片在母版里的起点秒数。

```bash
cd <ass 所在目录>          # ⚠️ 必须 cd 进去，下面用相对文件名
ffmpeg -y -ss <切片起点秒> -i "<无字幕母版.mp4>" \
  -vf "subtitles=<候选.ass>" -frames:v 1 -q:v 2 frame.jpg
```

要点 / 坑：

- **cd + 相对 ass 文件名** 是为了绕开 Windows `subtitles=` filter 的路径转义地狱
  （`D:` 里的冒号在 filtergraph 里要写成 `D\\:` 很容易踩错）。cd 进去后写
  `subtitles=fresh_A.ass` 最稳。
- **`-ss` input seek 会把输出 PTS 重置到 0**，所以 `subtitles=` filter 渲染的是
  ASS 里 **time 0（第一句）** 的字幕，无论你 seek 到哪一秒。结果 = 背景是 seek
  那一帧的画面，字幕是第一句。**对比描边/字体/字号的可读性完全够用**（不需要像素级同帧）。
- 想换背景画面就调 `-ss` 的秒数（落在第一句 cue 的显示区间内即可，文字不变）。
- 一次渲多个候选：复制 ass → 改 Style 行 → 各烧一帧 → 用 `MEDIA:` 内联发飞书对比。
  脚本见 `scripts/render_style_frames.py`。

## 二、ASS Style 行字段表

`[V4+ Styles]` 的 Format（逗号分隔，1-based 序号）：

```
1 Name  2 Fontname  3 Fontsize  4 PrimaryColour  5 SecondaryColour
6 OutlineColour  7 BackColour(=阴影色)  8 Bold  9 Italic ... 16 BorderStyle
17 Outline  18 Shadow  19 Alignment  20 MarginL  21 MarginR  22 MarginV  23 Encoding
```

实例：
```
Style: Default,Noto Sans SC Medium,168,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2.184,1.5,2,307,307,129,1
```

- 颜色格式 **`&HAABBGGRR`**（ASS 是 BGR + alpha，alpha 00=不透明，FF=全透明）。
  - `&H00FFFFFF` = 不透明纯白；`&H00000000` = 不透明黑；`&H96000000` = 半透明黑（alpha 0x96≈59%，柔和阴影）。
- **Outline / Shadow 单位是像素**（当 `ScaledBorderAndShadow: yes` 且 ASS 的
  `PlayResX/Y` == 实际渲染分辨率，比例 1:1）。本项目 4K → PlayRes 3840×2160。
- **Bold** 字段 0/1：`Noto Sans SC` family 同时有 Regular 文件和 Bold 文件，靠这个 flag 切。
- **字号 = xr × video_height**（xr 是配置主变量，见 SKILL.md「xr 是唯一主变量」）。
  快速调试时这里直接写绝对像素方便比，定稿后回写到 `styles/<name>.yaml` 的 xr。

## 三、字体选型：看不清的根因是字体瘦，不是描边不够

**用户在本 session 一刀切到根上：** 字幕弱描边后看不清，根因不是描边太细，是
**字体本身笔画瘦**。

- **宋体类（Serif，如 Noto Serif SC / 思源宋体）**：基因就是「横细竖粗」，横画细如发丝。
  无/弱描边时横画一糊就看不清。
- 想「清新干净 + 增大白色区域」却靠**加黑描边**补可读性 = **南辕北辙**：描边越粗 →
  黑色越多 → 白区越小 → 越不清新。这是个内在矛盾。
- **正解：换笔画饱满的字体（黑体 / Sans，如 Noto Sans SC）**。黑体横竖一样粗，字芯
  本身够白够饱满，描边只留极细一根做亮背景保命甚至不要 → 清新和可读同时成立。
- 字重梯队（同 Noto Sans SC family）：Regular(400) → **Medium(500，清新甜点)** →
  Bold(700，最扎实)。Medium 比 Regular 饱满、比 Bold 轻盈，最契合「清新干净」。

「清新版」一组验证下来的合理区间（4K，字号 168px）：
- 字体 Noto Sans SC Medium，纯白 `&H00FFFFFF`
- 描边 ~2.2–2.8px（1px 太弱看不清，cinematic 的 4.2px 太重）
- 阴影 0–2.5px 半透明黑（要立体感就给一层薄影，纯无阴影在亮背景上字会飘）

## 四、商用字体白名单 + fallback 风险（Windows 本机）

字幕字体**必须可商用**。本机已装、可安全用的：

| 字体（ASS Fontname） | 类型 | 许可 |
|---|---|---|
| `Noto Serif SC` | 宋体 | ✅ SIL OFL 1.1 |
| `Noto Sans SC`（+Bold flag） | 黑体 400/700 | ✅ OFL |
| `Noto Sans SC Medium` | 黑体 500 | ✅ OFL |
| `Source Han Serif SC Heavy` | 宋体 900 | ✅ OFL |

**❌ 本机也装了但商用受限、禁用：** `Microsoft YaHei`(msyh)、`SimSun`(宋体)、
`SimHei`(黑体)、`DengXian`(等线) —— 都是 Windows 系统捆绑字体，商用需授权。

**fallback 风险：** ASS 里声明一个本机没有的 Fontname → libass 会 fallback，可能落到
上面那些受限字体上 → 埋下商用隐患。所以**新建样式时 Fontname 只用上表白名单里的**。

**VF / 同名陷阱：** 本机 `NotoSansSC-VF.ttf`（可变字体，weight=100 极细）和静态
`Noto Sans SC` otf（400/700）**family name 同为 "Noto Sans SC"**。libass/fontconfig
按 weight 匹配时**可能选到极细的 VF**。规避：① 用唯一 family 名 `Noto Sans SC Medium`
（无 VF 同名干扰）② 或靠 Bold=1 请求 weight 700 让它命中静态 Bold。渲完务必目视确认
字重对不对——如果 Bold 反而比 Medium 还细，就是选到 VF 了。

**验证某字体是否 OFL：** 读字体内嵌 name table 的 license 字段（fontTools
`TTFont(path)["name"].getDebugName(13)` / `getDebugName(14)`），Noto 系会写明
"licensed under the SIL Open Font License, Version 1.1"。

## 五、定稿回写

一帧对比定好参数后，回写到正式配置（不要把绝对像素留在临时 ass）：
- 字号 → `styles/<name>.yaml` 的 `font_size_ratio`（xr，= font_size/height）
- 描边/阴影/颜色/字体 → 对应 `styles/<name>.yaml` 字段（`_apply_overrides` 支持覆盖
  `StyleDef` 任意字段）。代码 `.py` 不动。
- 决定是**覆盖现有样式**还是**新建独立样式名**（如 `fresh`，以后按片选）——动手前问用户。
