"""Built-in AI provider presets and model catalogs.

Each preset knows its base URL, wire protocol and a static model list, so the
user only has to pick a provider, paste a key and choose a model. Protocol can
be overridden per model for aggregators such as OpenCode Go, which fronts
Anthropic, OpenAI Responses and Chat Completions behind one host.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROTOCOL_CHAT = "chat"
PROTOCOL_RESPONSES = "responses"
PROTOCOL_ANTHROPIC = "anthropic"
PROTOCOL_GEMINI = "gemini"
PROTOCOLS = (PROTOCOL_CHAT, PROTOCOL_RESPONSES, PROTOCOL_ANTHROPIC, PROTOCOL_GEMINI)

CUSTOM_PROVIDER = "openai_compatible"


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    vision: bool = False
    free: bool = False
    protocol: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vision": self.vision,
            "free": self.free,
        }


@dataclass(frozen=True)
class Group:
    label: str
    models: tuple[Model, ...]


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    tagline: str
    base_url: str
    protocol: str
    key_url: str = ""
    key_placeholder: str = "sk-…"
    key_required: bool = True
    custom_base_url: bool = False
    supports_model_listing: bool = True
    default_model: str = ""
    region: str = "global"
    groups: tuple[Group, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    # OpenCode's free tier refuses requests that do not carry a session id.
    session_header: bool = False

    def models(self) -> list[Model]:
        return [model for group in self.groups for model in group.models]

    def find_model(self, model_id: str) -> Model | None:
        for model in self.models():
            if model.id == model_id:
                return model
        return None

    def protocol_for(self, model_id: str) -> str:
        known = self.find_model(model_id)
        if known and known.protocol:
            return known.protocol
        guess = _guess_protocol(self.id, model_id)
        return guess or self.protocol

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "tagline": self.tagline,
            "base_url": self.base_url,
            "protocol": self.protocol,
            "key_url": self.key_url,
            "key_placeholder": self.key_placeholder,
            "key_required": self.key_required,
            "custom_base_url": self.custom_base_url,
            "supports_model_listing": self.supports_model_listing,
            "default_model": self.default_model,
            "region": self.region,
            "groups": [
                {"label": group.label, "models": [model.to_dict() for model in group.models]}
                for group in self.groups
            ],
        }


def _m(model_id: str, name: str, *, vision: bool = False, free: bool = False, protocol: str = "") -> Model:
    return Model(model_id, name, vision=vision, free=free, protocol=protocol)


def _guess_protocol(provider_id: str, model_id: str) -> str:
    """Route unknown OpenCode models the same way the official client does."""
    if provider_id != "opencode_go":
        return ""
    lowered = model_id.lower()
    if lowered.startswith("claude"):
        return PROTOCOL_ANTHROPIC
    if lowered.startswith(("gpt-", "grok-", "muse-")):
        return PROTOCOL_RESPONSES
    if lowered.startswith("gemini"):
        return PROTOCOL_GEMINI
    return PROTOCOL_CHAT


_GO_MODELS = (
    _m("glm-5.3-flash", "GLM-5.3 Flash", vision=True),
    _m("glm-5.3", "GLM-5.3"),
    _m("glm-5.2", "GLM-5.2"),
    _m("glm-5.1", "GLM-5.1"),
    _m("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", vision=True),
    _m("deepseek-v4-flash", "DeepSeek V4 Flash"),
    _m("deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision", vision=True),
    _m("deepseek-v4-pro", "DeepSeek V4 Pro"),
    _m("kimi-k3", "Kimi K3", vision=True),
    _m("kimi-k2.7-code", "Kimi K2.7 Code", vision=True),
    _m("kimi-k2.6", "Kimi K2.6", vision=True),
    _m("qwen3.8-max", "Qwen3.8 Max", vision=True),
    _m("qwen3.8-flash", "Qwen3.8 Flash", vision=True, protocol=PROTOCOL_ANTHROPIC),
    _m("qwen3.7-max", "Qwen3.7 Max"),
    _m("qwen3.7-plus", "Qwen3.7 Plus", vision=True),
    _m("qwen3.6-plus", "Qwen3.6 Plus", vision=True),
    _m("minimax-m3", "MiniMax M3", vision=True, protocol=PROTOCOL_ANTHROPIC),
    _m("minimax-m2.7", "MiniMax M2.7", protocol=PROTOCOL_ANTHROPIC),
    _m("mimo-v2.5-pro", "MiMo V2.5 Pro"),
    _m("mimo-v2.5", "MiMo V2.5", vision=True),
    _m("longcat-2.0", "LongCat 2.0"),
    _m("hy4-preview", "Hy4 Preview"),
    _m("hy3", "Hy3"),
    _m("gpt-5.6-luna", "GPT-5.6 Luna", vision=True, protocol=PROTOCOL_RESPONSES),
    _m("grok-4.6", "Grok 4.6", vision=True, protocol=PROTOCOL_RESPONSES),
    _m("muse-spark-1.3-contributor", "Muse Spark 1.3 Contributor", vision=True, protocol=PROTOCOL_RESPONSES),
)


PROVIDERS: dict[str, Provider] = {
    provider.id: provider
    for provider in (
        Provider(
            id="opencode_go",
            label="OpenCode Go",
            tagline="OpenCode 低价套餐 · 开源模型为主",
            base_url="https://opencode.ai/zen/go/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://opencode.ai/auth",
            default_model="glm-5.3-flash",
            session_header=True,
            groups=(Group("Go 套餐模型", _GO_MODELS),),
        ),
        Provider(
            id="openrouter",
            label="OpenRouter",
            tagline="聚合数百个模型 · 含 :free 免费模型",
            base_url="https://openrouter.ai/api/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://openrouter.ai/settings/keys",
            key_placeholder="sk-or-v1-…",
            default_model="openrouter/free",
            headers={"HTTP-Referer": "http://127.0.0.1:3217", "X-Title": "InkRead"},
            groups=(
                Group(
                    "免费模型",
                    (
                        _m("openrouter/free", "OpenRouter Free 自动路由", free=True),
                        _m("inclusionai/ling-3.0-flash-vl:free", "Ling 3.0 Flash VL", vision=True, free=True),
                        _m("nex-agi/nex-n2.5-pro:free", "Nex N2.5 Pro", vision=True, free=True),
                        _m("nex-agi/nex-n2.5-mini:free", "Nex N2.5 Mini", vision=True, free=True),
                    ),
                ),
                Group(
                    "常用模型",
                    (
                        _m("openai/gpt-6-astra", "GPT-6 Astra", vision=True),
                        _m("openai/gpt-5.6-luna", "GPT-5.6 Luna", vision=True),
                        _m("anthropic/claude-sonnet-5", "Claude Sonnet 5", vision=True),
                        _m("anthropic/claude-opus-5", "Claude Opus 5", vision=True),
                        _m("google/gemini-3.8-flash", "Gemini 3.8 Flash", vision=True),
                        _m("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", vision=True),
                        _m("qwen/qwen3.8-max-0902", "Qwen3.8 Max", vision=True),
                        _m("meta/muse-spark-1.3", "Muse Spark 1.3", vision=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="openai",
            label="OpenAI",
            tagline="GPT 系列官方接口",
            base_url="https://api.openai.com/v1",
            protocol=PROTOCOL_RESPONSES,
            key_url="https://platform.openai.com/api-keys",
            key_placeholder="sk-proj-…",
            default_model="gpt-5.6-luna",
            groups=(
                Group(
                    "GPT",
                    tuple(
                        _m(model_id, name, vision=True)
                        for model_id, name in (
                            ("gpt-6-astra", "GPT-6 Astra"),
                            ("gpt-5.6", "GPT-5.6"),
                            ("gpt-5.6-sol", "GPT-5.6 Sol"),
                            ("gpt-5.6-terra", "GPT-5.6 Terra"),
                            ("gpt-5.6-luna", "GPT-5.6 Luna"),
                            ("gpt-5.5", "GPT-5.5"),
                            ("gpt-5.4", "GPT-5.4"),
                            ("gpt-5.4-mini", "GPT-5.4 Mini"),
                            ("gpt-5.4-nano", "GPT-5.4 Nano"),
                            ("gpt-5.2", "GPT-5.2"),
                            ("gpt-5.1", "GPT-5.1"),
                            ("gpt-5", "GPT-5"),
                        )
                    ),
                ),
            ),
        ),
        Provider(
            id="anthropic",
            label="Anthropic",
            tagline="Claude 系列官方接口",
            base_url="https://api.anthropic.com/v1",
            protocol=PROTOCOL_ANTHROPIC,
            key_url="https://console.anthropic.com/settings/keys",
            key_placeholder="sk-ant-…",
            default_model="claude-sonnet-5",
            groups=(
                Group(
                    "Claude",
                    tuple(
                        _m(model_id, name, vision=True)
                        for model_id, name in (
                            ("claude-fable-5-1", "Claude Fable 5.1"),
                            ("claude-opus-5", "Claude Opus 5"),
                            ("claude-sonnet-5", "Claude Sonnet 5"),
                            ("claude-opus-4-8", "Claude Opus 4.8"),
                            ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
                            ("claude-opus-4-5", "Claude Opus 4.5"),
                            ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
                            ("claude-haiku-4-5", "Claude Haiku 4.5"),
                        )
                    ),
                ),
            ),
        ),
        Provider(
            id="google",
            label="Google Gemini",
            tagline="Gemini 官方接口 · AI Studio 有免费额度",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            protocol=PROTOCOL_GEMINI,
            key_url="https://aistudio.google.com/apikey",
            key_placeholder="AIza…",
            default_model="gemini-3.8-flash",
            groups=(
                Group(
                    "Gemini",
                    tuple(
                        _m(model_id, name, vision=True)
                        for model_id, name in (
                            ("gemini-3.8-flash", "Gemini 3.8 Flash"),
                            ("gemini-3.7-flash", "Gemini 3.7 Flash"),
                            ("gemini-3.6-flash", "Gemini 3.6 Flash"),
                            ("gemini-3.5-flash", "Gemini 3.5 Flash"),
                            ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
                            ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
                            ("gemini-flash-latest", "Gemini Flash Latest"),
                            ("gemini-flash-lite-latest", "Gemini Flash Lite Latest"),
                        )
                    ),
                ),
            ),
        ),
        Provider(
            id="deepseek",
            label="DeepSeek",
            tagline="深度求索官方接口",
            base_url="https://api.deepseek.com/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://platform.deepseek.com/api_keys",
            default_model="deepseek-v4-flash",
            region="cn",
            groups=(
                Group(
                    "DeepSeek",
                    (
                        _m("deepseek-v4-flash", "DeepSeek V4 Flash", vision=True),
                        _m("deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision", vision=True),
                        _m("deepseek-flash", "DeepSeek V4.1 Flash", vision=True),
                        _m("deepseek-v4-pro", "DeepSeek V4 Pro"),
                    ),
                ),
            ),
        ),
        Provider(
            id="moonshot",
            label="Moonshot Kimi",
            tagline="月之暗面官方接口",
            base_url="https://api.moonshot.cn/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://platform.moonshot.cn/console/api-keys",
            default_model="kimi-k2.6",
            region="cn",
            groups=(
                Group(
                    "Kimi",
                    (
                        _m("kimi-k3", "Kimi K3", vision=True),
                        _m("kimi-k2.7-code", "Kimi K2.7 Code", vision=True),
                        _m("kimi-k2.6", "Kimi K2.6", vision=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="dashscope",
            label="阿里云百炼 · 通义千问",
            tagline="Qwen 系列与百炼平台聚合模型",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://bailian.console.aliyun.com/?tab=model#/api-key",
            default_model="qwen3.8-flash",
            region="cn",
            groups=(
                Group(
                    "Qwen",
                    (
                        _m("qwen3.8-max", "Qwen3.8 Max", vision=True),
                        _m("qwen3.8-flash", "Qwen3.8 Flash", vision=True),
                        _m("qwen3.7-plus", "Qwen3.7 Plus", vision=True),
                        _m("qwen3.7-flash", "Qwen3.7 Flash", vision=True),
                        _m("qwen3.6-plus", "Qwen3.6 Plus", vision=True),
                    ),
                ),
                Group(
                    "百炼第三方模型",
                    (
                        _m("deepseek-v4-flash", "DeepSeek V4 Flash"),
                        _m("glm-5.2", "GLM-5.2"),
                        _m("kimi-k2.6", "Kimi K2.6", vision=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="zhipu",
            label="智谱 GLM",
            tagline="智谱 BigModel 开放平台",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            protocol=PROTOCOL_CHAT,
            key_url="https://open.bigmodel.cn/usercenter/apikeys",
            default_model="glm-5.3-flash",
            region="cn",
            groups=(
                Group(
                    "GLM",
                    (
                        _m("glm-5.3-flash", "GLM-5.3 Flash", vision=True),
                        _m("glm-5.3", "GLM-5.3"),
                        _m("glm-5.2", "GLM-5.2"),
                        _m("glm-5v-turbo", "GLM-5V Turbo", vision=True),
                        _m("glm-4.7-flash", "GLM-4.7 Flash", free=True),
                        _m("glm-4.5-flash", "GLM-4.5 Flash", free=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="minimax",
            label="MiniMax",
            tagline="MiniMax 开放平台（国内站）",
            base_url="https://api.minimaxi.com/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://platform.minimaxi.com/user-center/basic-information/interface-key",
            default_model="MiniMax-M2.7",
            region="cn",
            groups=(
                Group(
                    "MiniMax",
                    (
                        _m("MiniMax-M3", "MiniMax M3", vision=True),
                        _m("MiniMax-M2.7", "MiniMax M2.7"),
                        _m("MiniMax-M2.5", "MiniMax M2.5"),
                    ),
                ),
            ),
        ),
        Provider(
            id="volcengine",
            label="火山引擎 · 豆包",
            tagline="火山方舟 Ark 平台",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            protocol=PROTOCOL_CHAT,
            key_url="https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
            default_model="doubao-seed-2-1-turbo-260628",
            region="cn",
            supports_model_listing=False,
            groups=(
                Group(
                    "豆包 Seed",
                    (
                        _m("doubao-seed-2-1-pro-260628", "Doubao Seed 2.1 Pro", vision=True),
                        _m("doubao-seed-2-1-turbo-260628", "Doubao Seed 2.1 Turbo", vision=True),
                        _m("doubao-seed-2-0-lite-260428", "Doubao Seed 2.0 Lite", vision=True),
                        _m("doubao-seed-2-0-mini-260428", "Doubao Seed 2.0 Mini", vision=True),
                        _m("deepseek-v4-flash-ga-260731", "DeepSeek V4 Flash"),
                        _m("deepseek-v4-pro-ga-260813", "DeepSeek V4 Pro"),
                    ),
                ),
            ),
        ),
        Provider(
            id="siliconflow",
            label="硅基流动 SiliconFlow",
            tagline="开源模型托管平台",
            base_url="https://api.siliconflow.cn/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://cloud.siliconflow.cn/account/ak",
            default_model="deepseek-ai/DeepSeek-V4-Flash",
            region="cn",
            groups=(
                Group(
                    "开源模型",
                    (
                        _m("deepseek-ai/DeepSeek-V4-Flash", "DeepSeek V4 Flash"),
                        _m("deepseek-ai/DeepSeek-V4-Pro", "DeepSeek V4 Pro"),
                        _m("zai-org/GLM-5.2", "GLM-5.2"),
                        _m("zai-org/GLM-5V-Turbo", "GLM-5V Turbo", vision=True),
                        _m("Qwen/Qwen3.6-27B", "Qwen3.6 27B"),
                        _m("moonshotai/Kimi-K2.6", "Kimi K2.6", vision=True),
                        _m("Qwen/Qwen3-VL-32B-Thinking", "Qwen3 VL 32B Thinking", vision=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="xai",
            label="xAI Grok",
            tagline="Grok 系列官方接口",
            base_url="https://api.x.ai/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://console.x.ai/",
            key_placeholder="xai-…",
            default_model="grok-4.6",
            groups=(
                Group(
                    "Grok",
                    (
                        _m("grok-4.6", "Grok 4.6", vision=True),
                        _m("grok-4.5", "Grok 4.5", vision=True),
                        _m("grok-4.3", "Grok 4.3", vision=True),
                    ),
                ),
            ),
        ),
        Provider(
            id="ollama",
            label="Ollama（本地）",
            tagline="本机运行开源模型 · 无需密钥",
            base_url="http://127.0.0.1:11434/v1",
            protocol=PROTOCOL_CHAT,
            key_url="https://ollama.com/download",
            key_placeholder="无需填写",
            key_required=False,
            custom_base_url=True,
            default_model="",
            region="local",
            groups=(),
        ),
        Provider(
            id=CUSTOM_PROVIDER,
            label="自定义 OpenAI 兼容接口",
            tagline="vLLM、LM Studio、one-api 等任意兼容服务",
            base_url="",
            protocol=PROTOCOL_CHAT,
            key_placeholder="按服务要求填写",
            key_required=False,
            custom_base_url=True,
            default_model="",
            groups=(),
        ),
    )
}

DEFAULT_PROVIDER = "openrouter"


def get_provider(provider_id: str) -> Provider:
    return PROVIDERS.get(str(provider_id or ""), PROVIDERS[CUSTOM_PROVIDER])


def catalog() -> dict:
    return {
        "default_provider": DEFAULT_PROVIDER,
        "providers": [provider.to_dict() for provider in PROVIDERS.values()],
    }


def model_vision(provider_id: str, model_id: str) -> bool | None:
    """Return the catalog's vision flag, or None when the model is unknown."""
    known = get_provider(provider_id).find_model(model_id)
    return None if known is None else known.vision
