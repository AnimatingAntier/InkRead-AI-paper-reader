# 砚读 InkRead v1.1.0

多供应商 AI 设置：选供应商、填 API Key，不用再手填网址。

## 这次更新

- 内置 OpenRouter、OpenAI、OpenCode Zen、DeepSeek、Moonshot/Kimi、阿里云百炼、智谱 GLM、SiliconFlow、Groq、xAI Grok、Google Gemini，以及自定义 OpenAI 兼容接口
- 目录内供应商自动使用官方 Base URL，设置里只需粘贴该供应商的 API Key
- 未填写 Key 时，设置页会给出该供应商的官方申请链接
- 每次启动会刷新已配置供应商的模型列表；失败时保留上次成功缓存
- 多家供应商的 Key 和上次选用的模型会分别保存，切换时不必重填
- 旧版 settings.json 会自动迁移进新的按供应商存储结构

## 便携版

请下载 InkRead-1.1.0-windows-x64.zip。解压后保留 InkRead.exe 与同目录的 _internal 文件夹，不要单独移动 EXE。

设置仍保存在 %LOCALAPPDATA%\InkRead\settings.json。
