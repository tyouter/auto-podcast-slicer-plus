# 飞书视频交付

`send_message` 的 `MEDIA:` 前缀不支持飞书平台发送视频文件。
用 lark-cli 的 `im +messages-send --video` 命令。

## 完整流程

```bash
# 1. 提取封面帧（从视频第3秒截取）
ffmpeg -y -ss 3 -i video.mp4 -vframes 1 -q:v 2 cover.jpg

# 2. 压缩到 30MB 以下（飞书 Bot 视频上限）
ffmpeg -y -i video.mp4 -c:v libx264 -crf 28 -preset fast \
  -c:a aac -b:a 128k -movflags +faststart compressed.mp4

# 3. 发送（必须 cd 到文件所在目录，lark-cli 要求相对路径）
cd /path/to/output/dir && HOME=$HERMES_HOME npx @larksuite/cli im +messages-send \
  --chat-id oc_xxxxxxxx \
  --video "./compressed.mp4" \
  --video-cover "./cover.jpg"
```

## 关键约束

- **文件上限：30MB**（飞书 Bot 限制，超过报 `file size exceed the max value`）
- **路径格式：相对路径**（lark-cli 拒绝绝对路径，报 `must be a relative path within the current directory`）
- **封面必填：** `--video-cover` 与 `--video` 必须同时提供，否则发送失败
- **压缩参数：** `crf 28` + `aac 128k` 通常可将 1080p 视频从 40MB 压到 13MB，画质可接受
- **chat-id：** 主 Agent 飞书 DM 为 `oc_xxxxxxxx`
