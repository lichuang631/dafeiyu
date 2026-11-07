"""测试本地优先、断开备用和恢复后的自动切换。"""

import asyncio
import importlib.util
import io
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location(
    "hybrid", Path(__file__).resolve().parents[1] / "hybrid.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HybridTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.local = AsyncMock(return_value="local.wav")
        self.cloud = AsyncMock(return_value="cloud.wav")
        self.router = module.HybridAudio(
            self.local, self.cloud, timeout=0.02, clock=lambda: self.now
        )

    async def test_local_success_never_calls_cloud(self):
        self.assertEqual(await self.router.get_audio("在吗"), "local.wav")
        self.cloud.assert_not_awaited()

    async def test_disconnect_immediately_uses_original_cloud_and_keeps_arguments(self):
        self.local.side_effect = ConnectionError()
        self.assertEqual(
            await self.router.get_audio("在吗", emotion="calm"), "cloud.wav"
        )
        self.cloud.assert_awaited_once_with("在吗", emotion="calm")

    async def test_cooldown_skips_offline_local_then_automatically_recovers(self):
        self.local.side_effect = ConnectionError()
        await self.router.get_audio("第一句")
        self.local.side_effect = None
        self.assertEqual(await self.router.get_audio("第二句"), "cloud.wav")
        self.local.assert_awaited_once()
        self.now += 16
        self.assertEqual(await self.router.get_audio("第三句"), "local.wav")
        self.assertEqual(self.local.await_count, 2)

    async def test_timeout_uses_cloud(self):
        async def slow(_text):
            await asyncio.sleep(1)

        self.local.side_effect = slow
        self.assertEqual(await self.router.get_audio("测试"), "cloud.wav")
        self.assertEqual(self.router.last_failure, "TimeoutError")

    async def test_invalid_local_audio_uses_cloud(self):
        self.local.side_effect = ValueError("无效音频")
        self.assertEqual(await self.router.get_audio("测试"), "cloud.wav")

    async def test_task_cancellation_does_not_generate_an_unwanted_cloud_reply(self):
        self.local.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.router.get_audio("取消")
        self.cloud.assert_not_awaited()

    async def test_cloud_failure_propagates_without_recursion(self):
        self.local.side_effect = ConnectionError()
        self.cloud.side_effect = RuntimeError("原语音服务失败")
        with self.assertRaises(RuntimeError):
            await self.router.get_audio("测试")
        self.cloud.assert_awaited_once()

    def test_wav_validation_rejects_error_pages_empty_and_truncated_audio(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(32000)
            audio.writeframes(b"\x00\x00" * 3200)
        good = buffer.getvalue()
        module.validate_wav(good)
        for content in (b"", b"<html>wrong</html>", good[:-10]):
            with (
                self.subTest(size=len(content)),
                self.assertRaises((ValueError, wave.Error, EOFError)),
            ):
                module.validate_wav(content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
