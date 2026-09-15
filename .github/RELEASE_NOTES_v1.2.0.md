# 砚读 InkRead v1.2.0

全屏设置页与全新的多供应商 AI 接入层：选供应商、贴 Key、选模型，三步完成配置。

## 这次更新

- 设置改为全屏页面，分为 AI 模型 / 学术检索 / 翻译 / 阅读与批注 四类，`Ctrl+,` 打开，`Ctrl+S` 保存，离开前会提示未保存的修改
- 内置 15 个供应商预设：OpenRouter（默认，含 `:free` 免费模型）、OpenCode Go、OpenAI、Anthropic、Google Gemini、DeepSeek、Moonshot Kimi、阿里云百炼、智谱 GLM、MiniMax、火山引擎、硅基流动、xAI Grok、Ollama（本地）以及任意 OpenAI 兼容接口；接口地址与协议（Chat Completions / Responses / Anthropic Messages / Gemini）由程序自动选择
- 每个供应商的 API Key 单独记忆，切换供应商不会丢失
- 模型列表：内置常用目录 + 自动在线刷新。打开设置页或切换供应商时先显示上次拉取结果，再在后台更新；拉取失败保留原列表；已选模型不在供应商当前列表时给出提示
- 新增“测试连接”，发送一条极短消息验证 Key、模型与协议是否匹配，并直接显示供应商返回的原始错误
- 移除 OpenCode Zen 供应商；旧版本保存的 Zen 配置会自动回退到默认供应商，其余供应商的 Key 不受影响
- 设置页中的外部链接改为在系统浏览器打开
- 修复更新后界面仍加载旧前端资源的问题（入口页不再被缓存）

## 便携版

请下载 `InkRead-1.2.0-windows-x64.zip`。解压后保留 `InkRead.exe` 与同目录的 `_internal` 文件夹，不要单独移动 EXE。

设置仍保存在 `%LOCALAPPDATA%\InkRead\settings.json`，升级后文库、阅读进度与已填写的 Key 都会保留。
