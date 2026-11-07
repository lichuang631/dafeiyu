"""本地语音优先，失败时调用原有云端语音。"""

import asyncio
import io
import time
import wave


def validate_wav(content: bytes):
    """拒绝空文件、错误页和超出语音回复范围的音频。"""
    if not 44 < len(content) <= 8_000_000:
        raise ValueError("本地语音长度异常")
    with wave.open(io.BytesIO(content), "rb") as audio:
        if (
            audio.getnframes() <= 0
            or audio.getnchannels() not in (1, 2)
            or audio.getframerate() not in (16000, 22050, 24000, 32000, 44100, 48000)
            or audio.getnframes() / audio.getframerate() > 180
        ):
            raise ValueError("本地语音内容异常")
        expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
        if len(audio.readframes(audio.getnframes())) != expected:
            raise ValueError("本地语音文件不完整")


class HybridAudio:
    def __init__(
        self, local_call, cloud_call, timeout=30, cooldown=15, clock=time.monotonic
    ):
        self.local_call = local_call
        self.cloud_call = cloud_call
        self.timeout = timeout
        self.cooldown = cooldown
        self.clock = clock
        self.retry_at = 0
        self.last_source = "尚未生成"
        self.last_failure = ""

    async def get_audio(self, text: str, *args, **kwargs):
        if self.clock() >= self.retry_at:
            try:
                async with asyncio.timeout(self.timeout):
                    result = await self.local_call(text)
                self.retry_at = 0
                self.last_failure = ""
                self.last_source = "本地训练声音"
                return result
            except Exception as error:  # noqa: BLE001 - 失败时保留原语音回复。
                self.retry_at = self.clock() + self.cooldown
                self.last_failure = type(error).__name__
        self.last_source = "云端龙嫱备用声音"
        return await self.cloud_call(text, *args, **kwargs)
