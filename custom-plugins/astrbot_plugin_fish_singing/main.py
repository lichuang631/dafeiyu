"""直接点歌，本地换成指定声音，复用已有私有语音连接。"""

import asyncio
import re
import time
from pathlib import Path
from uuid import uuid4

import aiohttp
from astrbot.api.event import filter
from astrbot.api.message_components import Record
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path


@register("astrbot_plugin_fish_singing", "本机定制", "按歌名自动找歌，用本地指定声音翻唱", "1.0.2")
class FishSinging(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_fish_hybrid_voice")
        self.active = False
        self.last_requested = {}

    def connection(self):
        token = (self.data_dir / "bridge-token").read_text(encoding="utf-8").strip()
        connector = aiohttp.UnixConnector(path=str(self.data_dir / "tunnel/voice.sock"))
        return aiohttp.ClientSession(
            connector=connector, headers={"Authorization": "Bearer " + token},
            timeout=aiohttp.ClientTimeout(total=8, connect=2), trust_env=False,
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=900000)
    async def handle_song(self, event):
        text = event.get_message_str().strip()
        match = re.fullmatch(r"/?(?:唱歌|翻唱|唱一首|大肥鱼唱歌)(?:\s+(.{1,80}))?", text)
        if not match:
            return
        event.stop_event()
        query = (match[1] or "").strip()
        if not query:
            await event.send(event.plain_result("点歌用：/唱歌 歌名 歌手，例如 /唱歌 叹云兮 鞠婧祎。"))
            return
        if "://" in query:
            await event.send(event.plain_result("请发歌名和歌手，不接受下载链接。"))
            return
        owner = str(self.config.get("owner_qq", "100000001"))
        sender = str(event.get_sender_id())
        if self.config.get("owner_only", False) and sender != owner:
            await event.send(event.plain_result("唱歌暂时只给主人使用。"))
            return
        if self.active:
            await event.send(event.plain_result("我正在唱另一首，完成后再点歌呀。"))
            return
        cooldown = float(self.config.get("cooldown_seconds", 300))
        if sender != owner and time.monotonic() - self.last_requested.get(sender, -cooldown) < cooldown:
            await event.send(event.plain_result("点歌稍微歇一会儿，五分钟后再来呀。"))
            return
        self.active = True
        try:
            async with self.connection() as session:
                async with session.post("http://local-voice/sing/jobs", json={"query": query, "request_id": uuid4().hex}) as response:
                    if response.status == 429:
                        await event.send(event.plain_result("本地正在处理另一首歌，完成后再来点。"))
                        return
                    response.raise_for_status()
                    accepted = await response.json()
                    job = accepted["job_id"]
                    cached = accepted.get("cache_hit", False)
                self.last_requested[sender] = time.monotonic()
                notice = "这首已经唱好啦，直接发给你。" if cached else f"收到，我去找《{query}》的音源，再换成我的声音。需要一点时间，完成后发给你。"
                await event.send(event.plain_result(notice))
                deadline = time.monotonic() + 900
                previous = None
                notice_at = time.monotonic()
                waited_from = notice_at
                result = None
                while time.monotonic() < deadline:
                    await asyncio.sleep(0 if cached else 3)
                    async with session.get(f"http://local-voice/sing/jobs/{job}") as response:
                        response.raise_for_status()
                        result = await response.json()
                    if result["state"] == "error":
                        self.last_requested.pop(sender, None)
                        await event.send(event.plain_result(result.get("message", "这次没唱好，请稍后再试。")))
                        return
                    if result["state"] == "done":
                        break
                    if previous != result["state"] and result["state"] == "converting":
                        song = result.get("song", {})
                        notice = "音乐平台只提供试听，这次唱可用的试听片段。" if song.get("preview_only") else "原唱和伴奏已分开，正在换成我的声音。"
                        await event.send(event.plain_result(notice))
                        notice_at = time.monotonic()
                    elif time.monotonic() - notice_at >= 30:
                        phase = {"searching": "找音源", "separating": "分离人声", "converting": "换声音", "mixing": "混音"}.get(result["state"], "处理歌曲")
                        await event.send(event.plain_result(f"还在{phase}，已等待{int(time.monotonic() - waited_from)}秒；超时会明确告诉你。"))
                        notice_at = time.monotonic()
                    previous = result["state"]
                else:
                    await event.send(event.plain_result("这次处理超过等待时间，稍后再试一首较短的歌吧。"))
                    return
                parts = int(result.get("parts", 0))
                if not 1 <= parts <= 6:
                    raise ValueError("歌曲分段数量异常")
                for index in range(parts):
                    async with session.get(f"http://local-voice/sing/jobs/{job}/audio/{index}", timeout=aiohttp.ClientTimeout(total=25, connect=2)) as response:
                        response.raise_for_status()
                        content = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            content.extend(chunk)
                            if len(content) > 2_000_000:
                                raise ValueError("单段音频过大")
                    path = Path(get_astrbot_temp_path()) / f"fish_singing_{job}_{index}.mp3"
                    path.write_bytes(content)
                    await event.send(event.chain_result([Record.fromFileSystem(str(path))]))
                    if index < parts - 1:
                        await asyncio.sleep(1)
                song = result.get("song", {})
                label = "公开试听片段" if song.get("preview_only") else "可用音源"
                extra = "；原曲较长，本次最多处理前五分钟" if result.get("clipped") else ""
                await event.send(event.plain_result(f"《{song.get('title', query)}》—{song.get('artist', '')}，已用我的声音唱好。音源：{song.get('source', '音乐平台')}{label}{extra}。"))
        except (TimeoutError, aiohttp.ClientError, OSError):
            self.last_requested.pop(sender, None)
            await event.send(event.plain_result("本地唱歌服务暂时连不上，电脑联网并启动本地声音后会自动恢复；普通聊天仍可继续。"))
        except (ValueError, KeyError):
            await event.send(event.plain_result("本次音频没有完整取回，请稍后再试。"))
        finally:
            self.active = False
