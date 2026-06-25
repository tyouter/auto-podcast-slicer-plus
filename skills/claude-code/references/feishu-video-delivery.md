# 视频压缩与交付

剪辑产出的成品视频在通过 IM / 聊天通道分发前，通常需要先压缩到通道允许的大小，并附带一张封面帧。本文给出与平台无关的压缩与交付流程。

## 完整流程

```bash
# 1. 提取封面帧（从视频第3秒截取）
ffmpeg -y -ss 3 -i video.mp4 -vframes 1 -q:v 2 cover.jpg

# 2. 压缩到 30MB 以下
ffmpeg -y -i video.mp4 -c:v libx264 -crf 28 -preset fast \
  -c:a aac -b:a 128k -movflags +faststart compressed.mp4
```

压缩完成后，用你所在平台的 IM / 通道发送 `compressed.mp4`，并随附 `cover.jpg` 作为封面。

## 关键约束

- **文件上限：** 大多数 IM 对机器人 / 上传的视频有大小上限，常见为 **≤30MB**（超限通常报类似 `file size exceed the max value` 的错误）。把成品压到 30MB 以内是通用的安全做法。
- **封面帧：** 多数通道在发送视频时需要或建议同时提供一张封面图。封面缺失时，部分通道会发送失败或显示黑帧，因此建议始终同时提供封面帧。
- **压缩参数：** `crf 28` + `aac 128k` 通常可将 1080p 视频从 40MB 压到 13MB 左右，画质可接受。`-movflags +faststart` 让视频可边下边播。
- **路径要求：** 部分上传工具要求相对路径或要求在文件所在目录执行，按你所用工具的约定调整即可。
