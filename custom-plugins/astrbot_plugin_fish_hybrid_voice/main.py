"""给大肥鱼已有语音提供商接入本地训练声音和自动回退。"""

from pathlib import Path
from uuid import uuid4

import aiohttp
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .hybrid import HybridAudio, validate_wav


@register(
    "astrbot_plugin_fish_hybrid_voice",
    "本机定制",
    "本地训练声音优先，断开自动回到龙嫱",
    "1.0.1",
)
class FishHybridVoice(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_fish_hybrid_voice")
        self.installed = {}

    async def initialize(self):
        self.attach_provider()

    @filter.on_astrbot_loaded()
    async def after_loaded(self):
        self.attach_provider()

    @filter.on_llm_request(priority=950000)
    async def before_reply(self, event, request):
        # 提供商在面板重载后会换实例，在下一次回复前重新接入。
        self.attach_provider()

    def attach_provider(self):
        provider_id = self.config.get("provider_id", "bailian_voice")
        provider = self.context.get_provider_by_id(provider_id)
        if provider is None or not hasattr(provider, "get_audio"):
            return
        if id(provider) in self.installed:
            return
        original = getattr(provider, "_fish_cloud_audio", provider.get_audio)
        provider._fish_cloud_audio = original
        hybrid = HybridAudio(
            self.local_audio,
            original,
            timeout=float(self.config.get("local_timeout", 30)),
            cooldown=float(self.config.get("cooldown_seconds", 15)),
        )

        async def routed(text, *args, **kwargs):
            previous = hybrid.last_source
            audio = await hybrid.get_audio(text, *args, **kwargs)
            if previous != hybrid.last_source:
                logger.info("大肥鱼语音来源：%s。", hybrid.last_source)
            return audio

        provider.get_audio = routed
        self.installed[id(provider)] = (provider, original, routed, hybrid)
        logger.info("大肥鱼语音已接入本地优先及云端备用。")

    async def local_audio(self, text: str) -> str:
        token = (self.data_dir / "bridge-token").read_text(encoding="utf-8").strip()
        if not token or not text or len(text) > 800:
            raise ValueError("本地语音请求尚未就绪")
        socket = self.data_dir / "tunnel/voice.sock"
        connector = aiohttp.UnixConnector(path=str(socket))
        timeout = aiohttp.ClientTimeout(
            total=float(self.config.get("local_timeout", 30)), connect=1
        )
        headers = {"Authorization": "Bearer " + token}
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False
        ) as session:
            async with session.get(
                "http://local-voice/health",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=2, connect=1),
            ) as health:
                health.raise_for_status()
                if (await health.json()).get("ready") is not True:
                    raise ValueError("本地声音尚未就绪")
            async with session.post(
                "http://local-voice/tts",
                json={"text": text},
                headers=headers,
            ) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 8_000_000:
                        raise ValueError("本地语音超过长度限制")
                    chunks.append(chunk)
                content = b"".join(chunks)
        validate_wav(content)
        target = Path(get_astrbot_temp_path()) / f"fish_local_voice_{uuid4().hex}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    async def terminate(self):
        for provider, original, routed, _hybrid in self.installed.values():
            if provider.get_audio is routed:
                provider.get_audio = original
                del provider._fish_cloud_audio
        self.installed.clear()
