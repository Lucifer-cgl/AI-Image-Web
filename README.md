# AI Image Web

Windows 本地网页图片生成器。双击启动后在浏览器中使用，模型、提示词、原图与生成历史均留在本机，不调用收费生图 API。

## 功能

- DreamShaper 8 FP16 本地文生图
- 本地图生图与修改强度
- 中文提示词本地翻译（可选）
- 常用、横屏、竖屏输出尺寸
- 自动保存历史记录
- 历史图片预览、下载、删除
- OpenAI 风格接口：`POST /v1/images/generations`

## Windows 使用

1. 安装 Python 3.11 和 NVIDIA 显卡驱动。
2. 运行 `install.ps1` 安装 Python 依赖。
3. 运行 `download-model.ps1` 下载 DreamShaper 与中文翻译模型附件；脚本优先国内镜像，失败后回退 GitHub。
4. 双击 `start.ps1`，浏览器会自动打开 `http://127.0.0.1:8091/`。

如果电脑已有 `E:\AI-Models\image\dreamshaper-8-fp16`，`start.ps1` 会直接复用，无需重复下载。

生成图片保存在 `data/history/`。删除网页历史记录会同时删除对应 PNG 和元数据。

## 接口示例

```powershell
$body = @{
  prompt = 'a small dog resting under a tree, illustration'
  size = '512x512'
  steps = 20
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8091/v1/images/generations -ContentType application/json -Body $body
```

## 许可证

程序代码采用 MIT；DreamShaper 与翻译模型分别沿用其上游 CreativeML Open RAIL-M、CC BY 4.0 许可，参见 [MODEL_LICENSE.md](MODEL_LICENSE.md)。

