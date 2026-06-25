# 字幕风格快速迭代 + 字体清晰度根因 + 配置化陷阱

会话实证（garden-production cinematic → fresh 清新黑体）。这套方法把"调一个字幕参数要等整条管线"压缩成秒级一帧对比。

## 1. 快速预览：改 ASS Style 行 + ffmpeg 烧单帧（不跑全管线）

每改一档参数都跑 garden_core 全管线太慢。正确做法：直接编辑一个 `.ass` 的 Style 行，用 ffmpeg 把它烧到母版的一帧上抽出来看。

```bash
# cd 到 ass 所在目录，用相对路径引 ass —— 避开 Windows subtitles filter 的盘符冒号/反斜杠转义地狱
cd "/d/.../_freshtest"
ffmpeg -y -ss 1803 -i "MASTER.mp4" -vf "subtitles=variant.ass" -frames:v 1 -q:v 2 frame.jpg
```

- `-ss <秒>` 用 input seek，输出 PTS 从 0 开始，subtitles filter 渲染 ass `0:00:00` 处的字幕；母版那一秒的画面 + 第一句字幕，足够看清描边/字重/颜色差异，不必和历史帧像素级同帧。
- 要做"候选 A / B"梯度对比：复制 ass，只改 Outline / Shadow / Fontname 字段，各烧一帧，并排发给用户裁决（用户对视觉逐张审查，梯度帧 ≠ 选项菜单）。
- 母版（无字幕背景）是唯一能重烧的源；已烧字幕的成片不能再烧（会双重字幕）。

### ASS Style 行字段位（V4+）
```
Style: Default,<Fontname>,<Fontsize>,<PrimaryColour>,<SecondaryColour>,<OutlineColour>,<BackColour>,<Bold>,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,<Outline>,<Shadow>,Alignment,MarginL,MarginR,MarginV,Encoding
```
- `ScaledBorderAndShadow: yes` + PlayRes=渲染分辨率时，Outline/Shadow 数值≈像素。
- 描边像素 ≈ `outline_ratio × font_size`（例：fresh outline_ratio 0.0167 × 168px ≈ 2.8px）。

## 2. 字幕看不清的根因常是「字体字重/字族」，不是描边

宋体（Serif，如 Noto Serif SC）基因是横细竖粗，横画极细——弱描边/无阴影时横画一糊就看不清。**别用加粗黑描边去补**：描边越粗黑色越多、白字区越小，跟"清新干净 / 增大白区"是反着来的。

正解：换**笔画本身饱满的黑体（Sans）**，横竖一样粗，字芯自己够白够亮，描边只留一根细的做亮背景保命。
- 清新甜点：**Noto Sans SC Medium（weight 500）** —— 比 Regular 饱满、比 Bold 轻盈。
- 调胖瘦走字重（Regular 400 / Medium 500 / Bold 700），不是堆描边。

判断顺序：先问字体/字重对不对，再调描边/阴影。outline 是补丁，font family/weight 才是根因。

## 3. 字体商用许可速查（免费商用 = OFL）

新建样式声明字体前先验许可——libass 精确 family 匹配命中才不 fallback；声明一个系统没有的字体名会 fallback 到雅黑/宋体等**商用受限**字体，埋下版权雷。

| 字体 | 许可 | 商用 |
|---|---|---|
| Noto Serif SC / Noto Sans SC / Source Han Serif/Sans | SIL OFL 1.1 | ✅ 免费商用（含嵌入，唯一限制：不能单独打包卖字体） |
| 微软雅黑 msyh / 宋体 simsun / 黑体 simhei / 等线 DengXian | 系统专有 | ❌ 受限 |

验许可：读字体文件内嵌 license（fontTools name table 第 13/14 项，或 `strings *.ttf | grep -i license`）。OFL 即可商用。**新样式 font_family 只用 OFL 白名单字体。**

## 4. garden_core 配置层覆盖：StyleDef 字段名 ≠ mold 字段名（静默丢弃陷阱）

garden_core 的 `_apply_overrides` 只保留 **StyleDef 字段名**的 key（`valid = {f.name for f in fields(StyleDef)}`），其余 yaml key 被静默丢弃、覆盖不生效。

| 想覆盖 | mold 字段名（❌ 写这个会被丢） | StyleDef 字段名（✅ yaml 里写这个） |
|---|---|---|
| 描边 | outline_ratio | **outline_width** |
| 阴影 | shadow_ratio | **shadow_depth** |
| 字号比 | font_size_ratio | font_size_ratio（同名 OK） |
| 字体 | font_family | font_family（同名 OK） |
| 颜色 | primary_color / outline_color / shadow_color | 同名 OK |

值仍是 ratio（ass_writer 用 `ratio × font_size_px` 转像素）。

## 5. 新增一个字幕样式 = 加一个 yaml，别动 molds.py（最 surgical）

garden_core 已把 font_family 和 xr 做成**必填配置、代码零兜底**（mold 里 `Optional[str/float] = None`，resolver 出口 `require_font_family` / `require_xr` 缺失抛 `ConfigError`）。新增样式不需要改代码：

```yaml
# styles/<name>.yaml —— mold 提供版式基底，override 改审美
mold: cinematic            # 复用 cinematic 的位置/边距/版式
font_size_ratio: 0.078     # xr 必填
font_family: Noto Sans SC Medium
outline_width: 0.0167      # StyleDef 字段名！
shadow_depth: 0.0149
```
- 把字体/描边/阴影做成配置项时，比照 xr：mold 默认值改 None + 加 require_ 门控 + 现有样式 yaml 全部补该字段（否则它们因必填而坏，回归！例如 cinematic.yaml 必须补 `font_family: Noto Serif SC`）。
- 验证：`YamlStyleResolver().resolve('<name>', 2160)` 打印 StyleDef 字段，对照 ground-truth ASS Style 行；再渲一帧对照。**渲染产出的 Style 行与手写 ground-truth 差 ~0.01px 是 font_size 168.48 vs 168 取整的亚像素差，视觉无别。**
