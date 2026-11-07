"""模拟消息后置插件停止事件，确认全部进度与歌曲仍完成发送。"""

import importlib.util
import inspect
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

modules = {name: types.ModuleType(name) for name in ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.message_components", "astrbot.api.star", "astrbot.core", "astrbot.core.utils", "astrbot.core.utils.astrbot_path")}
modules["astrbot.api.event"].filter = types.SimpleNamespace(event_message_type=lambda *a, **kw: lambda f: f, EventMessageType=types.SimpleNamespace(ALL="all"))
modules["astrbot.api.star"].register = lambda *a, **kw: lambda cls: cls
modules["astrbot.api.star"].Context = object
modules["astrbot.api.star"].Star = object
modules["astrbot.api.star"].StarTools = types.SimpleNamespace(get_data_dir=lambda name: Path(tempfile.gettempdir()))
modules["astrbot.api.message_components"].Record = types.SimpleNamespace(fromFileSystem=lambda path: {"record": path})
modules["astrbot.core.utils.astrbot_path"].get_astrbot_temp_path = tempfile.gettempdir
spec = importlib.util.spec_from_file_location("singing_delivery_test", Path(__file__).resolve().parents[1] / "main.py")
plugin = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, modules):
    spec.loader.exec_module(plugin)


class Response:
    status = 200

    def __init__(self, data):
        self.data = data
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data

    def raise_for_status(self):
        pass

    async def iter_chunked(self, size):
        yield b"ID3" + b"unit-test-audio" * 10


class Session(Response):
    def __init__(self):
        super().__init__({})
        self.polls = 0

    def post(self, *args, **kwargs):
        return Response({"job_id": "a" * 32})

    def get(self, url, **kwargs):
        if "/audio/" in url:
            return Response({})
        self.polls += 1
        return Response({"state": "converting" if self.polls == 1 else "done", "parts": 2, "song": {"title": "叹云兮", "artist": "鞠婧祎", "preview_only": True}})


class Event:
    def __init__(self):
        self.stopped = False
        self.sent = []

    def get_message_str(self):
        return "/唱歌 叹云兮 鞠婧祎"

    def get_sender_id(self):
        return "100000001"

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return {"text": text}

    def chain_result(self, chain):
        return {"chain": chain}

    async def send(self, result):
        self.sent.append(result)
        self.stop_event()  # 重现meme_manager消息后置钩子的行为。


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def instance(self):
        obj = object.__new__(plugin.FishSinging)
        obj.config = {}
        obj.active = False
        obj.last_requested = {}
        obj.connection = lambda: Session()
        return obj

    async def test_stopped_event_after_progress_does_not_drop_music(self):
        obj = self.instance()
        event = Event()
        with tempfile.TemporaryDirectory() as folder, patch.object(plugin, "get_astrbot_temp_path", return_value=folder), patch.object(plugin.asyncio, "sleep", new=AsyncMock()):
            self.assertTrue(inspect.iscoroutinefunction(obj.handle_song))
            await obj.handle_song(event)
            records = [r for r in event.sent if "chain" in r]
            self.assertEqual(len(records), 2)
            self.assertIn("唱好", event.sent[-1]["text"])
            self.assertTrue(event.stopped)
            self.assertFalse(obj.active)

    async def test_connection_failure_clears_busy_state_and_reports_error(self):
        obj = self.instance()
        obj.connection = lambda: (_ for _ in ()).throw(OSError("offline"))
        event = Event()
        await obj.handle_song(event)
        self.assertFalse(obj.active)
        self.assertIn("暂时连不上", event.sent[-1]["text"])


if __name__ == "__main__":
    unittest.main()
